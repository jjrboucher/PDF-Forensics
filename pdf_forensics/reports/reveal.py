"""
reports/reveal.py
Overlay suppression for the "before/after" reveal in the visual report.

Given a source PDF page and one or more detected overlay findings, this
module produces a modified copy of the PDF with the overlay content
suppressed, so the report can render "what is hidden beneath" an overlay.

Three overlay kinds are handled, mirroring the detectors that produce them
(see analysis/detectors.py):

  white_box      A white(ish) filled rectangle painted over existing
                 content, with new text drawn on top. Reveal removes the
                 white rectangle's paint operators and the text-show
                 operators drawn on top inside that rectangle, exposing the
                 original content drawn earlier in the same stream.

  text_over_text New glyphs painted directly over original glyphs at the
                 same position, with no masking rectangle. Reveal removes
                 the later (overlying) text-show operators in the region,
                 exposing the earlier (original) glyphs. Best-effort.

  annotation     An opaque annotation (FreeText / Widget / Square / Redact)
                 placed over text. Reveal removes the matching annotation
                 from the page's /Annots array.

The recovery is non-destructive to the *original* content: the underlying
material is exposed only because the overlay merely hid it -- it was never
removed from the file. Operators are matched by re-parsing the content
stream and tracking graphics state exactly as the detectors do, because the
database stores only each finding's bounding box and kind, not stream
offsets.

Coordinate systems: finding bounding boxes are stored in PyMuPDF top-left
origin coordinates. Content-stream geometry is in PDF bottom-left origin
coordinates. A finding box (mx0, my0, mx1, my1) corresponds to the PDF-space
rectangle (mx0, H - my1, mx1, H - my0), where H is the page height in points.

This module depends only on pikepdf. Rasterization of the revealed PDF is
performed by the caller (reports/visual.py) using the same PyMuPDF path used
for the normal page render.
"""

import io

import pikepdf
from pikepdf import Name

# --- Constants kept in sync with analysis/detectors.py --------------------
# (Defined locally rather than imported, because detectors.py imports
#  pymupdf at module load; reveal.py is intentionally pymupdf-free so the
#  suppression logic can be exercised independently of the renderer.)
WHITE_THRESHOLD = 0.9            # per-channel min for a fill to be "white"
NEAR_RECT_TOLERANCE = 15.0       # pts tolerance, text-position vs rect
TEXT_OVERLAY_MIN_AREA_SQPTS = 4.0
RECT_MATCH_TOLERANCE = 2.0       # pts tolerance, matching a finding rect

# Annotation subtypes the annotation detector flags
_OVERLAY_ANNOT_SUBTYPES = ("/FreeText", "/Widget", "/Square", "/Redact")

# Text-showing operators
_TEXT_SHOW_OPS = ("Tj", "TJ", "'", '"')
# Operators that paint a preceding `re`
_RECT_FILL_OPS = ("f", "F", "B", "B*", "b", "b*")


# --------------------------------------------------------------------------
# Graphics-state helpers (identical math to the detectors)
# --------------------------------------------------------------------------
def _transform_point(ctm, x, y):
    a, b, c, d, e, f = ctm
    return a * x + c * y + e, b * x + d * y + f


def _rect_to_page(ctm, rx, ry, rw, rh):
    corners = [(rx, ry), (rx + rw, ry), (rx, ry + rh), (rx + rw, ry + rh)]
    xs = [_transform_point(ctm, cx, cy)[0] for cx, cy in corners]
    ys = [_transform_point(ctm, cx, cy)[1] for cx, cy in corners]
    return min(xs), min(ys), max(xs), max(ys)


def _multiply_ctm(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def _instr_parts(instr):
    """Return (operator_str, operands_list) for a parsed instruction,
    tolerant of both ContentStreamInstruction objects and (operands, op)
    tuples across pikepdf versions."""
    try:
        return str(instr.operator), list(instr.operands)
    except AttributeError:
        operands, op = instr
        return str(op), list(operands)


def _finding_rect_to_pdf(bbox, page_height):
    """Convert a finding bbox (PyMuPDF top-left) to PDF bottom-left space."""
    mx0, my0, mx1, my1 = bbox
    px0 = min(mx0, mx1)
    px1 = max(mx0, mx1)
    py0 = page_height - max(my0, my1)
    py1 = page_height - min(my0, my1)
    return px0, py0, px1, py1


def _rects_match(r1, r2, tol):
    """True if two (x0,y0,x1,y1) rects coincide within tolerance."""
    return (abs(r1[0] - r2[0]) <= tol and abs(r1[1] - r2[1]) <= tol and
            abs(r1[2] - r2[2]) <= tol and abs(r1[3] - r2[3]) <= tol)


def _point_in_rect(px, py, rect, tol):
    x0, y0, x1, y1 = rect
    return (x0 - tol <= px <= x1 + tol and
            y0 - tol <= py <= y1 + tol)


# --------------------------------------------------------------------------
# Operator-index collection per overlay kind
# --------------------------------------------------------------------------
def _white_box_indices(ops, target_rects_pdf):
    """
    Return a set of operator indices to drop to suppress white-box overlays
    whose painted rectangle matches one of target_rects_pdf (PDF space).
    Drops the matched `re` and its fill operator, and any text-show
    operators positioned inside the rect and drawn after it.
    """
    drop = set()

    # Pass 1: locate white filled rectangles and their operator indices.
    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    ctm_stack = []
    fill_color = (0.0, 0.0, 0.0)
    white_rects = []   # (x0, y0, x1, y1, re_idx, fill_idx)

    for i, instr in enumerate(ops):
        op, operands = _instr_parts(instr)
        if op == 'q':
            ctm_stack.append(ctm)
        elif op == 'Q':
            if ctm_stack:
                ctm = ctm_stack.pop()
        elif op == 'cm':
            try:
                vals = tuple(float(str(x)) for x in operands)
                ctm = _multiply_ctm(vals, ctm)
            except Exception:
                pass
        elif op == 'g':
            try:
                v = float(str(operands[0]))
                fill_color = (v, v, v)
            except Exception:
                pass
        elif op == 'rg':
            try:
                fill_color = tuple(float(str(x)) for x in operands[:3])
            except Exception:
                pass
        elif op in ('sc', 'scn'):
            try:
                vals = [float(str(x)) for x in operands
                        if _is_number(x)]
                if len(vals) == 1:
                    fill_color = (vals[0],) * 3
                elif len(vals) >= 3:
                    fill_color = tuple(vals[:3])
            except Exception:
                pass
        elif op == 're':
            if i + 1 < len(ops):
                next_op = _instr_parts(ops[i + 1])[0]
                if next_op in _RECT_FILL_OPS:
                    if (len(fill_color) >= 3 and
                            all(v >= WHITE_THRESHOLD
                                for v in fill_color[:3])):
                        try:
                            rx, ry, rw, rh = (
                                float(str(x)) for x in operands[:4])
                            if abs(rw * rh) >= TEXT_OVERLAY_MIN_AREA_SQPTS:
                                x0, y0, x1, y1 = _rect_to_page(
                                    ctm, rx, ry, rw, rh)
                                white_rects.append(
                                    (x0, y0, x1, y1, i, i + 1))
                        except Exception:
                            pass

    # Match white rects against the requested target rects.
    matched = []   # (x0, y0, x1, y1, re_idx)
    for (x0, y0, x1, y1, re_idx, fill_idx) in white_rects:
        for tr in target_rects_pdf:
            if _rects_match((x0, y0, x1, y1), tr, RECT_MATCH_TOLERANCE):
                drop.add(re_idx)
                drop.add(fill_idx)
                matched.append((x0, y0, x1, y1, re_idx))
                break

    if not matched:
        return drop

    # Pass 2: drop text-show ops inside a matched rect, drawn after it.
    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    ctm_stack = []
    Tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    Tlm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    in_bt = False

    for i, instr in enumerate(ops):
        op, operands = _instr_parts(instr)
        if op == 'q':
            ctm_stack.append(ctm)
        elif op == 'Q':
            if ctm_stack:
                ctm = ctm_stack.pop()
        elif op == 'cm':
            try:
                vals = tuple(float(str(x)) for x in operands)
                ctm = _multiply_ctm(vals, ctm)
            except Exception:
                pass
        elif op == 'BT':
            in_bt = True
            Tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            Tlm = list(Tm)
        elif op == 'ET':
            in_bt = False
        elif in_bt and op == 'Tm':
            try:
                Tm = [float(str(x)) for x in operands]
                Tlm = list(Tm)
            except Exception:
                pass
        elif in_bt and op in ('Td', 'TD'):
            try:
                tx = float(str(operands[0]))
                ty = float(str(operands[1]))
                Tlm[4] += tx * Tlm[0] + ty * Tlm[2]
                Tlm[5] += tx * Tlm[1] + ty * Tlm[3]
                Tm = list(Tlm)
            except Exception:
                pass
        elif in_bt and op == 'T*':
            Tm = list(Tlm)
        elif in_bt and op in _TEXT_SHOW_OPS:
            tm_x, tm_y = Tm[4], Tm[5]
            px, py = _transform_point(ctm, tm_x, tm_y)
            for (rx0, ry0, rx1, ry1, re_idx) in matched:
                if i <= re_idx:
                    continue
                if _point_in_rect(px, py, (rx0, ry0, rx1, ry1),
                                  NEAR_RECT_TOLERANCE):
                    drop.add(i)
                    break

    return drop


def _text_over_text_indices(ops, target_rects_pdf):
    """
    Return operator indices to drop to suppress text-over-text overlays in
    the target regions. Within each region, text-show operators are grouped
    by near-identical baseline position; the earliest in each group is kept
    (the original) and later ones are dropped (the overlying glyphs).

    Best-effort: relies on the common manipulation pattern of re-drawing a
    field value at the same origin. Returns indices to drop.
    """
    NEAR_POS = 2.0   # pts; group shows at the "same" position

    drop = set()
    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    ctm_stack = []
    Tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    Tlm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    in_bt = False

    shows = []   # (op_index, px, py) for shows inside a target region

    for i, instr in enumerate(ops):
        op, operands = _instr_parts(instr)
        if op == 'q':
            ctm_stack.append(ctm)
        elif op == 'Q':
            if ctm_stack:
                ctm = ctm_stack.pop()
        elif op == 'cm':
            try:
                vals = tuple(float(str(x)) for x in operands)
                ctm = _multiply_ctm(vals, ctm)
            except Exception:
                pass
        elif op == 'BT':
            in_bt = True
            Tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            Tlm = list(Tm)
        elif op == 'ET':
            in_bt = False
        elif in_bt and op == 'Tm':
            try:
                Tm = [float(str(x)) for x in operands]
                Tlm = list(Tm)
            except Exception:
                pass
        elif in_bt and op in ('Td', 'TD'):
            try:
                tx = float(str(operands[0]))
                ty = float(str(operands[1]))
                Tlm[4] += tx * Tlm[0] + ty * Tlm[2]
                Tlm[5] += tx * Tlm[1] + ty * Tlm[3]
                Tm = list(Tlm)
            except Exception:
                pass
        elif in_bt and op == 'T*':
            Tm = list(Tlm)
        elif in_bt and op in _TEXT_SHOW_OPS:
            px, py = _transform_point(ctm, Tm[4], Tm[5])
            for rect in target_rects_pdf:
                if _point_in_rect(px, py, rect, NEAR_RECT_TOLERANCE):
                    shows.append((i, px, py))
                    break

    # Group shows by near-identical position; keep earliest, drop the rest.
    groups = []   # list of dicts {x, y, indices: [...] }
    for (idx, px, py) in shows:
        placed = False
        for g in groups:
            if abs(g["x"] - px) < NEAR_POS and abs(g["y"] - py) < NEAR_POS:
                g["indices"].append(idx)
                placed = True
                break
        if not placed:
            groups.append({"x": px, "y": py, "indices": [idx]})

    for g in groups:
        if len(g["indices"]) > 1:
            ordered = sorted(g["indices"])
            for idx in ordered[1:]:   # drop all but the earliest
                drop.add(idx)

    return drop


def _is_number(x):
    try:
        float(str(x))
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Annotation suppression
# --------------------------------------------------------------------------
def _suppress_annotations(page, target_rects_pdf, suppress_all):
    """
    Remove overlay annotations from a pikepdf page in-place.

    If suppress_all is True, every overlay-type annotation is removed.
    Otherwise only annotations whose /Rect matches a target rect are
    removed. Returns the number of annotations removed.
    """
    try:
        annots = page.get("/Annots")
    except Exception:
        annots = None
    if not annots:
        return 0

    keep = []
    removed = 0
    for annot in list(annots):
        try:
            obj = annot.obj if hasattr(annot, "obj") else annot
            subtype = str(obj.get("/Subtype") or "")
            rect_raw = obj.get("/Rect")
            is_overlay_type = subtype in _OVERLAY_ANNOT_SUBTYPES
            match = False
            if is_overlay_type and rect_raw is not None:
                try:
                    coords = [float(v) for v in rect_raw]
                    ax0, ay0 = min(coords[0], coords[2]), min(coords[1],
                                                              coords[3])
                    ax1, ay1 = max(coords[0], coords[2]), max(coords[1],
                                                              coords[3])
                    ann_rect = (ax0, ay0, ax1, ay1)
                    if suppress_all:
                        match = True
                    else:
                        for tr in target_rects_pdf:
                            if _rects_match(ann_rect, tr,
                                            RECT_MATCH_TOLERANCE):
                                match = True
                                break
                except Exception:
                    match = False
            if match:
                removed += 1
            else:
                keep.append(annot)
        except Exception:
            keep.append(annot)

    if removed:
        page.Annots = pikepdf.Array(keep)
    return removed


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def build_revealed_pdf_bytes(src_path, page_index, findings, page_height):
    """
    Produce a copy of the PDF at src_path with the given overlay findings
    suppressed on page `page_index` (0-based). `findings` is a list of dicts
    each with keys: 'bbox' (PyMuPDF top-left coords) and 'kind' (one of
    'white_box', 'text_over_text', 'annotation').

    Returns (pdf_bytes, info) where info is a dict:
        {
          "changed": bool,            # whether anything was suppressed
          "kinds": set(...),          # kinds actually suppressed
          "ops_dropped": int,
          "annots_removed": int,
        }
    On any failure, returns (None, info_with_changed_False).
    """
    info = {"changed": False, "kinds": set(),
            "ops_dropped": 0, "annots_removed": 0}

    # Group target rects (PDF space) by kind.
    rects_by_kind = {"white_box": [], "text_over_text": [], "annotation": []}
    for fnd in findings:
        kind = fnd.get("kind", "other")
        if kind not in rects_by_kind:
            continue
        rects_by_kind[kind].append(
            _finding_rect_to_pdf(fnd["bbox"], page_height))

    try:
        pdf = pikepdf.open(src_path)
    except Exception:
        return None, info

    try:
        if page_index < 0 or page_index >= len(pdf.pages):
            pdf.close()
            return None, info
        page = pdf.pages[page_index]

        # --- Annotation suppression -------------------------------------
        if rects_by_kind["annotation"]:
            n = _suppress_annotations(
                page, rects_by_kind["annotation"], suppress_all=False)
            if n:
                info["annots_removed"] += n
                info["kinds"].add("annotation")

        # --- Content-stream suppression ---------------------------------
        cs_kinds = [k for k in ("white_box", "text_over_text")
                    if rects_by_kind[k]]
        if cs_kinds:
            try:
                ops = list(pikepdf.parse_content_stream(page))
            except Exception:
                ops = None
            if ops:
                drop = set()
                if rects_by_kind["white_box"]:
                    wb = _white_box_indices(
                        ops, rects_by_kind["white_box"])
                    if wb:
                        drop |= wb
                        info["kinds"].add("white_box")
                if rects_by_kind["text_over_text"]:
                    tt = _text_over_text_indices(
                        ops, rects_by_kind["text_over_text"])
                    if tt:
                        drop |= tt
                        info["kinds"].add("text_over_text")
                if drop:
                    kept = [instr for idx, instr in enumerate(ops)
                            if idx not in drop]
                    new_stream = pikepdf.unparse_content_stream(kept)
                    # Replace the page content with a single stream.
                    page.Contents = pdf.make_stream(new_stream)
                    info["ops_dropped"] += len(drop)

        info["changed"] = bool(info["ops_dropped"] or
                               info["annots_removed"])

        if not info["changed"]:
            pdf.close()
            return None, info

        buf = io.BytesIO()
        pdf.save(buf)
        pdf.close()
        return buf.getvalue(), info
    except Exception:
        try:
            pdf.close()
        except Exception:
            pass
        return None, info
