"""
Main analysis orchestrator — analyze_pdf and process_pdfs.
"""

import os
import hashlib
from datetime import datetime, timezone

import pymupdf
import pikepdf
from pikepdf import Name

from pdf_forensics.database import (
    init_db, FINDING_TYPE_DEFS, save_to_db,
    check_pdf_already_analyzed,
)
from pdf_forensics.analysis.metadata import (
    extract_pdf_metadata, detect_pdf_versions,
)
from pdf_forensics.analysis.images import (
    find_image_placements, build_image_map,
)
from pdf_forensics.analysis.transparency import (
    enrich_image_transparency,
    get_zorder_and_graphics_state,
)
from pdf_forensics.analysis.detectors import (
    analyze_form_xobject, check_overlapping_images,
    check_image_smasks, check_offpage_images,
    check_dpi_anomalies, check_text_overlays,
    check_content_stream_text_overlay, check_text_over_text,
)
from pdf_forensics.analysis.risk import compute_risk_scores


def print_report(all_findings):
    """Print findings to console."""
    print()
    print("=" * 60)
    print("FINDINGS")
    print("=" * 60)
    print()

    findings = []
    for page_findings in all_findings.values():
        findings.extend(page_findings)

    if not findings:
        print("No image manipulation indicators detected.")
        return

    type_counts = {}
    for f in findings:
        type_counts[f["type"]] = type_counts.get(f["type"], 0) + 1

    print(f"{len(findings)} finding(s) across "
          f"{len(type_counts)} category/categories:\n")
    for t, count in type_counts.items():
        label = FINDING_TYPE_DEFS.get(t, (t, ""))[0]
        print(f"  [{t}] {label}: {count}")
    print()

    high_severity = {"BBOX_CROP", "EXPLICIT_CLIP", "OVERLAP", "OFFPAGE"}
    idx = 0
    for page_num in sorted(all_findings.keys()):
        for f in all_findings[page_num]:
            idx += 1
            severity = "!!!" if f["type"] in high_severity else " ! "
            print(f"--- Finding {idx} [{severity}] ---")
            print(f"  Page:    {page_num}")
            print(f"  Image:   {f['image']}")
            print(f"  Type:    {f['type']} - "
                  f"{FINDING_TYPE_DEFS.get(f['type'], ('',''))[0]}")
            print(f"  Detail:  {f['detail']}")
            print()


def analyze_pdf(pdf_path, db_path, extract_dir=None,
                store_images=True, conn=None, session=None,
                skip_duplicates=True, force=False,
                quiet=False, progress_callback=None):
    """
    Analyze a single PDF.

    Parameters:
      pdf_path          : path to the PDF file
      db_path           : SQLite database file (created if missing)
      extract_dir       : directory to write extracted image files to;
                          None means do not write images to disk
      store_images      : whether to store image bytes inside the database
      conn              : optional pre-opened sqlite connection (for batch
                          processing); if None, one is opened and closed
      session           : optional Session for forensic logging
      skip_duplicates   : if True, skip PDFs already in the database
                          (by MD5 match) unless force is True
      force             : if True, process even if already analyzed
      quiet             : if True, suppress all terminal output
      progress_callback : callable(page_num, total_pages) called after
                          each page is processed (for GUI progress)

    Returns a dict summarising the run, or None if skipped/failed.
    """
    def _out(*args, **kwargs):
        if not quiet:
            print(*args, **kwargs)

    if not os.path.isfile(pdf_path):
        msg = f"File not found: {pdf_path}"
        _out(f"Error: {msg}")
        if session:
            session.log(msg, "error")
        return None

    _out("PDF Forensics")
    _out("=" * 60)
    _out(f"  File:     {os.path.basename(pdf_path)}")
    _out(f"  Path:     {os.path.abspath(pdf_path)}")
    _out(f"  Size:     {os.path.getsize(pdf_path):,} bytes")
    _out(f"  Database: {os.path.abspath(db_path)}")
    _out(f"  Store images in DB: {'yes' if store_images else 'no'}")

    if session:
        pdf_md5 = hashlib.md5()
        with open(pdf_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                pdf_md5.update(chunk)
        session.log_pdf_start(pdf_path, pdf_md5.hexdigest(),
                              os.path.getsize(pdf_path))

    if extract_dir:
        os.makedirs(extract_dir, exist_ok=True)
        _out(f"  Extract:  {os.path.abspath(extract_dir)}")
    else:
        _out(f"  Extract:  (disk extraction disabled)")

    own_conn = False
    if conn is None:
        conn = init_db(db_path, session=session)
        own_conn = True

    # Duplicate detection
    if skip_duplicates and not force:
        already, info = check_pdf_already_analyzed(conn, pdf_path)
        if already:
            msg = (f"Already analyzed: {info['pdf_filename']} "
                   f"on {info['analyzed_at']}")
            _out(f"  SKIPPED — {msg}")
            if session:
                session.log(f"  Skipped (duplicate): {msg}")
            if own_conn:
                conn.close()
            return {"pdf": pdf_path, "skipped": True,
                    "reason": msg}

    doc_mu = pymupdf.open(pdf_path)
    doc_pk = pikepdf.open(pdf_path)

    total_pages = len(doc_mu)
    page_pad = len(str(total_pages))
    _out(f"  Pages:    {total_pages}")

    # Extract PDF metadata and detect prior versions
    pdf_metadata = extract_pdf_metadata(doc_pk, doc_mu)
    pdf_versions = detect_pdf_versions(pdf_path)
    _out(f"  Metadata: {len(pdf_metadata)} entries")
    _out(f"  Versions: {len(pdf_versions)} %%EOF marker(s)"
         + (" — incremental updates present!"
            if len(pdf_versions) > 1 else ""))
    _out()

    all_findings = {}
    page_data = {}
    total_extracted = 0

    for page_idx in range(total_pages):
        page_num = page_idx + 1
        page_mu = doc_mu[page_idx]
        page_pk = doc_pk.pages[page_idx]

        # Build image map from content stream
        placements, label_to_info, xref_to_labels, \
            form_xref_to_labels = \
            build_image_map(page_pk, page_num, page_pad, doc_mu)

        img_count = len(label_to_info)
        _out(f"  Page {page_num}: {img_count} image(s)")
        for label in sorted(label_to_info.keys()):
            info = label_to_info[label]
            _out(f"    {label}.{info['ext']}")

            # Write image to extraction directory (if requested)
            if extract_dir and info.get("image_bytes"):
                filename = f"{label}.{info['ext']}"
                filepath = os.path.join(extract_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(info["image_bytes"])
                total_extracted += 1

        # Z-order and graphics state
        gstate_per_do = get_zorder_and_graphics_state(page_pk)
        transparency = enrich_image_transparency(
            label_to_info, placements, gstate_per_do, page_pk
        )

        # Print transparency info
        for label, t in sorted(transparency.items()):
            parts = [f"z={t['z_order']}"]
            if t["opacity"] < 1.0:
                parts.append(f"opacity={t['opacity']:.0%}")
            if t["blend_mode"] != "/Normal":
                parts.append(f"blend={t['blend_mode']}")
            if t["has_smask"]:
                parts.append("SMask")
            if t["in_transparency_group"]:
                parts.append("TransparencyGroup")
            if len(parts) > 1 or t["opacity"] < 1.0 or t["has_smask"]:
                _out(f"      {label}: {', '.join(parts)}")

        findings = []

        # Analyze Form XObjects for cropping / clipping
        xobjects = page_pk.get("/Resources", {}).get("/XObject", {})
        analyzed_forms = set()
        for xobj_name, xobj_ref in xobjects.items():
            try:
                resolved = (xobj_ref.resolve()
                            if hasattr(xobj_ref, "resolve")
                            else xobj_ref)
            except Exception:
                continue
            if resolved.get("/Subtype") != Name("/Form"):
                continue

            form_objnum = (xobj_ref.objgen[0]
                           if hasattr(xobj_ref, "objgen") else None)

            if form_objnum in analyzed_forms:
                continue
            analyzed_forms.add(form_objnum)

            image_labels = form_xref_to_labels.get(form_objnum, [])
            analyze_form_xobject(resolved, xobj_name, page_num,
                                 findings, image_labels)

        check_overlapping_images(page_mu, page_num, findings,
                                 label_to_info, transparency)
        check_image_smasks(page_pk, page_num, findings, label_to_info)
        check_offpage_images(page_mu, page_num, findings, label_to_info)
        check_text_overlays(page_pk, page_mu, page_num, findings)
        check_content_stream_text_overlay(
            page_pk, page_mu, page_num, findings)
        check_text_over_text(page_mu, page_num, findings, page_pk=page_pk)

        # Compute per-image risk scores from the findings on this page
        risk_scores = compute_risk_scores(findings, label_to_info)

        all_findings[page_num] = findings
        page_data[page_num] = {
            "label_to_info": label_to_info,
            "transparency": transparency,
            "findings": findings,
            "risk_scores": risk_scores,
        }

        if progress_callback:
            progress_callback(page_num, total_pages)

    # Document-level DPI anomaly detection (runs after all pages)
    dpi_findings = check_dpi_anomalies(page_data)
    if dpi_findings:
        for df in dpi_findings:
            pg = df["page_num"]
            if pg in page_data:
                page_data[pg]["findings"].append(df)
                if pg in all_findings:
                    all_findings[pg].append(df)
                else:
                    all_findings[pg] = [df]
                # Recompute risk scores for affected pages
                page_data[pg]["risk_scores"] = compute_risk_scores(
                    page_data[pg]["findings"],
                    page_data[pg]["label_to_info"])

    # Extract reviewer comments / markup annotations before closing.
    try:
        from pdf_forensics.analysis.comments import extract_comments
        pdf_comments = extract_comments(doc_pk)
    except Exception:
        pdf_comments = []

    doc_mu.close()
    doc_pk.close()

    if not quiet:
        print_report(all_findings)

    save_to_db(conn, pdf_path, total_pages, page_data,
               pdf_metadata=pdf_metadata,
               pdf_versions=pdf_versions,
               store_images=store_images,
               comments=pdf_comments)
    if own_conn:
        conn.close()

    total_findings = sum(len(f) for f in all_findings.values())
    _out(f"Results saved to: {os.path.abspath(db_path)}")
    _out(f"  {total_findings} finding(s) recorded.")
    if extract_dir:
        _out(f"  {total_extracted} image(s) extracted to: "
             f"{os.path.abspath(extract_dir)}")
    _out(f"  {len(pdf_metadata)} metadata entries stored.")
    _out(f"  {len(pdf_versions)} version marker(s) stored.")

    # High-risk image summary
    high_risk = []
    total_risk_imgs = 0
    for page_num, pd in page_data.items():
        for label, score in pd.get("risk_scores", {}).items():
            if score > 0:
                total_risk_imgs += 1
            if score >= 30:
                high_risk.append((page_num, label, score))

    if total_risk_imgs:
        _out(f"  {total_risk_imgs} image(s) carry a non-zero risk score.")
    if high_risk:
        high_risk.sort(key=lambda x: -x[2])
        _out(f"  {len(high_risk)} high-risk image(s) (score >= 30):")
        for page_num, label, score in high_risk[:10]:
            _out(f"    page {page_num}, {label}: risk score {score}")
        if len(high_risk) > 10:
            _out(f"    ... and {len(high_risk) - 10} more")

    # Session logging
    if session:
        session.log_pdf_complete(
            pdf_path, total_pages, total_extracted,
            total_findings, high_risk_count=len(high_risk))

    return {
        "pdf": pdf_path,
        "db": os.path.abspath(db_path),
        "extract_dir": (os.path.abspath(extract_dir)
                        if extract_dir else None),
        "total_pages": total_pages,
        "total_findings": total_findings,
        "total_extracted": total_extracted,
        "metadata_count": len(pdf_metadata),
        "version_count": len(pdf_versions),
    }


def process_pdfs(pdf_paths, db_path, output_dir=None,
                 store_images=True, extract_to_disk=True,
                 session=None, skip_duplicates=True, force=False,
                 quiet=False, progress_callback=None):
    """
    Process one or more PDFs in a single batch.

    For each PDF, an extraction subfolder is created under
    output_dir (named after the PDF basename without extension).
    If output_dir is None and extract_to_disk is True, defaults to
    a per-PDF folder in the current working directory.
    """
    conn = init_db(db_path, session=session)
    summaries = []
    skipped = 0

    for pdf_path in pdf_paths:
        if not os.path.isfile(pdf_path):
            msg = f"Skipping (not found): {pdf_path}"
            if not quiet:
                print(msg)
            if session:
                session.log(msg, "warning")
            continue

        if extract_to_disk:
            base = os.path.splitext(os.path.basename(pdf_path))[0]
            if output_dir:
                pdf_extract_dir = os.path.join(output_dir, base)
            else:
                pdf_extract_dir = base + "_images"
        else:
            pdf_extract_dir = None

        try:
            summary = analyze_pdf(
                pdf_path, db_path,
                extract_dir=pdf_extract_dir,
                store_images=store_images,
                conn=conn,
                session=session,
                skip_duplicates=skip_duplicates,
                force=force,
                quiet=quiet,
                progress_callback=progress_callback,
            )
            if summary:
                if summary.get("skipped"):
                    skipped += 1
                else:
                    summaries.append(summary)
        except Exception as e:
            if not quiet:
                print(f"Error processing {pdf_path}: {e}")
            if session:
                session.log_pdf_error(pdf_path, e)
        if not quiet:
            print()

    conn.close()

    if skipped and not quiet:
        print(f"  {skipped} PDF(s) skipped (already in database)")

    return summaries


def extract_prior_versions(pdf_path, output_dir, session=None):
    """
    Extract prior versions of a PDF from incremental updates.

    Each %%EOF marker in the file delimits a version. The first
    %%EOF is version 1 (original), the second is version 2, etc.
    The full file is the final version.

    Only extracts if 2+ %%EOF markers are found. Extracted files
    are saved as {basename}_version1.pdf, {basename}_version2.pdf, etc.
    The final version is not extracted (it's the original file).

    Parameters:
      pdf_path   : path to the PDF file
      output_dir : directory to write extracted versions into
      session    : optional Session for logging

    Returns a list of extracted file paths (empty if no prior versions).
    """
    from pdf_forensics.analysis.metadata import detect_pdf_versions

    versions = detect_pdf_versions(pdf_path)
    if len(versions) <= 1:
        return []

    try:
        with open(pdf_path, "rb") as f:
            data = f.read()
    except Exception as e:
        if session:
            session.log(f"  Could not read {pdf_path}: {e}", "error")
        return []

    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    version_dir = os.path.join(output_dir, basename + "_versions")
    os.makedirs(version_dir, exist_ok=True)

    extracted = []
    # Extract all versions except the last (which is the full file)
    for version_num, eof_offset in versions[:-1]:
        # Include the %%EOF marker itself plus trailing newline
        end_pos = eof_offset + 5  # len(b"%%EOF")
        # Skip trailing whitespace/newlines
        while end_pos < len(data) and data[end_pos:end_pos+1] in (
                b"\r", b"\n", b" "):
            end_pos += 1

        version_data = data[:end_pos]
        version_filename = f"{basename}_version{version_num}.pdf"
        version_path = os.path.join(version_dir, version_filename)

        with open(version_path, "wb") as f:
            f.write(version_data)

        extracted.append(version_path)
        if session:
            session.log(
                f"  Extracted version {version_num}: "
                f"{version_filename} ({len(version_data):,} bytes)")

    return extracted
