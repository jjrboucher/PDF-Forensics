"""
One image-relationship graph, from the database to its HTML file.

Used by the GUI and the command line, in the main process or, when several
graphs are made at once (1.3.0, build 2026-11-19), in a worker process each.
It reads the database and writes only its own output file; the caller logs,
registers the output and records the timings, in the order the graphs were
asked for, from the dict this returns.

Progress (build 2026-11-19b): generate_scope reports each stage through
progress(stage, info); generate_scopes passes these to the caller's
on_progress(scope, stage, info) on the caller's thread, from worker
processes too, and reports "finished" for a graph as soon as it ends (its
result is still handed back in the order listed). Every stage is timed
(t_load, t_thumbnails, t_build, t_network, t_write_html, t_custom_ui).
"""

import hashlib
import sqlite3
import time

THUMB_REPORT_EVERY = 250        # thumbnails between progress reports


def generate_scope(spec, progress=None):
    """
    spec: {"db": database path, "scope": scope name,
           "group_versions": bool, "out_path": output file,
           "case_number": str or None}
    progress: optional callable(stage, info)

    Returns {"scope", "rows", "unique_images", "digest" (identifies the
    dataset, so two scopes that select the same data can be reported),
    "thumb_images", "t_thumb", "elapsed", "out_path", "thumbnails"
    (count), "timings" (seconds per stage), "nodes", "edges"};
    rows == 0 means no data (nothing written).
    """
    from pdf_forensics.graph.data import (load_data, load_image_bytes,
                                          load_findings_for_md5s)
    from pdf_forensics.graph.builder import (build_graph,
                                             build_image_metadata,
                                             build_document_metadata)
    from pdf_forensics.graph.thumbnails import make_thumbnail_data_uri

    def report(stage, **info):
        if progress:
            try:
                progress(stage, info)
            except Exception:
                pass

    t0 = time.perf_counter()
    timings = {}
    scope = spec["scope"]
    out = {"scope": scope, "rows": 0, "out_path": spec["out_path"],
           "timings": timings}
    report("loading")
    conn = sqlite3.connect(spec["db"])
    try:
        rows = load_data(conn, scope=scope,
                         group_versions=spec["group_versions"])
        if not rows:
            timings["t_load"] = time.perf_counter() - t0
            out["elapsed"] = time.perf_counter() - t0
            return out
        md5_set = {row[6] for row in rows}
        out["rows"] = len(rows)
        out["unique_images"] = len(md5_set)
        # rows are tuples of plain values: equal datasets, equal digests
        out["digest"] = hashlib.sha256(repr(rows).encode(
            "utf-8", "surrogatepass")).hexdigest()
        image_bytes = load_image_bytes(conn, md5_set)
        findings_by_md5 = load_findings_for_md5s(conn, md5_set)
        timings["t_load"] = time.perf_counter() - t0
        report("loaded", placements=len(rows), unique_images=len(md5_set))

        tt0 = time.perf_counter()
        thumbnails = {}
        total = len(image_bytes)
        report("thumbnails", done=0, total=total)
        for k, (md5, (blob, ext, w, h)) in enumerate(image_bytes.items(), 1):
            thumb = make_thumbnail_data_uri(blob, ext, w, h)
            if thumb:
                thumbnails[md5] = thumb
            if k % THUMB_REPORT_EVERY == 0:
                report("thumbnails", done=k, total=total)
        out["t_thumb"] = timings["t_thumbnails"] = time.perf_counter() - tt0
        out["thumb_images"] = total
        out["thumbnails"] = len(thumbnails)

        tb0 = time.perf_counter()
        report("building")
        from pdf_forensics.graph.visualization import visualize_graph
        G = build_graph(rows, thumbnails)
        image_meta = build_image_metadata(rows, findings_by_md5)
        doc_meta = build_document_metadata(rows)
        out["nodes"] = G.number_of_nodes()
        out["edges"] = G.number_of_edges()
        timings["t_build"] = time.perf_counter() - tb0
        visualize_graph(G, image_meta, thumbnails, spec["db"],
                        doc_meta=doc_meta, output_path=spec["out_path"],
                        case_number=spec.get("case_number"), scope=scope,
                        group_versions=spec["group_versions"],
                        progress=lambda st, info: report(st, **info),
                        timings=timings)
        out["elapsed"] = time.perf_counter() - t0
        return out
    finally:
        conn.close()


# -- worker side ----------------------------------------------------------

_EVENTS = None


def _init_worker(events):
    global _EVENTS
    _EVENTS = events


def _worker(spec):
    scope = spec["scope"]

    def progress(stage, info):
        if _EVENTS is not None:
            try:
                _EVENTS.put_nowait((scope, stage, info))
            except Exception:
                pass
    return generate_scope(spec, progress=progress)


# -- main side --------------------------------------------------------------

def generate_scopes(specs, workers=1, on_progress=None):
    """Generate several graphs, one process each when workers > 1.
    Yields (spec, result_or_exception) in the order of specs.
    on_progress(scope, stage, info), if given, is called on this thread for
    every stage of every graph, and with stage "finished" ({"elapsed"}) or
    "failed" as soon as a graph ends."""
    def notify(scope, stage, info):
        if on_progress:
            try:
                on_progress(scope, stage, info)
            except Exception:
                pass

    workers = max(1, min(int(workers or 1), len(specs)))
    if workers <= 1:
        for spec in specs:
            scope = spec["scope"]
            try:
                res = generate_scope(
                    spec, progress=lambda st, info, _s=scope:
                    notify(_s, st, info))
                notify(scope, "finished", {"elapsed": res.get("elapsed", 0),
                                           "rows": res["rows"]})
                yield spec, res
            except Exception as e:
                notify(scope, "failed", {"error": str(e)})
                yield spec, e
        return

    import multiprocessing as mp
    import queue as _queue
    from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
    ctx = mp.get_context("spawn")
    events = ctx.Queue()

    def drain():
        while True:
            try:
                scope, stage, info = events.get_nowait()
            except (_queue.Empty, OSError, ValueError, EOFError):
                return
            notify(scope, stage, info)

    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx,
                             initializer=_init_worker,
                             initargs=(events,)) as pool:
        futs = [pool.submit(_worker, s) for s in specs]
        announced = set()
        nxt = 0
        while nxt < len(futs):
            wait([f for f in futs[nxt:] if not f.done()] or futs[nxt:nxt + 1],
                 timeout=0.25, return_when=FIRST_COMPLETED)
            drain()
            for k, f in enumerate(futs):          # finished, any order
                if k in announced or not f.done():
                    continue
                announced.add(k)
                exc = f.exception()
                if exc is None:
                    r = f.result()
                    notify(specs[k]["scope"], "finished",
                           {"elapsed": r.get("elapsed", 0),
                            "rows": r["rows"]})
                else:
                    notify(specs[k]["scope"], "failed", {"error": str(exc)})
            while nxt < len(futs) and futs[nxt].done():   # in order
                f = futs[nxt]
                exc = f.exception()
                yield specs[nxt], (f.result() if exc is None else exc)
                nxt += 1
        drain()
