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
import io
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
    Fast scan of a single PDF file. Returns a dict with triage data,
    or None if the file can't be opened.
    """
    if not os.path.isfile(pdf_path):
        return None
    try:
        with open(pdf_path, "rb") as f:
            data = f.read()
    except Exception:
        return None
    return triage_pdf_bytes(data, os.path.basename(pdf_path),
                            os.path.abspath(pdf_path))


def triage_pdf_bytes(data, filename, path, source="Current",
                     version_number=None, password_manager=None,
                     parent_password=None):
    """
    Fast scan of a PDF held in memory. Used both for files on disk
    (via triage_pdf) and for prior versions reconstructed in memory,
    so that prior-version metadata is extracted by exactly the same
    method as the current version and appears in the same worksheet.

    Parameters:
      data           : the raw PDF bytes
      filename       : display filename for the row
      path           : source path (the parent file's path for a
                       reconstructed prior version)
      source         : "Current" or a prior-version label
      version_number : the version number for a prior version, else None
      password_manager : the run's PasswordManager (supplied list and
                       passwords already found to work), or None
      parent_password : for a prior version, the password that opened the
                       current version. Tried first, as in analysis,
                       because a genuine earlier version normally shares
                       the parent document's encryption.

    Returns a triage result dict, or None if the bytes can't be parsed.
    """
    if not data:
        return None

    result = {
        "path": path,
        "filename": filename,
        "source": source,
        "version_number": version_number,
        "size_bytes": len(data),
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
        "enc_status": "",
        "enc_password": "",
        "enc_opened": True,
        "version_check": "",
        "md5": "",
        "metadata": {},
    }

    # MD5 hash (over the exact bytes triaged — for a prior version this
    # equals the MD5 of the file the version-extraction feature would
    # write to disk, so the two agree)
    try:
        result["md5"] = hashlib.md5(data).hexdigest()
    except Exception:
        pass

    # %%EOF version count within these bytes
    try:
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

    # Encryption: detect reliably (also catches permissions-only and
    # locked files that PyMuPDF will not open from a stream), and if a
    # password list was supplied, find a password that opens the file so
    # its metadata can still be read.
    enc_pw = None
    try:
        from pdf_forensics import passwords as _pw
        from pdf_forensics import _mupdf as _mu
        _mu.silence()
        if data and _pw.is_encrypted(data):
            result["encrypted"] = True
            mgr = (password_manager if password_manager is not None
                   else _pw.PasswordManager())
            res = None
            # A prior version: try the parent document's password first.
            # The empty password is excluded here because try_open below
            # always tries it first anyway.
            if parent_password:
                try:
                    if _pw._pikepdf_opens(data, parent_password):
                        res = {"opened": True, "password": parent_password,
                               "label": "parent document's password"}
                except Exception:
                    res = None
            if res is None:
                res = _pw.try_open(data, mgr)
            if res["opened"]:
                enc_pw = res["password"]
                result["enc_password"] = res["password"]
                result["enc_status"] = (
                    "Opened with no password (permissions-only)"
                    if res["password"] == ""
                    else "Opened with the parent document's password"
                    if res.get("label") == "parent document's password"
                    else "Opened with a supplied password")
            else:
                result["enc_opened"] = False
                result["enc_status"] = (
                    "Not opened \u2014 no password list supplied"
                    if mgr.supplied_count == 0
                    else "Not opened \u2014 no supplied password worked")
    except Exception:
        pass

    # PyMuPDF scan
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
        if enc_pw:
            try:
                doc.authenticate(enc_pw)
            except Exception:
                pass
        result["pages"] = len(doc)
        result["encrypted"] = result["encrypted"] or doc.is_encrypted

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
            doc_pk = pikepdf.open(io.BytesIO(data),
                                  password=(enc_pw or ""))
            if doc_pk.docinfo:
                for k, v in doc_pk.docinfo.items():
                    key = _safe_str(k).lstrip("/")
                    result["metadata"][f"info:{key}"] = _safe_str(v)
            try:
                with doc_pk.open_metadata() as xmp:
                    for k, v in xmp.items():
                        if isinstance(v, (set, frozenset)):
                            val = ", ".join(sorted(_safe_str(x) for x in v))
                        elif isinstance(v, (list, tuple)):
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


def reconstruct_prior_versions(data, password=None):
    """
    Reconstruct the bytes of each genuine prior version of a PDF from its
    incremental-update structure, in memory.

    Each %%EOF marker before the last may delimit a version, but not every
    one does: a linearized file's first %%EOF ends its first-page section,
    and some markers end bytes that are not a usable PDF. Those are
    excluded (see metadata.classify_prior_versions). The bytes returned are
    byte-identical to the files extract_prior_versions() writes to disk.

    Returns a list of (version_number, version_bytes) for usable versions
    ('valid' or password-protected); version_number is the ordinal of the
    %%EOF marker, kept for traceability to the byte offset.
    """
    if not data:
        return []
    from pdf_forensics.analysis.metadata import classify_prior_versions
    return [(c["version_number"], data[:c["end"]])
            for c in classify_prior_versions(data, password=password)
            if c["status"] in ("valid", "encrypted")]

def run_triage(pdf_paths, output_path, session=None,
               progress_callback=None, include_prior_versions=True,
               password_manager=None, run_state=None):
    """
    Triage a list of PDFs and write results to an Excel file.

    Parameters:
      pdf_paths              : list of PDF file paths
      output_path            : path for the output .xlsx file
      session                : optional Session for logging
      progress_callback      : callable(index, total, filename) per PDF
      include_prior_versions : when True (default), any PDF containing
                               incremental updates (2+ %%EOF markers)
                               also contributes one row per prior
                               version, so the prior versions' metadata
                               appears in the spreadsheet alongside the
                               current version's.

      password_manager       : the run's PasswordManager, or None
      run_state              : optional dict that carries a triage run's
                               rows between calls, so a later call can be
                               merged into the same spreadsheet. Pass an
                               empty dict to the first call; it is filled
                               with that run's rows. Pass the same dict to
                               a later call (e.g. the end-of-run retry of
                               encrypted files with a new password list):
                               that call re-triages only its files, then
                               replaces every row for each of them
                               (current version, prior versions and
                               comments) in place and rewrites the
                               spreadsheet with all rows. Rows for other
                               files are kept unchanged, in their original
                               order. A file whose re-triage produced no
                               row keeps its earlier rows. A merging call
                               uses the first call's include_prior_versions
                               setting, so prior-version rows are replaced
                               rather than dropped.

    Returns (processed_count, skipped_count, output_path, locked), where
    processed_count counts the rows triaged in this call (including
    prior-version rows) and locked lists the encrypted files this call
    could not open. When nothing could be triaged, no spreadsheet is
    written (an existing one is left unchanged) and processed_count is 0.
    """
    from openpyxl import Workbook
    from openpyxl.styles import (
        Font, PatternFill, Alignment, Border, Side)
    from openpyxl.utils import get_column_letter

    merging = (run_state is not None
               and run_state.get("results") is not None)
    if merging:
        include_prior_versions = run_state.get(
            "include_prior_versions", include_prior_versions)

    results = []
    skipped = 0
    all_comments = []   # flat list across all triaged PDFs

    def _extract_comments(data_or_path, row):
        """Append this row's reviewer comments to all_comments,
        tagged with the row's filename/path/source. Accepts a path
        (str) or raw bytes."""
        # An encrypted file is opened with the password that opened it for
        # triage ("" for permissions-only files); one that could not be
        # opened has no readable comments and is already reported as such.
        if row.get("encrypted") and not row.get("enc_opened", True):
            return
        password = row.get("enc_password") or ""
        try:
            import pikepdf
            from pdf_forensics.analysis.comments import extract_comments
            if isinstance(data_or_path, (bytes, bytearray)):
                ctx = pikepdf.open(io.BytesIO(data_or_path),
                                   password=password)
            else:
                ctx = pikepdf.open(data_or_path, password=password)
            with ctx as _cpdf:
                for c in extract_comments(_cpdf):
                    c = dict(c)
                    c["filename"] = row["filename"]
                    c["path"] = row["path"]
                    c["source"] = row.get("source", "Current")
                    all_comments.append(c)
        except Exception as e:
            if session:
                session.log(
                    f"  Could not extract comments from "
                    f"{row['filename']}: {e}", "warning")

    # PyMuPDF messages raised while triaging (e.g. "corrupt object stream")
    # are kept off the console by _mupdf.silence() and written to the
    # session log here, attributed to the file or prior version that
    # produced them, as analysis does. Anything left over from earlier
    # processing in the session is logged first under its own label so it
    # is not attributed to the first triaged file.
    from pdf_forensics import _mupdf as _mu

    def _log_mupdf(context):
        try:
            _mu.drain(session, context)
        except Exception:
            pass

    _log_mupdf("before triage")

    locked_unopened = []
    for i, pdf_path in enumerate(pdf_paths):
        if progress_callback:
            progress_callback(i + 1, len(pdf_paths),
                              os.path.basename(pdf_path))

        try:
            # Read once; reuse the bytes for the current-version triage,
            # prior-version reconstruction, and comment extraction.
            file_data = None
            try:
                with open(pdf_path, "rb") as fh:
                    file_data = fh.read()
            except Exception:
                file_data = None

            if file_data is not None:
                triage = triage_pdf_bytes(
                    file_data, os.path.basename(pdf_path),
                    os.path.abspath(pdf_path),
                    password_manager=password_manager)
            else:
                triage = triage_pdf(pdf_path)
            _log_mupdf(f"triage: {os.path.basename(pdf_path)}")
            if triage and triage.get("encrypted") and not triage.get("enc_opened", True):
                locked_unopened.append(os.path.abspath(pdf_path))
                if session:
                    session.log(f"  Encrypted, not opened: "
                                f"{os.path.basename(pdf_path)} — "
                                f"{triage.get('enc_status','')}", "warning")

            if triage:
                results.append(triage)
                _extract_comments(
                    file_data if file_data is not None else pdf_path,
                    triage)
                if session:
                    session.log(
                        f"  Triaged: {os.path.basename(pdf_path)} "
                        f"({triage['pages']} pages, "
                        f"{triage['image_count']} images)")

                # Prior versions: reconstruct in memory and triage each
                # with the same method, so their metadata lands in the
                # spreadsheet just as it does in the HTML metadata report.
                if include_prior_versions and file_data is not None:
                    base = os.path.splitext(
                        os.path.basename(pdf_path))[0]
                    try:
                        from pdf_forensics.analysis.metadata import (
                            classify_prior_versions, describe_version_check)
                        _ppw = (triage.get("enc_password") or None) if triage else None
                        _checks = classify_prior_versions(file_data, password=_ppw)
                        if triage is not None:
                            triage["version_check"] = describe_version_check(_checks)
                        for _c in _checks:
                            if _c["status"] in ("valid", "encrypted") or not session:
                                continue
                            session.log(
                                f"    \u21b3 %%EOF {_c['version_number']} at byte "
                                f"{_c['eof_offset']:,}: "
                                + ("not a prior version (linearized file, "
                                   "first-page section)"
                                   if _c["status"] == "linearization" else
                                   f"not a usable prior version ({_c['reason']})"))
                        priors = [(_c["version_number"], file_data[:_c["end"]])
                                  for _c in _checks
                                  if _c["status"] in ("valid", "encrypted")]
                    except Exception as e:
                        priors = []
                        if session:
                            session.log(
                                f"  Could not reconstruct prior "
                                f"versions of "
                                f"{os.path.basename(pdf_path)}: {e}",
                                "warning")
                    for vnum, vbytes in priors:
                        vname = f"{base}_version{vnum}.pdf"
                        # Same password handling as the current version:
                        # the parent's password first, then the run's
                        # list. Without these a prior version of an
                        # encrypted file could not be opened, and was
                        # reported as "no password list supplied" even
                        # when one had been.
                        vtriage = triage_pdf_bytes(
                            vbytes, vname,
                            os.path.abspath(pdf_path),
                            source=f"Prior v{vnum}",
                            version_number=vnum,
                            password_manager=password_manager,
                            parent_password=_ppw)
                        _log_mupdf(f"triage: {vname}")
                        if (vtriage and vtriage.get("encrypted")
                                and not vtriage.get("enc_opened", True)
                                and session):
                            session.log(
                                f"    \u21b3 Prior version {vnum} is "
                                f"encrypted and was not opened: {vname} "
                                f"\u2014 {vtriage.get('enc_status', '')}",
                                "warning")
                        if vtriage:
                            results.append(vtriage)
                            _extract_comments(vbytes, vtriage)
                            if session:
                                session.log(
                                    f"    \u21b3 Prior version {vnum} "
                                    f"metadata included ({vname})")
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
        # Nothing triaged: write nothing, so a spreadsheet from an earlier
        # call (when merging) is left as it was.
        if session and merging:
            session.log(f"Triage re-run produced no rows; "
                        f"{os.path.basename(output_path)} left unchanged.")
        return 0, skipped, output_path, locked_unopened

    processed_now = len(results)
    if merging:
        replaced = []
        for r in results:
            if r["path"] not in replaced:
                replaced.append(r["path"])
        results = _merge_rows(run_state["results"], results, replaced)
        all_comments = _merge_rows(run_state.get("comments") or [],
                                   all_comments, replaced)
        # Keep comments in the same file order as the triage rows.
        order = {}
        for i, r in enumerate(results):
            order.setdefault(r["path"], i)
        all_comments.sort(key=lambda c: order.get(c.get("path"), len(order)))

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
        "Filename", "Source", "Path", "Size (bytes)", "Pages",
        "Images", "Fonts", "Versions (%%EOF)",
        "DPI Min", "DPI Max", "Mixed DPI",
        "Created", "Modified", "Author", "Creator",
        "Producer", "Title", "PDF Version",
        "Encrypted", "Encryption Status", "Password", "Prior-Version Check",
        "MD5",
    ]

    for col, hdr in enumerate(triage_headers, 1):
        cell = ws1.cell(row=1, column=col, value=hdr)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = border

    for row_idx, r in enumerate(results, 2):
        values = [
            r["filename"], r.get("source", "Current"), r["path"],
            r["size_bytes"],
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
            _safe_str(r.get("enc_status", "")),
            _safe_str(r.get("enc_password", "")),
            _safe_str(r.get("version_check", "")),
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

    ws1.freeze_panes = "C2"
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

    # Info vs XMP date comparison: TRUE when both denote the same moment
    # (within 60 seconds, after conversion to UTC), FALSE when they do
    # not, blank when either is missing or unparseable.
    cmp_headers = ["CreationDate: Info = XMP", "ModDate: Info = XMP"]

    def _cmp(meta, info_key, xmp_suffix):
        from pdf_forensics.reports.queries import _dates_match
        info = meta.get(f"info:{info_key}")
        xmp = next((v for k, v in meta.items()
                    if k.startswith("xmp:") and k.lower().endswith(xmp_suffix)
                    and v), None)
        return _dates_match(info, xmp)

    meta_headers = (["Filename", "Source", "Path"] + cmp_headers
                    + all_meta_keys)

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
                 value=r.get("source", "Current")).font = cell_font
        ws2.cell(row=row_idx, column=3,
                 value=r["path"]).font = cell_font
        for ci, (ik, xs) in enumerate((("CreationDate", "createdate"),
                                       ("ModDate", "modifydate"))):
            v = _cmp(r["metadata"], ik, xs)
            cell = ws2.cell(row=row_idx, column=4 + ci, value=v)
            cell.font = cell_font
            cell.border = border
            if v == "FALSE":
                cell.font = Font(name=cell_font.name, size=cell_font.size,
                                 bold=True, color="C00000")
        for col_offset, key in enumerate(all_meta_keys):
            val = _safe_str(r["metadata"].get(key, ""))
            cell = ws2.cell(row=row_idx, column=col_offset + 6,
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

    # --- Sheet 3: comments (only if any comments were found) ---
    if all_comments:
        ws3 = wb.create_sheet("comments")
        comment_headers = [
            "Filename", "Source", "Path", "Page", "Type", "Author",
            "Date/Time", "Created", "Modified", "Comment", "Object",
        ]
        for col, hdr in enumerate(comment_headers, 1):
            cell = ws3.cell(row=1, column=col, value=hdr)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            cell.border = border

        for row_idx, c in enumerate(all_comments, 2):
            obj = ""
            if c.get("obj_num") is not None:
                obj = f"{c['obj_num']} {c.get('obj_gen', 0)} R"
            # Date/Time prefers the modification date, falling back to
            # creation date, matching the requested single date column.
            dt = c.get("modified_date") or c.get("created_date") or ""
            row_vals = [
                c.get("filename", ""),
                c.get("source", "Current"),
                c.get("path", ""),
                c.get("page_number", ""),
                c.get("annot_subtype", ""),
                c.get("author", ""),
                dt,
                c.get("created_date", ""),
                c.get("modified_date", ""),
                c.get("contents", ""),
                obj,
            ]
            for col, val in enumerate(row_vals, 1):
                cell = ws3.cell(row=row_idx, column=col,
                                value=_safe_str(val))
                cell.font = cell_font
                cell.border = border

        # Auto-fit comment columns
        for col_idx in range(1, len(comment_headers) + 1):
            hdr = comment_headers[col_idx - 1]
            max_len = len(hdr)
            for row_idx in range(2, len(all_comments) + 2):
                val = str(ws3.cell(row=row_idx, column=col_idx).value
                          or "")
                max_len = max(max_len, min(len(val), 60))
            ws3.column_dimensions[
                get_column_letter(col_idx)].width = max_len + 3

        ws3.freeze_panes = "C2"
        last_col = get_column_letter(len(comment_headers))
        ws3.auto_filter.ref = f"A1:{last_col}{len(all_comments) + 1}"

    # Save
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    wb.save(output_path)

    if session:
        if merging:
            session.log(f"Triage re-run merged: {len(replaced)} file(s) "
                        f"re-triaged ({processed_now} row(s)) and their "
                        f"earlier rows replaced; the spreadsheet now has "
                        f"{len(results)} row(s) -> {output_path}")
        else:
            session.log(f"Triage complete: {len(results)} PDFs -> "
                        f"{output_path}")
        if all_comments:
            session.log(f"  {len(all_comments)} comment(s) extracted "
                        f"to the 'comments' worksheet.")
        if ("triage", os.path.abspath(output_path)) not in getattr(
                session, "outputs", []):
            session.register_output("triage", output_path)

    if run_state is not None:
        run_state["results"] = results
        run_state["comments"] = all_comments
        run_state["include_prior_versions"] = include_prior_versions
        run_state["output_path"] = output_path

    return processed_now, skipped, output_path, locked_unopened


def _merge_rows(old_rows, new_rows, paths):
    """Replace, in place, every old row whose "path" is in paths with the
    new rows for that path (in their new order); keep all other old rows
    unchanged and in order. New rows for a path with no old rows are
    appended at the end."""
    paths = set(paths)
    by_path = {}
    for r in new_rows:
        by_path.setdefault(r.get("path"), []).append(r)
    out, emitted = [], set()
    for r in old_rows:
        p = r.get("path")
        if p in paths:
            if p not in emitted:
                out.extend(by_path.get(p, []))
                emitted.add(p)
            continue
        out.append(r)
    for p in paths:
        if p not in emitted:
            out.extend(by_path.get(p, []))
    return out
