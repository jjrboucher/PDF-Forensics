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
    init_db, FINDING_TYPE_DEFS, save_to_db, record_submission,
    check_pdf_already_analyzed,
)
from pdf_forensics.analysis.metadata import (
    extract_pdf_metadata, detect_pdf_versions, detect_linearization,
)
from pdf_forensics.analysis.images import (
    find_image_placements, build_image_map,
)
from pdf_forensics.analysis.transparency import (
    enrich_image_transparency,
    get_zorder_and_graphics_state,
)
from pdf_forensics.analysis.detectors import (
    extract_page_text, merge_text_over_white_box,
    analyze_form_xobject, check_overlapping_images,
    check_image_smasks, check_offpage_images,
    check_dpi_anomalies, check_text_overlays,
    check_content_stream_text_overlay, check_text_over_text,
    collect_page_fonts, check_font_anomalies,
)
from pdf_forensics.analysis.risk import (
    compute_risk_scores, compute_document_risk,
)
from pdf_forensics.analysis.doc_checks import (
    check_metadata_consistency, check_signature_coverage,
    check_structural_integrity, check_mixed_cameras,
    check_unapplied_redactions, extract_camera_info,
    check_version_anachronism, check_metadata_history,
)
from pdf_forensics.analysis.timeline import (
    build_timeline, timeline_findings, timeline_rows, exif_dates,
)
from pdf_forensics.database import save_timeline


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
                quiet=False, progress_callback=None,
                source_analysis_id=None, version_number=None,
                password=None):
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
                session.log(
                    f"  Skipped: {os.path.basename(pdf_path)} is "
                    f"byte-identical to {info['pdf_filename']} (already "
                    f"analysed {info['analyzed_at']}); not re-analysed")
            record_submission(conn, pdf_path, "duplicate", session=session,
                              analysis_id=info.get("id"),
                              duplicate_of=info.get("pdf_filename"),
                              is_version=version_number is not None)
            if own_conn:
                conn.close()
            return {"pdf": pdf_path, "skipped": True,
                    "reason": msg, "duplicate_of": info.get("pdf_filename")}

    # password is the empty/real password that opens an encrypted file
    # (found by process_pdfs). pikepdf takes it directly; PyMuPDF opens
    # then authenticates. Harmless for unencrypted files.
    from pdf_forensics import _mupdf as _mu
    _mu.silence()
    if password is not None:
        doc_pk = pikepdf.open(pdf_path, password=password)
        doc_mu = pymupdf.open(pdf_path)
        if doc_mu.needs_pass:
            doc_mu.authenticate(password)
    else:
        doc_mu = pymupdf.open(pdf_path)
        doc_pk = pikepdf.open(pdf_path)

    _mu.drain(session, os.path.basename(pdf_path))
    total_pages = len(doc_mu)
    page_pad = len(str(total_pages))
    _out(f"  Pages:    {total_pages}")

    # Extract PDF metadata and detect prior versions
    pdf_metadata = extract_pdf_metadata(doc_pk, doc_mu)
    pdf_versions = detect_pdf_versions(pdf_path)
    # Linearized (web-optimized) files legitimately carry two %%EOF
    # markers; record the linearization state so the %%EOF count can be
    # interpreted correctly downstream. If the file head could not be
    # read the state is recorded as 'indeterminate' rather than guessed.
    linearized = detect_linearization(pdf_path)
    pdf_metadata.append(("catalog", "linearized",
                         "indeterminate" if linearized is None
                         else str(linearized)))
    _out(f"  Metadata: {len(pdf_metadata)} entries")
    _out(f"  Versions: {len(pdf_versions)} %%EOF marker(s)"
         + (" — incremental updates present!"
            if len(pdf_versions) > 1 else ""))
    _out()

    all_findings = {}
    page_data = {}
    total_extracted = 0
    doc_font_spans = []   # accumulated across pages for font analysis (ANAL-03)
    doc_cameras = {}      # {label: (make, model)} for mixed-camera check
    doc_exif_dates = []   # photo capture dates for the timeline

    for page_idx in range(total_pages):
        page_num = page_idx + 1
        page_mu = doc_mu[page_idx]
        page_pk = doc_pk.pages[page_idx]

        # Parse the page content stream ONCE and extract page text
        # ONCE; both are shared by every consumer below instead of
        # each detector re-doing the work (previously 3 parses and
        # 3 text extractions per page). On failure the shared value
        # is None and each consumer falls back to its own
        # extraction, preserving its original error behaviour.
        try:
            page_ops = list(pikepdf.parse_content_stream(page_pk))
        except Exception:
            page_ops = None
        page_text = extract_page_text(page_mu)

        # Build image map from content stream
        placements, label_to_info, xref_to_labels, \
            form_xref_to_labels = \
            build_image_map(page_pk, page_num, page_pad, doc_mu,
                            content_ops=page_ops)

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
        gstate_per_do = get_zorder_and_graphics_state(
            page_pk, content_ops=page_ops)
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
        check_text_overlays(page_pk, page_mu, page_num, findings,
                            text_page=page_text)
        check_content_stream_text_overlay(
            page_pk, page_mu, page_num, findings,
            content_ops=page_ops)
        check_text_over_text(page_mu, page_num, findings,
                             page_pk=page_pk, text_page=page_text)
        # One white box with text painted on it is ONE alteration; the
        # text-over-text detector also fires on that text (the hidden
        # original glyphs are still extractable). Fold those into the
        # white-box finding so counts and risk reflect one edit.
        _merged_list, _n_merged = merge_text_over_white_box(findings)
        if _n_merged:
            findings[:] = _merged_list
            if session:
                session.log(f"  Page {page_num}: {_n_merged} "
                            f"text-over-text detection(s) consolidated "
                            f"into a white-box alteration")
        findings.extend(check_unapplied_redactions(page_pk, page_num))

        # Collect EXIF capture-device info for the document-level
        # mixed-camera check (cheap: reads only Make/Model tags).
        for label in label_to_info:
            cam = extract_camera_info(
                label_to_info[label].get("image_bytes"),
                label_to_info[label].get("ext"))
            if cam:
                doc_cameras[label] = cam
            doc_exif_dates.extend(exif_dates(
                label, label_to_info[label].get("image_bytes"),
                label_to_info[label].get("ext")))

        # Collect font usage for document-level font consistency analysis
        doc_font_spans.extend(collect_page_fonts(
            page_mu, page_num, text_page=page_text))

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

    # Document-level font consistency analysis (ANAL-03), runs after all
    # pages so the dominant body font can be established document-wide.
    font_findings = check_font_anomalies(doc_font_spans)
    if font_findings:
        for ff in font_findings:
            pg = ff["page_num"]
            if pg in page_data:
                page_data[pg]["findings"].append(ff)
                if pg in all_findings:
                    all_findings[pg].append(ff)
                else:
                    all_findings[pg] = [ff]
                page_data[pg]["risk_scores"] = compute_risk_scores(
                    page_data[pg]["findings"],
                    page_data[pg]["label_to_info"])

    # Extract reviewer comments / markup annotations before closing.
    try:
        from pdf_forensics.analysis.comments import extract_comments
        pdf_comments = extract_comments(doc_pk)
    except Exception:
        pdf_comments = []

    # Document-level checks (analysis/doc_checks.py): metadata
    # consistency, signature ByteRange coverage, structural integrity,
    # and cross-image capture-device consistency. Run before the
    # documents close (signature/structural checks need doc_pk).
    doc_findings = []
    doc_findings.extend(check_metadata_consistency(pdf_metadata))
    doc_findings.extend(check_signature_coverage(doc_pk, pdf_path))
    # Metadata changed by later revisions, and ExifTool's update marker:
    # submitted files only (a prior version is a subset of that history).
    if version_number is None:
        doc_findings.extend(check_metadata_history(pdf_path,
                                                   password=password))
    doc_findings.extend(check_structural_integrity(doc_pk))
    doc_findings.extend(check_mixed_cameras(doc_cameras))
    # Revision history is examined on the submitted file only; a prior
    # version analysed in its own right is a subset of that history.
    doc_findings.extend(check_version_anachronism(
        doc_pk, pdf_path, pdf_metadata, password=password,
        history=(version_number is None)))
    # Timeline: every timestamp in every revision, normalised to UTC.
    # Built for submitted files only; a prior version analysed in its own
    # right is already part of its parent's timeline.
    timeline = None
    if version_number is None:
        try:
            timeline = build_timeline(pdf_path, password=password,
                                      exif=doc_exif_dates)
            doc_findings.extend(timeline_findings(timeline))
            if session:
                session.log(
                    f"  Timeline: {len(timeline['occurrences'])} timestamp(s) "
                    f"in {len(timeline['revisions'])} revision(s) "
                    f"({', '.join(timeline['revisions'])}), "
                    f"{len(timeline['issues'])} inconsistency(ies), "
                    f"{timeline['assumed_utc']} with no timezone "
                    f"(assumed UTC)")
        except Exception as e:
            timeline = None
            if session:
                session.log(f"  Timeline analysis failed: {e}", "warning")

    if doc_findings and session:
        for df in doc_findings:
            session.log(f"  Document-level finding: {df['type']}")
            for w in df.get("_all_warnings", []):
                session.log(f"    qpdf: {w}")

    doc_mu.close()
    doc_pk.close()

    # Document-level risk: aggregate page/document-level findings (text
    # overlays, font anomalies, unapplied redactions) and document-wide
    # findings (metadata anomalies, signature coverage, mixed cameras,
    # structural warnings) plus the presence of reviewer comments into a
    # per-page and a document-wide score. Kept separate from the
    # per-image scores so document-level signals draw the examiner's eye
    # in ranked views instead of being detected but invisible.
    page_risk_scores, doc_risk = compute_document_risk(
        all_findings, pdf_comments, doc_findings)
    for pg, pd in page_data.items():
        pd["page_risk"] = page_risk_scores.get(pg, 0)

    # Document-level findings carry no page of their own; they are
    # stored attached to page 1 (their detail text identifies them as
    # document-level) so they appear in the findings reports. They are
    # deliberately merged AFTER risk computation so they never count
    # toward page 1's page-level score.
    if doc_findings:
        first_page = min(page_data.keys(), default=None)
        if first_page is not None:
            for df in doc_findings:
                df.pop("_all_warnings", None)
                df.pop("_temporal", None)
            page_data[first_page]["findings"].extend(doc_findings)
            all_findings.setdefault(first_page, []).extend(doc_findings)
        elif session:
            session.log("  Warning: document-level findings could not "
                        "be stored (document has no pages).")

    if not quiet:
        print_report(all_findings)
        if doc_risk:
            _out(f"  Document risk score: {doc_risk} "
                 f"(highest page: {max(page_risk_scores.values(), default=0)})")

    analysis_id = save_to_db(conn, pdf_path, total_pages, page_data,
                             pdf_metadata=pdf_metadata,
                             pdf_versions=pdf_versions,
                             store_images=store_images,
                             comments=pdf_comments,
                             doc_risk=doc_risk,
                             source_analysis_id=source_analysis_id,
                             version_number=version_number)
    if timeline is not None:
        try:
            save_timeline(conn, analysis_id, timeline_rows(timeline))
        except Exception as e:
            if session:
                session.log(f"  Timeline could not be stored: {e}",
                            "warning")
    record_submission(conn, pdf_path, "analysed", session=session,
                      analysis_id=analysis_id,
                      is_version=version_number is not None)
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
        "analysis_id": analysis_id,
        "version_number": version_number,
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
                 quiet=False, progress_callback=None,
                 password_manager=None):
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

    failed = 0
    not_found = 0
    encrypted_unopened = 0
    for pdf_path in pdf_paths:
        if not os.path.isfile(pdf_path):
            msg = f"Skipping (not found): {pdf_path}"
            if not quiet:
                print(msg)
            if session:
                session.log(msg, "warning")
            record_submission(conn, pdf_path, "not_found", session=session)
            not_found += 1
            continue

        if extract_to_disk:
            base = os.path.splitext(os.path.basename(pdf_path))[0]
            if output_dir:
                pdf_extract_dir = os.path.join(output_dir, base)
            else:
                pdf_extract_dir = base + "_images"
        else:
            pdf_extract_dir = None

        # Encryption: find a password that opens the file (empty first,
        # then known-good, then the supplied list). Always run, so
        # permissions-only files open and genuinely locked files are
        # recorded even when no list was supplied; a locked file no
        # password opens is recorded and skipped, not analysed.
        from pdf_forensics import passwords as _pw
        enc = _pw.resolve_file_password(conn, pdf_path, password_manager,
                                        session=session, quiet=quiet)
        if enc["skip"]:
            encrypted_unopened += 1
            continue
        file_password = enc["password"]
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
                password=file_password,
            )
            if summary:
                if summary.get("skipped"):
                    skipped += 1
                else:
                    summaries.append(summary)
                    if password_manager is not None and summary.get("analysis_id"):
                        try:
                            conn.execute(
                                "UPDATE encryption SET analysis_id=? WHERE "
                                "id=(SELECT MAX(id) FROM encryption WHERE "
                                "pdf_path=?)",
                                (summary["analysis_id"],
                                 os.path.abspath(pdf_path)))
                            conn.commit()
                        except Exception:
                            pass
        except Exception as e:
            if not quiet:
                print(f"Error processing {pdf_path}: {e}")
            if session:
                session.log_pdf_error(pdf_path, e)
            record_submission(conn, pdf_path, "failed", session=session,
                              reason=e)
            failed += 1
        if not quiet:
            print()

    conn.close()

    line = (f"{len(pdf_paths)} submitted: {len(summaries)} analysed, "
            f"{skipped} skipped as identical copies of files already "
            f"analysed, {failed} failed"
            + (f", {encrypted_unopened} encrypted and not opened"
               if encrypted_unopened else "")
            + (f", {not_found} not found" if not_found else ""))
    if not quiet:
        print(f"  {line}")
    if session:
        session.log(f"Run summary: {line}")

    return summaries


def extract_prior_versions(pdf_path, output_dir, session=None,
                           password=None):
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

    output_dir = os.path.normpath(output_dir)
    basename = os.path.splitext(os.path.basename(pdf_path))[0]

    # Only extract %%EOF markers that end a genuine, usable earlier version.
    # A linearized file's first %%EOF (end of the first-page section) and
    # markers whose bytes do not form a usable PDF are recorded and skipped;
    # extracting them produced small non-PDF fragments that were then
    # mis-reported (e.g. as password-protected). password is the parent's,
    # tried first because a genuine earlier version shares its encryption.
    from pdf_forensics.analysis.metadata import classify_prior_versions
    checks = classify_prior_versions(data, password=password)
    usable = {c["version_number"] for c in checks
              if c["status"] in ("valid", "encrypted")}
    for c in checks:
        if c["version_number"] in usable:
            continue
        if session:
            if c["status"] == "linearization":
                session.log(f"  Not a prior version: %%EOF {c['version_number']}"
                            f" at byte {c['eof_offset']:,} in "
                            f"{os.path.basename(pdf_path)} ends the "
                            f"linearization first-page section (the file is "
                            f"linearized for fast web view).")
            else:
                session.log(f"  Not extracted: the {c['size']:,} bytes up to "
                            f"%%EOF {c['version_number']} (byte "
                            f"{c['eof_offset']:,}) of "
                            f"{os.path.basename(pdf_path)} are not a usable "
                            f"PDF: {c['reason']}.")
    versions = [v for v in versions if v[0] in usable] + [versions[-1]]
    if len(versions) <= 1:
        return []

    # Keep the extracted-version paths within Windows' 260-character limit.
    # The document name would otherwise appear twice (the "_versions"
    # folder and each "_versionN.pdf" file) on top of a possibly deep
    # case path, and a path over 260 characters cannot be reopened by the
    # PDF libraries (pikepdf / PyMuPDF), so analysis of the extracted
    # version fails with "No such file or directory" and the folder looks
    # empty. When the full name does not fit, it is shortened and a short
    # hash of the original name is appended so it stays unique and the
    # "_versionN.pdf" suffix (used to identify the version) is preserved.
    max_vnum = max(v for v, _ in versions[:-1])
    suffix_len = len(f"_version{max_vnum}.pdf")           # longest filename tail
    # Budget: output_dir \ {base}_versions \ {base}{suffix}; keep margin.
    fixed = len(os.path.abspath(output_dir)) + 2 + len("_versions") + suffix_len
    allow = 255 - fixed
    safe_base = basename
    if allow < len(basename) * 2:
        per_name = max(8, allow // 2 - 8)                 # room for a hash tag
        tag = "~" + hashlib.md5(basename.encode("utf-8", "replace")
                                ).hexdigest()[:6]
        safe_base = basename[:per_name].rstrip(" .") + tag
        if session:
            session.log(
                f"  Note: shortening extracted-version names for "
                f"{basename!r} to stay within the Windows path limit "
                f"(using {safe_base!r}).")

    version_dir = os.path.join(output_dir, safe_base + "_versions")
    try:
        os.makedirs(version_dir, exist_ok=True)
    except OSError as e:
        if session:
            session.log(f"  Could not create version folder for "
                        f"{basename!r}: {e}", "error")
        return []

    extracted = []
    for version_num, eof_offset in versions[:-1]:
        end_pos = eof_offset + 5  # len(b"%%EOF")
        while end_pos < len(data) and data[end_pos:end_pos+1] in (
                b"\r", b"\n", b" "):
            end_pos += 1

        version_data = data[:end_pos]
        version_filename = f"{safe_base}_version{version_num}.pdf"
        version_path = os.path.join(version_dir, version_filename)

        try:
            with open(version_path, "wb") as f:
                f.write(version_data)
        except OSError as e:
            # Do not queue a path that was not written: that would be
            # recorded as a failed analysis of a non-existent file.
            if session:
                session.log(
                    f"  Could not write version {version_num} of "
                    f"{basename!r}: {e}", "error")
            continue

        extracted.append(version_path)
        if session:
            session.log(
                f"  Extracted version {version_num}: "
                f"{version_filename} ({len(version_data):,} bytes)")

    return extracted
