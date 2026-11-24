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

from pdf_forensics import __version__, __tool_name__, BUILD_DATE
from pdf_forensics.session import Session


def main_cli():
    """Main CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="pdf_forensics",
        description=f"{__tool_name__} v{__version__} (build {BUILD_DATE})")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__} (build {BUILD_DATE})")
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
    p_analyze.add_argument("-p", "--password-list", default=None,
                           help="Text file of candidate passwords to open "
                                "encrypted PDFs (one per line, tried in order; "
                                "the empty password and passwords already found "
                                "this run are tried first).")
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
    p_analyze.add_argument("--watchdog-minutes", type=float, default=None,
                           help="With more than one worker: stop a file "
                                "that makes no progress for this many "
                                "minutes and record it as failed (timed "
                                "out). Default 30; 0 turns it off.")
    p_analyze.add_argument("-w", "--workers", default="auto",
                           help="PDFs analysed at the same time, each in its "
                                "own process: 'auto' (default: from the "
                                "processor cores and memory) or a number. 1 "
                                "analyses one file at a time. Results are "
                                "written in the order given either way.")
    p_analyze.add_argument("--prior-versions", action="store_true",
                           help="Also extract and analyse the prior versions "
                                "of PDFs with incremental updates (as the "
                                "GUI's 'Extract and process prior PDF "
                                "versions' option)")

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
    p_report.add_argument("-w", "--workers", default="auto",
                          help="Visual overlay reports made at the same "
                               "time, each in its own process: 'auto' "
                               "(default) or a number; 1 makes one at a "
                               "time. The reports are the same either way.")

    # --- triage subcommand ---
    p_triage = sub.add_parser("triage",
                              help="Quick PDF triage to Excel")
    p_triage.add_argument("pdf", nargs="*",
                          help="PDF file(s) to triage")
    p_triage.add_argument("-l", "--pdf-list",
                          help="Text file with PDF paths")
    p_triage.add_argument("-p", "--password-list", default=None,
                           help="Text file of candidate passwords to open "
                                "encrypted PDFs (one per line, tried in order; "
                                "the empty password and passwords already found "
                                "this run are tried first).")
    p_triage.add_argument("-o", "--output", default=None,
                          help="Output Excel file path")
    p_triage.add_argument("-w", "--workers", default="auto",
                          help="PDFs triaged at the same time, each in its "
                               "own process: 'auto' (default) or a number; "
                               "1 for one at a time. Rows are written in the "
                               "order given either way. With a password "
                               "list, always one at a time.")
    p_triage.add_argument("--no-prior-versions", action="store_true",
                          help="Do not include prior-version metadata "
                               "for PDFs with incremental updates "
                               "(by default each prior version's "
                               "metadata is added as its own row)")

    args = parser.parse_args()

    # Paths are normalised where they enter (native separators, absolute;
    # see pathutil). Wildcard patterns keep their * and ?.
    from pdf_forensics.pathutil import norm_path
    for name in ("pdf_list", "password_list", "database", "extract_dir",
                 "output_dir", "output"):
        if getattr(args, name, None):
            setattr(args, name, norm_path(getattr(args, name)))
    if getattr(args, "pdf", None):
        args.pdf = [norm_path(p) for p in args.pdf]

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


def _expand_pdf_args(items, session=None):
    """Expand wildcard patterns (* and ?) in PDF arguments.

    macOS and Linux shells expand `*.pdf` before the program sees it, but
    Windows (cmd and PowerShell) passes the pattern through unchanged, so it
    was reported as "not found". Patterns are therefore expanded here, the
    same way on every platform.

    - An argument naming an existing file is used as is, even if its name
      contains wildcard characters.
    - Square brackets are matched literally first, so exhibit prefixes such
      as "[010] *.pdf" work; only if that finds nothing are they given their
      glob meaning (a character class).
    - A pattern that matches nothing is passed through unchanged and is
      reported as not found, as before.
    - Matches are sorted, and a file already listed is not added twice.
    """
    import glob as _glob
    out, seen = [], set()

    def _key(p):
        return os.path.normcase(os.path.abspath(p))

    for item in items:
        if os.path.exists(item) or not any(c in item for c in "*?["):
            out.append(item)
            seen.add(_key(item))
            continue
        literal = item.replace("[", "[[]")
        matches = _glob.glob(literal)
        if not matches and "[" in item:
            matches = _glob.glob(item)
        matches = sorted(m for m in matches if os.path.isfile(m))
        if not matches:
            out.append(item)
            continue
        added = 0
        for m in matches:
            k = _key(m)
            if k not in seen:
                seen.add(k)
                out.append(m)
                added += 1
        msg = f"Pattern {item}: {len(matches)} file(s) matched, {added} added"
        print(msg)
        if session:
            session.log(msg)
    return out


def _build_password_manager(list_path, session=None, quiet=False):
    """Build a PasswordManager from a password-list file, or None when no
    list was given (the engine still tries the empty password and records
    locked files as 'no list supplied')."""
    if not list_path:
        return None
    from pdf_forensics import passwords as _pw
    if not os.path.isfile(list_path):
        print(f"Error: password list not found: {list_path}")
        return None
    passwords, info = _pw.read_password_list(list_path)
    if len(passwords) > _pw.SOFT_LIMIT and not quiet:
        print(f"Warning: {len(passwords)} passwords supplied "
              f"(> {_pw.SOFT_LIMIT}); this may be slow for AES-256 files.")
    if session:
        session.log(f"Password list loaded: {info['path']} (MD5 {info['md5']}, "
                    f"{info['encoding']}): {info['count']} password(s)")
    if not quiet:
        print(f"Password list: {info['count']} password(s) from "
              f"{os.path.basename(list_path)}")
    return _pw.PasswordManager(passwords, info)


def _cli_analyze(args, session, case):
    """Handle the 'analyze' CLI subcommand."""
    from pdf_forensics.analysis.engine import process_pdfs

    pdfs = _expand_pdf_args(list(args.pdf), session) if args.pdf else []

    # Load from list file
    if args.pdf_list:
        if not os.path.isfile(args.pdf_list):
            print(f"Error: List file not found: {args.pdf_list}")
            sys.exit(1)
        from pdf_forensics.pathlist import read_path_list, log_list
        res = read_path_list(args.pdf_list)
        pdfs.extend(res["paths"])
        log_list(session, res)
        print(f"List {os.path.basename(args.pdf_list)} ({res['encoding']}): "
              f"{len(res['paths'])} found, {res['duplicates']} duplicate(s) "
              f"ignored, {len(res['missing'])} not found")
        for m_ in res["missing"]:
            print(f"  Not found: {m_}")

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

    pw_manager = _build_password_manager(getattr(args, "password_list", None),
                                         session, quiet=args.quiet)
    from pdf_forensics.analysis.parallel import (resolve_workers,
                                                 auto_choice, describe_auto)
    _wv = getattr(args, "workers", "auto")
    if _wv in (None, "", "auto", "Auto", 0, "0"):
        workers, _why = auto_choice("analysis")
        if not args.quiet:
            print(describe_auto(workers, _why))
    else:
        workers = resolve_workers(_wv)
    if workers > 1 or getattr(args, "prior_versions", False):
        st = _cli_analyze_parallel(valid, db_path, extract_dir, session,
                                   args, workers, pw_manager)
        from pdf_forensics.reports.case_index import refresh_case_index
        _idx = refresh_case_index(session, log=print)
        if _idx:
            print(f"Case index updated: {_idx}")
        session.write_summary(
            stats={
                "PDFs processed": st["analysed"] - st["versions"],
                "Prior versions analysed": st["versions"],
                "PDFs failed": st["failed"],
                "Identical copies skipped": st["duplicates"],
                "Encrypted, not opened": st["encrypted"],
                "Total images": st["images"],
                "Total findings": st["findings"],
            },
            db_path=db_path)
        return

    summaries = process_pdfs(
        valid, db_path,
        output_dir=extract_dir,
        store_images=not args.no_store_images,
        extract_to_disk=True,
        session=session,
        quiet=args.quiet,
        force=args.force,
        password_manager=pw_manager)

    from pdf_forensics.reports.case_index import refresh_case_index
    _idx = refresh_case_index(session, log=print)
    if _idx:
        print(f"Case index updated: {_idx}")

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


def _cli_analyze_parallel(paths, db_path, extract_dir, session, args,
                          workers, pw_manager):
    """analyze with several worker processes and/or prior versions
    (analysis/parallel.py). Same results as one file at a time."""
    import time as _time
    from pdf_forensics import perf as _perf
    from pdf_forensics.database import init_db, refresh_statistics
    from pdf_forensics.analysis.parallel import ParallelRunner

    quiet = args.quiet
    conn = init_db(db_path, session=session)
    pf = _perf.get(session)
    pf.run_begin("analysis", len(paths), interface="command line",
                 workers=workers, store_images=not args.no_store_images,
                 extract_to_disk=True, skip_duplicates=not args.force,
                 password_list=pw_manager is not None,
                 prior_versions=bool(getattr(args, "prior_versions", False)))
    versions_out = None
    if getattr(args, "prior_versions", False):
        versions_out = session.pdf_versions_dir or os.path.join(
            os.path.dirname(db_path), "pdf_versions")
        os.makedirs(versions_out, exist_ok=True)

    def on_event(evt):
        if quiet or evt["type"] not in ("result", "versions"):
            return
        if evt["type"] == "versions":
            print(f"    -> {evt['count']} prior version(s) of {evt['name']} "
                  f"analysed")
            return
        oc, name = evt["outcome"], evt["name"]
        if oc == "analysed":
            print(f"  OK  {name}: {evt.get('images', 0)} image(s), "
                  f"{evt.get('findings', 0)} finding(s)")
        elif oc == "duplicate":
            print(f"  --  {name}: identical copy of {evt.get('duplicate_of')}"
                  f" (not re-analysed)")
        elif oc == "encrypted":
            print(f"  --  {name}: encrypted, not opened")
        elif oc == "not_found":
            print(f"  !!  {name}: not found")
        else:
            print(f"  !!  {name}: failed ({evt.get('error')})")

    if not quiet:
        print(f"Analysing {workers} file(s) at a time; results are written "
              f"in the order given.")
    runner = ParallelRunner(
        paths, conn, db_path, session=session, workers=workers,
        out_dir=extract_dir, store_images=not args.no_store_images,
        skip_duplicates=not args.force,
        extract_versions=bool(getattr(args, "prior_versions", False)),
        versions_out=versions_out, password_manager=pw_manager,
        link_encryption=pw_manager is not None, on_event=on_event,
        watchdog_minutes=getattr(args, "watchdog_minutes", None))
    try:
        st = runner.run()
    except KeyboardInterrupt:
        runner.terminate()
        raise
    t0 = _time.perf_counter()
    refresh_statistics(conn)
    pf.event("database", "statistics", _time.perf_counter() - t0)
    conn.close()
    pf.run_end()
    line = (f"{len(paths)} submitted: {st['analysed'] - st['versions']} "
            f"analysed, {st['duplicates']} skipped as identical copies of "
            f"files already analysed, {st['failed']} failed"
            + (f", {st['encrypted']} encrypted and not opened"
               if st["encrypted"] else "")
            + (f", {st['not_found']} not found" if st["not_found"] else "")
            + (f"; plus {st['versions']} prior version(s) extracted and "
               f"analysed" if st["versions"] else ""))
    if not quiet:
        print(f"  {line}")
    session.log(f"Run summary: {line}")
    return st


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

    import time as _time
    from pdf_forensics import perf as _perf
    _gpf = _perf.get(session)
    _gpf.load_begin()
    _tg0 = _time.perf_counter()
    md5_set = {row[6] for row in rows}
    image_bytes = load_image_bytes(conn, md5_set)
    findings_by_md5 = load_findings_for_md5s(conn, md5_set)

    _tt0 = _time.perf_counter()
    thumbnails = {}
    for md5, (blob, ext, w, h) in image_bytes.items():
        thumb = make_thumbnail_data_uri(blob, ext, w, h)
        if thumb:
            thumbnails[md5] = thumb
    _gpf.event("graph_thumbnails", args.scope, _time.perf_counter() - _tt0,
               images=len(image_bytes))

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
    _gpf.event("graph", args.scope, _time.perf_counter() - _tg0,
               placements=len(rows), unique_images=len(md5_set))
    _gpf.load_end("graphs")
    graph_print_summary(rows, G, len(thumbnails))
    print(f"\nGraph written to: {out_path}")
    from pdf_forensics.reports.case_index import refresh_case_index
    _idx = refresh_case_index(session, log=print)
    if _idx:
        print(f"Case index updated: {_idx}")
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
        from pdf_forensics.reports.visual import generate_visual_reports
        visual_path = os.path.join(
            out_dir, session.make_filename("visual-overlays", "html"))
        print(f"\nGenerating visual overlay reports...")
        ndocs, n = generate_visual_reports(
            args.database, visual_path, session=session,
            progress=lambda i, t: print(f"  document {i} of {t}", end="\r"),
            workers=getattr(args, "workers", "auto"))
        if n > 0:
            print(f"  Visual reports: {ndocs} document(s), {n} finding(s); "
                  f"index -> {os.path.basename(visual_path)}")
        else:
            print("  No overlay findings to visualize.")

    # Document Risk Overview (Excel) + report index page.
    ov_path = None
    try:
        from pdf_forensics.reports.risk_overview import (
            generate_risk_overview_xlsx)
        ov_path = os.path.join(
            out_dir, session.make_filename("risk-overview", "xlsx"))
        nov = generate_risk_overview_xlsx(
            args.database, ov_path, session=session,
            case_number=session.case_number)
        print(f"  Document Risk Overview: {nov} document(s) -> "
              f"{os.path.basename(ov_path)}")
    except Exception as e:
        ov_path = None
        print(f"  Document Risk Overview skipped: {e}")
    try:
        from pdf_forensics.reports.timeline_xlsx import generate_timeline_xlsx
        tl_path = os.path.join(
            out_dir, session.make_filename("timeline-analysis", "xlsx"))
        ntl = generate_timeline_xlsx(
            args.database, tl_path, session=session,
            case_number=session.case_number)
        session.register_output("timeline_xlsx", tl_path)
        print(f"  Timeline Analysis spreadsheet: {ntl} document(s) -> "
              f"{os.path.basename(tl_path)}")
    except Exception as e:
        print(f"  Timeline Analysis spreadsheet skipped: {e}")
    from pdf_forensics.reports.case_index import refresh_case_index
    _idx = refresh_case_index(session, log=print)
    if _idx:
        print(f"Case index updated: {_idx}")

    session.write_summary(db_path=args.database)


def _cli_triage(args, session, case):
    """Handle the 'triage' CLI subcommand."""
    from pdf_forensics.analysis.triage import run_triage

    pdfs = _expand_pdf_args(list(args.pdf), session) if args.pdf else []

    if args.pdf_list:
        if not os.path.isfile(args.pdf_list):
            print(f"Error: List file not found: {args.pdf_list}")
            sys.exit(1)
        from pdf_forensics.pathlist import read_path_list, log_list
        res = read_path_list(args.pdf_list)
        pdfs.extend(res["paths"])
        log_list(session, res)
        print(f"List {os.path.basename(args.pdf_list)} ({res['encoding']}): "
              f"{len(res['paths'])} found, {res['duplicates']} duplicate(s) "
              f"ignored, {len(res['missing'])} not found")
        for m_ in res["missing"]:
            print(f"  Not found: {m_}")

    if not pdfs:
        print("Error: No PDF files specified.")
        sys.exit(1)

    valid = [p for p in pdfs if os.path.isfile(p)]
    if not valid:
        print("Error: No valid PDF files found.")
        sys.exit(1)

    output_dir = os.path.join(os.getcwd(), case)
    session.set_db_dir(output_dir)

    if args.output:
        xlsx_path = args.output
        if not os.path.isabs(xlsx_path):
            xlsx_path = os.path.join(output_dir, xlsx_path)
    else:
        # Timed per run, so an earlier triage spreadsheet is never replaced.
        xlsx_path = session.make_run_path(output_dir, "triage", "xlsx")

    print(f"Case: {case}")
    print(f"Triaging {len(valid)} PDF(s)")
    print(f"Output: {xlsx_path}")

    def progress(idx, total, filename):
        print(f"  [{idx}/{total}] {filename}")

    pw_manager = _build_password_manager(getattr(args, "password_list", None),
                                         session, quiet=False)
    processed, skipped, out, locked = run_triage(
        valid, xlsx_path, session=session,
        progress_callback=progress,
        include_prior_versions=not args.no_prior_versions,
        password_manager=pw_manager,
        workers=getattr(args, "workers", "auto"))

    print(f"\nTriage complete: {processed} processed, "
          f"{skipped} skipped")
    if locked:
        print(f"{len(locked)} encrypted PDF(s) could not be opened"
              + ("" if pw_manager else "; re-run with --password-list to "
                 "try candidate passwords") + ".")
    print(f"Output: {out}")
    from pdf_forensics.reports.case_index import refresh_case_index
    _idx = refresh_case_index(session, log=print)
    if _idx:
        print(f"Case index updated: {_idx}")

    session.write_summary()
