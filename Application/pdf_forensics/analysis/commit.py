"""
Writing one analysis to the database (split from analysis/engine.py).

analyze_pdf builds a payload and, normally, calls commit_analysis at
once. Parallel analysis (analysis/parallel.py) builds payloads in worker
processes and calls commit_analysis in the main process, in submission
order, so the database is written exactly as a sequential run writes it.
This module does not import PyMuPDF, so the main process can commit
without it.
"""

import os

from pdf_forensics.database import (save_to_db, save_timeline,
                                    record_submission)


def commit_analysis(conn, payload, session=None, quiet=False):
    """
    Write one analysis (the payload built by analyze_pdf) to the database
    and finish its log entries. analyze_pdf calls this directly; parallel
    analysis calls it in the main process, in submission order, so the
    database is written exactly as a sequential run would write it.

    The performance-log record of the file must be open (file_begin or
    file_resume); this credits the db_save and finish stages.

    Returns the analysis summary dict.
    """
    def _out(*args, **kwargs):
        if not quiet:
            print(*args, **kwargs)

    from pdf_forensics import perf as _perf
    pf = _perf.get(session)
    lap = pf.lap
    pdf_path = payload["pdf_path"]
    db_path = payload["db_path"]
    page_data = payload["page_data"]
    pdf_metadata = payload["pdf_metadata"]
    pdf_versions = payload["pdf_versions"]
    extract_dir = payload["extract_dir"]
    version_number = payload["version_number"]
    total_pages = payload["total_pages"]
    total_extracted = payload["total_extracted"]
    total_findings = payload["total_findings"]

    _escaped0 = getattr(conn, "escaped", [0])[0]
    analysis_id = save_to_db(conn, pdf_path, total_pages, page_data,
                             pdf_metadata=pdf_metadata,
                             pdf_versions=pdf_versions,
                             store_images=payload["store_images"],
                             comments=payload["comments"],
                             doc_risk=payload["doc_risk"],
                             source_analysis_id=payload["source_analysis_id"],
                             version_number=version_number)
    if payload.get("timeline_error") and session:
        session.log(f"  Timeline could not be stored: "
                    f"{payload['timeline_error']}", "warning")
    elif payload["timeline_rows"] is not None:
        try:
            save_timeline(conn, analysis_id, payload["timeline_rows"])
        except Exception as e:
            if session:
                session.log(f"  Timeline could not be stored: {e}",
                            "warning")
    record_submission(conn, pdf_path, "analysed", session=session,
                      analysis_id=analysis_id,
                      is_version=version_number is not None)
    pf.set("findings", total_findings)
    _escaped = getattr(conn, "escaped", [0])[0] - _escaped0
    if _escaped and session:
        session.log(f"  {_escaped} text value(s) contained invalid UTF-16 "
                    f"(unpaired surrogates) and were stored with \\uXXXX "
                    f"escapes, e.g. \\udc8f, so the analysis could be saved",
                    "warning")
    lap("db_save")

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
    lap("finish")

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
