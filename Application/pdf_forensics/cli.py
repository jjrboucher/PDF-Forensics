"""
Command-line interface for PDF Forensics Suite.

Usage:
  python -m pdf_forensics                         # Launch GUI (default)
  python -m pdf_forensics --version               # Print version
  python -m pdf_forensics analyze file.pdf [...]   # Analyze PDFs
  python -m pdf_forensics graph db.db              # Generate graph
"""

import sys
import os
import sqlite3
from datetime import datetime

from pdf_forensics import __version__, __tool_name__
from pdf_forensics.session import Session


def main_cli():
    """Main CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="pdf_forensics",
        description=f"{__tool_name__} v{__version__}")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    parser.add_argument("--gui", action="store_true",
                        help="Launch GUI mode")
    parser.add_argument("--case", default=None,
                        help="Case number for this session")

    sub = parser.add_subparsers(dest="command")

    # --- analyze subcommand ---
    p_analyze = sub.add_parser("analyze",
                               help="Run PDF forensic analysis")
    p_analyze.add_argument("pdf", nargs="*",
                           help="PDF file(s) to analyze")
    p_analyze.add_argument("-l", "--pdf-list",
                           help="Text file with PDF paths (one per line)")
    p_analyze.add_argument("-d", "--database",
                           default=None,
                           help="SQLite database path")
    p_analyze.add_argument("-e", "--extract-dir", default=None,
                           help="Output directory for extracted images")
    p_analyze.add_argument("-o", "--output-dir", default=None,
                           help="Base output directory for case files")
    p_analyze.add_argument("--no-store-images", action="store_true",
                           help="Do not store image blobs in database")
    p_analyze.add_argument("--force", action="store_true",
                           help="Process PDFs even if already analyzed")
    p_analyze.add_argument("--quiet", "-q", action="store_true",
                           help="Suppress terminal output")

    # --- graph subcommand ---
    p_graph = sub.add_parser("graph",
                             help="Generate relationship graph")
    p_graph.add_argument("database", help="Path to forensics database")
    p_graph.add_argument("-s", "--scope",
                         choices=["all_placements", "cross_page",
                                  "cross_document"],
                         default="cross_document",
                         help="Scope for duplicate detection")
    p_graph.add_argument("-o", "--output", default=None,
                         help="Output HTML file path")
    p_graph.add_argument("--separate-versions", action="store_true",
                         help="Treat each extracted prior version as a "
                              "separate document in cross-document scope "
                              "(default: group a document with its own "
                              "prior versions by lineage, so within-"
                              "version reuse is not counted as "
                              "cross-document)")

    # --- report subcommand ---
    p_report = sub.add_parser("report",
                              help="Generate forensic HTML reports")
    p_report.add_argument("database", help="Path to forensics database")
    p_report.add_argument("-r", "--reports", nargs="*", default=["all"],
                          help="Report IDs to generate (default: all)")
    p_report.add_argument("-o", "--output-dir", default=None,
                          help="Output directory for report files")
    p_report.add_argument("--list", action="store_true",
                          help="List available report IDs and exit")
    p_report.add_argument("--visual", action="store_true",
                          help="Also generate the visual overlay report "
                               "(annotated page images of detected "
                               "text/image overlays)")

    # --- triage subcommand ---
    p_triage = sub.add_parser("triage",
                              help="Quick PDF triage to Excel")
    p_triage.add_argument("pdf", nargs="*",
                          help="PDF file(s) to triage")
    p_triage.add_argument("-l", "--pdf-list",
                          help="Text file with PDF paths")
    p_triage.add_argument("-o", "--output", default=None,
                          help="Output Excel file path")
    p_triage.add_argument("--no-prior-versions", action="store_true",
                          help="Do not include prior-version metadata "
                               "for PDFs with incremental updates "
                               "(by default each prior version's "
                               "metadata is added as its own row)")

    args = parser.parse_args()

    # No command and no --gui → launch GUI
    if not args.command and not args.gui:
        from pdf_forensics.gui.app import launch_app
        launch_app(initial_case=args.case)
        return

    if args.gui:
        from pdf_forensics.gui.app import launch_app
        launch_app(initial_case=args.case)
        return

    # CLI mode: surface the short disclaimer once at the start of the run so
    # headless / automated users see it too (the GUI shows it as a first-run
    # acknowledgment). Printed to stderr so it never pollutes redirected
    # stdout, and suppressed in --quiet mode and for the report listing.
    _quiet = bool(getattr(args, "quiet", False))
    _listing = bool(getattr(args, "list", False))
    if not _quiet and not _listing:
        from pdf_forensics import disclaimers as _disc
        import textwrap as _tw
        sys.stderr.write(
            "\n" + "=" * 70 + "\n")
        sys.stderr.write(
            _tw.fill(_disc.SHORT_DISCLAIMER, width=70) + "\n")
        sys.stderr.write("=" * 70 + "\n\n")

    # CLI mode: set up session
    case = args.case or f"CLI_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    session = Session(case)

    if args.command == "analyze":
        _cli_analyze(args, session, case)
    elif args.command == "graph":
        _cli_graph(args, session)
    elif args.command == "report":
        _cli_report(args, session)
    elif args.command == "triage":
        _cli_triage(args, session, case)

    print()
    print("Processing complete.")


def _cli_analyze(args, session, case):
    """Handle the 'analyze' CLI subcommand."""
    from pdf_forensics.analysis.engine import process_pdfs

    pdfs = list(args.pdf) if args.pdf else []

    # Load from list file
    if args.pdf_list:
        if not os.path.isfile(args.pdf_list):
            print(f"Error: List file not found: {args.pdf_list}")
            sys.exit(1)
        with open(args.pdf_list) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    pdfs.append(line)

    if not pdfs:
        print("Error: No PDF files specified.")
        sys.exit(1)

    # Check for missing files
    valid = [p for p in pdfs if os.path.isfile(p)]
    missing = [p for p in pdfs if not os.path.isfile(p)]
    if missing and not args.quiet:
        print(f"Warning: {len(missing)} file(s) not found:")
        for p in missing[:10]:
            print(f"  {p}")
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more")
    if not valid:
        print("Error: No valid PDF files to process.")
        sys.exit(1)

    # Set up output directory
    output_dir = args.output_dir or os.path.join(os.getcwd(), case)
    session.set_db_dir(output_dir)

    db_path = args.database or session.make_db_path()
    extract_dir = args.extract_dir or session.extracted_images_dir

    if not args.quiet:
        print(f"Case: {case}")
        print(f"Processing {len(valid)} PDF(s)")
        print(f"Database: {db_path}")
        print(f"Output: {output_dir}")

    session.register_output("database", db_path)

    summaries = process_pdfs(
        valid, db_path,
        output_dir=extract_dir,
        store_images=not args.no_store_images,
        extract_to_disk=True,
        session=session,
        quiet=args.quiet,
        force=args.force)

    session.write_summary(
        stats={
            "PDFs processed": len(summaries),
            "PDFs failed": len(valid) - len(summaries),
            "Total images": sum(s["total_extracted"]
                                for s in summaries),
            "Total findings": sum(s["total_findings"]
                                  for s in summaries),
        },
        db_path=db_path)


def _cli_graph(args, session):
    """Handle the 'graph' CLI subcommand."""
    try:
        from pdf_forensics.graph.data import (
            load_data, load_image_bytes, load_findings_for_md5s)
        from pdf_forensics.graph.builder import (
            build_graph, build_image_metadata,
            build_document_metadata, graph_print_summary)
        from pdf_forensics.graph.thumbnails import make_thumbnail_data_uri
        from pdf_forensics.graph.visualization import visualize_graph
        from pdf_forensics.database import validate_database
    except ImportError:
        print("Error: networkx and pyvis required. "
              "Install with: pip install networkx pyvis")
        sys.exit(1)

    # Set db_dir from the database location
    db_dir = os.path.dirname(os.path.abspath(args.database))
    session.set_db_dir(db_dir)

    conn = sqlite3.connect(args.database)
    validate_database(conn)

    group_versions = not args.separate_versions
    rows = load_data(conn, scope=args.scope,
                     group_versions=group_versions)
    if not rows:
        print(f"No data for scope: {args.scope}")
        conn.close()
        return

    md5_set = {row[6] for row in rows}
    image_bytes = load_image_bytes(conn, md5_set)
    findings_by_md5 = load_findings_for_md5s(conn, md5_set)

    thumbnails = {}
    for md5, (blob, ext, w, h) in image_bytes.items():
        thumb = make_thumbnail_data_uri(blob, ext, w, h)
        if thumb:
            thumbnails[md5] = thumb

    G = build_graph(rows, thumbnails)
    image_meta = build_image_metadata(rows, findings_by_md5)
    doc_meta = build_document_metadata(rows)

    scope_label = args.scope.replace("_", "")
    out_path = args.output or session.make_graph_path(scope_label)
    if not out_path:
        out_path = f"graph-{scope_label}.html"

    visualize_graph(
        G, image_meta, thumbnails, args.database,
        doc_meta=doc_meta, output_path=out_path,
        case_number=session.case_number,
        scope=args.scope, group_versions=group_versions)

    session.register_output("graph", out_path)
    graph_print_summary(rows, G, len(thumbnails))
    print(f"\nGraph written to: {out_path}")
    conn.close()

    session.write_summary(db_path=args.database)


def _cli_report(args, session):
    """Handle the 'report' CLI subcommand."""
    from pdf_forensics.reports import generate_reports
    from pdf_forensics.reports.queries import list_reports

    # List mode
    if args.list:
        print("Available reports:")
        for rid, rname, rdesc in list_reports():
            print(f"  {rid:25s} {rname}")
        return

    # Set db_dir from the database location
    db_dir = os.path.dirname(os.path.abspath(args.database))
    session.set_db_dir(db_dir)

    out_dir = args.output_dir or session.reports_dir
    if not out_dir:
        out_dir = os.path.join(db_dir, "reports")

    report_ids = args.reports if args.reports else ["all"]

    print(f"Database: {args.database}")
    print(f"Output:   {out_dir}")
    print(f"Reports:  {', '.join(report_ids)}")
    print()

    results = generate_reports(
        args.database, report_ids, out_dir, session=session)

    for rid, path, rows in results:
        print(f"  {rid}: {rows} rows -> {os.path.basename(path)}")

    print(f"\n{len(results)} report(s) generated.")

    # Visual overlay report (optional)
    if args.visual:
        from pdf_forensics.reports.visual import generate_visual_report
        visual_path = os.path.join(
            out_dir, session.make_filename("visual_overlays", "html"))
        print(f"\nGenerating visual overlay report...")
        n = generate_visual_report(
            args.database, visual_path, session=session)
        if n > 0:
            print(f"  Visual report: {n} finding(s) -> "
                  f"{os.path.basename(visual_path)}")
        else:
            print("  No overlay findings to visualize.")

    session.write_summary(db_path=args.database)


def _cli_triage(args, session, case):
    """Handle the 'triage' CLI subcommand."""
    from pdf_forensics.analysis.triage import run_triage

    pdfs = list(args.pdf) if args.pdf else []

    if args.pdf_list:
        if not os.path.isfile(args.pdf_list):
            print(f"Error: List file not found: {args.pdf_list}")
            sys.exit(1)
        with open(args.pdf_list) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    pdfs.append(line)

    if not pdfs:
        print("Error: No PDF files specified.")
        sys.exit(1)

    valid = [p for p in pdfs if os.path.isfile(p)]
    if not valid:
        print("Error: No valid PDF files found.")
        sys.exit(1)

    output_dir = os.path.join(os.getcwd(), case)
    session.set_db_dir(output_dir)

    xlsx_path = args.output or session.make_filename("triage", "xlsx")
    if not os.path.isabs(xlsx_path):
        xlsx_path = os.path.join(output_dir, xlsx_path)

    print(f"Case: {case}")
    print(f"Triaging {len(valid)} PDF(s)")
    print(f"Output: {xlsx_path}")

    def progress(idx, total, filename):
        print(f"  [{idx}/{total}] {filename}")

    processed, skipped, out = run_triage(
        valid, xlsx_path, session=session,
        progress_callback=progress,
        include_prior_versions=not args.no_prior_versions)

    print(f"\nTriage complete: {processed} processed, "
          f"{skipped} skipped")
    print(f"Output: {out}")
    session.write_summary()
