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

from pdf_forensics import __version__, __tool_name__
from pdf_forensics.reports import reveal as _reveal

# Render resolution for full pages and crops (DPI)
PAGE_RENDER_DPI = 144
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
    img.save(out, format="PNG", optimize=True)
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
    diff = ImageChops.difference(base, over).convert("L")
    # Binary mask: 255 where changed beyond tolerance, else 0.
    mask = diff.point(lambda v: 255 if v > tolerance else 0)
    layer = over.convert("RGBA")
    layer.putalpha(mask)
    out = io.BytesIO()
    layer.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _b64_png(png_bytes):
    """Return a data URI for PNG bytes."""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def generate_visual_report(db_path, output_path, analysis_id=None,
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

            # Number overlays in z-order (paint order): findings are
            # ordered by id = /Annots order = bottom-to-top stacking.
            for fnd in findings:
                finding_counter += 1
                fnd["_number"] = finding_counter

            # Base layer: the page with ALL overlays removed (the true
            # original). This is the always-present bottom layer.
            try:
                rb, rinfo = _reveal.build_revealed_pdf_bytes(
                    fpath, page_index, findings, page_height)
                if rb and rinfo.get("recovered", 0) >= 1:
                    base_png = _render_revealed_page_png(
                        rb, page_index, PAGE_RENDER_DPI)
                    base_all_removed = (
                        rinfo.get("skipped", 0) == 0)
                else:
                    base_png = _render_page_png(page, PAGE_RENDER_DPI)[0]
                    base_all_removed = False
            except Exception:
                base_png = _render_page_png(page, PAGE_RENDER_DPI)[0]
                base_all_removed = False
            base_uri = _b64_png(base_png)

            # One isolated, transparent layer per overlay. "Only overlay
            # k present" is produced by removing every OTHER overlay
            # (precise, by object reference for annotations), then the
            # layer is the pixel difference from the base.
            overlays = []
            for fnd in findings:
                others = [o for o in findings if o is not fnd]
                layer_uri = None
                isolated = False
                try:
                    if others:
                        ro, roinfo = _reveal.build_revealed_pdf_bytes(
                            fpath, page_index, others, page_height)
                        if ro is not None:
                            only_png = _render_revealed_page_png(
                                ro, page_index, PAGE_RENDER_DPI)
                            isolated = (roinfo.get("skipped", 0) == 0)
                        else:
                            only_png = _render_page_png(
                                page, PAGE_RENDER_DPI)[0]
                            isolated = False
                    else:
                        # Sole overlay on the page.
                        only_png = _render_page_png(
                            page, PAGE_RENDER_DPI)[0]
                        isolated = True
                    layer_uri = _b64_png(
                        _isolate_layer_png(base_png, only_png))
                except Exception as e:
                    if session:
                        session.log(
                            f"Overlay layer {fnd['_number']} "
                            f"(p{page_num}) failed: {e}", "warning")
                    layer_uri = None
                    isolated = False

                overlays.append({
                    "number": fnd["_number"],
                    "kind": fnd["kind"],
                    "detail": fnd["detail"],
                    "bbox": fnd["bbox"],      # PyMuPDF top-left pts
                    "layer_uri": layer_uri,
                    "isolated": isolated,
                })

            page_blocks.append({
                "page_num": page_num,
                "uid": f"{aid}-{page_num}",
                "base_uri": base_uri,
                "base_all_removed": base_all_removed,
                "page_w": page_width,
                "page_h": page_height,
                "overlays": overlays,
                "count": len(findings),
            })
            total_findings += len(findings)

        doc.close()
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


def _fan_badges(overlays, page_w, page_h):
    """Assign each overlay a badge position (% of page) and fan apart
    badges that would land on top of each other, so stacked overlays
    stay individually visible. Records the true anchor too, for a
    leader line."""
    placed = []
    for ov in overlays:
        x0, y0, x1, y1 = ov["bbox"]
        lx = (x0 / page_w * 100.0) if page_w else 0.0
        ly = (y0 / page_h * 100.0) if page_h else 0.0
        lx = max(0.0, min(100.0, lx))
        ly = max(0.0, min(100.0, ly))
        off = sum(1 for (px, py) in placed
                  if abs(px - lx) < 3.5 and abs(py - ly) < 3.5)
        placed.append((lx, ly))
        ov["anchor_left"] = lx
        ov["anchor_top"] = ly
        ov["badge_left"] = max(0.0, min(100.0, lx + off * 2.6))
        ov["badge_top"] = max(0.0, min(100.0, ly + off * 2.6))


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
        _fan_badges(overlays, pb["page_w"], pb["page_h"])

        parts.append('<div class="page-block">')
        parts.append(
            f'<h3 class="page-title">Page {pb["page_num"]} '
            f'<span class="page-count">({pb["count"]} '
            f'overlay{"s" if pb["count"] != 1 else ""} detected)'
            f'</span></h3>')

        parts.append('<div class="page-layout">')

        # ---- LEFT: checkbox control panel ----
        parts.append('<div class="overlay-controls">')
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
            'page; untick to peel it away. Unticking all shows the '
            'recovered original. Overlays are numbered in stacking order '
            '(1 = bottom).</div>')
        parts.append('<ul class="overlay-list">')
        for ov in overlays:
            style = OVERLAY_STYLES.get(ov["kind"], OVERLAY_STYLES["other"])
            n = ov["number"]
            toggleable = bool(ov["layer_uri"])
            dis = "" if toggleable else " disabled"
            note = ("" if toggleable else
                    '<span class="ov-note"> (not independently '
                    'viewable \u2014 shown in context)</span>')
            approx = ("" if ov["isolated"] or not toggleable else
                      '<span class="ov-note"> (approximate isolation)</span>')
            parts.append(
                f'<li class="overlay-item" data-ov="{uid}-{n}">'
                f'<label><input type="checkbox" class="ov-toggle" '
                f'data-ov="{uid}-{n}" checked{dis}>'
                f'<span class="ov-badge-mini" '
                f'style="background:{style["hex"]};">{n}</span>'
                f'<span class="ov-kind">{style["label"]}</span>'
                f'{note}{approx}</label></li>')
        parts.append('</ul>')
        parts.append('</div>')   # overlay-controls

        # ---- RIGHT: layered page stage ----
        parts.append('<div class="page-stage-wrap">')
        parts.append(f'<div class="page-stage" id="stage-{uid}">')
        parts.append(
            f'<img class="base-layer" src="{pb["base_uri"]}" '
            f'alt="Page {pb["page_num"]} original (overlays removed)">')
        for ov in overlays:
            n = ov["number"]
            if ov["layer_uri"]:
                parts.append(
                    f'<img class="ov-layer" id="layer-{uid}-{n}" '
                    f'data-ov="{uid}-{n}" style="z-index:{n};" '
                    f'src="{ov["layer_uri"]}" alt="Overlay {n}">')
        # leader lines + fanned badges (DOM, not baked into the image)
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
                f'style="left:{ov["badge_left"]:.2f}%;'
                f'top:{ov["badge_top"]:.2f}%;'
                f'background:{style["hex"]};">{n}</span>')
        parts.append('</div>')   # page-stage
        if not pb.get("base_all_removed", False):
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
            parts.append(
                f'<div class="summary-row" data-ov="{uid}-{n}">'
                f'<span class="ov-badge-mini" '
                f'style="background:{style["hex"]};">{n}</span>'
                f'<span class="summary-kind">{style["label"]}</span>'
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
    text-align: center; box-shadow: 0 0 0 2px #fff; z-index: 999; }}
  .ov-badge.hot {{ outline: 3px solid #111; }}
  .ov-anchor {{ position: absolute; width: 8px; height: 8px;
    border-radius: 50%; transform: translate(-50%, -50%);
    box-shadow: 0 0 0 1.5px #fff; z-index: 998; }}
  .overlay-summary {{ margin-top: 16px; border-top: 1px solid #2c2c2c;
    padding-top: 10px; }}
  .summary-head {{ font-weight: 700; color: #fff; margin-bottom: 6px; }}
  .summary-row {{ display: flex; gap: 8px; align-items: baseline;
    padding: 5px 6px; border-radius: 5px; font-size: 13px; }}
  .summary-row.hot {{ background: #262626; }}
  .summary-kind {{ font-weight: 600; color: #cfcfcf; white-space: nowrap; }}
  .summary-detail {{ color: #bdbdbd; }}
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
    .page-stage .ov-layer {{ display: block !important; }}
    .overlay-summary {{ color: #000; }}
    .summary-kind, .summary-detail, .summary-head {{ color: #000 !important; }}
    .ov-anchor {{ display: none; }}
  }}
</style>
</head>
<body>
{classification_html}
<div id="header">
  {app_logo_html}
  <div class="header-text">
    <h1>Visual Overlay Report</h1>
    <div class="subtitle">{__tool_name__} v{__version__} &mdash;
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
  // Show/hide one overlay's layer + its on-page badge/anchor.
  function setOverlay(ovid, on) {{
    var q = '[data-ov="' + cssEsc(ovid) + '"]';
    document.querySelectorAll('.ov-layer' + q).forEach(function (el) {{
      el.style.display = on ? "block" : "none";
    }});
    document.querySelectorAll('.ov-badge' + q + ', .ov-anchor' + q)
      .forEach(function (el) {{ el.style.display = on ? "" : "none"; }});
  }}
  // Checkbox toggles one overlay.
  document.addEventListener("change", function (ev) {{
    var cb = ev.target;
    if (!cb.classList || !cb.classList.contains("ov-toggle")) return;
    setOverlay(cb.getAttribute("data-ov"), cb.checked);
  }});
  // "All" / "None" buttons set every overlay on a page.
  document.addEventListener("click", function (ev) {{
    var b = ev.target.closest ? ev.target.closest(".ctrl-all") : null;
    if (!b) return;
    var page = b.getAttribute("data-page");
    var on = b.getAttribute("data-set") === "on";
    document.querySelectorAll(
      '.ov-toggle[data-ov^="' + cssEsc(page) + '-"]').forEach(function (cb) {{
        if (cb.disabled) return;
        cb.checked = on;
        setOverlay(cb.getAttribute("data-ov"), on);
      }});
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
}})();
</script>

</body>
</html>"""
