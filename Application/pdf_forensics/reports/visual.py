"""
Visual overlay report generator.

Produces a self-contained HTML report that shows, for a non-technical
reader, exactly where text/image overlays were detected on each page
of a PDF. The report contains:

  1. Full annotated page images — each flagged page rendered as a PNG
     with coloured boxes drawn over every detected overlay region, plus
     a numbered marker per finding and a legend.

  2. Per-finding detail cards — a zoomed-in crop of each overlay region
     shown at high magnification, alongside a plain-language description.

  3. Before/after reveal toggles — where an overlay's underlying content
     is recoverable, the reader can flip between "as displayed" (overlay
     present) and the page/region rendered with the overlay suppressed,
     showing what is hidden beneath. Two independent modes are offered:
     a page-level toggle (all overlays on the page suppressed at once) on
     the full page image, and a per-finding toggle (only that one overlay
     suppressed) on each detail card. Suppression is performed by
     reports/reveal.py. Where the underlying content cannot be cleanly
     recovered, the reveal is skipped for that finding and the card is
     labelled accordingly, rather than showing a misleading partial result.
     For printed copies, both states are shown stacked with captions.

Highlight colours by overlay kind:
  - text_over_text : red    (#E24B4A) — new text painted over old text
  - white_box      : orange (#EF9F27) — white rectangle masking content
  - annotation     : blue   (#4A90D9) — annotation placed over text

The report is self-contained: all images are embedded as base64 data
URIs, so the single HTML file can be moved, emailed, or printed.

Requires PyMuPDF (pymupdf) for page rendering. The original PDF file
must be available at the path recorded in the database.
"""

import os
import io
import base64
import sqlite3
import html as html_mod
from datetime import datetime

from pdf_forensics import __version__, __tool_name__, BUILD_DATE
from pdf_forensics.reports import reveal as _reveal

# Render resolution for full pages and crops (DPI)
PAGE_RENDER_DPI = 144
# Per-document counters reported in the performance log (reset per
# document): pages using the one-page fast path or the whole document;
# renders reused from a prior version; verification comparisons; and the
# seconds spent in each part of the work (t_*).
_RUN_T0 = None        # time.time() when the visual reports began

_VISUAL_STATS = {"fast": 0, "fallback": 0, "reused": 0, "verified": 0,
                 "mismatch": 0, "t_build": 0.0, "t_render": 0.0,
                 "t_isolate": 0.0, "t_whitebox": 0.0, "t_single": 0.0,
                 "t_check": 0.0, "t_encode": 0.0,
                 "nothing": 0, "measured": 0}

# ---------------------------------------------------------------------
# Render cache (1.2.0): a prior version's page that is unchanged from an
# earlier document's page (same fingerprint, analysis/page_reuse.py) and
# has the same findings shows the same images, so its renders are reused;
# the version's own numbering and labels are still built afresh. Keyed by
# (fingerprint, resolution, findings, part); least recently used first out.
# ---------------------------------------------------------------------
from collections import OrderedDict as _OrderedDict

_RENDER_CACHE = _OrderedDict()
_RENDER_BYTES = [0]
_RENDER_BUDGET = 1536 * 1024 * 1024


def _render_size(v):
    if isinstance(v, (bytes, bytearray)):
        return len(v)
    if isinstance(v, (tuple, list)):
        return sum(_render_size(x) for x in v)
    return 64


def _rc_get(key):
    v = _RENDER_CACHE.get(key)
    if v is not None:
        _RENDER_CACHE.move_to_end(key)
    return v


def _rc_put(key, value):
    if value is None or key in _RENDER_CACHE:
        return
    size = _render_size(value)
    _RENDER_CACHE[key] = value
    _RENDER_BYTES[0] += size
    while _RENDER_BYTES[0] > _RENDER_BUDGET and _RENDER_CACHE:
        _, old = _RENDER_CACHE.popitem(last=False)
        _RENDER_BYTES[0] -= _render_size(old)


def _mupdf_reset():
    """Stop MuPDF printing its diagnostics to the terminal and discard any
    pending ones; they are collected per document instead."""
    try:
        from pdf_forensics import _mupdf as _mu
        _mu.silence()       # PyMuPDF's own messages too (2026-11-23b)
    except Exception:
        pass
    try:
        import pymupdf
        pymupdf.TOOLS.mupdf_display_errors(False)
        pymupdf.TOOLS.mupdf_warnings(reset=True)
    except Exception:
        pass


def _mupdf_lines():
    """MuPDF's diagnostic lines since the last reset."""
    out = []
    try:
        from pdf_forensics import _mupdf as _mu      # PyMuPDF's and
        for item in _mu._PK_BUF:                      # pikepdf's own
            src, ln = item if isinstance(item, tuple) else ("pikepdf", item)
            out.append(f"{src}: {str(ln).strip()}")
        del _mu._PK_BUF[:]
    except Exception:
        pass
    try:
        import pymupdf
        text = pymupdf.TOOLS.mupdf_warnings(reset=True) or ""
    except Exception:
        return out
    return out + [ln.strip() for ln in text.splitlines() if ln.strip()]


def _mupdf_collect(session, doc_name):
    """MuPDF's diagnostics since the last reset (e.g. 'invalid ICC
    colorspace' for a malformed colour profile, which MuPDF replaces with a
    standard colour space): written to the session log with the document
    they came from. Returns the number of message lines."""
    return _mupdf_log(session, doc_name, _mupdf_lines())


def _mupdf_log(session, doc_name, lines):
    if lines and session:
        counts = {}
        for ln in lines:
            counts[ln] = counts.get(ln, 0) + 1
        summary = "; ".join(f"{m} (x{n})" if n > 1 else m
                            for m, n in list(counts.items())[:12])
        session.log(f"Visual report, {doc_name}: MuPDF reported "
                    f"{len(lines)} message(s) while rendering: {summary}",
                    "warning")
    return len(lines)


def clear_render_cache():
    _RENDER_CACHE.clear()
    _RENDER_BYTES[0] = 0
    _decoded_clear()


def _verify_on():
    try:
        from pdf_forensics.analysis import page_reuse as _pr
        return _pr.verify_mode()
    except Exception:
        return False


def _same_pixels(a_png, b_png):
    """True if two PNGs decode to identical pixels."""
    if a_png == b_png:
        return True
    try:
        from PIL import Image, ImageChops
        a = Image.open(io.BytesIO(a_png)).convert("RGBA")
        b = Image.open(io.BytesIO(b_png)).convert("RGBA")
        return a.size == b.size and ImageChops.difference(a, b).getbbox() \
            is None
    except Exception:
        return False


def _same_render(a, b):
    if isinstance(a, (bytes, bytearray)) and isinstance(b, (bytes, bytearray)):
        return _same_pixels(a, b)
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same_render(x, y)
                                        for x, y in zip(a, b))
    return a == b
CROP_RENDER_DPI = 300
CROP_PADDING_PTS = 12   # padding around a finding region in the crop

# Highlight colours (RGB 0-1 for PyMuPDF, hex for HTML/legend)
OVERLAY_STYLES = {
    "text_over_text": {
        "rgb": (0.886, 0.294, 0.290),
        "hex": "#E24B4A",
        "label": "Text painted over text",
    },
    "white_box": {
        "rgb": (0.937, 0.624, 0.153),
        "hex": "#EF9F27",
        "label": "White box masking content",
    },
    "annotation": {
        "rgb": (0.290, 0.565, 0.851),
        "hex": "#4A90D9",
        "label": "Annotation over text",
    },
    "other": {
        "rgb": (0.5, 0.5, 0.5),
        "hex": "#888888",
        "label": "Other overlay",
    },
}


def _load_overlay_findings(conn, analysis_id):
    """
    Load all TEXT_OVERLAY findings with bounding boxes for one
    analysis, grouped by page number.

    Returns: {page_number: [ {finding_id, detail, bbox, kind}, ... ]}
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT p.page_number, f.id, f.detail,
               f.bbox_x0, f.bbox_y0, f.bbox_x1, f.bbox_y1,
               f.overlay_kind, f.obj_num, f.obj_gen
        FROM findings f
        JOIN finding_types ft ON ft.id = f.finding_type_id
        JOIN pages p          ON p.id = f.page_id
        WHERE p.analysis_id = ?
          AND ft.code = 'TEXT_OVERLAY'
          AND f.bbox_x0 IS NOT NULL
        ORDER BY p.page_number, f.id
    """, (analysis_id,))

    by_page = {}
    for row in cur.fetchall():
        pg = row[0]
        by_page.setdefault(pg, []).append({
            "finding_id": row[1],
            "detail": row[2],
            "bbox": (row[3], row[4], row[5], row[6]),
            "kind": row[7] or "other",
            "obj_num": row[8],
            "obj_gen": row[9],
        })
    return by_page


def _get_analysis_info(conn, analysis_id):
    """Return (pdf_filename, pdf_path, pdf_md5) for an analysis."""
    cur = conn.cursor()
    cur.execute("""
        SELECT pdf_filename, pdf_path, pdf_md5
        FROM analyses WHERE id = ?
    """, (analysis_id,))
    row = cur.fetchone()
    return row if row else (None, None, None)


def _list_analyses_with_overlays(conn):
    """Return [(analysis_id, pdf_filename), ...] that have overlay findings."""
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT a.id, a.pdf_filename
        FROM analyses a
        JOIN pages p     ON p.analysis_id = a.id
        JOIN findings f  ON f.page_id = p.id
        JOIN finding_types ft ON ft.id = f.finding_type_id
        WHERE ft.code = 'TEXT_OVERLAY' AND f.bbox_x0 IS NOT NULL
        ORDER BY a.pdf_filename
    """)
    return cur.fetchall()


def _render_page_png(page, dpi):
    """Render a PyMuPDF page to PNG bytes at the given DPI."""
    import pymupdf
    zoom = dpi / 72.0
    mat = pymupdf.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return pix.tobytes("png"), zoom


def _draw_box_on_pixmap_png(png_bytes, boxes, zoom):
    """
    Draw highlight rectangles + numbered labels on a rendered page PNG.
    boxes: list of {bbox (pts, top-left origin), kind, number}.
    Returns new PNG bytes. Uses Pillow for drawing.
    """
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
    except Exception:
        font = ImageFont.load_default()

    for box in boxes:
        x0, y0, x1, y1 = box["bbox"]
        # Convert PDF points to pixel coordinates
        px0, py0 = x0 * zoom, y0 * zoom
        px1, py1 = x1 * zoom, y1 * zoom
        # Pad slightly so the box doesn't clip the glyphs
        pad = 3
        px0 -= pad; py0 -= pad; px1 += pad; py1 += pad

        style = OVERLAY_STYLES.get(box["kind"], OVERLAY_STYLES["other"])
        hexc = style["hex"].lstrip("#")
        rgb = tuple(int(hexc[i:i+2], 16) for i in (0, 2, 4))

        # Semi-transparent fill + solid border
        draw.rectangle([px0, py0, px1, py1],
                       fill=rgb + (40,), outline=rgb + (255,), width=3)

        # Numbered marker (circle with number) at top-left of box
        num = str(box["number"])
        marker_r = 16
        mx, my = px0, py0
        draw.ellipse([mx - marker_r, my - marker_r,
                      mx + marker_r, my + marker_r],
                     fill=rgb + (255,))
        # Center the number text in the circle
        try:
            bbox_txt = draw.textbbox((0, 0), num, font=font)
            tw = bbox_txt[2] - bbox_txt[0]
            th = bbox_txt[3] - bbox_txt[1]
        except Exception:
            tw, th = 10, 14
        draw.text((mx - tw / 2, my - th / 2 - 2), num,
                  fill=(255, 255, 255, 255), font=font)

    out = io.BytesIO()
    img.save(out, format="PNG", compress_level=6)
    return out.getvalue()


def _crop_region_png(page, bbox, dpi, padding_pts):
    """
    Render a zoomed crop of a single finding region.
    bbox in PDF points (top-left origin). Returns PNG bytes.
    """
    import pymupdf
    x0, y0, x1, y1 = bbox
    # Expand the crop region with padding, clamped to page bounds
    page_rect = page.rect
    cx0 = max(page_rect.x0, x0 - padding_pts)
    cy0 = max(page_rect.y0, y0 - padding_pts)
    cx1 = min(page_rect.x1, x1 + padding_pts)
    cy1 = min(page_rect.y1, y1 + padding_pts)
    clip = pymupdf.Rect(cx0, cy0, cx1, cy1)

    zoom = dpi / 72.0
    mat = pymupdf.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    return pix.tobytes("png")


def _render_revealed_page_png(pdf_bytes, page_index, dpi):
    """
    Render a full page from an in-memory revealed PDF (overlays
    suppressed) to PNG bytes. Rendered clean, without highlight boxes,
    so the reader sees the recovered content plainly.
    """
    import pymupdf
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[page_index]
        zoom = dpi / 72.0
        mat = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def _render_revealed_crop_png(pdf_bytes, page_index, bbox, dpi, padding_pts):
    """Render a zoomed crop of one region from a revealed PDF."""
    import pymupdf
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[page_index]
        return _crop_region_png(page, bbox, dpi, padding_pts)
    finally:
        doc.close()


# Decoded page images (build 2026-11-19d). On a page with many overlays the
# same images are compared again and again: the base (every overlay
# removed) for every overlay, and a white box's page for its measurement
# and for each line painted on it. They are decoded once and kept here,
# keyed by the PNG bytes object itself (the identical object, not equal
# contents, so no comparison is needed; the entry holds the bytes, so the
# key stays valid). The decoded images are only read, never changed.
_DECODED = _OrderedDict()
_DECODED_MAX = 8                        # images
_DECODED_BUDGET = 192 * 1024 * 1024     # bytes of decoded pixels
_DECODED_BYTES = [0]


def _decoded_rgb(png_bytes, keep=True):
    from PIL import Image
    k = id(png_bytes)
    hit = _DECODED.get(k)
    if hit is not None and hit[0] is png_bytes:
        _DECODED.move_to_end(k)
        return hit[1]
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    size = im.width * im.height * 3
    if keep and size <= _DECODED_BUDGET // 2:
        if hit is not None:                     # a stale entry (id reused)
            _DECODED_BYTES[0] -= hit[2]
        _DECODED[k] = (png_bytes, im, size)
        _DECODED_BYTES[0] += size
        while (len(_DECODED) > _DECODED_MAX
               or _DECODED_BYTES[0] > _DECODED_BUDGET):
            _DECODED_BYTES[0] -= _DECODED.popitem(last=False)[1][2]
    return im


# The opaque part of each layer just made (build 2026-11-19d), for the
# self-check of the same page, so it composites the layers without decoding
# each PNG again: {id(layer png bytes): (bytes, box, RGBA crop)}. The crop
# is the layer's pixels inside the box around its opaque pixels; outside it
# the layer is fully transparent, which leaves the composite unchanged.
_LAYERS = _OrderedDict()
_LAYERS_BUDGET = 128 * 1024 * 1024
_LAYERS_BYTES = [0]


def _layer_keep(png_bytes, layer):
    bb = layer.getchannel("A").getbbox()
    crop = layer.crop(bb) if bb else None
    size = crop.width * crop.height * 4 if crop is not None else 0
    if size > _LAYERS_BUDGET // 4:
        return
    _LAYERS[id(png_bytes)] = (png_bytes, bb, crop, size, layer.size)
    _LAYERS_BYTES[0] += size
    while _LAYERS_BYTES[0] > _LAYERS_BUDGET and _LAYERS:
        _LAYERS_BYTES[0] -= _LAYERS.popitem(last=False)[1][3]


def _layer_take(png_bytes, size):
    """(found, box, crop) for a layer made in this process at this size,
    else (False, None, None)."""
    hit = _LAYERS.pop(id(png_bytes), None)
    if hit is None:
        return False, None, None
    _LAYERS_BYTES[0] -= hit[3]
    if hit[0] is not png_bytes or hit[4] != size:
        return False, None, None
    return True, hit[1], hit[2]


def _decoded_clear():
    _DECODED.clear()
    _DECODED_BYTES[0] = 0
    _LAYERS.clear()
    _LAYERS_BYTES[0] = 0


def _isolate_layer_png(base_png, with_overlay_png, tolerance=10):
    """
    Isolate a single overlay as a transparent RGBA layer.

    base_png          : the page with ALL overlays removed (true original)
    with_overlay_png  : the page with ONLY this overlay present
    Returns PNG bytes (RGBA) that are opaque exactly where the overlay
    changed the page relative to the original, and fully transparent
    everywhere else. Stacking these layers over the base in z-order (via
    the report's checkboxes) reproduces the document with any chosen
    subset of overlays shown.

    tolerance absorbs anti-aliasing noise: a pixel is treated as part of
    the overlay only when it differs from the base by more than
    `tolerance` on any channel.
    """
    from PIL import ImageChops
    base = _decoded_rgb(base_png)                    # reused per page
    over = _decoded_rgb(with_overlay_png, keep=False)
    if base.size != over.size:
        over = over.resize(base.size)
    # Per-channel maximum difference. (A luminance-based difference
    # under-weights blue: e.g. dark-blue text painted over black text
    # differs by ~90 in blue but only ~10 in luminance, and would be
    # wrongly treated as unchanged and dropped from the layer.)
    r, g, b = ImageChops.difference(base, over).split()
    diff = ImageChops.lighter(ImageChops.lighter(r, g), b)
    # Binary mask: 255 where changed beyond tolerance, else 0.
    mask = diff.point(lambda v: 255 if v > tolerance else 0)
    layer = over.convert("RGBA")
    layer.putalpha(mask)
    out = io.BytesIO()
    layer.save(out, format="PNG", compress_level=6)
    png = out.getvalue()
    _layer_keep(png, layer)
    return png


def _nothing_wording(detail):
    """The analysis's description of a white box, for one measured to hide
    nothing: its claim that the box covers page content is replaced."""
    d = (detail or "").replace(
        "covers existing page content",
        "lies on blank paper (nothing visible beneath it)")
    return d.replace(
        "This pattern is characteristic of in-place text alteration without "
        "using an annotation.",
        "A white box with text painted on it is the pattern of in-place "
        "alteration, but this box hides nothing.")


def _classify_white_boxes(overlays, verified):
    """
    Mark the white boxes that hide nothing (1.3.0). Only on a page whose
    layers passed the self-check and whose base image had every overlay
    removed (verified: otherwise a box left in the base would measure 0
    and be taken for one that hides nothing), only for white boxes, and only
    when the measurement (hidden_px, from _hidden_pixels) was made;
    everything else stays in the main list. Nothing is dropped: boxes that
    hide nothing are listed in a collapsed group, still ticked and still
    toggleable. Sets "nothing" or "hides" on every item of the box's
    alteration, updates the descriptions, and returns the number of white
    boxes that hide nothing.
    """
    n_nothing = 0
    if verified:
        for it in overlays:
            if (it["kind"] == "white_box"
                    and it.get("part") in ("box", None)
                    and it.get("hidden_px") is not None):
                _VISUAL_STATS["measured"] += 1
                if it["hidden_px"] == 0:
                    n_nothing += 1
                    grp = it["group"]
                    for o in overlays:
                        if o["group"] == grp:
                            o["nothing"] = True
                            if o.get("group_detail"):
                                o["group_detail"] = _nothing_wording(
                                    o["group_detail"])
                    if it.get("part") is None:
                        it["detail"] = _nothing_wording(it["detail"])
                    if it.get("part") == "box":
                        it["detail"] = (
                            "White box drawn on the page. Removing "
                            "it changes no pixel where the page "
                            "beneath is not blank: it hides nothing "
                            "visible. The text listed after it was "
                            "painted on it.")
                    else:
                        it["detail"] = (
                            it["detail"] + " Removing it changes no "
                            "pixel where the page beneath is not "
                            "blank: it hides nothing visible.")
                else:
                    note = (f" Removing it reveals content: "
                            f"{it['hidden_px']} pixel(s) where the "
                            f"page beneath is not blank "
                            f"(at {PAGE_RENDER_DPI} dpi).")
                    it["detail"] = it["detail"] + note
                    it["hides"] = True
                    for o in overlays:
                        if o["group"] == it["group"]:
                            o["hides"] = True
    _VISUAL_STATS["nothing"] += n_nothing
    return n_nothing


def _hidden_pixels(base_png, with_png, bbox, zoom, tolerance=10):
    """
    How much a white box hides (1.3.0): the number of pixels inside the
    box's area that the box changes (any channel differs by more than
    `tolerance`, as for its layer) where the page without it is not blank
    (any channel below 255 - tolerance). 0 means removing the box reveals
    nothing: the box lies on blank paper.

    base_png : the page with every overlay removed (what lies beneath)
    with_png : the same page with only this box (and nothing painted on
               it) put back
    Any pixel counts; there is no minimum. Returns None if it cannot be
    measured (the box is then treated as hiding content).
    """
    from PIL import ImageChops
    try:
        base = _decoded_rgb(base_png)
        over = _decoded_rgb(with_png)   # its painted lines reuse it
        if base.size != over.size:
            return None
        pad = 2
        x0, y0, x1, y1 = (float(v) * zoom for v in bbox)
        box = (max(0, int(x0) - pad), max(0, int(y0) - pad),
               min(base.size[0], int(x1 + 0.999) + pad),
               min(base.size[1], int(y1 + 0.999) + pad))
        if box[2] <= box[0] or box[3] <= box[1]:
            return None
        b = base.crop(box)
        o = over.crop(box)
        r, g, bl = ImageChops.difference(b, o).split()
        changed = ImageChops.lighter(ImageChops.lighter(r, g), bl).point(
            lambda v: 255 if v > tolerance else 0)
        br, bg, bb = b.split()
        dark = ImageChops.darker(ImageChops.darker(br, bg), bb).point(
            lambda v: 255 if v < 255 - tolerance else 0)
        hit = ImageChops.multiply(changed, dark)
        return sum(hit.histogram()[1:])
    except Exception:
        return None


# Self-check thresholds: a pixel counts as different when any channel
# differs by more than COMPOSITE_PIXEL_TOL; the reconstruction is accepted
# when no more than COMPOSITE_MAX_DIFF_FRAC of the pixels inside the
# overlay regions differ (whole page if no regions).
COMPOSITE_PIXEL_TOL = 64
COMPOSITE_MAX_DIFF_FRAC = 0.02
COMPOSITE_REGION_PAD_PX = 6


def _composite_matches(base_png, layer_pngs, asis_png, regions_px=None):
    """
    Verify the layered reconstruction: base + all overlay layers (in
    z-order) must reproduce the page exactly as received. This catches
    any removal that destroyed genuine content or lost the overlay itself
    \u2014 failures the reveal step cannot see, because it reports a
    destructive removal as a successful one.

    regions_px : list of (x0, y0, x1, y1) pixel boxes to compare within
                 (the overlay areas, where errors would appear). When
                 None/empty the whole page is compared.

    Returns (ok, diff_fraction).
    """
    from PIL import Image, ImageChops
    asis = Image.open(io.BytesIO(asis_png)).convert("RGB")
    comp = Image.open(io.BytesIO(base_png)).convert("RGBA")
    if comp.size != asis.size:
        comp = comp.resize(asis.size)
    for lp in layer_pngs:
        if not lp:
            continue
        found, bb, crop = _layer_take(lp, comp.size)
        if found:                       # made here: no need to decode it
            if bb is None:
                continue                # fully transparent
            comp.alpha_composite(crop, dest=bb[:2])
            continue
        lay = Image.open(io.BytesIO(lp)).convert("RGBA")
        if lay.size != comp.size:
            lay = lay.resize(comp.size)
        # Only the part of the layer that is not transparent (build
        # 2026-11-19d): a fully transparent pixel leaves the composite
        # exactly as it was, so the result is the same, without blending
        # the whole page for each overlay.
        bb = lay.getchannel("A").getbbox()
        if bb:
            comp.alpha_composite(lay, dest=bb[:2], source=bb)
    diff = ImageChops.difference(comp.convert("RGB"), asis)
    # per-pixel max channel difference
    r, g, b = diff.split()
    mx = ImageChops.lighter(ImageChops.lighter(r, g), b)
    mask = mx.point(lambda v: 255 if v > COMPOSITE_PIXEL_TOL else 0)

    W, H = asis.size
    boxes = []
    for (x0, y0, x1, y1) in (regions_px or []):
        x0 = max(0, int(x0) - COMPOSITE_REGION_PAD_PX)
        y0 = max(0, int(y0) - COMPOSITE_REGION_PAD_PX)
        x1 = min(W, int(x1) + COMPOSITE_REGION_PAD_PX)
        y1 = min(H, int(y1) + COMPOSITE_REGION_PAD_PX)
        if x1 > x0 and y1 > y0:
            boxes.append((x0, y0, x1, y1))
    if not boxes:
        boxes = [(0, 0, W, H)]

    total = 0
    differ = 0
    for bx in boxes:
        crop = mask.crop(bx)
        hist = crop.histogram()
        total += crop.size[0] * crop.size[1]
        differ += hist[255]
    frac = (differ / total) if total else 0.0
    return frac <= COMPOSITE_MAX_DIFF_FRAC, frac


def _b64_png(png_bytes):
    """Return a data URI for PNG bytes."""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


from pdf_forensics.perf import timed as _timed



# ---------------------------------------------------------------------
# Where each document's visual report spends its time (1.2.0): seconds per
# kind of work, accumulated in _VISUAL_STATS and reported per document in
# the performance log. The functions are wrapped once here; the rendering
# code itself is unchanged.
# ---------------------------------------------------------------------
def _stat_timer(key, fn):
    import functools
    import time as _time

    @functools.wraps(fn)
    def wrapper(*a, **k):
        t0 = _time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            _VISUAL_STATS[key] += _time.perf_counter() - t0
    return wrapper


_render_page_png = _stat_timer("t_render", _render_page_png)
_render_revealed_page_png = _stat_timer("t_render", _render_revealed_page_png)
_isolate_layer_png = _stat_timer("t_isolate", _isolate_layer_png)
_composite_matches = _stat_timer("t_check", _composite_matches)
_b64_png = _stat_timer("t_encode", _b64_png)
def _build_variant_checked(*a, **k):
    """Build a variant from the shared page state; in verification mode
    also build it from scratch and compare the two (the from-scratch
    variant is used if they differ)."""
    out = _reveal.build_revealed_pdf_bytes(*a, **k)
    if _verify_on():
        ref = _reveal._build_revealed_pdf_bytes_reference(*a, **k)
        ok = (out[0] is None) == (ref[0] is None) and out[1] == ref[1]
        if ok and out[0] is not None:
            try:
                idx = 0 if k.get("single_page") else a[1]
                ok = (_reveal.variant_digest(out[0], idx)
                      == _reveal.variant_digest(ref[0], idx))
            except Exception:
                ok = False
        _VISUAL_STATS["verified" if ok else "mismatch"] += 1
        if not ok:
            return ref
    return out


_build_variant = _stat_timer("t_build", _build_variant_checked)
_white_box = _stat_timer(
    "t_whitebox", lambda *a, **k: _reveal.white_box_components(*a, **k))
_single_page = _stat_timer(
    "t_single", lambda *a, **k: _reveal.single_page_pdf_bytes(*a, **k))

def _generate_visual_report_impl(db_path, output_path, analysis_id=None,
                                 session=None):
    """
    Generate a visual overlay report.

    If analysis_id is given, reports on that single PDF. Otherwise,
    generates a combined report covering every analyzed PDF that has
    overlay findings.

    Returns the number of findings visualized, or 0 if none / error.
    """
    try:
        import pymupdf
    except ImportError:
        if session:
            session.log("Visual report requires PyMuPDF.", "error")
        return 0

    conn = sqlite3.connect(db_path)

    if analysis_id is not None:
        targets = [(analysis_id,
                    _get_analysis_info(conn, analysis_id)[0])]
    else:
        targets = _list_analyses_with_overlays(conn)

    if not targets:
        conn.close()
        if session:
            session.log("No overlay findings with coordinates found.",
                        "warning")
        return 0

    data = []
    for aid, pdf_filename in targets:
        d = _doc_section_data(conn, aid, session, pymupdf)
        if d is not None:
            data.append(d)
    conn.close()
    return _visual_write(db_path, output_path, data, session)


def _doc_section_data(conn, aid, session, pymupdf, pages=None,
                      log_doc=True):
    """
    One document's part of a visual report, as data (build 2026-11-19e):
    None (no findings, or the file could not be opened), {"kind":
    "missing", "html", "n"} when the file is not found, or {"kind": "doc",
    "fname", "fmd5", "blocks" (one per page), "n" (findings), "nothing"}.

    pages, if given, is the set of page numbers to render (a part of a
    long document made in another process): every page is still read and
    numbered, so overlay numbers are the same as for the whole document;
    only the selected pages are rendered and logged. log_doc=False leaves
    the document-level messages (file not found or not opened) to another
    part.
    """
    from pdf_forensics.analysis.detectors import (
        merge_text_over_white_box)
    fname, fpath, fmd5 = _get_analysis_info(conn, aid)
    by_page = _load_overlay_findings(conn, aid)
    if not by_page:
        return None

    # Open the source PDF
    if not fpath or not os.path.isfile(fpath):
        if session and log_doc:
            session.log(
                f"Source PDF not found for visual report: {fpath}",
                "warning")
        # Still emit a text-only section, and count its findings so
        # the report is written even when no page could be rendered.
        return {"kind": "missing",
                "html": _render_missing_pdf_section(fname, fpath, by_page),
                "n": sum(len(v) for v in by_page.values())}

    try:
        doc = pymupdf.open(fpath)
    except Exception as e:
        if session and log_doc:
            session.log(f"Could not open {fpath}: {e}", "error")
        return None

    page_blocks = []
    finding_counter = 0
    total_findings = 0
    total_nothing = 0

    for page_num in sorted(by_page.keys()):
        findings = by_page[page_num]
        if page_num < 1 or page_num > len(doc):
            continue
        # Fold text-over-text detections that sit inside a white box
        # into that box (one alteration). Also protects databases
        # analysed before the engine applied the same consolidation.
        findings, _n_merged = merge_text_over_white_box(
            findings, kind_key="kind")
        if _n_merged and session and (pages is None or page_num in pages):
            session.log(f"Visual report p{page_num}: {_n_merged} "
                        f"text-over-text finding(s) consolidated into "
                        f"a white-box alteration")
        page = doc[page_num - 1]
        page_index = page_num - 1
        try:
            page_height = float(page.rect.height)
        except Exception:
            page_height = 792.0
        try:
            page_width = float(page.rect.width)
        except Exception:
            page_width = 612.0

        # Number overlays in z-order (paint order).
        for fnd in findings:
            finding_counter += 1
            fnd["_number"] = finding_counter
        # Pages not in this part are numbered (above) but not rendered.
        if pages is not None and page_num not in pages:
            continue

        # The page exactly as received (what a PDF viewer shows).
        # Render cache (1.2.0): an unchanged page of a prior version
        # with the same findings reuses an earlier document's renders.
        _fp = _reveal.page_fingerprint(fpath, page_index)
        _fsig = tuple(
            (f.get("kind"),
             tuple(round(float(v), 2) for v in (f.get("bbox") or ())),
             f.get("obj_num"), f.get("obj_gen")) for f in findings)
        _ck = (_fp, PAGE_RENDER_DPI, _fsig) if _fp else None
        _verify = _verify_on()

        def _cached(part, compute):
            """compute(), unless this page was rendered before with
            the same findings; in verification mode always compute and
            compare with the stored result."""
            key = (_ck, part) if _ck is not None else None
            hit = _rc_get(key) if key is not None else None
            if hit is not None and not _verify:
                _VISUAL_STATS["reused"] += 1
                return hit
            val = compute()
            if hit is not None:
                if _same_render(val, hit):
                    _VISUAL_STATS["verified"] += 1
                else:
                    _VISUAL_STATS["mismatch"] += 1
                    if session:
                        session.log(f"Visual report p{page_num}: reused "
                                    f"render {part!r} differs from a "
                                    f"fresh render (fresh render used)",
                                    "warning")
            elif key is not None:
                _rc_put(key, val)
            return val

        asis_png, zoom = _cached(
            "asis", lambda: _render_page_png(page, PAGE_RENDER_DPI))
        asis_uri = _b64_png(asis_png)

        # Fast path: build this page's variants as one-page PDFs, but
        # only if the unedited one-page copy renders identically to the
        # page as received; otherwise use the whole document.
        def _single_ok():
            try:
                _sp = _single_page(fpath, page_index)
                return bool(_sp) and _render_revealed_page_png(
                    _sp, 0, PAGE_RENDER_DPI) == asis_png
            except Exception:
                return False
        _single = _cached("single", _single_ok)
        _VISUAL_STATS["fast" if _single else "fallback"] += 1
        _ri = 0 if _single else page_index

        def _base():
            try:
                rb, rinfo = _build_variant(
                    fpath, page_index, findings, page_height,
                    single_page=_single)
                if rb and rinfo.get("recovered", 0) >= 1:
                    return (_render_revealed_page_png(
                                rb, _ri, PAGE_RENDER_DPI),
                            rinfo.get("skipped", 0) == 0)
                return asis_png, False
            except Exception:
                return asis_png, False
        base_png, base_all_removed = _cached("base", _base)

        def _render_variant(remove, keep=None):
            """Page with `remove` findings suppressed (except the
            `keep` operations). Unchanged page -> the as-received
            render."""
            rb2, _info2 = _build_variant(
                fpath, page_index, remove, page_height, keep_ops=keep,
                single_page=_single)
            if rb2 is None:
                return asis_png
            return _render_revealed_page_png(
                rb2, _ri, PAGE_RENDER_DPI)

        def _layer(onto_png, remove, keep, bbox):
            """(layer_png, variant_png) for one overlay: the page with
            `remove` suppressed except `keep`, rendered in full and
            isolated against onto_png."""
            full = _render_variant(remove, keep)
            return _isolate_layer_png(onto_png, full), full

        items = []
        for _j, fnd in enumerate(findings):
            n = fnd["_number"]
            comp = None
            if fnd["kind"] == "white_box":
                def _wb(_f=fnd):
                    try:
                        c = _white_box(
                            fpath, page_index, _f, page_height)
                    except Exception:
                        c = None
                    if c and not c["lines"]:
                        c = None
                    return c if c is not None else False
                comp = _cached(("wb", _j), _wb) or None
            try:
                if comp:
                    fill_layer, fill_png = _cached(
                        ("fill", _j),
                        lambda: _layer(base_png, findings, comp["fill"],
                                       fnd["bbox"]))
                    items.append({
                        "number": f"{n}a", "group": n, "part": "box",
                        "hidden_px": _hidden_pixels(
                            base_png, fill_png, fnd["bbox"], zoom),
                        "kind": "white_box", "title": "White box",
                        "detail": ("White box drawn over the original "
                                   "content, hiding what lies beneath. "
                                   f"First step of alteration {n}; the "
                                   "text listed after it was then "
                                   "painted on the box."),
                        "bbox": fnd["bbox"],
                        "layer_png": fill_layer})
                    for j, ln in enumerate(comp["lines"]):
                        lbl = (f"{n}{chr(ord('b') + j)}" if j < 25
                               else f"{n}.{j + 2}")
                        line_layer, _only = _cached(
                            ("line", _j, j),
                            lambda: _layer(fill_png, findings,
                                           comp["fill"] + ln["ops"],
                                           ln["bbox"]))
                        if ln["text"]:
                            title = "Painted text"
                            det = ("Text painted on the white box: "
                                   f"\u201c{ln['text']}\u201d.")
                        else:
                            title = "Painted text"
                            det = ("Text painted on the white box (line "
                                   f"{j + 1}); its characters use a font "
                                   "encoding that cannot be shown as "
                                   "plain text here.")
                        items.append({
                            "number": lbl, "group": n, "part": "line",
                            "kind": "text_over_text", "title": title,
                            "line_text": ln["text"],
                            "detail": det, "bbox": ln["bbox"],
                            "layer_png": line_layer})
                    items[-1 - len(comp["lines"])]["group_detail"] = \
                        fnd["detail"]
                else:
                    others = [o for o in findings if o is not fnd]
                    if others:
                        one_layer, _v = _cached(
                            ("one", _j),
                            lambda: _layer(base_png, others, None,
                                           fnd["bbox"]))
                    else:
                        one_layer, _v = _cached(
                            ("one", _j),
                            lambda: (_isolate_layer_png(base_png,
                                                        asis_png),
                                     asis_png))
                    items.append({
                        "number": str(n), "group": n, "part": None,
                        "hidden_px": (_hidden_pixels(
                            base_png, _v, fnd["bbox"], zoom)
                            if fnd["kind"] == "white_box" else None),
                        "kind": fnd["kind"], "title": None,
                        "detail": fnd["detail"], "bbox": fnd["bbox"],
                        "layer_png": one_layer})
            except Exception as e:
                if session:
                    session.log(f"Overlay layer {n} (p{page_num}) "
                                f"failed: {e}", "warning")
                items.append({
                    "number": str(n), "group": n, "part": None,
                    "kind": fnd["kind"], "title": None,
                    "detail": fnd["detail"], "bbox": fnd["bbox"],
                    "layer_png": None})
        overlays = []
        layer_pngs = []
        for z, it in enumerate(items, 1):
            lp = it.pop("layer_png")
            layer_pngs.append(lp)
            it["z"] = z
            it["layer_uri"] = _b64_png(lp) if lp else None
            overlays.append(it)

        # Self-check: base + all layers must reproduce the page as
        # received. If it does not, the decomposition is unreliable
        # (a removal destroyed genuine content or lost the overlay),
        # so show the page as received and do not offer toggles.
        regions_px = [(b[0] * zoom, b[1] * zoom, b[2] * zoom, b[3] * zoom)
                      for b in (o["bbox"] for o in overlays) if b]
        try:
            verified, diff_frac = _composite_matches(
                base_png, layer_pngs, asis_png, regions_px)
        except Exception:
            verified, diff_frac = False, None
        if not all(layer_pngs):
            verified = False
        if not verified and session:
            session.log(
                f"Visual report p{page_num}: layered reconstruction "
                f"did not match the page as received"
                + (f" ({diff_frac:.1%} of overlay-area pixels differ)"
                   if diff_frac is not None else "")
                + "; showing the page as received without toggles.",
                "warning")

        # Which white boxes hide nothing (1.3.0); see
        # _classify_white_boxes.
        n_nothing = _classify_white_boxes(
            overlays, verified and base_all_removed)

        page_blocks.append({
            "page_num": page_num,
            "nothing": n_nothing,
            "uid": f"{aid}-{page_num}",
            "mode": "layered" if verified else "as_received",
            "asis_uri": asis_uri,
            "base_uri": _b64_png(base_png) if verified else None,
            "base_all_removed": base_all_removed,
            "page_w": page_width,
            "page_h": page_height,
            "overlays": overlays,
            "count": len(findings),
        })
        total_findings += len(findings)
        total_nothing += n_nothing

    doc.close()
    _reveal.clear_source_cache()
    return {"kind": "doc", "fname": fname, "fmd5": fmd5,
            "blocks": page_blocks, "n": total_findings,
            "nothing": total_nothing}


def _visual_write(db_path, output_path, data, session):
    """Write a visual report from _doc_section_data results (the whole
    document's, or its parts' joined by _join_parts)."""
    doc_sections = []
    total_findings = 0
    total_nothing = 0
    for d in data:
        if d["kind"] == "missing":
            doc_sections.append(d["html"])
        else:
            doc_sections.append(_render_doc_section(
                d["fname"], d["fmd5"], d["blocks"]))
            total_nothing += d["nothing"]
        total_findings += d["n"]

    if total_findings == 0:
        if session:
            session.log("No overlays could be visualized.", "warning")
        return 0

    html = _assemble_html(doc_sections, db_path, total_findings,
                          session=session, nothing=total_nothing)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    if session:
        session.log(f"Visual report generated: {total_findings} "
                    f"finding(s) -> {output_path}")
        session.register_output("report", output_path)

    return total_findings


def _esc(val):
    return html_mod.escape(str(val)) if val is not None else ""


def _init_badge_positions(overlays, page_w, page_h):
    """Assign each overlay an anchor (its true on-page location) and a
    default badge position close to that anchor. Badges start near their
    target rather than being fanned far away; coincident badges get only
    a small, capped nudge so they remain individually grabbable. The
    examiner can then drag any badge, with a leader line tracing back to
    the anchor (as on the relationship graphs)."""
    def clamp(v):
        return max(0.0, min(100.0, v))
    placed = []
    for ov in overlays:
        x0, y0, x1, y1 = ov["bbox"]
        lx = clamp((x0 / page_w * 100.0) if page_w else 0.0)
        ly = clamp((y0 / page_h * 100.0) if page_h else 0.0)
        off = sum(1 for (px, py) in placed
                  if abs(px - lx) < 3.5 and abs(py - ly) < 3.5)
        placed.append((lx, ly))
        ov["anchor_left"] = lx
        ov["anchor_top"] = ly
        # Default badge: just up-and-left of the corner, with a small
        # capped nudge for coincident badges (drag handles the rest).
        k = min(off, 5)
        ov["badge_left"] = clamp(lx - 2.2 - k * 1.8)
        ov["badge_top"] = clamp(ly - 3.2 - k * 0.6)


def _render_doc_section(fname, fmd5, page_blocks):
    """Build the HTML for one document's section: an interactive layered
    page with a left-hand checkbox panel (one per overlay), fanned
    numbered badges, and a text summary beneath. No per-overlay crops."""
    parts = []
    parts.append('<div class="doc-section">')
    parts.append(f'<h2 class="doc-title">{_esc(fname)}</h2>')
    if fmd5:
        parts.append(f'<div class="doc-md5">MD5: '
                     f'<span class="mono">{_esc(fmd5)}</span></div>')

    for pb in page_blocks:
        uid = pb["uid"]
        overlays = pb["overlays"]
        _init_badge_positions(overlays, pb["page_w"], pb["page_h"])

        n_nothing = pb.get("nothing", 0)
        parts.append('<div class="page-block">')
        parts.append(
            f'<h3 class="page-title">Page {pb["page_num"]} '
            f'<span class="page-count">({pb["count"]} '
            f'overlay{"s" if pb["count"] != 1 else ""} detected'
            + (f', shown as {len(overlays)} separate edits'
               if len(overlays) > pb["count"] else '')
            + (f'; {n_nothing} hide{"s" if n_nothing == 1 else ""} '
               f'nothing visible' if n_nothing else '')
            + ')</span></h3>')

        parts.append('<div class="page-layout">')

        layered = pb.get("mode") == "layered"

        # ---- LEFT: checkbox control panel ----
        parts.append('<div class="overlay-controls">')
        if layered:
            parts.append(
                '<div class="ctrl-head">Overlays'
                f'<span class="ctrl-btns">'
                f'<button type="button" class="ctrl-all" '
                f'data-page="{uid}" data-set="on">All</button>'
                f'<button type="button" class="ctrl-all" '
                f'data-page="{uid}" data-set="off">None</button>'
                '</span></div>')
            parts.append(
                '<div class="ctrl-hint">Tick an overlay to show it on the '
                'page; untick to peel it away. With every overlay ticked '
                'the page is shown exactly as received; unticking all '
                'shows the recovered original. Overlays are numbered in '
                'stacking order (1 = bottom).</div>')
        else:
            parts.append('<div class="ctrl-head">Overlays</div>')
            parts.append(
                '<div class="ctrl-hint not-separable">The overlays on this '
                'page could not be separated reliably: rebuilding the page '
                'from its layers did not reproduce the page as received. '
                'To avoid showing a misleading reconstruction, the page is '
                'shown exactly as received and the overlays cannot be '
                'toggled individually. The numbers mark where each was '
                'detected; see the summary below and examine the source '
                'file directly.</div>')
        parts.append(
            f'<label class="marker-toggle"><input type="checkbox" '
            f'class="markers-toggle" data-page="{uid}" checked> '
            f'Show numbers &amp; lines</label>')
        def _li(ov):
            out = []
            style = OVERLAY_STYLES.get(ov["kind"], OVERLAY_STYLES["other"])
            n = ov["number"]
            dis = "" if layered else " disabled"
            if ov.get("part") == "box":
                out.append(
                    f'<li class="ov-group">Alteration {ov["group"]}: '
                    f'white box with text painted on it (one edit, '
                    f'shown step by step)</li>')
            sub = " sub" if ov.get("part") else ""
            label = _esc(ov.get("title") or style["label"])
            if ov.get("part") == "line" and ov.get("line_text"):
                snippet = ov["line_text"]
                if len(snippet) > 34:
                    snippet = snippet[:33] + "\u2026"
                label += (f'<span class="ov-snippet">'
                          f'\u201c{_esc(snippet)}\u201d</span>')
            if ov.get("hides") and ov.get("part") in ("box", None):
                label += '<span class="tag-hides">hides content</span>'
            badge_bg = "#8A8A8A" if ov.get("nothing") else style["hex"]
            out.append(
                f'<li class="overlay-item{sub}" data-ov="{uid}-{n}">'
                f'<label><input type="checkbox" class="ov-toggle" '
                f'data-ov="{uid}-{n}" data-page="{uid}" checked{dis}>'
                f'<span class="ov-badge-mini" '
                f'style="background:{badge_bg};">{n}</span>'
                f'<span class="ov-kind">{label}</span>'
                f'</label></li>')
            return "".join(out)

        main = [ov for ov in overlays if not ov.get("nothing")]
        quiet = [ov for ov in overlays if ov.get("nothing")]
        parts.append('<ul class="overlay-list">')
        parts.extend(_li(ov) for ov in main)
        parts.append('</ul>')
        if quiet:
            # White boxes measured to hide nothing (1.3.0): still listed,
            # still ticked (so the page is shown as received) and still
            # toggleable; their numbers are shown on the page when the
            # group is opened.
            parts.append(
                f'<details class="ov-nothing" data-page="{uid}">'
                f'<summary>Hides nothing visible ({n_nothing})</summary>'
                f'<ul class="overlay-list">')
            parts.extend(_li(ov) for ov in quiet)
            parts.append(
                '</ul><div class="nothing-note">Removing these changes no '
                'pixel where the page beneath is not blank. They are '
                'usually layout (cell backgrounds, panels) but are listed, '
                'and can be shown and toggled, for completeness. Open this '
                'group to show their numbers on the page.</div></details>')
        parts.append('</div>')   # overlay-controls

        # ---- RIGHT: page stage ----
        parts.append('<div class="page-stage-wrap">')
        parts.append(f'<div class="page-stage" id="stage-{uid}">')
        if layered:
            parts.append(
                f'<img class="base-layer" src="{pb["base_uri"]}" '
                f'alt="Page {pb["page_num"]} original (overlays removed)">')
            for ov in overlays:
                n = ov["number"]
                if ov["layer_uri"]:
                    parts.append(
                        f'<img class="ov-layer" id="layer-{uid}-{n}" '
                        f'data-ov="{uid}-{n}" style="z-index:{ov["z"]};" '
                        f'src="{ov["layer_uri"]}" alt="Overlay {n}">')
            # The page exactly as received, shown on top whenever every
            # overlay is ticked, so the opening view always matches what
            # a PDF viewer displays.
            parts.append(
                f'<img class="asis-layer" id="asis-{uid}" '
                f'data-page="{uid}" src="{pb["asis_uri"]}" '
                f'alt="Page {pb["page_num"]} as received">')
        else:
            parts.append(
                f'<img class="base-layer" src="{pb["asis_uri"]}" '
                f'alt="Page {pb["page_num"]} as received">')
        # Leader lines: one SVG line per badge, anchor -> badge, in a
        # percentage coordinate system so it tracks the responsive image.
        # Updated live as badges are dragged.
        parts.append(
            f'<svg class="leader-svg" id="leaders-{uid}" '
            f'viewBox="0 0 100 100" preserveAspectRatio="none">')
        for ov in overlays:
            style = OVERLAY_STYLES.get(ov["kind"], OVERLAY_STYLES["other"])
            n = ov["number"]
            nc = " nothing" if ov.get("nothing") else ""
            parts.append(
                f'<line class="leader-line{nc}" data-ov="{uid}-{n}" '
                f'x1="{ov["anchor_left"]:.2f}" y1="{ov["anchor_top"]:.2f}" '
                f'x2="{ov["badge_left"]:.2f}" y2="{ov["badge_top"]:.2f}" '
                f'stroke="{style["hex"]}"></line>')
        parts.append('</svg>')
        # Anchor dots (true location) + draggable numbered badges.
        for ov in overlays:
            style = OVERLAY_STYLES.get(ov["kind"], OVERLAY_STYLES["other"])
            n = ov["number"]
            nc = " nothing" if ov.get("nothing") else ""
            parts.append(
                f'<span class="ov-anchor{nc}" data-ov="{uid}-{n}" '
                f'style="left:{ov["anchor_left"]:.2f}%;'
                f'top:{ov["anchor_top"]:.2f}%;'
                f'background:{style["hex"]};"></span>')
            parts.append(
                f'<span class="ov-badge{nc}" data-ov="{uid}-{n}" '
                f'title="Drag to reposition (line traces back to the '
                f'overlay)" '
                f'style="left:{ov["badge_left"]:.2f}%;'
                f'top:{ov["badge_top"]:.2f}%;'
                f'background:{style["hex"]};">{n}</span>')
        parts.append('</div>')   # page-stage
        if layered and not pb.get("base_all_removed", False):
            parts.append(
                '<div class="reveal-note sm">Note: not every detected '
                'overlay could be cleanly removed from the base image, so '
                'the fully-peeled view may still contain residual overlay '
                'content. Examine the source file directly to confirm.</div>')
        parts.append('</div>')   # page-stage-wrap

        parts.append('</div>')   # page-layout

        # ---- Summary beneath (text only, no crops) ----
        parts.append('<div class="overlay-summary">')
        parts.append('<div class="summary-head">Overlay summary</div>')

        def _rows(ovs):
            out = []
            for ov in ovs:
                style = OVERLAY_STYLES.get(ov["kind"],
                                           OVERLAY_STYLES["other"])
                n = ov["number"]
                if ov.get("part") == "box":
                    out.append(
                        f'<div class="summary-row summary-group" '
                        f'data-ov="{uid}-{n}">'
                        f'<span class="summary-kind">Alteration '
                        f'{ov["group"]}</span><span class="summary-detail">'
                        f'{_esc(ov.get("group_detail") or "")}</span></div>')
                sub = " sub" if ov.get("part") else ""
                badge_bg = "#8A8A8A" if ov.get("nothing") else style["hex"]
                out.append(
                    f'<div class="summary-row{sub}" data-ov="{uid}-{n}">'
                    f'<span class="ov-badge-mini" '
                    f'style="background:{badge_bg};">{n}</span>'
                    f'<span class="summary-kind">'
                    f'{_esc(ov.get("title") or style["label"])}</span>'
                    f'<span class="summary-detail">{_esc(ov["detail"])}'
                    f'</span></div>')
            return "".join(out)
        parts.append(_rows(main))
        if quiet:
            parts.append(
                f'<details class="sum-nothing"><summary>{n_nothing} white '
                f'box{"es" if n_nothing != 1 else ""} that hide'
                f'{"s" if n_nothing == 1 else ""} nothing visible</summary>'
                + _rows(quiet) + '</details>')
        parts.append('</div>')   # overlay-summary
        parts.append('</div>')   # page-block

    parts.append('</div>')   # doc-section
    return "".join(parts)


def _render_missing_pdf_section(fname, fpath, by_page):
    """Section shown when the source PDF can't be located."""
    parts = [f'<div class="doc-section">',
             f'<h2 class="doc-title">{_esc(fname)}</h2>',
             f'<div class="warning">The source PDF could not be '
             f'located at <span class="mono">{_esc(fpath)}</span>, '
             f'so page images cannot be rendered. The detected '
             f'overlays are listed below.</div>']
    for page_num in sorted(by_page.keys()):
        parts.append(f'<h3 class="page-title">Page {page_num}</h3>')
        parts.append('<div class="findings-grid">')
        for i, fnd in enumerate(by_page[page_num], 1):
            style = OVERLAY_STYLES.get(fnd["kind"],
                                       OVERLAY_STYLES["other"])
            parts.append(
                f'<div class="finding-card">'
                f'<div class="finding-head" '
                f'style="border-left:6px solid {style["hex"]};">'
                f'<span class="finding-kind">{style["label"]}</span>'
                f'</div>'
                f'<div class="finding-detail">'
                f'{_esc(fnd["detail"])}</div></div>')
        parts.append('</div>')
    parts.append('</div>')
    return "".join(parts)


def _assemble_html(doc_sections, db_path, total_findings, session=None,
                   nothing=0):
    """Wrap document sections in the full HTML page with logo + legend."""
    nothing_note = ""
    if nothing:
        nothing_note = (
            f" Of these, {nothing} "
            + ("is a white box that hides" if nothing == 1
               else "are white boxes that hide")
            + " nothing visible (listed in a collapsed group on each page).")
    from pdf_forensics import branding as _branding
    from pdf_forensics.database import compute_file_md5

    cfg = _branding.load_branding()
    case_number = session.case_number if session else ""
    agency_logo = _branding.get_agency_logo_data_uri(cfg)
    info_pairs = _branding.case_info_pairs(case_number, cfg)
    classification = _branding.classification_text(cfg)
    foot_text = _branding.footer_text(case_number, cfg)
    db_md5 = compute_file_md5(db_path) if db_path else ""

    # Application (suite) logo for the left of the banner
    app_logo = ""
    try:
        from pdf_forensics.assets import get_logo_base64
        app_logo = get_logo_base64() or ""
    except Exception:
        pass
    app_logo_html = ""
    if app_logo:
        app_logo_html = (
            f'<img class="app-logo" src="{app_logo}" '
            f'alt="PDF Forensics Suite">')

    # Case/agency info block (middle banner column)
    info_block = ""
    if info_pairs:
        rows_html = "".join(
            f'<div class="bi-row"><span class="bi-label">{_esc(lbl)}</span>'
            f'<span class="bi-val">{_esc(val)}</span></div>'
            for lbl, val in info_pairs)
        info_block = f'<div class="case-info">{rows_html}</div>'

    # Agency logo (right banner column)
    agency_logo_html = ""
    if agency_logo:
        agency_logo_html = (
            f'<img class="agency-logo" src="{agency_logo}" '
            f'alt="Agency logo">')

    classification_html = ""
    if classification:
        classification_html = (
            f'<div id="classification">{_esc(classification)}</div>')

    footer_html = ""
    if foot_text or db_md5:
        md5_part = (f'<span class="ft-md5">DB MD5: {_esc(db_md5)}</span>'
                    if db_md5 else "")
        footer_html = (
            f'<div id="print-footer">'
            f'<span class="ft-left">{_esc(foot_text)}</span>'
            f'{md5_part}</div>')

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Legend items
    legend_items = []
    for key in ("text_over_text", "white_box", "annotation"):
        s = OVERLAY_STYLES[key]
        legend_items.append(
            f'<span class="legend-item">'
            f'<span class="legend-swatch" '
            f'style="background:{s["hex"]};"></span>'
            f'{s["label"]}</span>')
    legend_html = "".join(legend_items)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Visual Overlay Report — {__tool_name__}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #F4F4F4; color: #1B1B1B;
    font-family: "Segoe UI", "SF Pro Text", "DejaVu Sans", sans-serif;
    font-size: 14px; line-height: 1.5;
  }}
  #classification {{
    background: #ED1C24; color: #fff; text-align: center;
    font-size: 12px; font-weight: 700; letter-spacing: 1px;
    text-transform: uppercase; padding: 5px 10px;
  }}
  #header {{
    background: #252525; color: #F0F0F0;
    padding: 18px 30px; border-bottom: 3px solid #ED1C24;
    display: flex; align-items: center; gap: 24px;
  }}
  #header .app-logo {{ height: 54px; flex-shrink: 0; }}
  #header .header-text {{ flex: 1; min-width: 0; }}
  #header h1 {{ font-size: 22px; font-weight: 700; }}
  #header .subtitle {{ color: #A8A8A8; font-size: 12px; margin-top: 4px;
    line-height: 1.5; }}
  #header .case-info {{
    border-left: 1px solid #444; padding-left: 24px;
    font-size: 12px; line-height: 1.7; flex-shrink: 0; max-width: 320px;
  }}
  #header .case-info .bi-row {{ white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; }}
  #header .case-info .bi-label {{ color: #8A8A8A; }}
  #header .case-info .bi-label::after {{ content: ": "; }}
  #header .case-info .bi-val {{ color: #F0F0F0; }}
  #header .agency-logo {{ height: 60px; max-width: 150px;
    object-fit: contain; flex-shrink: 0; }}
  #print-footer {{ display: none; }}
  #intro {{
    background: #fff; margin: 20px 30px; padding: 20px 24px;
    border-radius: 6px; border: 1px solid #E0E0E0;
  }}
  #intro p {{ margin-bottom: 10px; }}
  #intro .big {{ font-size: 16px; font-weight: 600; color: #ED1C24; }}
  #legend {{
    display: flex; gap: 24px; flex-wrap: wrap;
    margin: 14px 0 0 0; padding-top: 14px;
    border-top: 1px solid #E8E8E8;
  }}
  .legend-item {{ display: flex; align-items: center;
    font-size: 13px; color: #444; }}
  .legend-swatch {{ width: 16px; height: 16px; border-radius: 3px;
    margin-right: 7px; display: inline-block; }}
  .doc-section {{
    background: #fff; margin: 20px 30px; padding: 24px;
    border-radius: 6px; border: 1px solid #E0E0E0;
  }}
  .doc-title {{ font-size: 19px; color: #1B1B1B;
    border-bottom: 2px solid #ED1C24; padding-bottom: 8px;
    margin-bottom: 6px; }}
  .doc-md5 {{ font-size: 12px; color: #888; margin-bottom: 18px; }}
  .mono {{ font-family: "Consolas","Monaco",monospace; font-size: 12px; }}
  .page-block {{ margin-bottom: 40px; }}
  .page-title {{ font-size: 16px; color: #333; margin-bottom: 12px; }}
  .page-count {{ color: #ED1C24; font-weight: 600; font-size: 14px; }}
  .page-image-wrap {{
    text-align: center; background: #FAFAFA; padding: 16px;
    border: 1px solid #E8E8E8; border-radius: 4px; margin-bottom: 20px;
  }}
  .page-image {{ max-width: 100%; height: auto;
    box-shadow: 0 2px 12px rgba(0,0,0,0.15); }}
  .findings-grid {{
    display: grid; grid-template-columns: repeat(auto-fill,
    minmax(320px, 1fr)); gap: 18px;
  }}
  .finding-card {{
    border: 1px solid #E0E0E0; border-radius: 6px; overflow: hidden;
    background: #fff;
  }}
  .finding-head {{
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px; background: #FAFAFA;
    border-bottom: 1px solid #EEE;
  }}
  .finding-num {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 26px; height: 26px; border-radius: 50%;
    color: #fff; font-weight: 700; font-size: 14px;
  }}
  .finding-kind {{ font-weight: 600; font-size: 14px; color: #333; }}
  .crop-wrap {{
    text-align: center; background: #fff; padding: 14px;
    border-bottom: 1px solid #EEE;
  }}
  .crop-image {{ max-width: 100%; height: auto;
    border: 1px solid #DDD; image-rendering: crisp-edges; }}
  .finding-detail {{
    padding: 12px 14px; font-size: 13px; color: #444; line-height: 1.6;
  }}
  .warning {{
    background: #FFF4E5; border: 1px solid #EF9F27;
    color: #8A5A00; padding: 12px 16px; border-radius: 4px;
    margin: 12px 0;
  }}
  #footer {{ text-align: center; color: #999; font-size: 12px;
    padding: 20px; }}
  /* Before/after toggle */
  .toggle-bar {{ display: flex; align-items: center; gap: 8px;
    margin-bottom: 12px; }}
  .toggle-label {{ font-size: 13px; color: #666; margin-right: 2px; }}
  .crop-toggle {{ display: flex; gap: 6px; margin-bottom: 8px; }}
  .tg-btn {{ font: inherit; font-size: 13px; cursor: pointer;
    border: 1px solid #C9C9C9; background: #fff; color: #333;
    padding: 5px 14px; border-radius: 4px; transition: all .12s ease; }}
  .tg-btn.sm {{ font-size: 12px; padding: 3px 10px; }}
  .tg-btn:hover {{ border-color: #ED1C24; }}
  .tg-btn.active {{ background: #252525; color: #fff;
    border-color: #252525; font-weight: 600; }}
  .img-stack .layer {{ display: none; }}
  .img-stack .layer.active {{ display: block; }}
  .print-cap {{ display: none; }}
  .reveal-note {{ font-size: 12px; color: #666; margin-top: 8px;
    padding: 8px 12px; background: #F0F4F8; border-radius: 4px;
    border-left: 3px solid #4A90D9; }}
  .reveal-note.best-effort {{ background: #FFF8EC;
    border-left-color: #EF9F27; color: #7A5500; }}
  .reveal-note.sm {{ font-size: 11px; padding: 5px 9px; margin-top: 6px; }}
  /* ---- Layered interactive overlay UI ---- */
  .page-layout {{ display: flex; gap: 18px; align-items: flex-start;
    flex-wrap: wrap; }}
  .overlay-controls {{ flex: 0 0 260px; width: 260px; background: #1b1b1b;
    border: 1px solid #333; border-radius: 8px; padding: 12px; }}
  .ctrl-head {{ font-weight: 700; color: #fff; display: flex;
    justify-content: space-between; align-items: center; margin-bottom: 6px; }}
  .ctrl-btns .ctrl-all {{ font: inherit; font-size: 12px; cursor: pointer;
    margin-left: 6px; background: #2a2a2a; color: #ddd; border: 1px solid #444;
    border-radius: 5px; padding: 2px 8px; }}
  .ctrl-btns .ctrl-all:hover {{ border-color: #ED1C24; }}
  .ctrl-hint {{ font-size: 12px; color: #9a9a9a; margin-bottom: 10px;
    line-height: 1.4; }}
  .overlay-list {{ list-style: none; margin: 0; padding: 0; }}
  .overlay-item {{ margin: 3px 0; }}
  .overlay-item label {{ display: flex; align-items: center; gap: 7px;
    cursor: pointer; font-size: 13px; color: #ddd; padding: 4px 6px;
    border-radius: 5px; }}
  .overlay-item label:hover, .overlay-item.hot label {{ background: #262626; }}
  .overlay-item input[disabled] {{ opacity: .4; }}
  .ov-badge-mini {{ display: inline-flex; align-items: center;
    justify-content: center; min-width: 20px; height: 20px; padding: 0 5px;
    border-radius: 11px; color: #fff; font-weight: 700; font-size: 12px; }}
  .ov-kind {{ flex: 1; }}
  .ov-group {{ font-size: 12px; font-weight: 700; color: #f2c48d;
    margin: 8px 0 2px; padding: 0 6px; }}
  .overlay-item.sub {{ margin-left: 14px; }}
  .ov-snippet {{ display: block; font-size: 11px; color: #bdbdbd;
    font-style: italic; }}
  .summary-row.summary-group {{ background: #f4f4f4; font-weight: 600; }}
  .summary-row.sub {{ padding-left: 26px; }}
  .ov-note {{ color: #8a8a8a; font-size: 11px; }}
  .page-stage-wrap {{ flex: 1 1 420px; min-width: 320px; }}
  .page-stage {{ position: relative; display: inline-block; max-width: 100%;
    border: 1px solid #333; line-height: 0; }}
  .page-stage .base-layer {{ display: block; max-width: 100%; height: auto; }}
  .page-stage .ov-layer {{ position: absolute; top: 0; left: 0;
    width: 100%; height: auto; pointer-events: none; }}
  .ov-badge {{ position: absolute; transform: translate(-50%, -50%);
    min-width: 22px; height: 22px; padding: 0 6px; border-radius: 12px;
    color: #fff; font-weight: 700; font-size: 12px; line-height: 22px;
    text-align: center; box-shadow: 0 0 0 2px #fff; z-index: 999;
    cursor: grab; user-select: none; touch-action: none; }}
  .ov-badge:active, .ov-badge.dragging {{ cursor: grabbing;
    outline: 2px solid #111; }}
  .ov-badge.hot {{ outline: 3px solid #111; }}
  .ov-anchor {{ position: absolute; width: 9px; height: 9px;
    border-radius: 50%; transform: translate(-50%, -50%);
    box-shadow: 0 0 0 1.5px #fff; z-index: 998; pointer-events: none; }}
  .leader-svg {{ position: absolute; top: 0; left: 0; width: 100%;
    height: 100%; z-index: 990; pointer-events: none; overflow: visible; }}
  .leader-line {{ stroke-width: 1.5; vector-effect: non-scaling-stroke;
    opacity: 0.8; stroke-dasharray: 4 3; }}
  .leader-line.hot {{ stroke-width: 2.5; opacity: 1; stroke-dasharray: none; }}
  .page-stage .asis-layer {{ position: absolute; top: 0; left: 0;
    width: 100%; height: auto; z-index: 900; pointer-events: none; }}
  /* "Show numbers & lines" off: hide every marker on that page. */
  .page-stage.hide-markers .ov-badge,
  .page-stage.hide-markers .ov-anchor,
  .page-stage.hide-markers .leader-svg {{ display: none !important; }}
  /* White boxes that hide nothing (1.3.0): numbers shown when opened */
  .page-stage:not(.show-nothing) .nothing {{ display: none !important; }}
  details.ov-nothing {{ margin-top: 10px; border-top: 1px solid #3A3A3A;
         padding-top: 8px; }}
  details.ov-nothing > summary {{ cursor: pointer; color: #C8C8C8;
         font-size: 13px; font-weight: 600; }}
  .nothing-note {{ color: #9a9a9a; font-size: 11px; margin-top: 6px;
         line-height: 1.35; }}
  details.sum-nothing {{ margin-top: 8px; }}
  details.sum-nothing > summary {{ cursor: pointer; color: #555;
         font-size: 13px; font-weight: 600; padding: 6px 0; }}
  .tag-hides {{ margin-left: 8px; background: #E24B4A; color: #fff;
         font-size: 10px; padding: 1px 6px; border-radius: 8px;
         font-weight: 700; white-space: nowrap; }}
  .marker-toggle {{ display: flex; align-items: center; gap: 7px;
    font-size: 13px; color: #ddd; margin: 4px 0 10px; cursor: pointer;
    padding: 4px 6px; border-top: 1px solid #333; padding-top: 9px; }}
  .ctrl-hint.not-separable {{ color: #f2c48d; border-left: 3px solid #EF9F27;
    padding-left: 8px; }}
  /* Summary is always black-on-white so it stays legible on screen and
     when the page is printed/saved to PDF. */
  .overlay-summary {{ margin-top: 16px; background: #fff; color: #000;
    border: 1px solid #ccc; border-radius: 8px; padding: 12px 14px; }}
  .summary-head {{ font-weight: 700; color: #000; margin-bottom: 8px;
    font-size: 14px; }}
  .summary-row {{ display: flex; gap: 10px; align-items: baseline;
    padding: 6px 6px; border-radius: 5px; font-size: 13px; color: #000;
    border-top: 1px solid #eee; }}
  .summary-row:first-of-type {{ border-top: none; }}
  .summary-row.hot {{ background: #fff3cd; }}
  .summary-kind {{ font-weight: 700; color: #000; white-space: nowrap; }}
  .summary-detail {{ color: #000; }}
  @media print {{
    @page {{
      margin: 1.4cm 1.2cm 1.8cm 1.2cm;
      @bottom-right {{
        content: "Page " counter(page) " of " counter(pages);
        font-size: 9px; color: #777;
      }}
    }}
    body {{ background: #fff; }}
    #classification {{
      -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    #header {{ background: #252525 !important;
      -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .doc-section, #intro {{ margin: 10px 0; border: none; }}
    .finding-num, .legend-swatch, .finding-head {{
      -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .page-block {{ page-break-inside: avoid; }}
    .finding-card {{ page-break-inside: avoid; }}
    #print-footer {{
      display: flex; justify-content: space-between; align-items: center;
      position: fixed; bottom: 0; left: 0; right: 0;
      padding: 6px 4px; border-top: 1px solid #bbb;
      font-size: 9px; color: #555;
    }}
    #print-footer .ft-md5 {{
      font-family: "Consolas","Monaco",monospace; color: #777; }}
    /* In print, show both layers stacked with captions; hide toggles */
    .toggle-bar, .crop-toggle {{ display: none !important; }}
    .img-stack .layer {{ display: block !important; }}
    .img-stack .layer + .layer {{ margin-top: 10px; }}
    .print-cap {{ display: block; font-size: 11px; font-weight: 700;
      color: #333; margin: 6px 0 4px; }}
    /* Layered UI in print: hide the controls, keep the page with all
       overlays shown (as received), and render the summary as text. */
    .overlay-controls {{ display: none !important; }}
    .page-layout {{ display: block; }}
    .page-stage {{ border: 1px solid #999; }}
    /* print shows the page exactly as toggled on screen */
    .overlay-summary {{ color: #000 !important; background: #fff !important;
      border: 1px solid #999; }}
    .summary-kind, .summary-detail, .summary-head {{ color: #000 !important; }}
    .summary-row {{ color: #000 !important; }}
    /* keep badges + leader lines where the examiner placed them */
    .ov-badge, .leader-svg {{ -webkit-print-color-adjust: exact;
      print-color-adjust: exact; }}
  }}
</style>
</head>
<body>
{classification_html}
<div id="header">
  {app_logo_html}
  <div class="header-text">
    <h1>Visual Overlay Report</h1>
    <div class="subtitle">{__tool_name__} v{__version__} &middot; build {BUILD_DATE} &mdash;
      Generated {now} &mdash;
      Database: {_esc(os.path.basename(db_path))}</div>
  </div>
  {info_block}
  {agency_logo_html}
</div>
{footer_html}

<div id="intro">
  <p class="big">{total_findings} overlay finding(s) detected across
    the analyzed document(s).{nothing_note}</p>
  <p>This report shows where text or image overlays were detected on
    each page. An overlay is content placed on top of other content,
    which can be used to alter what a reader sees &mdash; for example,
    changing a visible date or amount while the original value remains
    hidden underneath in the file.</p>
  <p>Each flagged page is shown with the detected overlays numbered in
    stacking order. Use the checkboxes on the left of each page to show or
    hide individual overlays: start with all overlays shown (the document
    as received) and untick them to peel the layers away &mdash; unticking
    all reveals the recovered original content beneath. A text summary of
    each overlay, including any text it carries, appears below the page.</p>
  <p><strong>Note:</strong> A detected overlay is an indicator that
    warrants review. It is not, by itself, proof of fraudulent intent.
    Some overlays have legitimate explanations. A qualified examiner
    should review each finding in context.</p>
  <div id="legend">{legend_html}</div>
</div>

{"".join(doc_sections)}

<div id="footer">
  {__tool_name__} v{__version__} &mdash; Visual Overlay Report
</div>

<script>
(function () {{
  function cssEsc(s) {{
    return s.replace(/["\\\\]/g, "\\\\$&");
  }}
  // Show/hide one overlay: its layer, badge, anchor dot AND leader line
  // (hiding the badge alone would leave a stray line on the page).
  function setOverlay(ovid, on) {{
    var q = '[data-ov="' + cssEsc(ovid) + '"]';
    document.querySelectorAll('.ov-layer' + q).forEach(function (el) {{
      el.style.display = on ? "block" : "none";
    }});
    document.querySelectorAll(
      '.ov-badge' + q + ', .ov-anchor' + q + ', .leader-line' + q)
      .forEach(function (el) {{ el.style.display = on ? "" : "none"; }});
  }}
  // With every overlay on a page ticked, show the page exactly as
  // received (guaranteed to match a PDF viewer); otherwise show the
  // base + the ticked layers.
  function refreshAsis(page) {{
    var img = document.getElementById("asis-" + page);
    if (!img) return;
    var boxes = document.querySelectorAll(
      '.ov-toggle[data-page="' + cssEsc(page) + '"]');
    var all = true;
    boxes.forEach(function (cb) {{
      if (!cb.disabled && !cb.checked) all = false;
    }});
    img.style.display = all ? "block" : "none";
  }}
  document.addEventListener("change", function (ev) {{
    var cb = ev.target;
    if (!cb.classList) return;
    if (cb.classList.contains("ov-toggle")) {{
      setOverlay(cb.getAttribute("data-ov"), cb.checked);
      refreshAsis(cb.getAttribute("data-page"));
    }} else if (cb.classList.contains("markers-toggle")) {{
      var st = document.getElementById("stage-" + cb.getAttribute("data-page"));
      if (st) st.classList.toggle("hide-markers", !cb.checked);
    }}
  }});
  // "All" / "None" buttons set every overlay on a page.
  document.addEventListener("click", function (ev) {{
    var b = ev.target.closest ? ev.target.closest(".ctrl-all") : null;
    if (!b) return;
    var page = b.getAttribute("data-page");
    var on = b.getAttribute("data-set") === "on";
    document.querySelectorAll(
      '.ov-toggle[data-page="' + cssEsc(page) + '"]').forEach(function (cb) {{
        if (cb.disabled) return;
        cb.checked = on;
        setOverlay(cb.getAttribute("data-ov"), on);
      }});
    refreshAsis(page);
  }});
  // Hover-linking: hovering a badge, list item or summary row highlights
  // every element that refers to the same overlay.
  function hot(ovid, on) {{
    document.querySelectorAll('[data-ov="' + cssEsc(ovid) + '"]')
      .forEach(function (el) {{ el.classList.toggle("hot", on); }});
  }}
  ["mouseover", "mouseout"].forEach(function (evt) {{
    document.addEventListener(evt, function (ev) {{
      var t = ev.target.closest ? ev.target.closest("[data-ov]") : null;
      if (!t) return;
      hot(t.getAttribute("data-ov"), evt === "mouseover");
    }});
  }});

  // ---- Draggable badges with leader lines (graph-style) ----
  var drag = null;
  function updateLine(ovid) {{
    var line = document.querySelector('.leader-line[data-ov="'
      + cssEsc(ovid) + '"]');
    var badge = document.querySelector('.ov-badge[data-ov="'
      + cssEsc(ovid) + '"]');
    if (!line || !badge || !badge.parentElement) return;
    var stage = badge.parentElement.getBoundingClientRect();
    if (!stage.width || !stage.height) return;
    var bx = (parseFloat(badge.style.left) || 0);
    var by = (parseFloat(badge.style.top) || 0);
    line.setAttribute("x2", bx.toFixed(2));
    line.setAttribute("y2", by.toFixed(2));
  }}
  document.addEventListener("pointerdown", function (ev) {{
    var badge = ev.target.closest ? ev.target.closest(".ov-badge") : null;
    if (!badge) return;
    var stage = badge.parentElement;
    var rect = stage.getBoundingClientRect();
    drag = {{ badge: badge, stage: stage, rect: rect,
             ovid: badge.getAttribute("data-ov") }};
    badge.classList.add("dragging");
    badge.setPointerCapture && badge.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  }});
  document.addEventListener("pointermove", function (ev) {{
    if (!drag) return;
    var r = drag.rect;
    var x = ((ev.clientX - r.left) / r.width) * 100;
    var y = ((ev.clientY - r.top) / r.height) * 100;
    x = Math.max(0, Math.min(100, x));
    y = Math.max(0, Math.min(100, y));
    drag.badge.style.left = x.toFixed(2) + "%";
    drag.badge.style.top = y.toFixed(2) + "%";
    updateLine(drag.ovid);
  }});
  function endDrag() {{
    if (!drag) return;
    drag.badge.classList.remove("dragging");
    drag = null;
  }}
  document.addEventListener("pointerup", endDrag);

  // Boxes that hide nothing: show their numbers on the page while their
  // group is open; open every such group for printing.
  document.addEventListener("toggle", function (ev) {{
    var d = ev.target;
    if (!d.classList || !d.classList.contains("ov-nothing")) return;
    var st = document.getElementById("stage-" + d.getAttribute("data-page"));
    if (st) st.classList.toggle("show-nothing", d.open);
  }}, true);
  window.addEventListener("beforeprint", function () {{
    document.querySelectorAll("details.ov-nothing, details.sum-nothing")
      .forEach(function (d) {{ d.open = true; }});
  }});
  document.addEventListener("pointercancel", endDrag);
}})();
</script>

</body>
</html>"""



# ---------------------------------------------------------------------
# Per-document reports with an index page (1.1.6)
#
# With dozens or hundreds of documents, one combined report is impractical.
# generate_visual_reports() writes one report per document that has overlay
# findings into a folder beside the index ({index}_files/), and an index
# page listing them (sortable, filterable), each opening in a new tab.
# ---------------------------------------------------------------------

# The single-document / combined entry point, kept for compatibility.
generate_visual_report = _timed("report", "visual_overlay_combined")(
    _generate_visual_report_impl)


def _overlay_counts(conn, analysis_id, per_page=False):
    by_page = _load_overlay_findings(conn, analysis_id)
    kinds = {}
    for items in by_page.values():
        for f in items:
            kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    if per_page:
        return (len(by_page), sum(kinds.values()), kinds,
                {p: len(v) for p, v in by_page.items()})
    return len(by_page), sum(kinds.values()), kinds


def _source_path(conn, analysis_id):
    try:
        return _get_analysis_info(conn, analysis_id)[1]
    except Exception:
        return None


def _source_exists(conn, analysis_id):
    try:
        fpath = _get_analysis_info(conn, analysis_id)[1]
        return bool(fpath) and os.path.isfile(fpath)
    except Exception:
        return False


def _visual_one(db_path, it, session):
    """One document's visual report (in this process). Returns its timings
    and counters for the performance log."""
    import time as _time
    for _k in _VISUAL_STATS:
        _VISUAL_STATS[_k] = 0
    _mupdf_reset()
    _decoded_clear()
    t0 = _time.perf_counter()
    res = {"i": it["i"], "t_start": _time.time()}
    try:
        res["n"] = _generate_visual_report_impl(db_path, it["path"],
                                                analysis_id=it["aid"],
                                                session=session)
        res["elapsed"] = _time.perf_counter() - t0
        res["stats"] = dict(_VISUAL_STATS)
        res["mupdf"] = _mupdf_collect(session, it["pdf_filename"])
    except Exception as e:
        res["n"] = 0
        res["error"] = str(e)
    res["t_end"] = _time.time()
    return res


def _visual_part(db_path, it, session):
    """Part of a long document's report (build 2026-11-19e): its pages
    it["part_pages"] rendered in this process, returned as data for
    _join_parts; nothing is written here. Log entries go to session (a
    recording one in a worker)."""
    import time as _time
    for _k in _VISUAL_STATS:
        _VISUAL_STATS[_k] = 0
    _mupdf_reset()
    _decoded_clear()
    t0 = _time.perf_counter()
    res = {"i": it["i"], "part": it["part"], "t_start": _time.time()}
    try:
        import pymupdf
        conn = sqlite3.connect(db_path)
        try:
            res["data"] = _doc_section_data(
                conn, it["aid"], session, pymupdf,
                pages=set(it["part_pages"]), log_doc=it["part"] == 0)
        finally:
            conn.close()
        res["elapsed"] = _time.perf_counter() - t0
        res["stats"] = dict(_VISUAL_STATS)
        res["mupdf_lines"] = _mupdf_lines()
    except Exception as e:
        res["error"] = str(e)
    res["t_end"] = _time.time()
    return res


def _join_data(parts):
    """The parts' _doc_section_data results as one document's."""
    got = [d for d in parts if d is not None]
    if not got:
        return None
    if any(d["kind"] == "missing" for d in got):
        return next(d for d in got if d["kind"] == "missing")
    return {"kind": "doc", "fname": got[0]["fname"],
            "fmd5": got[0]["fmd5"],
            "blocks": [b for d in got for b in d["blocks"]],
            "n": sum(d["n"] for d in got),
            "nothing": sum(d["nothing"] for d in got)}


def _join_parts(db_path, it, outs, session):
    """Join a document's parts (in page order) and write its report, in
    the main process: the same report, log entries and counts as when the
    whole document is made at once (_visual_one). Log entries are recorded
    and returned in res["logs"], to be written in document order."""
    import time as _time
    from pdf_forensics.analysis.parallel import (RecordingSession,
                                                 session_info)
    outs = sorted(outs, key=lambda o: o.get("part", 0))
    logs = [e for o in outs for e in (o.get("logs") or [])]
    res = {"i": it["i"], "parts": len(outs),
           "t_start": min(o.get("t_start", _time.time()) for o in outs)}
    errors = [o["error"] for o in outs if "error" in o]
    if errors:
        res.update(n=0, error=errors[0], logs=logs, t_end=_time.time())
        return res
    rs = RecordingSession(session_info(session))
    t0 = _time.perf_counter()
    for _k in _VISUAL_STATS:
        _VISUAL_STATS[_k] = 0
    try:
        joined = _join_data([o.get("data") for o in outs])
        res["n"] = _visual_write(db_path, it["path"],
                                 [joined] if joined else [], rs)
        lines = [ln for o in outs for ln in o.get("mupdf_lines", [])]
        res["mupdf"] = _mupdf_log(rs, it["pdf_filename"], lines)
    except Exception as e:
        res.update(n=0, error=str(e))
    stats = dict(_VISUAL_STATS)
    for o in outs:
        for k, v in (o.get("stats") or {}).items():
            stats[k] = stats.get(k, 0) + v
    res["stats"] = stats
    res["elapsed"] = (sum(o.get("elapsed", 0.0) for o in outs)
                      + _time.perf_counter() - t0)
    res["logs"] = logs + rs.take()
    res["t_end"] = _time.time()
    return res


_VEVENTS = None       # progress queue in worker processes


def _visual_init(events):
    global _VEVENTS
    _VEVENTS = events


def _vemit(*evt):
    if _VEVENTS is not None:
        try:
            _VEVENTS.put_nowait(evt)
        except Exception:
            pass


def _visual_worker(spec):
    """Worker process: the visual reports of one document and its prior
    versions, in order (so unchanged pages reuse renders). Log entries are
    recorded and written by the main process (analysis/parallel.py)."""
    global _RENDER_BUDGET
    from pdf_forensics.analysis.parallel import RecordingSession
    _RENDER_BUDGET = spec["render_budget"]
    rs = RecordingSession(spec.get("session_info"))
    out = []
    import time as _time
    for it in spec["items"]:
        rs.take()
        key = (it["i"], it["part"]) if "part_pages" in it else it["i"]
        _vemit("start", key, _time.time())
        if "part_pages" in it:
            res = _visual_part(spec["db_path"], it, rs)
        else:
            res = _visual_one(spec["db_path"], it, rs)
        _vemit("end", key, _time.time())
        res["logs"] = rs.take()
        out.append(res)
    return out


def _lineage_groups(items, meta):
    """Group documents by lineage (a submitted file and its prior
    versions), in order of first appearance."""
    def root(aid):
        seen = set()
        while aid in meta and meta[aid][3] and aid not in seen:
            seen.add(aid)
            aid = meta[aid][3]
        return aid
    groups = {}
    for it in items:
        groups.setdefault(root(it["aid"]), []).append(it)
    return list(groups.values())


@_timed("report", "visual_overlay")
def generate_visual_reports(db_path, index_path, session=None,
                            progress=None, workers=1, status=None):
    """One visual overlay report per document with overlay findings, plus
    an index page at index_path. progress(i, n) is called per document.
    workers > 1 renders several documents at once in separate processes
    (a document and its prior versions in the same one); the reports, the
    index and the log entries are the same as with one.
    status(dict), if given, is called with {"done", "total", "running":
    {i: (file name, start time as time.time())}} as documents start and
    finish (for a live line in the Report Log; build 2026-11-19b).
    Returns (documents_with_reports, findings_visualized)."""
    import urllib.parse
    from pdf_forensics.pathutil import safe_name
    from pdf_forensics import perf as _perf
    import time as _time
    global _RUN_T0
    _RUN_T0 = _time.time()
    conn = sqlite3.connect(db_path)
    clear_render_cache()        # renders are reused within one run only
    _perf.get(session).load_begin()
    try:
        targets = _list_analyses_with_overlays(conn)
        if not targets:
            if session:
                session.log("No overlay findings with coordinates found.",
                            "warning")
            return 0, 0
        stem = os.path.splitext(os.path.basename(index_path))[0]
        folder_name = f"{stem}_files"
        folder = os.path.join(os.path.dirname(os.path.abspath(index_path)),
                              folder_name)
        os.makedirs(folder, exist_ok=True)
        meta = {r[0]: r[1:] for r in conn.execute(
            "SELECT id, pdf_filename, pdf_md5, version_number, "
            "source_analysis_id, doc_risk_score FROM analyses")}
        import importlib.util as _ilu
        can_split = _ilu.find_spec("pymupdf") is not None
        items = []
        for i, (aid, fname) in enumerate(targets, 1):
            pdf_filename, md5, vnum, parent, risk = meta.get(
                aid, (fname, "", None, None, None))
            pages, n_over, kinds, page_over = _overlay_counts(
                conn, aid, per_page=True)
            doc_stem = os.path.splitext(
                pdf_filename or f"document_{aid}")[0].strip(" .")
            # Short, Windows-safe names; the MD5 prefix keeps them unique.
            name = safe_name(f"{i:03d}_{doc_stem}_{(md5 or '')[:8]}",
                             folder, max_path=250, reserve=5) + ".html"
            items.append({"i": i, "aid": aid, "pdf_filename": pdf_filename,
                          "md5": md5, "vnum": vnum, "parent": parent,
                          "risk": risk, "pages": pages, "n_over": n_over,
                          "kinds": kinds, "name": name,
                          "page_over": page_over,
                          "src_ok": can_split and _source_exists(conn, aid),
                          "src": _source_path(conn, aid),
                          "path": os.path.join(folder, name)})
        conn.close()
        conn = None

        from pdf_forensics.analysis.parallel import resolve_workers
        # Processes: no more than there are pieces of work. A document
        # whose source can be read can be drawn in parts (runs of pages),
        # so its pages with overlays count, not just the document (build
        # 2026-11-24b: a case of one 70-page document and its three
        # versions ran 4 processes, one per document, not 18).
        pieces = sum(max(1, len(it.get("page_over") or {}))
                     if it.get("src_ok") else 1 for it in items)
        workers = min(resolve_workers(workers), max(1, pieces))
        results = {}
        def _status(done, running):
            if status:
                try:
                    status({"done": done, "total": len(items),
                            "running": running})
                except Exception:
                    pass

        if workers <= 1:
            for k, it in enumerate(items, 1):
                if progress:
                    try:
                        progress(k, len(items))
                    except Exception:
                        pass
                _status(k - 1, {it["i"]: (it["pdf_filename"],
                                          _time.time())})
                results[it["i"]] = _visual_one(db_path, it, session)
                _visual_record(it, results[it["i"]], session, live=True)
            _status(len(items), {})
        else:
            _visual_parallel(db_path, items, meta, session, workers,
                             progress, results, _status)

        rows, total = [], 0
        for it in items:
            res = results.get(it["i"], {"n": 0})
            made = os.path.isfile(it["path"])
            total += res.get("n", 0) if made else 0
            kind = "Submitted"
            if it["vnum"] is not None:
                parent = it["parent"]
                pname = meta.get(parent, ("?",))[0] if parent else "?"
                kind = f"Prior version {it['vnum']} of {pname}"
            kinds = it["kinds"]
            # Overlays not found to hide nothing (1.3.0); None if the
            # report was not made.
            hides = None
            if made and "stats" in res:
                hides = max(0, res.get("n", 0)
                            - res["stats"].get("nothing", 0))
            rows.append({"n": it["i"], "file": it["pdf_filename"],
                         "kind": kind, "hides": hides,
                         "pages": it["pages"], "overlays": it["n_over"],
                         "tot": kinds.get("text_over_text", 0),
                         "wb": kinds.get("white_box", 0),
                         "ann": kinds.get("annotation", 0),
                         "other": sum(v for k, v in kinds.items() if k not in
                                      ("text_over_text", "white_box",
                                       "annotation")),
                         "risk": it["risk"], "md5": it["md5"] or "",
                         "href": (f"{urllib.parse.quote(folder_name)}/"
                                  f"{urllib.parse.quote(it['name'])}")
                                 if made else None})
        with open(index_path, "w", encoding="utf-8") as fh:
            fh.write(_index_html(rows, db_path, session))
        if session:
            session.register_output("visual", index_path)
        return sum(1 for r in rows if r["href"]), total
    finally:
        _perf.get(session).load_end("visual reports")
        if conn is not None:
            conn.close()


def _visual_record(it, res, session, live=False):
    """Write one document's performance-log event (and, for results from
    a worker, its log entries) — the same entries in the same order as when
    the report is made in this process."""
    from pdf_forensics import perf as _perf
    if not live and session and res.get("logs"):
        session.replay(res["logs"])
    if "error" in res:
        if session:
            session.log(f"Visual report failed for "
                        f"{it['pdf_filename']}: {res['error']}", "error")
        return
    st = res.get("stats", {})
    t0 = _RUN_T0 or res.get("t_start") or 0
    _perf.get(session).event(
        "visual_overlay_document", (it["md5"] or "")[:32],
        res.get("elapsed", 0.0),
        start=round(res.get("t_start", t0) - t0, 1),
        end=round(res.get("t_end", t0) - t0, 1),
        pages=it["pages"],
        findings=it["n_over"], fast_pages=st.get("fast", 0),
        fallback_pages=st.get("fallback", 0),
        renders_reused=st.get("reused", 0),
        verified=st.get("verified", 0),
        mismatches=st.get("mismatch", 0),
        white_boxes_measured=st.get("measured", 0),
        hide_nothing=st.get("nothing", 0),
        mupdf_messages=res.get("mupdf", 0),
        **({"parts": res["parts"]} if res.get("parts") else {}),
        **({"est": round(it["work"], 2)} if "work" in it else {}),
        **({"probe_s": round(it["probe_s"], 3)}
           if it.get("probe_s") is not None else {}),
        **({"max_area": it["max_area"]} if it.get("max_area") else {}),
        **{k: round(v, 2) for k, v in st.items() if k.startswith("t_")})


SPLIT_MIN_OVERLAYS = 40     # documents smaller than this are never split
PROBE_DPI = 36              # quick render for the work estimate
RENDERS_PER_PAGE = 3        # as received, nothing overlaid, single page
# The work estimate (build 2026-11-20b), fitted to a 325-file case at 16
# processes (correlation 0.93 with the time each document took): about
# DRAW_S seconds per drawing of a page, plus, for a page that is slow to
# draw (its quick drawing took HEAVY_PROBE_S or more; an ordinary page
# takes about 0.02 s), HEAVY_FACTOR times its quick drawing per drawing.
DRAW_S = 0.4
HEAVY_PROBE_S = 0.2
HEAVY_FACTOR = 110


def _probe_doc(spec):
    """Worker: draw each page with overlays once at PROBE_DPI and time it
    (build 2026-11-20). How long a page takes to draw depends on its size
    and what is drawn on it, not on the file's size or its overlays: in a
    325-file case, four small one-page files (about 0.2 MB, one overlay
    each) took 150 to 240 s each, nearly all of it drawing. Returns {page:
    seconds}, or None if the file could not be drawn. MuPDF's messages from
    this are discarded, so they are not reported against a document.
    spec["areas"] (a dict), if given, receives each page's area in square
    inches, for the performance log."""
    import time as _time
    try:
        import pymupdf
    except ImportError:
        return None
    out = {}
    _mupdf_reset()          # build 2026-11-23: nothing on the console
    try:
        doc = pymupdf.open(spec["src"])
        try:
            for p in spec["pages"]:
                if 1 <= p <= len(doc):
                    page = doc[p - 1]
                    t0 = _time.perf_counter()
                    page.get_pixmap(dpi=PROBE_DPI, alpha=False)
                    out[p] = _time.perf_counter() - t0
                    try:
                        out[("area", p)] = round(
                            page.rect.width * page.rect.height / 5184, 1)
                    except Exception:
                        pass
        finally:
            doc.close()
    except Exception:
        out = None
    try:
        pymupdf.TOOLS.mupdf_warnings(reset=True)
    except Exception:
        pass
    return out


def _estimate_work(items, probes):
    """Each item's estimated work ("work") and each page's ("page_work"),
    in seconds (build 2026-11-20b): a page is drawn about once per overlay
    plus RENDERS_PER_PAGE times; each drawing costs about DRAW_S, plus
    HEAVY_FACTOR times the page's quick drawing if that took HEAVY_PROBE_S
    or more. (Build 2026-11-20 used the quick drawing alone, which missed
    the cost every overlay has whatever the page: building its variant,
    separating its layer and encoding it; a 30-page document with 1,627
    overlays was rated small, not split, and ran 773 s alone.) Pages not
    measured count as ordinary. Also notes the largest page's area
    ("max_area", square inches) for the performance log."""
    for it in items:
        po = it.get("page_over") or {}
        pr = probes.get(it["i"]) or {}
        pw = {}
        for p, k in po.items():
            draws = k + RENDERS_PER_PAGE
            q = pr.get(p)
            cost = DRAW_S * draws
            if q is not None and q >= HEAVY_PROBE_S:
                cost += HEAVY_FACTOR * q * draws
            pw[p] = cost
        it["page_work"] = pw
        it["work"] = sum(pw.values())
        times = [v for key, v in pr.items() if not isinstance(key, tuple)]
        it["probe_s"] = sum(times) if pr else None
        areas = [v for key, v in pr.items() if isinstance(key, tuple)]
        if areas:
            it["max_area"] = max(areas)


def _w(it):
    """An item's work estimate (overlays when not measured)."""
    return it.get("work", it["n_over"])


def _page_chunks(page_over, k):
    """Split a document's pages (with their overlay counts) into k runs of
    consecutive pages with about the same number of overlays each."""
    pages = sorted(page_over)
    k = max(1, min(k, len(pages)))
    chunks, cur, acc = [], [], 0
    left = sum(page_over[p] for p in pages)
    for idx, p in enumerate(pages):
        cur.append(p)
        acc += page_over[p]
        parts_after = k - len(chunks) - 1
        pages_after = len(pages) - idx - 1
        target = left / (k - len(chunks))
        if parts_after > 0 and (acc >= target or pages_after == parts_after):
            chunks.append(cur)
            left -= acc
            cur, acc = [], 0
    if cur:
        chunks.append(cur)
    return chunks


def _split_item(it, share, workers):
    """A document with more than a worker's share of the overlays, as
    parts of consecutive pages of at most about half a share each (build
    2026-11-19e); otherwise the document itself."""
    import math
    po = it.get("page_work") or it.get("page_over") or {}
    if (workers <= 1 or not it.get("src_ok") or len(po) < 2
            or _w(it) <= share or it["n_over"] < SPLIT_MIN_OVERLAYS):
        return [it]
    k = min(workers, len(po), math.ceil(_w(it) / (share / 2)))
    if k < 2:
        return [it]
    chunks = _page_chunks(po, k)
    over = it.get("page_over") or {}
    return [dict(it, part=n, parts=len(chunks), part_pages=c,
                 n_over=sum(over.get(p, 0) for p in c),
                 **({"work": sum(po[p] for p in c)} if "work" in it else {}))
            for n, c in enumerate(chunks)]



def _split_lineage(g, share, workers):
    """Tasks for a lineage (a document, then its prior versions) with more
    than a share of the work: runs of consecutive pages, each task holding
    those pages of every document in lineage order, so versions reuse the
    renders of the pages they share with the document. Pages are weighed
    by the work of all the documents that have them (whether versions can
    reuse a page's drawings is not known in advance, so none is assumed).
    A lineage within a share stays one task; one that cannot be split by
    page (no per-page figures, or a single page) is split into its
    documents."""
    import math
    work = {}
    for it in g:
        po = it.get("page_work") or it.get("page_over") or {}
        for p, w in po.items():
            # Build 2026-11-23b: every document's pages count in full.
            # Counting a page shared by versions once (build 2026-11-23)
            # assumed they reuse its drawings, but versions whose pages
            # all differ reuse nothing: a 70-page document and its three
            # versions were then kept in one process, drawn one after
            # another for 8,900 s.
            work[p] = work.get(p, 0) + w
    weight = sum(work.values())
    if workers > 1 and len(work) < 2:
        # Nothing to split by page (no per-page figures, or one page):
        # the documents go to different processes, as before.
        return [[p] for it in g for p in _split_item(it, share, workers)]
    if workers <= 1 or weight <= share:
        return [list(g)]
    k = min(workers, len(work), math.ceil(weight / (share / 2)))
    if k < 2:
        return [list(g)]
    chunks = _page_chunks(work, k)
    tasks = [[] for _ in chunks]
    for it in g:
        po = it.get("page_work") or it.get("page_over") or {}
        if not it.get("src_ok") or not po:
            tasks[0].append(it)
            continue
        mine = [(n, [p for p in c if p in po]) for n, c in enumerate(chunks)]
        mine = [(n, c) for n, c in mine if c]
        if len(mine) <= 1:
            tasks[mine[0][0] if mine else 0].append(it)
            continue
        over = it.get("page_over") or {}
        for part, (n, c) in enumerate(mine):
            tasks[n].append(dict(
                it, part=part, parts=len(mine), part_pages=c,
                n_over=sum(over.get(p, 0) for p in c),
                **({"work": sum(po[p] for p in c)} if "work" in it else {})))
    return [t for t in tasks if t]


def _plan_visual_tasks(groups, workers):
    """
    The tasks for the worker processes.

    A document and its prior versions normally go to one worker, so that
    pages they share reuse renders. A lineage with more than one worker's
    share of all the work would hold up the whole run, so it is split
    (_split_lineage): by page range across all its documents since build
    2026-11-23, so that each process draws a range of pages of the
    document and then the same pages of its versions, reusing renders
    where pages are unchanged.
    (Build 2026-11-20b split it into its documents, each in a different
    process: in a 12,745-file case a 70-page document and its three
    versions were each drawn in full, 3,200 s apiece, side by side.)

    The work estimate (build 2026-11-20) is each page's drawing time,
    measured by a quick low-resolution drawing (_probe_doc), times the
    number of times the page is drawn (about once per overlay, plus three;
    _estimate_work). Before, it was the number of overlays, which rated a
    one-overlay page that takes four minutes to draw as trivial, so such
    pages started late and finished last. Without measurements, the
    number of overlays is still used.

    Build 2026-11-19e: a single document with more than a share is split
    into parts of consecutive pages (at most about half a share each),
    rendered in different processes and joined in page order by the main
    process; overlay numbers, the report and the log entries are the same
    as for the whole document. (In a 325-file case, one 30-page document
    with 1,627 overlays was the last 150 to 180 seconds of the step, alone.)

    Splitting or reordering changes only the time taken: renders reused or
    made again are identical, and results are recorded in document order
    regardless.

    Order (build 2026-11-20): every task with more than half a share of
    the work, largest first, so nothing long starts late; then the rest in
    their listed order. (Build 2026-11-19b started only the largest first,
    after build 2026-11-19 had started every heavy document first and they
    slowed each other; with long documents now split and the estimate
    counting drawing time, the long tasks are few and must not start
    late.) If no task is above half a share, the largest goes first.
    """
    total = sum(_w(it) for g in groups for it in g) or 1
    share = total / max(1, workers)
    tasks = []
    for g in groups:
        if len(g) > 1 and sum(_w(it) for it in g) > share:
            tasks.extend(_split_lineage(g, share, workers))
            continue
        if len(g) == 1:
            tasks.extend([p] for p in _split_item(g[0], share, workers))
        else:
            tasks.append(g)
    # Order (build 2026-11-20): every task above half a share, largest
    # first, so nothing long starts late; then the rest in listed order.
    big = sorted([k for k, t in enumerate(tasks)
                  if sum(_w(it) for it in t) > share / 2],
                 key=lambda k: (-sum(_w(it) for it in tasks[k]), k))
    if not big and len(tasks) > 1:
        big = [max(range(len(tasks)),
                   key=lambda k: (sum(_w(it) for it in tasks[k]), -k))]
    chosen = set(big)
    return [tasks[k] for k in big] + [t for k, t in enumerate(tasks)
                                      if k not in chosen]


def _visual_parallel(db_path, items, meta, session, workers, progress,
                     results, status=None):
    """Render documents in worker processes (see _plan_visual_tasks);
    record results in document order as they become available. A document
    split into parts is joined and written here when its last part is in.
    Workers report each document's (or part's) start and end, for
    status()."""
    import multiprocessing as mp
    import queue as _queue
    from concurrent.futures import (ProcessPoolExecutor, wait,
                                    FIRST_COMPLETED)
    from pdf_forensics import perf as _perf
    from pdf_forensics.analysis.parallel import session_info
    import time as _time
    ctx = mp.get_context("spawn")
    events = ctx.Queue()
    pool = ProcessPoolExecutor(max_workers=workers, mp_context=ctx,
                               initializer=_visual_init, initargs=(events,))
    # Measure how long each page takes to draw (quick, in the workers),
    # for the work estimate (build 2026-11-20).
    probes = {}
    _tp = _time.perf_counter()
    try:
        specs = [(it["i"], {"src": it.get("src"),
                            "pages": sorted(it.get("page_over") or {})})
                 for it in items if it.get("src_ok") and it.get("src")]
        for (i, _), pr in zip(specs, pool.map(_probe_doc,
                                              [sp for _, sp in specs])):
            probes[i] = pr
    except Exception:
        probes = {}
    _estimate_work(items, probes)
    measured = [pr for pr in probes.values() if pr]
    n_pages = sum(1 for pr in measured for key in pr
                  if not isinstance(key, tuple))
    t_probe = sum(v for pr in measured for key, v in pr.items()
                  if not isinstance(key, tuple))
    n_heavy = sum(1 for pr in measured for key, v in pr.items()
                  if not isinstance(key, tuple) and v >= HEAVY_PROBE_S)
    _perf.get(session).note(
        f"visual reports: work estimated from the drawings needed and a "
        f"quick drawing of each page with overlays at {PROBE_DPI} dpi "
        f"({n_pages} page(s) of {len(measured)} document(s), {n_heavy} slow "
        f"to draw; {t_probe:.1f} s across processes, "
        f"{_time.perf_counter() - _tp:.1f} s elapsed)")
    try:
        groups = _plan_visual_tasks(_lineage_groups(items, meta), workers)
    except BaseException:
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    budget = max(384 * 1024 * 1024, (_RENDER_BUDGET * 2) // workers)
    split = {}
    for g in groups:
        for it in g:
            if "part_pages" in it:
                split[it["i"]] = it["parts"]
    note = (f"visual reports: {workers} worker process(es), tasks above "
            f"half a share of the estimated work first (largest first), "
            f"then listed order")
    if split:
        note += (f"; {len(split)} document(s) split by pages into "
                 f"{sum(split.values())} parts")
    _perf.get(session).note(note)
    if session:
        session.log(f"Visual overlay reports: {workers} worker "
                    f"process(es) (documents, or runs of pages of large "
                    f"documents, at a time)")
    order = [it["i"] for it in items]
    by_i = {it["i"]: it for it in items}
    nxt = 0
    done = 0
    running = {}
    parts_in = {}               # i -> part results so far
    labels = {}
    for g in groups:
        for it in g:
            if "part_pages" in it:
                pp = it["part_pages"]
                rng = (f"page {pp[0]}" if len(pp) == 1
                       else f"pages {pp[0]}\u2013{pp[-1]}")
                labels[(it["i"], it["part"])] = (
                    f"{it['pdf_filename']} ({rng})")
    ended = set()

    def drain():
        changed = False
        while True:
            try:
                kind, key, t = events.get_nowait()
            except (_queue.Empty, OSError, ValueError, EOFError):
                return changed
            changed = True
            if kind == "start":
                if key not in ended:
                    running[key] = (labels.get(key)
                                    or by_i[key]["pdf_filename"], t)
            else:
                ended.add(key)
                running.pop(key, None)

    def report():
        if status:
            status(done, dict(running))

    def finish(i, res):
        nonlocal done
        results[i] = res
        done += 1
        if progress:
            try:
                progress(done, len(items))
            except Exception:
                pass

    with pool:
        futs = {pool.submit(_visual_worker,
                            {"db_path": db_path, "items": g,
                             "render_budget": budget,
                             "session_info": session_info(session)}): g
                for g in groups}
        pending = set(futs)
        report()
        while pending:
            finished, pending = wait(pending, timeout=0.5,
                                     return_when=FIRST_COMPLETED)
            changed = drain()
            for fut in finished:
                g = futs[fut]
                try:
                    out = fut.result()
                except Exception as e:          # the worker process failed
                    out = [dict({"i": it["i"], "n": 0,
                                 "error": f"report process failed "
                                          f"({type(e).__name__})"},
                                **({"part": it["part"]}
                                   if "part_pages" in it else {}))
                           for it in g]
                for it, res in zip(g, out):
                    key = ((it["i"], it["part"]) if "part_pages" in it
                           else it["i"])
                    ended.add(key)
                    running.pop(key, None)
                    if "part_pages" in it:
                        got = parts_in.setdefault(it["i"], [])
                        got.append(res)
                        if len(got) == it["parts"]:
                            finish(it["i"], _join_parts(
                                db_path, by_i[it["i"]], got, session))
                            del parts_in[it["i"]]
                    else:
                        finish(res["i"], res)
                while nxt < len(order) and order[nxt] in results:
                    _visual_record(by_i[order[nxt]], results[order[nxt]],
                                   session)
                    nxt += 1
            if finished or changed:
                report()
    while nxt < len(order):
        _visual_record(by_i[order[nxt]],
                       results.get(order[nxt], {"n": 0, "error": "not made"}),
                       session)
        nxt += 1
    report()


def _index_html(rows, db_path, session=None):
    from pdf_forensics import branding as _branding
    from pdf_forensics.database import compute_file_md5
    cfg = _branding.load_branding()
    case_number = session.case_number if session else ""
    classification = _branding.classification_text(cfg)
    foot_text = _branding.footer_text(case_number, cfg)
    db_md5 = compute_file_md5(db_path) if db_path else ""
    app_logo = ""
    try:
        from pdf_forensics.assets import get_logo_base64
        app_logo = get_logo_base64() or ""
    except Exception:
        pass
    agency_logo = _branding.get_agency_logo_data_uri(cfg)
    info_pairs = _branding.case_info_pairs(case_number, cfg)
    info_block = ""
    if info_pairs:
        info_block = '<div class="case-info">' + "".join(
            f'<div class="bi-row"><span class="bi-label">{_esc(l)}</span>'
            f'<span class="bi-val">{_esc(v)}</span></div>'
            for l, v in info_pairs) + "</div>"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n_docs = sum(1 for r in rows if r["href"])
    n_over = sum(r["overlays"] for r in rows)

    def cell(v, cls=""):
        return f'<td class="{cls}">{_esc("" if v is None else v)}</td>'

    body = []
    for r in rows:
        link = (f'<a href="{r["href"]}" target="_blank" rel="noopener">'
                f'Open report</a>' if r["href"] else
                '<span class="missing">not generated</span>')
        body.append(
            "<tr>" + cell(r["n"], "num") + cell(r["file"], "fn")
            + cell(r["kind"]) + cell(r["overlays"], "num")
            + cell(r.get("hides"), "num hides" + (
                " hit" if r.get("hides") else ""))
            + cell(r["pages"], "num") + cell(r["tot"], "num")
            + cell(r["wb"], "num") + cell(r["ann"], "num")
            + cell(r["other"], "num") + cell(r["risk"], "num")
            + f'<td class="link">{link}</td>' + cell(r["md5"], "md5")
            + "</tr>")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Visual Overlay Reports — {__tool_name__}</title>
<style>
  :root {{ --bg:#1B1B1B; --panel:#242424; --line:#3A3A3A; --text:#E6E6E6;
          --dim:#A8A8A8; --accent:#ED1C24; --link:#6CB4FF; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
         font: 14px/1.45 "Segoe UI", Arial, sans-serif; }}
  #classification {{ background:var(--accent); color:#fff; text-align:center;
         font-weight:700; padding:4px; letter-spacing:.05em; }}
  #header {{ display:flex; align-items:center; gap:18px; padding:18px 24px;
         border-bottom:2px solid var(--accent); }}
  #header .app-logo {{ height:56px; }} #header .agency-logo {{ height:56px; margin-left:auto; }}
  #header h1 {{ margin:0; font-size:22px; }}
  .subtitle {{ color:var(--dim); font-size:12px; margin-top:4px; }}
  .case-info .bi-row {{ font-size:12px; }} .bi-label {{ color:var(--dim); margin-right:6px; }}
  .intro {{ padding:14px 24px 0; color:var(--dim); max-width:1100px; }}
  .bar {{ display:flex; gap:12px; align-items:center; padding:12px 24px; }}
  .bar input {{ background:var(--panel); color:var(--text); border:1px solid var(--line);
         padding:6px 10px; min-width:320px; border-radius:4px; }}
  .bar .count {{ color:var(--dim); font-size:13px; }}
  .wrap {{ padding:0 24px 24px; overflow-x:auto; }}
  table {{ border-collapse:collapse; width:100%; }}
  th, td {{ border:1px solid var(--line); padding:6px 9px; text-align:left; vertical-align:top; }}
  th {{ background:var(--panel); position:sticky; top:0; cursor:pointer; user-select:none;
        font-size:12px; text-transform:uppercase; color:var(--dim); white-space:nowrap; }}
  th[data-dir="asc"]::after {{ content:" \\25B2"; }} th[data-dir="desc"]::after {{ content:" \\25BC"; }}
  td.num {{ text-align:right; white-space:nowrap; }}
  td.hides {{ color:var(--dim); }} td.hides.hit {{ color:#ff6b6b; font-weight:700; }} td.md5 {{ font-family:Consolas,monospace; font-size:12px; color:var(--dim); }}
  td.link a {{ color:var(--link); font-weight:600; white-space:nowrap; }}
  .missing {{ color:var(--dim); font-style:italic; }}
  tr:hover td {{ background:#2B2B2B; }}
  #print-footer {{ padding:10px 24px; color:var(--dim); font-size:12px; display:flex; justify-content:space-between; }}
  @media print {{ body {{ background:#fff; color:#000; }} th {{ background:#eee; color:#000; position:static; }}
         .bar {{ display:none; }} td.link a {{ color:#000; }} }}
</style>
</head>
<body>
{f'<div id="classification">{_esc(classification)}</div>' if classification else ''}
<div id="header">
  {f'<img class="app-logo" src="{app_logo}" alt="PDF Forensics Suite">' if app_logo else ''}
  <div class="header-text">
    <h1>Visual Overlay Reports</h1>
    <div class="subtitle">{__tool_name__} v{__version__} &middot; build {BUILD_DATE} &mdash;
      Generated {now} &mdash;
      Database: {_esc(os.path.basename(db_path))}</div>
  </div>
  {info_block}
  {f'<img class="agency-logo" src="{agency_logo}" alt="Agency logo">' if agency_logo else ''}
</div>
<div class="intro">One report per document with overlay findings ({n_docs} document(s), {n_over} overlay finding(s)), including prior versions recovered from incremental updates. <b>Hides content</b> counts the overlays not found to hide nothing: white boxes that hide nothing visible (removing them changes no pixel where the page beneath is not blank) are not counted, and are listed in each report in a collapsed group. Click a column heading to sort (for example by hides content, overlays or risk score), type in the box to filter, and click <b>Open report</b> to open a document's report in a new tab. Each report shows the flagged pages with their overlays as toggleable layers.</div>
<div class="bar"><input id="flt" type="search" placeholder="Filter by file name, kind or MD5…" aria-label="Filter">
<span class="count" id="cnt"></span></div>
<div class="wrap"><table id="t">
<thead><tr><th data-t="n">#</th><th>Document</th><th>Kind</th><th data-t="n">Overlays</th>
<th data-t="n" title="Overlays not found to hide nothing: white boxes that reveal content when removed, white boxes that could not be measured, and every other kind of overlay">Hides content</th>
<th data-t="n">Pages</th><th data-t="n">Text over text</th><th data-t="n">White box</th>
<th data-t="n">Annotation</th><th data-t="n">Other</th><th data-t="n">Risk score</th>
<th>Report</th><th>PDF MD5</th></tr></thead>
<tbody>
{chr(10).join(body)}
</tbody></table></div>
<div id="print-footer"><span>{_esc(foot_text)}</span><span>{('DB MD5: ' + _esc(db_md5)) if db_md5 else ''}</span></div>
<script>
(function(){{
  var t=document.getElementById('t'), tb=t.tBodies[0], flt=document.getElementById('flt'),
      cnt=document.getElementById('cnt'), rows=[].slice.call(tb.rows);
  function count(){{ var v=rows.filter(function(r){{return r.style.display!=='none';}}).length;
    cnt.textContent=v+' of '+rows.length+' document(s)'; }}
  flt.addEventListener('input',function(){{ var q=flt.value.toLowerCase();
    rows.forEach(function(r){{ r.style.display=r.textContent.toLowerCase().indexOf(q)>=0?'':'none'; }}); count(); }});
  [].forEach.call(t.tHead.rows[0].cells,function(th,ci){{ th.addEventListener('click',function(){{
    var dir=th.getAttribute('data-dir')==='asc'?'desc':'asc', num=th.getAttribute('data-t')==='n';
    [].forEach.call(t.tHead.rows[0].cells,function(h){{h.removeAttribute('data-dir');}}); th.setAttribute('data-dir',dir);
    rows.sort(function(a,b){{ var x=a.cells[ci].textContent.trim(), y=b.cells[ci].textContent.trim();
      if(num){{ x=parseFloat(x)||0; y=parseFloat(y)||0; return dir==='asc'?x-y:y-x; }}
      return dir==='asc'?x.localeCompare(y):y.localeCompare(x); }});
    rows.forEach(function(r){{tb.appendChild(r);}}); }}); }});
  count();
}})();
</script>
</body>
</html>"""
