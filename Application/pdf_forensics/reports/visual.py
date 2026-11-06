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
# renders reused from a prior version; layers rendered clipped, or clipped
# then redone in full; verification comparisons.
_VISUAL_STATS = {"fast": 0, "fallback": 0, "reused": 0, "clipped": 0,
                 "clip_fallback": 0, "verified": 0, "mismatch": 0}

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
_CLIP_PAD_PTS = 24.0


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


def clear_render_cache():
    _RENDER_CACHE.clear()
    _RENDER_BYTES[0] = 0


def _verify_on():
    try:
        from pdf_forensics.analysis import page_reuse as _pr
        return _pr.verify_mode()
    except Exception:
        return False


def _clip_enabled():
    return os.environ.get("PDF_FORENSICS_VISUAL_CLIP", "1") != "0"


def _render_clip_onto(onto_png, pdf_bytes, page_index, bbox, zoom):
    """Render only the area around bbox (PyMuPDF top-left points, plus a
    margin) and paste it onto onto_png at its exact pixel position.
    Returns (png_bytes, (x0, y0, x1, y1) pasted box in pixels) or
    (None, None)."""
    import pymupdf
    from PIL import Image
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[page_index]
        p = _CLIP_PAD_PTS
        clip = pymupdf.Rect(bbox[0] - p, bbox[1] - p,
                            bbox[2] + p, bbox[3] + p) & page.rect
        if clip.is_empty:
            return None, None
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip,
                              alpha=False)
        if pix.n != 3:
            return None, None
        piece = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        bg = Image.open(io.BytesIO(onto_png)).convert("RGB")
        bg.paste(piece, (pix.x, pix.y))
        out = io.BytesIO()
        bg.save(out, format="PNG", compress_level=6)
        return out.getvalue(), (pix.x, pix.y, pix.x + pix.width,
                                pix.y + pix.height)
    finally:
        doc.close()


def _layer_touches_edge(layer_png, box):
    """True if the layer has any visible pixel on an interior edge of the
    pasted box: the overlay may then extend beyond the clipped area. Edges
    on the page boundary are not interior and are not checked."""
    from PIL import Image
    a = Image.open(io.BytesIO(layer_png)).getchannel("A")
    w, h = a.size
    x0, y0, x1, y1 = max(0, box[0]), max(0, box[1]), min(w, box[2]), \
        min(h, box[3])
    if x1 - x0 < 3 or y1 - y0 < 3:
        return True
    edges = []
    if y0 > 0:
        edges.append(a.crop((x0, y0, x1, y0 + 1)))
    if y1 < h:
        edges.append(a.crop((x0, y1 - 1, x1, y1)))
    if x0 > 0:
        edges.append(a.crop((x0, y0, x0 + 1, y1)))
    if x1 < w:
        edges.append(a.crop((x1 - 1, y0, x1, y1)))
    return any(e.getbbox() is not None for e in edges)


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
    from PIL import Image, ImageChops
    base = Image.open(io.BytesIO(base_png)).convert("RGB")
    over = Image.open(io.BytesIO(with_overlay_png)).convert("RGB")
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
    return out.getvalue()


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
        lay = Image.open(io.BytesIO(lp)).convert("RGBA")
        if lay.size != comp.size:
            lay = lay.resize(comp.size)
        comp.alpha_composite(lay)
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
    from pdf_forensics.analysis.detectors import (
        merge_text_over_white_box)

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

    doc_sections = []
    total_findings = 0

    for aid, pdf_filename in targets:
        fname, fpath, fmd5 = _get_analysis_info(conn, aid)
        by_page = _load_overlay_findings(conn, aid)
        if not by_page:
            continue

        # Open the source PDF
        if not fpath or not os.path.isfile(fpath):
            if session:
                session.log(
                    f"Source PDF not found for visual report: {fpath}",
                    "warning")
            # Still emit a text-only section, and count its findings so
            # the report is written even when no page could be rendered.
            doc_sections.append(_render_missing_pdf_section(
                fname, fpath, by_page))
            total_findings += sum(len(v) for v in by_page.values())
            continue

        try:
            doc = pymupdf.open(fpath)
        except Exception as e:
            if session:
                session.log(f"Could not open {fpath}: {e}", "error")
            continue

        page_blocks = []
        finding_counter = 0

        for page_num in sorted(by_page.keys()):
            findings = by_page[page_num]
            if page_num < 1 or page_num > len(doc):
                continue
            # Fold text-over-text detections that sit inside a white box
            # into that box (one alteration). Also protects databases
            # analysed before the engine applied the same consolidation.
            findings, _n_merged = merge_text_over_white_box(
                findings, kind_key="kind")
            if _n_merged and session:
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
                    _sp = _reveal.single_page_pdf_bytes(fpath, page_index)
                    return bool(_sp) and _render_revealed_page_png(
                        _sp, 0, PAGE_RENDER_DPI) == asis_png
                except Exception:
                    return False
            _single = _cached("single", _single_ok)
            _VISUAL_STATS["fast" if _single else "fallback"] += 1
            _ri = 0 if _single else page_index

            def _base():
                try:
                    rb, rinfo = _reveal.build_revealed_pdf_bytes(
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
                rb2, _info2 = _reveal.build_revealed_pdf_bytes(
                    fpath, page_index, remove, page_height, keep_ops=keep,
                    single_page=_single)
                if rb2 is None:
                    return asis_png
                return _render_revealed_page_png(
                    rb2, _ri, PAGE_RENDER_DPI)

            # Clipped renders (1.2.0): a layer differs from its background
            # only where its overlay is, so the variant is rendered only
            # around the overlay (with a margin) and pasted onto the
            # background. If any changed pixel touches an interior edge of
            # the pasted area, the overlay may extend beyond it and the
            # layer is redone on the full page. Rotated pages, and pages
            # whose coordinates do not start at the origin, always use full
            # renders. Verification mode compares clipped with full.
            try:
                _can_clip = (_clip_enabled() and not page.rotation
                             and page.rect.x0 == 0 and page.rect.y0 == 0)
            except Exception:
                _can_clip = False

            def _layer(onto_png, remove, keep, bbox):
                """(layer_png, variant_png) for one overlay: the page with
                `remove` suppressed except `keep`, isolated against
                onto_png."""
                if _can_clip and bbox:
                    rb2, _info2 = _reveal.build_revealed_pdf_bytes(
                        fpath, page_index, remove, page_height,
                        keep_ops=keep, single_page=_single)
                    if rb2 is None:
                        return _isolate_layer_png(onto_png, asis_png), asis_png
                    variant, box = _render_clip_onto(onto_png, rb2, _ri,
                                                     bbox, zoom)
                    if variant is not None:
                        layer = _isolate_layer_png(onto_png, variant)
                        if not _layer_touches_edge(layer, box):
                            if _verify:
                                full = _render_variant(remove, keep)
                                full_layer = _isolate_layer_png(onto_png, full)
                                if _same_pixels(layer, full_layer):
                                    _VISUAL_STATS["verified"] += 1
                                else:
                                    _VISUAL_STATS["mismatch"] += 1
                                    if session:
                                        session.log(
                                            f"Visual report p{page_num}: a "
                                            f"clipped layer differs from the "
                                            f"full render (full render "
                                            f"used)", "warning")
                                    return full_layer, full
                            _VISUAL_STATS["clipped"] += 1
                            return layer, variant
                    _VISUAL_STATS["clip_fallback"] += 1
                full = _render_variant(remove, keep)
                return _isolate_layer_png(onto_png, full), full

            items = []
            for _j, fnd in enumerate(findings):
                n = fnd["_number"]
                comp = None
                if fnd["kind"] == "white_box":
                    def _wb(_f=fnd):
                        try:
                            c = _reveal.white_box_components(
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
                            one_layer = _cached(
                                ("one", _j),
                                lambda: (_isolate_layer_png(base_png,
                                                            asis_png),
                                         asis_png))[0]
                        items.append({
                            "number": str(n), "group": n, "part": None,
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

            page_blocks.append({
                "page_num": page_num,
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

        doc.close()
        _reveal.clear_source_cache()
        doc_sections.append(_render_doc_section(
            fname, fmd5, page_blocks))

    conn.close()

    if total_findings == 0:
        if session:
            session.log("No overlays could be visualized.", "warning")
        return 0

    html = _assemble_html(doc_sections, db_path, total_findings,
                          session=session)

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

        parts.append('<div class="page-block">')
        parts.append(
            f'<h3 class="page-title">Page {pb["page_num"]} '
            f'<span class="page-count">({pb["count"]} '
            f'overlay{"s" if pb["count"] != 1 else ""} detected'
            + (f', shown as {len(overlays)} separate edits'
               if len(overlays) > pb["count"] else '')
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
        parts.append('<ul class="overlay-list">')
        for ov in overlays:
            style = OVERLAY_STYLES.get(ov["kind"], OVERLAY_STYLES["other"])
            n = ov["number"]
            dis = "" if layered else " disabled"
            if ov.get("part") == "box":
                parts.append(
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
            parts.append(
                f'<li class="overlay-item{sub}" data-ov="{uid}-{n}">'
                f'<label><input type="checkbox" class="ov-toggle" '
                f'data-ov="{uid}-{n}" data-page="{uid}" checked{dis}>'
                f'<span class="ov-badge-mini" '
                f'style="background:{style["hex"]};">{n}</span>'
                f'<span class="ov-kind">{label}</span>'
                f'</label></li>')
        parts.append('</ul>')
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
            parts.append(
                f'<line class="leader-line" data-ov="{uid}-{n}" '
                f'x1="{ov["anchor_left"]:.2f}" y1="{ov["anchor_top"]:.2f}" '
                f'x2="{ov["badge_left"]:.2f}" y2="{ov["badge_top"]:.2f}" '
                f'stroke="{style["hex"]}"></line>')
        parts.append('</svg>')
        # Anchor dots (true location) + draggable numbered badges.
        for ov in overlays:
            style = OVERLAY_STYLES.get(ov["kind"], OVERLAY_STYLES["other"])
            n = ov["number"]
            parts.append(
                f'<span class="ov-anchor" data-ov="{uid}-{n}" '
                f'style="left:{ov["anchor_left"]:.2f}%;'
                f'top:{ov["anchor_top"]:.2f}%;'
                f'background:{style["hex"]};"></span>')
            parts.append(
                f'<span class="ov-badge" data-ov="{uid}-{n}" '
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
        for ov in overlays:
            style = OVERLAY_STYLES.get(ov["kind"], OVERLAY_STYLES["other"])
            n = ov["number"]
            if ov.get("part") == "box":
                parts.append(
                    f'<div class="summary-row summary-group" '
                    f'data-ov="{uid}-{n}">'
                    f'<span class="summary-kind">Alteration {ov["group"]}'
                    f'</span><span class="summary-detail">'
                    f'{_esc(ov.get("group_detail") or "")}</span></div>')
            sub = " sub" if ov.get("part") else ""
            parts.append(
                f'<div class="summary-row{sub}" data-ov="{uid}-{n}">'
                f'<span class="ov-badge-mini" '
                f'style="background:{style["hex"]};">{n}</span>'
                f'<span class="summary-kind">'
                f'{_esc(ov.get("title") or style["label"])}</span>'
                f'<span class="summary-detail">{_esc(ov["detail"])}</span>'
                f'</div>')
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


def _assemble_html(doc_sections, db_path, total_findings, session=None):
    """Wrap document sections in the full HTML page with logo + legend."""
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
    the analyzed document(s).</p>
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


def _overlay_counts(conn, analysis_id):
    by_page = _load_overlay_findings(conn, analysis_id)
    kinds = {}
    for items in by_page.values():
        for f in items:
            kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    return len(by_page), sum(kinds.values()), kinds


@_timed("report", "visual_overlay")
def generate_visual_reports(db_path, index_path, session=None,
                            progress=None):
    """One visual overlay report per document with overlay findings, plus
    an index page at index_path. progress(i, n) is called per document.
    Returns (documents_with_reports, findings_visualized)."""
    import urllib.parse
    from pdf_forensics.pathutil import safe_name
    conn = sqlite3.connect(db_path)
    clear_render_cache()        # renders are reused within one run only
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
        rows, total = [], 0
        for i, (aid, fname) in enumerate(targets, 1):
            if progress:
                try:
                    progress(i, len(targets))
                except Exception:
                    pass
            pdf_filename, md5, vnum, parent, risk = meta.get(
                aid, (fname, "", None, None, None))
            pages, n_over, kinds = _overlay_counts(conn, aid)
            doc_stem = os.path.splitext(
                pdf_filename or f"document_{aid}")[0].strip(" .")
            # Short, Windows-safe names; the MD5 prefix keeps them unique.
            name = safe_name(f"{i:03d}_{doc_stem}_{(md5 or '')[:8]}",
                             folder, max_path=250, reserve=5) + ".html"
            path = os.path.join(folder, name)
            import time as _time
            from pdf_forensics import perf as _perf
            for _k in _VISUAL_STATS:
                _VISUAL_STATS[_k] = 0
            _t0 = _time.perf_counter()
            try:
                n = _generate_visual_report_impl(db_path, path,
                                                 analysis_id=aid,
                                                 session=session)
                _perf.get(session).event(
                    "visual_overlay_document", (md5 or "")[:32],
                    _time.perf_counter() - _t0, pages=pages,
                    findings=n_over, fast_pages=_VISUAL_STATS["fast"],
                    fallback_pages=_VISUAL_STATS["fallback"],
                    renders_reused=_VISUAL_STATS["reused"],
                    layers_clipped=_VISUAL_STATS["clipped"],
                    clip_fallbacks=_VISUAL_STATS["clip_fallback"],
                    verified=_VISUAL_STATS["verified"],
                    mismatches=_VISUAL_STATS["mismatch"])
            except Exception as e:
                n = 0
                if session:
                    session.log(f"Visual report failed for "
                                f"{pdf_filename}: {e}", "error")
            made = os.path.isfile(path)
            total += n if made else 0
            kind = "Submitted"
            if vnum is not None:
                pname = meta.get(parent, ("?",))[0] if parent else "?"
                kind = f"Prior version {vnum} of {pname}"
            rows.append({"n": i, "file": pdf_filename, "kind": kind,
                         "pages": pages, "overlays": n_over,
                         "tot": kinds.get("text_over_text", 0),
                         "wb": kinds.get("white_box", 0),
                         "ann": kinds.get("annotation", 0),
                         "other": sum(v for k, v in kinds.items() if k not in
                                      ("text_over_text", "white_box",
                                       "annotation")),
                         "risk": risk, "md5": md5 or "",
                         "href": (f"{urllib.parse.quote(folder_name)}/"
                                  f"{urllib.parse.quote(name)}")
                                 if made else None})
        with open(index_path, "w", encoding="utf-8") as fh:
            fh.write(_index_html(rows, db_path, session))
        if session:
            session.register_output("visual", index_path)
        return sum(1 for r in rows if r["href"]), total
    finally:
        conn.close()


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
  td.num {{ text-align:right; white-space:nowrap; }} td.md5 {{ font-family:Consolas,monospace; font-size:12px; color:var(--dim); }}
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
<div class="intro">One report per document with overlay findings ({n_docs} document(s), {n_over} overlay finding(s)), including prior versions recovered from incremental updates. Click a column heading to sort (for example by overlays or risk score), type in the box to filter, and click <b>Open report</b> to open a document's report in a new tab. Each report shows the flagged pages with their overlays as toggleable layers.</div>
<div class="bar"><input id="flt" type="search" placeholder="Filter by file name, kind or MD5…" aria-label="Filter">
<span class="count" id="cnt"></span></div>
<div class="wrap"><table id="t">
<thead><tr><th data-t="n">#</th><th>Document</th><th>Kind</th><th data-t="n">Overlays</th>
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
