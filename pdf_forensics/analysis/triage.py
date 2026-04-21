"""
PDF triage — fast, lightweight scanning for initial case assessment.

Produces an Excel workbook with two worksheets:
  - pdf-triage: condensed overview (path, dates, image count, author,
    producer, font count, version count, hash)
  - pdf-metadata: full metadata dump (one row per PDF, all metadata
    fields as columns)

Skips deep analysis (no image extraction, no risk scoring, no
overlap detection). Uses only PyMuPDF for speed.
"""

import os
import hashlib
from datetime import datetime

import pymupdf

try:
    import pikepdf
    HAS_PIKEPDF = True
except ImportError:
    HAS_PIKEPDF = False


def _safe_str(val):
    """Convert any value to a safe string for Excel cells."""
    if val is None:
        return ""
    s = str(val)
    # Remove null bytes and other control chars that break Excel
    s = s.replace("\x00", "")
    # Truncate extremely long values
    if len(s) > 32000:
        s = s[:32000] + "..."
    return s


def triage_pdf(pdf_path):
    """
    Fast scan of a single PDF. Returns a dict with triage data,
    or None if the file can't be opened.
    """
    if not os.path.isfile(pdf_path):
        return None

    result = {
        "path": os.path.abspath(pdf_path),
        "filename": os.path.basename(pdf_path),
        "size_bytes": os.path.getsize(pdf_path),
        "pages": 0,
        "image_count": 0,
        "font_count": 0,
        "version_count": 0,
        "dpi_min": "",
        "dpi_max": "",
        "dpi_mixed": "",
        "created": "",
        "modified": "",
        "author": "",
        "creator": "",
        "producer": "",
        "title": "",
        "subject": "",
        "pdf_version": "",
        "encrypted": False,
        "md5": "",
        "metadata": {},
    }

    # MD5 hash
    h = hashlib.md5()
    try:
        with open(pdf_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        result["md5"] = h.hexdigest()
    except Exception:
        pass

    # %%EOF version count
    try:
        with open(pdf_path, "rb") as f:
            data = f.read()
        pos = 0
        eof_count = 0
        while True:
            idx = data.find(b"%%EOF", pos)
            if idx == -1:
                break
            eof_count += 1
            pos = idx + 5
        result["version_count"] = eof_count
    except Exception:
        pass

    # PyMuPDF scan
    try:
        doc = pymupdf.open(pdf_path)
        result["pages"] = len(doc)
        result["encrypted"] = doc.is_encrypted

        meta = doc.metadata or {}
        result["author"] = _safe_str(meta.get("author", ""))
        result["creator"] = _safe_str(meta.get("creator", ""))
        result["producer"] = _safe_str(meta.get("producer", ""))
        result["title"] = _safe_str(meta.get("title", ""))
        result["subject"] = _safe_str(meta.get("subject", ""))
        result["created"] = _safe_str(meta.get("creationDate", ""))
        result["modified"] = _safe_str(meta.get("modDate", ""))
        result["pdf_version"] = _safe_str(meta.get("format", ""))

        for k, v in meta.items():
            if v:
                result["metadata"][_safe_str(k)] = _safe_str(v)

        # Count images and fonts, compute DPI range
        import math
        total_images = 0
        all_fonts = set()
        all_dpis = []
        for page_idx in range(len(doc)):
            try:
                page = doc[page_idx]
                total_images += len(page.get_images(full=True))
                for font in page.get_fonts(full=True):
                    try:
                        font_name = str(font[3]) if len(font) > 3 \
                            else ""
                        if font_name:
                            all_fonts.add(font_name)
                    except Exception:
                        pass

                # Get DPI from image placement transforms
                try:
                    for img_info in page.get_image_info(xrefs=True):
                        t = img_info.get("transform")
                        pw = img_info.get("width", 0)
                        ph = img_info.get("height", 0)
                        if t and pw > 0 and ph > 0 and len(t) >= 4:
                            a, b, c, d = t[0], t[1], t[2], t[3]
                            disp_w = math.sqrt(a*a + b*b)
                            disp_h = math.sqrt(c*c + d*d)
                            if disp_w > 0.01 and disp_h > 0.01:
                                dpi = (pw * 72.0 / disp_w
                                       + ph * 72.0 / disp_h) / 2.0
                                all_dpis.append(round(dpi, 1))
                except Exception:
                    pass
            except Exception:
                pass

        result["image_count"] = total_images
        result["font_count"] = len(all_fonts)

        if all_dpis:
            result["dpi_min"] = min(all_dpis)
            result["dpi_max"] = max(all_dpis)
            spread = max(all_dpis) - min(all_dpis)
            result["dpi_mixed"] = "Yes" if spread > 50 else "No"
        doc.close()
    except Exception as e:
        result["metadata"]["_error"] = _safe_str(e)

    # pikepdf metadata
    if HAS_PIKEPDF:
        try:
            doc_pk = pikepdf.open(pdf_path)
            if doc_pk.docinfo:
                for k, v in doc_pk.docinfo.items():
                    key = _safe_str(k).lstrip("/")
                    result["metadata"][f"info:{key}"] = _safe_str(v)
            try:
                with doc_pk.open_metadata() as xmp:
                    for k, v in xmp.items():
                        if isinstance(v, (list, tuple)):
                            val = ", ".join(_safe_str(x) for x in v)
                        else:
                            val = _safe_str(v)
                        result["metadata"][f"xmp:{k}"] = val
            except Exception:
                pass
            doc_pk.close()
        except Exception:
            pass

    return result


def run_triage(pdf_paths, output_path, session=None,
               progress_callback=None):
    """
    Triage a list of PDFs and write results to an Excel file.

    Parameters:
      pdf_paths         : list of PDF file paths
      output_path       : path for the output .xlsx file
      session           : optional Session for logging
      progress_callback : callable(index, total, filename) per PDF

    Returns (processed_count, skipped_count, output_path).
    """
    from openpyxl import Workbook
    from openpyxl.styles import (
        Font, PatternFill, Alignment, Border, Side)
    from openpyxl.utils import get_column_letter

    results = []
    skipped = 0

    for i, pdf_path in enumerate(pdf_paths):
        if progress_callback:
            progress_callback(i + 1, len(pdf_paths),
                              os.path.basename(pdf_path))

        try:
            triage = triage_pdf(pdf_path)
            if triage:
                results.append(triage)
                if session:
                    session.log(
                        f"  Triaged: {os.path.basename(pdf_path)} "
                        f"({triage['pages']} pages, "
                        f"{triage['image_count']} images)")
            else:
                skipped += 1
                if session:
                    session.log(f"  Skipped: {pdf_path}", "warning")
        except Exception as e:
            skipped += 1
            if session:
                session.log(f"  Error triaging {pdf_path}: {e}",
                            "error")

    if not results:
        return 0, skipped, output_path

    # Build Excel workbook
    wb = Workbook()

    header_font = Font(name="Arial", bold=True, color="FFFFFF",
                       size=10)
    header_fill = PatternFill("solid", fgColor="2B2B2B")
    header_align = Alignment(horizontal="center", vertical="center",
                             wrap_text=True)
    cell_font = Font(name="Arial", size=10)
    border = Border(
        bottom=Side(style="thin", color="3D3D3D"))

    # --- Sheet 1: pdf-triage ---
    ws1 = wb.active
    ws1.title = "pdf-triage"

    triage_headers = [
        "Filename", "Path", "Size (bytes)", "Pages",
        "Images", "Fonts", "Versions (%%EOF)",
        "DPI Min", "DPI Max", "Mixed DPI",
        "Created", "Modified", "Author", "Creator",
        "Producer", "Title", "PDF Version",
        "Encrypted", "MD5",
    ]

    for col, hdr in enumerate(triage_headers, 1):
        cell = ws1.cell(row=1, column=col, value=hdr)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = border

    for row_idx, r in enumerate(results, 2):
        values = [
            r["filename"], r["path"], r["size_bytes"],
            r["pages"], r["image_count"], r["font_count"],
            r["version_count"],
            r["dpi_min"], r["dpi_max"], r["dpi_mixed"],
            _safe_str(r["created"]),
            _safe_str(r["modified"]),
            _safe_str(r["author"]),
            _safe_str(r["creator"]),
            _safe_str(r["producer"]),
            _safe_str(r["title"]),
            _safe_str(r["pdf_version"]),
            "Yes" if r["encrypted"] else "No",
            r["md5"],
        ]
        for col, val in enumerate(values, 1):
            cell = ws1.cell(row=row_idx, column=col, value=val)
            cell.font = cell_font
            cell.border = border

    # Auto-fit column widths
    for col_idx in range(1, len(triage_headers) + 1):
        max_len = len(triage_headers[col_idx - 1])
        for row_idx in range(2, len(results) + 2):
            val = str(ws1.cell(row=row_idx, column=col_idx).value
                      or "")
            max_len = max(max_len, min(len(val), 60))
        col_letter = get_column_letter(col_idx)
        ws1.column_dimensions[col_letter].width = max_len + 3

    ws1.freeze_panes = "B2"
    last_col = get_column_letter(len(triage_headers))
    ws1.auto_filter.ref = f"A1:{last_col}{len(results) + 1}"

    # --- Sheet 2: pdf-metadata ---
    ws2 = wb.create_sheet("pdf-metadata")

    # Collect all unique metadata keys
    all_meta_keys = []
    seen_keys = set()
    for r in results:
        for k in r["metadata"]:
            if k not in seen_keys:
                all_meta_keys.append(k)
                seen_keys.add(k)

    meta_headers = ["Filename", "Path"] + all_meta_keys

    for col, hdr in enumerate(meta_headers, 1):
        cell = ws2.cell(row=1, column=col, value=_safe_str(hdr))
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = border

    for row_idx, r in enumerate(results, 2):
        ws2.cell(row=row_idx, column=1,
                 value=r["filename"]).font = cell_font
        ws2.cell(row=row_idx, column=2,
                 value=r["path"]).font = cell_font
        for col_offset, key in enumerate(all_meta_keys):
            val = _safe_str(r["metadata"].get(key, ""))
            cell = ws2.cell(row=row_idx, column=col_offset + 3,
                            value=val)
            cell.font = cell_font
            cell.border = border

    # Auto-fit metadata columns (limit to 100 columns to avoid
    # performance issues with very wide sheets)
    fit_cols = min(len(meta_headers), 100)
    for col_idx in range(1, fit_cols + 1):
        hdr = str(meta_headers[col_idx - 1])
        max_len = len(hdr)
        for row_idx in range(2, min(len(results) + 2, 102)):
            val = str(ws2.cell(row=row_idx, column=col_idx).value
                      or "")
            max_len = max(max_len, min(len(val), 50))
        col_letter = get_column_letter(col_idx)
        ws2.column_dimensions[col_letter].width = max_len + 3

    ws2.freeze_panes = "C2"
    if meta_headers:
        last_col = get_column_letter(len(meta_headers))
        ws2.auto_filter.ref = f"A1:{last_col}{len(results) + 1}"

    # Save
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    wb.save(output_path)

    if session:
        session.log(f"Triage complete: {len(results)} PDFs -> "
                    f"{output_path}")
        session.register_output("triage", output_path)

    return len(results), skipped, output_path
