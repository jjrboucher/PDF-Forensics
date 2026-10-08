"""
reports/reveal.py
Overlay suppression for the "before/after" reveal in the visual report.

Given a source PDF page and one or more detected overlay findings, this
module produces a modified copy of the PDF with the overlay content
suppressed, so the report can render "what is hidden beneath" an overlay.

Three overlay kinds are handled, mirroring the detectors that produce them
(see analysis/detectors.py): white_box, text_over_text, and annotation.

Real-world alterations (e.g. those produced by PDFium-based editors) are
frequently composited on top of the original through deeply nested Form
XObjects. The original content stays in the base page content stream (or a
lower layer), and each edit is layered on top as a TWO-part construct drawn
last:

  (1) a patch -- a white rectangle, or one or more small image/form patches
      -- that hides the original glyphs, and
  (2) forged text drawn over the patch.

Removing only the forged text leaves the patch covering the original, so the
reveal must remove BOTH halves together. Because both halves are emitted as
a contiguous group of "Do" invocations (and sometimes inline operators)
inside a small container form whose bounding box tightly frames the altered
region, the reliable unit of suppression is that *container form invocation*,
not the individual glyph-show operators.

This module therefore walks the entire content tree (page stream plus every
nested Form XObject) in draw order, recording for each form-invocation
("Do") site: the page-space bounding box of the invoked form, and a summary
of what its subtree paints (overlay text, patch content, and -- critically
-- any *legitimate* text that must not be destroyed). For each flagged
region it then selects the tightest container whose box frames the region
and whose subtree contains only overlay material; suppressing that container
removes patch and forged text together and exposes the untouched original.

Evidentiary safety: if no container can be found that isolates the overlay
from legitimate co-located content, the reveal is SKIPPED for that finding
rather than producing a misleading partial result. The caller is told which
findings were and were not recovered so the report can label accordingly.

Coordinate systems: finding bounding boxes are stored in PyMuPDF top-left
origin coordinates. Content-stream geometry is in PDF bottom-left origin
coordinates. A finding box (mx0, my0, mx1, my1) corresponds to the PDF-space
rectangle (mx0, H - my1, mx1, H - my0), where H is the page height in points.

This module depends only on pikepdf. Rasterization of the revealed PDF is
performed by the caller (reports/visual.py).
"""

import io

import pikepdf

# --- Constants kept in sync with analysis/detectors.py --------------------
WHITE_THRESHOLD = 0.9            # per-channel min for a fill to be "white"
NEAR_RECT_TOLERANCE = 15.0       # pts tolerance, text-position vs rect
TEXT_OVERLAY_MIN_AREA_SQPTS = 4.0
RECT_MATCH_TOLERANCE = 2.0       # pts tolerance, matching a finding rect
REGION_TOLERANCE = 12.0          # pts tolerance, show-position vs finding box
MAX_XOBJECT_DEPTH = 12           # guard against pathological / cyclic nesting

# A container form is only considered a clean overlay wrapper if it is not
# larger than this; bigger forms are assumed to also carry legitimate
# content and are never suppressed wholesale.
MAX_CONTAINER_W = 260.0
MAX_CONTAINER_H = 130.0
# How tightly a container's box must frame the flagged region. The container
# must not extend far beyond the region on any side.
CONTAINER_MARGIN = 24.0

_OVERLAY_ANNOT_SUBTYPES = ("/FreeText", "/Widget", "/Square", "/Redact",
                           "/Stamp")
_TEXT_SHOW_OPS = ("Tj", "TJ", "'", '"')
_RECT_FILL_OPS = ("f", "F", "B", "B*", "b", "b*")
# Fonts used for forged text differ from the document body fonts; we treat
# any text inside a tightly-framed small container as overlay text. The
# detector's own analysis is what flags the region, so this module does not
# re-classify fonts -- it only needs to ensure a container is "overlay only".


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------
def _transform_point(ctm, x, y):
    a, b, c, d, e, f = ctm
    return a * x + c * y + e, b * x + d * y + f


def _rect_to_page(ctm, rx, ry, rw, rh):
    corners = [(rx, ry), (rx + rw, ry), (rx, ry + rh), (rx + rw, ry + rh)]
    xs = [_transform_point(ctm, cx, cy)[0] for cx, cy in corners]
    ys = [_transform_point(ctm, cx, cy)[1] for cx, cy in corners]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_to_page(ctm, bb):
    return _rect_to_page(ctm, bb[0], bb[1], bb[2] - bb[0], bb[3] - bb[1])


def _multiply_ctm(m1, m2):
    """Return m1 x m2 (apply m1 first, then m2)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def _instr_parts(instr):
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
    return (abs(r1[0] - r2[0]) <= tol and abs(r1[1] - r2[1]) <= tol and
            abs(r1[2] - r2[2]) <= tol and abs(r1[3] - r2[3]) <= tol)


def _point_in_rect(px, py, rect, tol):
    x0, y0, x1, y1 = rect
    return (x0 - tol <= px <= x1 + tol and y0 - tol <= py <= y1 + tol)


def _rects_overlap(a, b, tol=0.0):
    return not (a[2] < b[0] - tol or a[0] > b[2] + tol or
                a[3] < b[1] - tol or a[1] > b[3] + tol)


def _frames_region(container_bb, region, margin):
    """True if container_bb overlaps region and does not extend more than
    `margin` beyond the region on any side (i.e. it tightly frames it)."""
    if not _rects_overlap(container_bb, region, 0.0):
        return False
    return (container_bb[0] >= region[0] - margin and
            container_bb[1] >= region[1] - margin and
            container_bb[2] <= region[2] + margin and
            container_bb[3] <= region[3] + margin)


def _is_number(x):
    try:
        float(str(x))
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Content-tree model
# --------------------------------------------------------------------------
class _Unit:
    """A single rewritable content stream (the page, or one Form XObject)."""
    __slots__ = ("obj", "kind", "ops", "drop", "shared")

    def __init__(self, obj, kind, ops):
        self.obj = obj
        self.kind = kind        # "page" or "form"
        self.ops = ops
        self.drop = set()       # local op indices to remove
        self.shared = False     # reached via >1 path -> do not edit


class _DoSite:
    """A 'Do /Form' invocation we may suppress as a whole.

    parent_uid/op_idx locate the invoking operator so it can be removed.
    page_bb is the invoked form's bounding box in page coords.
    has_text/has_legit_text/has_paint summarize the invoked subtree.
    """
    __slots__ = ("parent_uid", "op_idx", "page_bb",
                 "has_text", "has_legit_text", "has_paint")

    def __init__(self, parent_uid, op_idx, page_bb):
        self.parent_uid = parent_uid
        self.op_idx = op_idx
        self.page_bb = page_bb
        self.has_text = False        # any text-show in subtree
        self.has_legit_text = False  # text that looks like body content
        self.has_paint = False       # any image/fill/text drawn


def _walk_content(page):
    """
    Walk the page content stream and all nested Form XObjects in draw order.

    Returns (units, shows, rects, do_sites):
      units: dict id(obj) -> _Unit
      shows: list of {unit_id, idx, order, x, y, len_chars}
      rects: list of {unit_id, re_idx, fill_idx, order, rect}
      do_sites: list of _DoSite (one per Do/Form invocation)
    'order' reflects global draw order across the tree.
    """
    units = {}
    shows = []
    rects = []
    do_sites = []
    order = [0]

    def get_unit(obj, kind):
        oid = id(obj)
        if oid in units:
            units[oid].shared = True
            return units[oid], True
        try:
            ops = list(pikepdf.parse_content_stream(obj))
        except Exception:
            ops = None
        if ops is None:
            return None, False
        u = _Unit(obj, kind, ops)
        units[oid] = u
        return u, False

    def resources_of(obj, fallback):
        try:
            if "/Resources" in obj:
                return obj.Resources
        except Exception:
            pass
        return fallback

    def estimate_text_len(operands):
        n = 0
        for o in operands:
            if isinstance(o, pikepdf.String):
                n += len(bytes(o)) // 2 or len(bytes(o))
            else:
                try:
                    for e in o:
                        if isinstance(e, pikepdf.String):
                            n += len(bytes(e)) // 2 or len(bytes(e))
                except Exception:
                    pass
        return n

    def walk(obj, kind, base_ctm, resources, depth, site):
        """Walk one stream. `site` is the _DoSite that invoked this form
        (None for the page), so the subtree summary can be accumulated."""
        if depth > MAX_XOBJECT_DEPTH:
            return
        unit, already = get_unit(obj, kind)
        if unit is None:
            return
        ops = unit.ops
        uid = id(obj)

        xobjs = None
        try:
            if resources is not None and "/XObject" in resources:
                xobjs = resources.XObject
        except Exception:
            xobjs = None

        ctm = base_ctm
        ctm_stack = []
        Tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        Tlm = list(Tm)
        in_bt = False
        fill_color = (0.0, 0.0, 0.0)

        def mark_paint():
            s = site
            while s is not None:
                s.has_paint = True
                s = None  # only nearest; ancestors set via their own walks

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
                    vals = [float(str(x)) for x in operands if _is_number(x)]
                    if len(vals) == 1:
                        fill_color = (vals[0],) * 3
                    elif len(vals) >= 3:
                        fill_color = tuple(vals[:3])
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
                order[0] += 1
                nchars = estimate_text_len(operands)
                shows.append({"unit_id": uid, "idx": i, "order": order[0],
                              "x": px, "y": py, "len_chars": nchars})
                if site is not None:
                    site.has_text = True
                    site.has_paint = True
                    # Heuristic: a long run of characters is likely body
                    # text, not a small forged value.
                    if nchars >= 14:
                        site.has_legit_text = True
            elif op in ('Tj', 'TJ', "'", '"'):
                # text outside BT/ET (rare) -- treat as paint/text
                if site is not None:
                    site.has_text = True
                    site.has_paint = True
            elif op == 're':
                if i + 1 < len(ops):
                    next_op = _instr_parts(ops[i + 1])[0]
                    if next_op in _RECT_FILL_OPS:
                        if site is not None:
                            site.has_paint = True
                        if len(fill_color) >= 3 and \
                                all(v >= WHITE_THRESHOLD
                                    for v in fill_color[:3]):
                            try:
                                rx, ry, rw, rh = (float(str(x))
                                                  for x in operands[:4])
                                if abs(rw * rh) >= \
                                        TEXT_OVERLAY_MIN_AREA_SQPTS:
                                    rect = _rect_to_page(ctm, rx, ry, rw, rh)
                                    order[0] += 1
                                    rects.append({"unit_id": uid,
                                                  "re_idx": i,
                                                  "fill_idx": i + 1,
                                                  "order": order[0],
                                                  "rect": rect})
                            except Exception:
                                pass
            elif op in ('Do',):
                if site is not None:
                    site.has_paint = True
                if xobjs is not None and operands:
                    name = str(operands[0])
                    try:
                        xo = xobjs.get(name) if hasattr(xobjs, "get") \
                            else xobjs[name]
                    except Exception:
                        xo = None
                    if xo is None:
                        continue
                    subtype = str(xo.get("/Subtype"))
                    if subtype == "/Form":
                        mtx = xo.get("/Matrix")
                        try:
                            m = (tuple(float(x) for x in mtx) if mtx
                                 else (1, 0, 0, 1, 0, 0))
                        except Exception:
                            m = (1, 0, 0, 1, 0, 0)
                        child_ctm = _multiply_ctm(m, ctm)
                        bb = None
                        try:
                            if "/BBox" in xo:
                                raw = [float(x) for x in xo.BBox]
                                bb = (min(raw[0], raw[2]), min(raw[1], raw[3]),
                                      max(raw[0], raw[2]), max(raw[1], raw[3]))
                        except Exception:
                            bb = None
                        page_bb = (_bbox_to_page(child_ctm, bb)
                                   if bb else None)
                        child_site = _DoSite(uid, i, page_bb)
                        do_sites.append(child_site)
                        walk(xo, "form", child_ctm,
                             resources_of(xo, resources), depth + 1,
                             child_site)
                        # Bubble subtree facts up to the enclosing site so an
                        # ancestor container is also known to contain text.
                        if site is not None:
                            site.has_text = site.has_text or \
                                child_site.has_text
                            site.has_legit_text = site.has_legit_text or \
                                child_site.has_legit_text
                            site.has_paint = site.has_paint or \
                                child_site.has_paint
                    elif subtype == "/Image":
                        if site is not None:
                            site.has_paint = True

    walk(page, "page", (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
         page.Resources if "/Resources" in page else None, 0, None)
    return units, shows, rects, do_sites


# --------------------------------------------------------------------------
# Suppression strategy
# --------------------------------------------------------------------------
def _select_container_for_region(do_sites, region):
    """
    Choose the tightest Do-site that cleanly frames `region` and whose
    subtree contains no legitimate (long-run) text. Returns the _DoSite or
    None if the overlay cannot be isolated from legitimate content.
    """
    candidates = []
    for s in do_sites:
        if s.page_bb is None or not s.has_paint:
            continue
        w = s.page_bb[2] - s.page_bb[0]
        h = s.page_bb[3] - s.page_bb[1]
        if w > MAX_CONTAINER_W or h > MAX_CONTAINER_H:
            continue
        if not _frames_region(s.page_bb, region, CONTAINER_MARGIN):
            continue
        if s.has_legit_text:
            # Contains body-length text -> not a clean overlay wrapper.
            continue
        candidates.append((w * h, s))
    if not candidates:
        return None
    # Tightest (smallest area) container that frames the region.
    candidates.sort(key=lambda t: t[0])
    return candidates[0][1]


def _collect_region_siblings(do_sites, chosen, region):
    """
    Given a chosen container Do-site, also collect sibling Do-sites in the
    SAME parent unit whose boxes overlap the region. This captures the
    patch-image forms that accompany the forged-text form within one edit
    group. Returns a list of _DoSite to suppress (including `chosen`).
    """
    group = [chosen]
    for s in do_sites:
        if s is chosen:
            continue
        if s.parent_uid != chosen.parent_uid:
            continue
        if s.page_bb is None:
            continue
        if s.has_legit_text:
            continue
        w = s.page_bb[2] - s.page_bb[0]
        h = s.page_bb[3] - s.page_bb[1]
        if w > MAX_CONTAINER_W or h > MAX_CONTAINER_H:
            continue
        if _rects_overlap(s.page_bb, region, CONTAINER_MARGIN):
            group.append(s)
    return group


# --- text_over_text / white_box decisions, now container-aware -----------
_WB_MIN_MASK_HEIGHT = 4.0   # pts; below this a fill cannot hide a glyph row
_WB_V_TOL = 2.0             # pts; baseline must sit inside the rect


def _white_box_inline_targets(units, shows, rects, region):
    """
    For one white-box finding region, return the operations an inline
    (non-container) removal would drop, split into the two parts of the
    alteration:

      fill  : [(unit_id, op_idx), ...]  the rectangle path + fill ops
      text  : [show dict, ...]          text painted on top of the box

    Returns None when no qualifying fill matches the region (hairline
    rules are not masks; see _decide_white_box_inline).
    """
    matched = [r for r in rects
               if _rects_match(r["rect"], region, RECT_MATCH_TOLERANCE)
               and (r["rect"][3] - r["rect"][1]) >= _WB_MIN_MASK_HEIGHT]
    if not matched:
        return None
    fill = []
    for r in matched:
        u = units.get(r["unit_id"])
        if u is None or u.shared:
            continue
        fill.append((r["unit_id"], r["re_idx"]))
        fill.append((r["unit_id"], r["fill_idx"]))
    text = []
    seen = set()
    for r in matched:
        rx0, ry0, rx1, ry1 = r["rect"]
        for sh in shows:
            if sh["order"] <= r["order"]:
                continue
            if (rx0 - _WB_V_TOL <= sh["x"] <= rx1 + _WB_V_TOL and
                    ry0 - _WB_V_TOL <= sh["y"] <= ry1 + _WB_V_TOL):
                u = units.get(sh["unit_id"])
                key = (sh["unit_id"], sh["idx"])
                if u is not None and not u.shared and key not in seen:
                    seen.add(key)
                    text.append(sh)
    return {"fill": fill, "text": text}


def _decide_white_box_inline(units, shows, rects, regions, recovered_out,
                             info_kinds):
    """
    Fallback for white-box overlays that are NOT wrapped in a container form
    but drawn inline in a stream: drop the matched white rect and the text
    painted on top of it. Only applied to regions not already recovered via
    a container.

    Evidentiary safety: a matched rect is only treated as a genuine masking
    overlay if it is tall enough to actually cover a line of text. Thin
    hairline fills (e.g. table/email separator rules) are NOT masks; if the
    only thing matching a finding region is a hairline, the region is left
    untouched (skipped) rather than risk deleting legitimate nearby text.
    The text sweep is confined to glyphs whose baseline falls within the
    rect's own vertical span (plus a small tolerance), never a wide band.
    """
    for ridx, region in enumerate(regions):
        if ridx in recovered_out:
            continue
        t = _white_box_inline_targets(units, shows, rects, region)
        if not t:
            continue
        ok = False
        for uid, idx in t["fill"]:
            units[uid].drop.add(idx)
            ok = True
        for sh in t["text"]:
            units[sh["unit_id"]].drop.add(sh["idx"])
            ok = True
        if ok:
            recovered_out.add(ridx)
            info_kinds.add("white_box")


def _decide_text_inline(units, shows, regions, recovered_out, info_kinds):
    """
    Fallback for text-over-text overlays drawn inline (not in a container).

    The underlying layer is the stream (page content or Form XObject) that
    drew the earliest text in the region. Only text from a DIFFERENT
    stream, drawn after the last text of that underlying stream, is
    treated as the overlay and suppressed; every show belonging to the
    underlying stream is kept, even if drawn later than other shows in the
    region (a region typically spans several original lines, and those
    lines are not overlays).

    When all text in the region comes from one stream, original and
    overlying text cannot be told apart from the content structure, so the
    region is skipped rather than guessed at (skip rather than mislead).

    Previously this kept only the single earliest show and dropped all
    later shows regardless of stream, which deleted genuine original lines
    whenever a region spanned more than one line.
    """
    for ridx, region in enumerate(regions):
        if ridx in recovered_out:
            continue
        in_region = [s for s in shows
                     if _point_in_rect(s["x"], s["y"], region,
                                       REGION_TOLERANCE)]
        if len(in_region) < 2:
            continue
        in_region.sort(key=lambda s: s["order"])
        base_uid = in_region[0]["unit_id"]
        last_base = max(s["order"] for s in in_region
                        if s["unit_id"] == base_uid)
        overlay_shows = [s for s in in_region
                         if s["unit_id"] != base_uid
                         and s["order"] > last_base]
        if not overlay_shows:
            continue                     # single stream: cannot tell; skip
        dropped = False
        for s in overlay_shows:
            u = units.get(s["unit_id"])
            if u is not None and not u.shared:
                u.drop.add(s["idx"])
                dropped = True
        if dropped:
            recovered_out.add(ridx)
            info_kinds.add("text_over_text")


# --------------------------------------------------------------------------
# Annotation suppression
# --------------------------------------------------------------------------
def _suppress_annotations(page, target_rects_pdf, objrefs=None):
    """
    Remove overlay annotations from a page.

    Matching is by object reference first (objrefs = set of
    (obj_num, obj_gen)), which is exact even when several annotations
    share the same /Rect (stacked box-and-replace overlays). Any
    target rectangles without an object reference fall back to
    rectangle matching, preserving the original behaviour.
    """
    objrefs = objrefs or set()
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
            match = False

            # Precise: object-reference match (distinguishes stacked
            # annotations that share the same /Rect).
            if objrefs:
                try:
                    ref = annot if hasattr(annot, "objgen") else obj
                    og = ref.objgen
                    if (int(og[0]), int(og[1])) in objrefs:
                        match = True
                except Exception:
                    pass

            # Fallback: rectangle match (for findings with no objref).
            if not match and target_rects_pdf:
                subtype = str(obj.get("/Subtype") or "")
                rect_raw = obj.get("/Rect")
                if (subtype in _OVERLAY_ANNOT_SUBTYPES
                        and rect_raw is not None):
                    coords = [float(v) for v in rect_raw]
                    ann = (min(coords[0], coords[2]),
                           min(coords[1], coords[3]),
                           max(coords[0], coords[2]),
                           max(coords[1], coords[3]))
                    for tr in target_rects_pdf:
                        if _rects_match(ann, tr, RECT_MATCH_TOLERANCE):
                            match = True
                            break

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
def build_revealed_pdf_bytes(src_path, page_index, findings, page_height,
                             keep_ops=None):
    """
    Produce a copy of the PDF at src_path with the given overlay findings
    suppressed on page `page_index` (0-based). `findings` is a list of dicts
    each with keys: 'bbox' (PyMuPDF top-left coords) and 'kind' (one of
    'white_box', 'text_over_text', 'annotation').

    Returns (pdf_bytes, info) where info is a dict:
        {"changed": bool,
         "kinds": set(...),            # kinds actually suppressed
         "ops_dropped": int,
         "annots_removed": int,
         "recovered": int,             # findings whose overlay was removed
         "skipped": int}               # findings left intact (not isolable)
    On failure or when nothing was suppressed, returns (None, info) with the
    counters still populated so the caller can label the finding.
    """
    info = {"changed": False, "kinds": set(), "ops_dropped": 0,
            "annots_removed": 0, "recovered": 0, "skipped": 0}

    # Preserve original finding order so we can report per-finding outcomes.
    cs_findings = []   # (orig_index, kind, pdf_rect)
    annot_rects = []
    annot_objrefs = set()   # (obj_num, obj_gen) for precise removal
    for idx, fnd in enumerate(findings):
        kind = fnd.get("kind", "other")
        rect = _finding_rect_to_pdf(fnd["bbox"], page_height)
        if kind in ("white_box", "text_over_text"):
            cs_findings.append((idx, kind, rect))
        elif kind == "annotation":
            on = fnd.get("obj_num")
            if on is not None:
                try:
                    annot_objrefs.add((int(on), int(fnd.get("obj_gen") or 0)))
                except (TypeError, ValueError):
                    annot_rects.append(rect)
            else:
                annot_rects.append(rect)

    try:
        pdf = pikepdf.open(src_path)
    except Exception:
        info["skipped"] = len(findings)
        return None, info

    try:
        if page_index < 0 or page_index >= len(pdf.pages):
            pdf.close()
            info["skipped"] = len(findings)
            return None, info
        page = pdf.pages[page_index]

        # --- Annotations -------------------------------------------------
        n_annot_targets = len(annot_rects) + len(annot_objrefs)
        if n_annot_targets:
            n = _suppress_annotations(page, annot_rects,
                                      objrefs=annot_objrefs)
            if n:
                info["annots_removed"] += n
                info["kinds"].add("annotation")
                info["recovered"] += n
            info["skipped"] += max(0, n_annot_targets - n)

        # --- Content stream + nested form tree ---------------------------
        if cs_findings:
            units, shows, rects, do_sites = _walk_content(page)

            regions = [r for (_, _, r) in cs_findings]

            # Primary: container-level suppression (patch + forged text),
            # with proper per-finding kind accounting.
            recovered = set()
            for ridx, (orig_idx, kind, region) in enumerate(cs_findings):
                chosen = _select_container_for_region(do_sites, region)
                if chosen is None:
                    continue
                group = _collect_region_siblings(do_sites, chosen, region)
                ok = False
                for site in group:
                    u = units.get(site.parent_uid)
                    if u is None or u.shared:
                        continue
                    u.drop.add(site.op_idx)
                    ok = True
                if ok:
                    recovered.add(ridx)
                    info["kinds"].add(kind)

            # Fallbacks for inline (non-wrapped) overlays.
            wb_regions = [r for (_, k, r) in cs_findings
                          if k == "white_box"]
            tt_regions = [r for (_, k, r) in cs_findings
                          if k == "text_over_text"]
            # Map region-index spaces for fallbacks
            wb_recovered = set()
            tt_recovered = set()
            # Translate already-recovered global indices into per-kind lists
            for ridx, (orig_idx, kind, region) in enumerate(cs_findings):
                if ridx in recovered:
                    if kind == "white_box":
                        wb_recovered.add(wb_regions.index(region))
                    else:
                        tt_recovered.add(tt_regions.index(region))

            _decide_white_box_inline(units, shows, rects, wb_regions,
                                     wb_recovered, info["kinds"])
            _decide_text_inline(units, shows, tt_regions,
                                tt_recovered, info["kinds"])

            # Recount recovered across both mechanisms.
            recovered_total = 0
            for ridx, (orig_idx, kind, region) in enumerate(cs_findings):
                if kind == "white_box":
                    if wb_regions.index(region) in wb_recovered:
                        recovered_total += 1
                else:
                    if tt_regions.index(region) in tt_recovered:
                        recovered_total += 1
            info["recovered"] += recovered_total
            info["skipped"] += len(cs_findings) - recovered_total

            # --- Keep-list: operations to leave in place even though a
            # finding removal selected them. Keys are (unit_seq, op_idx);
            # unit_seq is the unit's position in the deterministic walk
            # order, which is stable across separate opens of the file.
            # Used to render one part of an alteration on its own (e.g. a
            # white box without the text painted on it).
            if keep_ops:
                seq_to_uid = {i: uid for i, uid in enumerate(units)}
                for (useq, idx) in keep_ops:
                    uid = seq_to_uid.get(useq)
                    if uid is not None:
                        units[uid].drop.discard(idx)

            # --- Rewrite affected streams --------------------------------
            for u in units.values():
                if not u.drop or u.shared:
                    continue
                kept = [ins for j, ins in enumerate(u.ops)
                        if j not in u.drop]
                new_stream = pikepdf.unparse_content_stream(kept)
                if u.kind == "page":
                    page.Contents = pdf.make_stream(new_stream)
                else:
                    try:
                        u.obj.write(new_stream)
                    except Exception:
                        continue
                info["ops_dropped"] += len(u.drop)

        info["changed"] = bool(info["ops_dropped"] or info["annots_removed"])
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
        info["skipped"] = len(findings)
        return None, info


# --------------------------------------------------------------------------
# White-box alteration components (for step-by-step display)
# --------------------------------------------------------------------------
LINE_GROUP_TOL = 3.0   # pts; text shows within this baseline gap = one line


def _decode_show_text(operands):
    """Best-effort readable text for a Tj/TJ/'/" show. Returns None when
    the bytes are not plain printable text (e.g. 2-byte CID codes in a
    subset font), so the caller labels the line generically instead of
    showing garbage."""
    parts = []
    def take(o):
        if isinstance(o, pikepdf.String):
            parts.append(bytes(o))
        else:
            try:
                for e in o:
                    if isinstance(e, pikepdf.String):
                        parts.append(bytes(e))
            except TypeError:
                pass
    for o in operands:
        take(o)
    raw = b"".join(parts)
    if not raw:
        return None
    try:
        txt = raw.decode("latin-1")
    except Exception:
        return None
    printable = sum(1 for ch in txt if 32 <= ord(ch) < 127 or ord(ch) >= 160)
    if printable < 0.9 * len(txt):
        return None
    return txt.strip() or None


def white_box_components(src_path, page_index, finding, page_height):
    """
    Break one white-box alteration into its component edits so the visual
    report can show each step: the white box itself, and each line of text
    painted on it (in drawing order).

    Only inline white boxes are decomposed. If the region is recovered via
    a container Form XObject (box and text wrapped together), or nothing
    qualifying matches, None is returned and the alteration is shown as a
    single layer.

    Returns:
      {"fill": [(unit_seq, op_idx), ...],
       "lines": [{"ops": [(unit_seq, op_idx), ...],
                  "text": str or None,
                  "bbox": (x0, y0, x1, y1)  # PyMuPDF top-left pts (approx)
                 }, ...]}           # top-to-bottom
    """
    try:
        pdf = pikepdf.open(src_path)
    except Exception:
        return None
    try:
        if page_index < 0 or page_index >= len(pdf.pages):
            return None
        page = pdf.pages[page_index]
        units, shows, rects, do_sites = _walk_content(page)
        region = _finding_rect_to_pdf(finding["bbox"], page_height)
        if _select_container_for_region(do_sites, region) is not None:
            return None
        t = _white_box_inline_targets(units, shows, rects, region)
        if not t or not t["fill"]:
            return None
        seq = {uid: i for i, uid in enumerate(units)}

        fill = [(seq[uid], idx) for uid, idx in t["fill"]]

        # Group the painted text into lines by baseline (PDF coords).
        text = sorted(t["text"], key=lambda sh: (-sh["y"], sh["order"]))
        lines = []
        for sh in text:
            if lines and abs(lines[-1]["y"] - sh["y"]) <= LINE_GROUP_TOL:
                lines[-1]["shows"].append(sh)
            else:
                lines.append({"y": sh["y"], "shows": [sh]})

        rx1 = region[2]
        out_lines = []
        for ln in lines:
            ln["shows"].sort(key=lambda sh: sh["order"])
            texts = []
            for sh in ln["shows"]:
                try:
                    _op, operands = _instr_parts(
                        units[sh["unit_id"]].ops[sh["idx"]])
                    tx = _decode_show_text(operands)
                except Exception:
                    tx = None
                if tx and tx not in texts:      # drop exact repeats
                    texts.append(tx)
            x0 = min(sh["x"] for sh in ln["shows"])
            y = ln["y"]
            out_lines.append({
                "ops": [(seq[sh["unit_id"]], sh["idx"]) for sh in ln["shows"]],
                "text": " ".join(texts) if texts else None,
                # approx line box: baseline-3 .. baseline+10, to box edge
                "bbox": (x0, page_height - (y + 10.0),
                         rx1, page_height - (y - 3.0)),
            })
        return {"fill": fill, "lines": out_lines}
    except Exception:
        return None
    finally:
        try:
            pdf.close()
        except Exception:
            pass
