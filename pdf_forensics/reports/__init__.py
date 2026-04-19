"""
Forensic HTML reports from pre-built database queries.

Usage:
    from pdf_forensics.reports import generate_reports
    generate_reports(db_path, report_ids, output_dir, session)
"""

import os
from pdf_forensics.reports.queries import REPORTS, get_report_by_id, list_reports
from pdf_forensics.reports.renderer import generate_report


def generate_reports(db_path, report_ids, output_dir, session=None,
                     filename_prefix=None):
    """
    Generate one or more HTML reports.

    Parameters:
      db_path         : path to the forensics database
      report_ids      : list of report id strings (or "all")
      output_dir      : directory to write HTML files into
      session         : optional Session for logging and naming
      filename_prefix : optional prefix for filenames; if None
                        and session is provided, uses session naming

    Returns a list of (report_id, output_path, row_count) tuples.
    """
    if report_ids == "all" or report_ids == ["all"]:
        report_ids = [r["id"] for r in REPORTS]

    os.makedirs(output_dir, exist_ok=True)
    results = []

    for rid in report_ids:
        report_def = get_report_by_id(rid)
        if not report_def:
            if session:
                session.log(f"Unknown report id: {rid}", "warning")
            continue

        # Build filename
        if session:
            fname = session.make_filename(
                f"report-{rid}", "html")
        elif filename_prefix:
            fname = f"{filename_prefix}_report-{rid}.html"
        else:
            fname = f"report-{rid}.html"

        out_path = os.path.join(output_dir, fname)

        try:
            row_count = generate_report(
                db_path, report_def, out_path, session=session)
            results.append((rid, out_path, row_count))
        except Exception as e:
            if session:
                session.log(
                    f"Error generating {rid}: {e}", "error")
            else:
                print(f"Error generating {rid}: {e}")

    return results
