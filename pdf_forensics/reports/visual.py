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
     reports/reveal.py. For printed copies, both states are shown stacked
     with captions.

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
               f.overlay_kind
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

            # Assign sequential numbers to findings on this page
            boxes = []
            for fnd in findings:
                finding_counter += 1
                fnd["_number"] = finding_counter
                boxes.append({
                    "bbox": fnd["bbox"],
                    "kind": fnd["kind"],
                    "number": finding_counter,
                })

            # Full annotated page
            page_png, zoom = _render_page_png(page, PAGE_RENDER_DPI)
            annotated = _draw_box_on_pixmap_png(page_png, boxes, zoom)
            page_uri = _b64_png(annotated)

            # Page-level reveal: suppress ALL overlays on the page at once
            # (one of the two before/after modes). Rendered clean, no boxes.
            page_reveal_uri = None
            page_reveal_kinds = set()
            try:
                rb, rinfo = _reveal.build_revealed_pdf_bytes(
                    fpath, page_index, findings, page_height)
                if rb:
                    page_reveal_uri = _b64_png(
                        _render_revealed_page_png(
                            rb, page_index, PAGE_RENDER_DPI))
                    page_reveal_kinds = rinfo.get("kinds", set())
            except Exception as e:
                if session:
                    session.log(
                        f"Page reveal failed (p{page_num}): {e}",
                        "warning")

            # Detail crops per finding, each with its own reveal (the
            # second before/after mode: suppress only this flagged overlay)
            crops = []
            for fnd in findings:
                crop_uri = None
                reveal_uri = None
                try:
                    crop_uri = _b64_png(_crop_region_png(
                        page, fnd["bbox"], CROP_RENDER_DPI,
                        CROP_PADDING_PTS))
                except Exception:
                    crop_uri = None

                try:
                    rb1, rinfo1 = _reveal.build_revealed_pdf_bytes(
                        fpath, page_index, [fnd], page_height)
                    if rb1:
                        reveal_uri = _b64_png(_render_revealed_crop_png(
                            rb1, page_index, fnd["bbox"],
                            CROP_RENDER_DPI, CROP_PADDING_PTS))
                except Exception:
                    reveal_uri = None

                crops.append({
                    "number": fnd["_number"],
                    "kind": fnd["kind"],
                    "detail": fnd["detail"],
                    "uri": crop_uri,
                    "reveal_uri": reveal_uri,
                    "best_effort": fnd["kind"] == "text_over_text",
                })

            page_blocks.append({
                "page_num": page_num,
                "page_uri": page_uri,
                "page_reveal_uri": page_reveal_uri,
                "page_reveal_best_effort": (
                    "text_over_text" in page_reveal_kinds),
                "crops": crops,
                "count": len(findings),
                "uid": f"{aid}-{page_num}",
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


def _render_doc_section(fname, fmd5, page_blocks):
    """Build the HTML for one document's section."""
    parts = []
    parts.append(f'<div class="doc-section">')
    parts.append(f'<h2 class="doc-title">{_esc(fname)}</h2>')
    if fmd5:
        parts.append(f'<div class="doc-md5">MD5: '
                     f'<span class="mono">{_esc(fmd5)}</span></div>')

    for pb in page_blocks:
        parts.append(f'<div class="page-block">')
        parts.append(
            f'<h3 class="page-title">Page {pb["page_num"]} '
            f'<span class="page-count">({pb["count"]} '
            f'overlay{"s" if pb["count"] != 1 else ""} detected)'
            f'</span></h3>')

        # Full annotated page, with before/after toggle when the page's
        # overlays are recoverable (suppress-all-on-page mode).
        if pb.get("page_reveal_uri"):
            sid = f'pg-{pb["uid"]}'
            be_note = ""
            if pb.get("page_reveal_best_effort"):
                be_note = (
                    '<div class="reveal-note best-effort">Reveal includes '
                    'text-over-text reconstruction (best-effort): overlying '
                    'text was suppressed to expose the glyphs beneath. '
                    'Verify against the source document.</div>')
            else:
                be_note = (
                    '<div class="reveal-note">The overlays were suppressed '
                    'to reveal content that remained in the file beneath '
                    'them.</div>')
            parts.append('<div class="page-image-wrap">')
            parts.append(
                f'<div class="toggle-bar" data-stack="{sid}">'
                f'<span class="toggle-label">View:</span>'
                f'<button class="tg-btn active" data-stack="{sid}" '
                f'data-mode="overlay">As displayed</button>'
                f'<button class="tg-btn" data-stack="{sid}" '
                f'data-mode="reveal">Overlays removed</button>'
                f'</div>')
            parts.append(f'<div class="img-stack" id="{sid}">')
            parts.append(
                f'<div class="layer layer-overlay active">'
                f'<div class="print-cap">As displayed '
                f'(overlays present)</div>'
                f'<img class="page-image" src="{pb["page_uri"]}" '
                f'alt="Annotated page {pb["page_num"]}"></div>')
            parts.append(
                f'<div class="layer layer-reveal">'
                f'<div class="print-cap">Overlays removed '
                f'(content beneath)</div>'
                f'<img class="page-image" src="{pb["page_reveal_uri"]}" '
                f'alt="Page {pb["page_num"]} with overlays removed">'
                f'</div>')
            parts.append('</div>')   # img-stack
            parts.append(be_note)
            parts.append('</div>')   # page-image-wrap
        else:
            parts.append('<div class="page-image-wrap">')
            parts.append(
                f'<img class="page-image" src="{pb["page_uri"]}" '
                f'alt="Annotated page {pb["page_num"]}">')
            parts.append('</div>')

        # Detail cards
        parts.append('<div class="findings-grid">')
        for crop in pb["crops"]:
            style = OVERLAY_STYLES.get(crop["kind"],
                                       OVERLAY_STYLES["other"])
            parts.append('<div class="finding-card">')
            parts.append(
                f'<div class="finding-head" '
                f'style="border-left: 6px solid {style["hex"]};">'
                f'<span class="finding-num" '
                f'style="background:{style["hex"]};">'
                f'{crop["number"]}</span>'
                f'<span class="finding-kind">{style["label"]}</span>'
                f'</div>')
            # Crop region: with per-finding before/after toggle when this
            # overlay's underlying content is recoverable.
            if crop["uri"] and crop.get("reveal_uri"):
                csid = f'cr-{pb["uid"]}-{crop["number"]}'
                parts.append(
                    f'<div class="crop-toggle" data-stack="{csid}">'
                    f'<button class="tg-btn sm active" data-stack="{csid}" '
                    f'data-mode="overlay">As displayed</button>'
                    f'<button class="tg-btn sm" data-stack="{csid}" '
                    f'data-mode="reveal">Hidden beneath</button>'
                    f'</div>')
                parts.append(f'<div class="img-stack crop-stack" id="{csid}">')
                parts.append(
                    f'<div class="layer layer-overlay active">'
                    f'<div class="print-cap">As displayed</div>'
                    f'<div class="crop-wrap">'
                    f'<img class="crop-image" src="{crop["uri"]}" '
                    f'alt="Detail {crop["number"]}"></div></div>')
                parts.append(
                    f'<div class="layer layer-reveal">'
                    f'<div class="print-cap">Hidden beneath</div>'
                    f'<div class="crop-wrap">'
                    f'<img class="crop-image" src="{crop["reveal_uri"]}" '
                    f'alt="Detail {crop["number"]} with overlay removed">'
                    f'</div></div>')
                parts.append('</div>')   # img-stack
                if crop.get("best_effort"):
                    parts.append(
                        '<div class="reveal-note best-effort sm">'
                        'Best-effort reconstruction.</div>')
            elif crop["uri"]:
                parts.append(
                    f'<div class="crop-wrap">'
                    f'<img class="crop-image" src="{crop["uri"]}" '
                    f'alt="Detail {crop["number"]}"></div>')
            parts.append(
                f'<div class="finding-detail">'
                f'{_esc(crop["detail"])}</div>')
            parts.append('</div>')
        parts.append('</div>')   # findings-grid
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
  <p>Each flagged page is shown with coloured boxes around the detected
    overlays, numbered to match the detail cards beneath it. Each detail
    card shows a zoomed-in view of the affected region.</p>
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
  function setMode(stackId, mode) {{
    var stack = document.getElementById(stackId);
    if (!stack) return;
    var layers = stack.querySelectorAll(".layer");
    for (var i = 0; i < layers.length; i++) {{
      var isOverlay = layers[i].classList.contains("layer-overlay");
      var on = (mode === "overlay") ? isOverlay : !isOverlay;
      layers[i].classList.toggle("active", on);
    }}
    var btns = document.querySelectorAll(
      '.tg-btn[data-stack="' + stackId + '"]');
    for (var j = 0; j < btns.length; j++) {{
      btns[j].classList.toggle(
        "active", btns[j].getAttribute("data-mode") === mode);
    }}
  }}
  document.addEventListener("click", function (ev) {{
    var btn = ev.target.closest ? ev.target.closest(".tg-btn") : null;
    if (!btn) return;
    var stackId = btn.getAttribute("data-stack");
    var mode = btn.getAttribute("data-mode");
    if (stackId && mode) setMode(stackId, mode);
  }});
}})();
</script>

</body>
</html>"""
