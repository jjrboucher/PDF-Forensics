"""
Parallel analysis: several submitted files analysed at once, in separate
worker processes, with results written exactly as a sequential run would
write them.

How it works
------------
* The unit of work is a lineage: one submitted file and, if prior
  versions are extracted, its prior versions. A lineage always runs in one
  worker, parent first, so prior versions reuse the parent's pages and
  images (analysis/page_reuse.py) exactly as in a sequential run.
* Workers only compute. They do not open the database or write the session
  or performance logs: log entries and timings are recorded
  (RecordingSession, perf.RecordingPerf) and the analysis results are
  returned as a payload (analyze_pdf(defer=True)).
* The main process commits lineages strictly in submission order: the
  duplicate check, the encryption record, the database writes
  (analysis/commit.commit_analysis), the log entries (replayed with the
  times they were recorded) and the performance-log rows. So analysis ids,
  duplicate decisions and every table come out as in a sequential run.
* Images are written by the worker to a private staging folder and moved
  into the document's image folder when the analysis is committed. If the
  file turns out to be an identical copy of one committed before it (which
  a sequential run would not have analysed), the staged images are deleted
  and nothing is left behind. Version files a sequential run would not
  have extracted (from a submitted file that turns out to be a copy) are
  deleted too; a version file that already existed is never deleted.
* Results are committed with a bounded look-ahead (window), so memory held
  for finished-but-not-yet-committed lineages stays limited.
* A worker that dies (for example a crash inside a PDF library) does not
  stop the run: the lineages it was running are re-run one at a time in a
  separate process; one that fails again is recorded as failed.

Workers = 1 is not handled here: the callers keep their sequential loop,
which is the reference implementation this module is checked against
(tests/test_parallel_equivalence.py).
"""

import os
import sys
import time
import shutil
import hashlib
import itertools

from pdf_forensics import perf as _perf


# ---------------------------------------------------------------------------
# Worker count
# ---------------------------------------------------------------------------

MAX_AUTO_WORKERS = 24
RAM_PER_WORKER_GB = 4      # page-reuse and image caches plus open documents


def physical_cores():
    """Physical processor cores, or None if not known (needs psutil)."""
    try:
        import psutil
        n = psutil.cpu_count(logical=False)
        return n if n and n > 0 else None
    except Exception:
        return None


def default_workers():
    """Workers to use for 'Auto' (build 2026-11-20): one per physical
    processor core, limited by memory (about 4 GB per worker) and to 24.
    Without psutil (cores unknown): one per logical processor less one.

    Many processors run two threads per core; for this work the second
    thread adds little. Measured on a machine with 18 cores and 36 logical
    processors (visual reports): 6, 18 and 24 processes did the work of
    about 6, 13.6 and 13.5 processes running alone, so 24 was no faster
    than 18 and slowed every document more."""
    return _ceiling(os.cpu_count() or 1, _perf._total_ram_gb(),
                    physical_cores())


def _ceiling(cpus, ram, cores=None):
    by_ram = int(ram // RAM_PER_WORKER_GB) if ram else 2
    by_cpu = cores if cores else cpus - 1
    return max(1, min(by_cpu, by_ram, MAX_AUTO_WORKERS))


FREE_GB_PER_WORKER = 2     # free memory Auto wants per extra process now
BUSY_IGNORE_PCT = 10       # background load Auto does not count


def machine_state(sample_seconds=0.5):
    """What Auto looks at: logical CPUs, total and free memory (GB), and
    how busy the processors are now (percent, sampled briefly). Values not
    available are None."""
    st = {"cpus": os.cpu_count() or 1, "ram_gb": _perf._total_ram_gb(),
          "cores": physical_cores(), "free_gb": None, "busy_pct": None}
    try:
        import psutil
        st["free_gb"] = round(psutil.virtual_memory().available
                              / 1073741824, 1)
        st["busy_pct"] = round(psutil.cpu_percent(interval=sample_seconds),
                               0)
    except Exception:
        pass
    return st


def auto_choice(step=None, state=None):
    """Auto, decided at the start of a step (build 2026-11-19b): the
    machine's ceiling (default_workers) lowered when memory is short or
    other programs are keeping the processors busy right now.

    Returns (workers, why) where why = {"state", "ceiling", "by_free",
    "by_idle", "limit"}; limit names what decided the number: "machine"
    (CPUs, installed memory or the cap of 12), "free memory" or
    "busy processors"."""
    st = state or machine_state()
    ceiling = _ceiling(st["cpus"], st.get("ram_gb"), st.get("cores"))
    by_free = by_idle = None
    if st.get("free_gb") is not None:
        by_free = max(1, int(st["free_gb"] // FREE_GB_PER_WORKER))
    if st.get("busy_pct") is not None:
        # the idle share of what Auto counts: cores if known, else
        # logical processors (the ceiling keeps one of those free)
        # Light background load (up to BUSY_IGNORE_PCT, which includes
        # this application's own window) is not counted (build
        # 2026-11-20b: at 3 to 9% busy, Auto had dropped to 17 and 16).
        base = st.get("cores") or st["cpus"]
        busy = max(0.0, st["busy_pct"] - BUSY_IGNORE_PCT)
        idle = base * (1 - busy / 100.0)
        by_idle = max(1, int(round(idle)))
    n = ceiling
    limit = "machine"
    if by_free is not None and by_free < n:
        n, limit = by_free, "free memory"
    if by_idle is not None and by_idle < n:
        n, limit = by_idle, "busy processors"
    return max(1, n), {"state": st, "ceiling": ceiling, "by_free": by_free,
                       "by_idle": by_idle, "limit": limit, "step": step}


def describe_auto(n, why):
    """One line for the logs: no names, only the machine's numbers."""
    st = why["state"]
    bits = ([f"{st['cores']} cores"] if st.get("cores") else []) + [
        f"{st['cpus']} logical CPU(s)"]
    if st.get("ram_gb"):
        bits.append(f"{st['ram_gb']:g} GB memory")
    if st.get("free_gb") is not None:
        bits.append(f"{st['free_gb']:g} GB free")
    if st.get("busy_pct") is not None:
        bits.append(f"processors {st['busy_pct']:.0f}% busy")
    if st.get("free_gb") is None and st.get("busy_pct") is None:
        bits.append("free memory and processor load not checked: psutil "
                    "is not installed")
    reason = {"machine": "the most this machine supports",
              "free memory": "lowered: free memory is short",
              "busy processors": "lowered: other programs are busy"
              }[why["limit"]]
    return (f"Auto: {n} at once ({reason}; {', '.join(bits)})")


def resolve_workers(value):
    """'auto' / None / 0 -> Auto as decided now (auto_choice: the
    machine's ceiling, lowered when free memory is short or the processors
    are busy); otherwise an int >= 1."""
    if value in (None, "", "auto", "Auto", 0, "0"):
        return auto_choice()[0]
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default_workers()


# ---------------------------------------------------------------------------
# Unique names for submitted files that share a name
# ---------------------------------------------------------------------------

def unique_stems(paths):
    """The name each submitted file's image folder and prior-version folder
    is based on, in submission order. Files with the same name (from
    different folders) get _2, _3 ... so their images and prior versions
    are never written into, or overwritten in, the same folder. Compared
    case-insensitively, as Windows does."""
    seen = {}
    taken = set()
    out = []
    for p in paths:
        stem = os.path.splitext(os.path.basename(p))[0]
        key = stem.casefold()
        if key not in taken:
            taken.add(key)
            seen[key] = 1
            out.append(stem)
            continue
        n = seen.get(key, 1)
        while True:
            n += 1
            cand = f"{stem}_{n}"
            if cand.casefold() not in taken:
                break
        seen[key] = n
        taken.add(cand.casefold())
        out.append(cand)
    return out


# ---------------------------------------------------------------------------
# Worker side
# ---------------------------------------------------------------------------

OUTPUT = "__output__"   # record kind: an output registered in a worker


def session_info(session):
    """What a worker's RecordingSession needs to know about the real
    session (plain values, so they can be sent to the worker)."""
    return {k: getattr(session, k, None) for k in
            ("case_number", "timestamp", "db_dir")} if session else {}


class RecordingSession:
    """Stand-in for Session in a worker process. Log entries (time, level,
    message) and registered outputs are recorded for the main process to
    write with Session.replay, in the order they happened. The case number,
    session timestamp and case folder are copies of the real session's.
    Anything else a Session offers is not available in a worker: adding a
    use of it to code that runs in workers must add it here too
    (tests/test_parallel_runner.py checks this)."""

    def __init__(self, info=None):
        info = info or {}
        self.records = []
        self.perf = _perf.RecordingPerf()
        self.case_number = info.get("case_number") or ""
        self.timestamp = info.get("timestamp")
        self.db_dir = info.get("db_dir")

    def __bool__(self):
        return True

    def log(self, msg, level="info"):
        self.records.append((time.time(), level, str(msg)))

    def register_output(self, kind, path):
        self.records.append((time.time(), OUTPUT, (kind, path)))

    def take(self):
        r, self.records = self.records, []
        return r

    # The same wording as Session's helpers (they only call self.log).
    def log_pdf_start(self, pdf_path, pdf_md5, pdf_size):
        from pdf_forensics.session import Session
        Session.log_pdf_start(self, pdf_path, pdf_md5, pdf_size)

    def log_pdf_complete(self, pdf_path, pages, images, findings,
                         high_risk_count=0):
        from pdf_forensics.session import Session
        Session.log_pdf_complete(self, pdf_path, pages, images, findings,
                                 high_risk_count=high_risk_count)

    def log_pdf_error(self, pdf_path, error):
        from pdf_forensics.session import Session
        Session.log_pdf_error(self, pdf_path, error)


_EVENTS = None      # progress queue, set in each worker by _init_worker


WATCHDOG_MINUTES = 30


def _init_worker(events):
    global _EVENTS
    _EVENTS = events


def _emit(*evt):
    if _EVENTS is not None:
        try:
            _EVENTS.put_nowait(evt)
        except Exception:
            pass


def _worker_entry(spec):
    """What a worker process runs: the lineage, returned already pickled
    (one pickling, however large the results). If the results cannot be
    pickled, says so, and the main process analyses that lineage itself,
    so the outcome is the same."""
    import pickle
    res = _run_lineage(spec)
    try:
        return pickle.dumps(res, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        return {"uid": spec["uid"], "unpicklable":
                f"{type(e).__name__}: {str(e)[:200]}"}


def _run_lineage(spec):
    """Worker: analyse one submitted file and, if requested, its prior
    versions, without touching the database. Returns entries in commit
    order (the submitted file, then each version)."""
    fn = spec.get("compute_fn")
    if fn:                                    # tests: a stand-in analysis
        import importlib
        mod, _, name = fn.rpartition(".")
        return getattr(importlib.import_module(mod), name)(spec)

    from pdf_forensics.analysis.engine import (analyze_pdf,
                                               extract_prior_versions)
    from pdf_forensics.pathutil import safe_name
    from pdf_forensics import passwords as _pw

    uid = spec["uid"]
    out_dir = spec.get("out_dir")
    rs = RecordingSession(spec.get("session_info"))
    rp = rs.perf

    def run_one(path, stem, version_number, password):
        rp.begin()
        rs.take()
        key = (uid, version_number or 0)
        stage = (os.path.join(spec["stage_root"],
                              f"{uid}_{version_number or 0}")
                 if out_dir else None)
        final = (os.path.join(out_dir, safe_name(stem, out_dir))
                 if out_dir else None)
        entry = {"path": path, "version_number": version_number,
                 "stage_dir": stage, "extract_dir": final}
        _emit("start", key, os.path.basename(path), version_number,
              os.getpid())
        try:
            summary = analyze_pdf(
                path, spec["db_path"], extract_dir=stage,
                store_images=spec["store_images"], session=rs, quiet=True,
                progress_callback=lambda p, n, _k=key:
                    _emit("page", _k, p, n),
                image_callback=lambda n, _k=key: _emit("images", _k, n),
                skip_duplicates=False, force=True, password=password,
                version_number=version_number, defer=True)
            if summary and summary.get("deferred"):
                entry["status"] = "ok"
                entry["payload"] = summary["deferred"]
            else:
                entry["status"] = "no_result"
        except Exception as e:
            rs.log_pdf_error(path, e)
            entry["status"] = "failed"
            entry["error"] = str(e)
            entry["error_label"] = _perf.error_label(e)
        entry["logs"] = rs.take()
        entry["perf"] = rp.take()
        _emit("finished", key)
        return entry

    parent = run_one(spec["path"], spec["stem"], None, spec.get("password"))
    entries = [parent]
    written = []
    if parent["status"] == "ok" and spec.get("extract_versions"):
        t0 = time.perf_counter()
        os.makedirs(spec["versions_out"], exist_ok=True)
        vpaths = extract_prior_versions(
            spec["path"], spec["versions_out"], session=rs,
            password=spec.get("password"), name=spec["stem"],
            written=written)
        parent["post_logs"] = rs.take()
        parent["perf"]["stages"]["prior_versions_extract"] = (
            parent["perf"]["stages"].get("prior_versions_extract", 0.0)
            + time.perf_counter() - t0)
        parent["versions"] = len(vpaths)
        mgr = spec.get("password_manager")
        import re
        for vpath in vpaths:
            m = re.search(r"_version(\d+)\.pdf$", os.path.basename(vpath))
            vnum = int(m.group(1)) if m else None
            vstem = os.path.splitext(os.path.basename(vpath))[0]
            t1 = time.perf_counter()
            probe = _pw.probe_file_password(vpath, mgr)
            enc_s = time.perf_counter() - t1
            res = probe.get("result")
            if res and not res["opened"]:
                rp.begin()
                entries.append({"path": vpath, "version_number": vnum,
                                "status": "unopened", "probe": probe,
                                "logs": [], "perf": rp.take(),
                                "enc_seconds": enc_s})
                continue
            if res and mgr is not None:
                mgr.record_success(res["password"])
            e = run_one(vpath, vstem, vnum,
                        res["password"] if res else None)
            e["probe"] = probe
            e["enc_seconds"] = enc_s
            entries.append(e)
    return {"uid": uid, "entries": entries, "written": written}


# ---------------------------------------------------------------------------
# Main side
# ---------------------------------------------------------------------------

def _md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _move_staged(stage, final):
    """Move a committed analysis's images into its folder (replacing files
    of the same name, as writing them there directly would)."""
    if final:
        os.makedirs(final, exist_ok=True)
    if not stage or not os.path.isdir(stage):
        return
    for name in sorted(os.listdir(stage)):
        os.replace(os.path.join(stage, name), os.path.join(final, name))
    try:
        os.rmdir(stage)
    except OSError:
        pass


def _discard_staged(stage):
    if stage and os.path.isdir(stage):
        shutil.rmtree(stage, ignore_errors=True)


def _undo_versions(written):
    """Remove version files written for a lineage a sequential run would
    not have extracted. Files that existed before are left alone."""
    dirs = set()
    for path, existed in written:
        dirs.add(os.path.dirname(path))
        if not existed:
            try:
                os.remove(path)
            except OSError:
                pass
    for d in dirs:
        try:
            os.rmdir(d)              # only if now empty
        except OSError:
            pass


class _Task:
    __slots__ = ("idx", "path", "stem", "state", "md5", "probe",
                 "enc_seconds", "future", "result", "uid", "attempts",
                 "pf_no")

    def __init__(self, idx, path, stem):
        self.idx, self.path, self.stem = idx, path, stem
        # new | not_found | dup_known | await | unopened | ready | running |
        # done
        self.state = "new"
        self.md5 = None
        self.probe = None
        self.enc_seconds = 0.0
        self.future = None
        self.result = None
        self.uid = f"{idx:05d}"
        self.attempts = 0
        self.pf_no = None


class ParallelRunner:
    """
    Run an analysis batch across worker processes.

    on_event(evt) receives dicts (called on the runner's thread):
      {"type": "start", "key", "name", "version"}        a worker began a file
      {"type": "progress", "key", "page", "pages"}
      {"type": "images", "key", "images"}
      {"type": "finished", "key"}       a worker finished computing a file;
          its result is written when its turn comes ("result")
      {"type": "result", "key", "name", "version", "outcome", ...}
          outcome: analysed | duplicate | failed | not_found | encrypted
          analysed: images, findings, analysis_id, versions (extracted)
          duplicate: duplicate_of; failed: error
      {"type": "versions", "key", "name", "count"}      prior versions queued
      {"type": "queued", "count"}                        total files known

    Call run(); it returns a stats dict. cancel() stops dispatching new
    lineages (those running finish and are committed).
    """

    def __init__(self, paths, conn, db_path, session=None, workers=None,
                 out_dir=None, store_images=True, skip_duplicates=True,
                 extract_versions=False, versions_out=None,
                 password_manager=None, on_event=None, compute_fn=None,
                 window=None, link_encryption=False, memory_budget=None,
                 order="largest", watchdog_minutes=None):
        self.paths = list(paths)
        self.conn = conn
        self.db_path = db_path
        self.session = session
        self.workers = resolve_workers(workers)
        self.out_dir = out_dir
        self.store_images = store_images
        self.skip_duplicates = skip_duplicates
        self.extract_versions = extract_versions
        self.versions_out = versions_out
        self.mgr = password_manager
        # Where the main loop's time goes (build 2026-11-20), so a run whose
        # workers wait can be explained: the caller's handling of progress
        # messages, writing results, the checks before sending, waiting.
        self._loop = {"events": 0.0, "events_n": 0, "commit": 0.0,
                      "prepare": 0.0, "wait": 0.0, "busy": 0.0,
                      "t": None, "start": None}
        self._user_event = on_event or (lambda evt: None)
        self.on_event = self._timed_event
        self.compute_fn = compute_fn
        # The command line's batch engine links an opened encrypted file's
        # encryption record to its analysis; the GUI's loop does not.
        # Each caller keeps its own behaviour.
        self.link_encryption = link_encryption
        # Lineages sent to workers but not finished: enough to keep every
        # worker busy with at most one waiting (build 2026-11-19).
        self.window = window or (self.workers + 1)
        # Finished results waiting for their turn to be written are kept in
        # memory up to this many bytes, then written to the staging folder.
        if memory_budget is None:
            ram = _perf._total_ram_gb() or 8
            memory_budget = int(min(4.0, ram * 0.15) * 1024 ** 3)
        self.memory_budget = memory_budget
        self.order = order            # "largest" first, or "submission"
        # Watchdog (build 2026-11-23): a file whose worker reports no
        # progress (a page finished, images extracted) for this long is
        # stopped and recorded as failed ("timed out"); 0 turns it off.
        # In a 12,745-file case one document's overlap check ran for over
        # three hours on a single step with no way to stop it but closing
        # the application.
        if watchdog_minutes is None:
            watchdog_minutes = WATCHDOG_MINUTES
        self.watchdog_s = max(0.0, float(watchdog_minutes) * 60.0)
        self._progress = {}    # task idx -> {t, page, pages, pid, name, v}
        self._stop_req = {}    # task idx -> "skip" (examiner's request)
        self._stopped = {}     # task idx -> (error text, error label)
        self._held = 0
        self.pf = _perf.get(session)
        self._cancel = False
        self.stats = {"submitted": len(self.paths), "analysed": 0,
                      "versions": 0, "duplicates": 0, "failed": 0,
                      "not_found": 0, "encrypted": 0, "images": 0,
                      "findings": 0, "encrypted_paths": [],
                      "worker_restarts": 0, "workers": self.workers,
                      "timed_out": 0, "skipped": 0,
                      "peak_held_mb": 0.0, "results_spilled": 0}
        token = f"{os.getpid()}_{int(time.time())}"
        self.stage_root = (os.path.join(out_dir, f".pending_{token}")
                           if out_dir else None)

    # -- helpers -------------------------------------------------------
    def _timed_event(self, evt):
        t0 = time.perf_counter()
        try:
            self._user_event(evt)
        finally:
            self._loop["events"] += time.perf_counter() - t0
            self._loop["events_n"] += 1

    def _busy_tick(self, n_running):
        """Count processes busy over time: n_running since the last tick."""
        now = time.perf_counter()
        lp = self._loop
        if lp["t"] is not None:
            lp["busy"] += (now - lp["t"]) * lp["n"]
        lp["t"] = now
        lp["n"] = min(n_running, self.workers)

    def loop_summary(self):
        """The main loop's time, for the performance log (numbers only)."""
        lp = self._loop
        if lp["start"] is None:
            return None
        total = max(1e-9, time.perf_counter() - lp["start"])
        return (f"parallel analysis main loop: {total:.0f} s in all; checks "
                f"before sending {lp['prepare']:.0f} s, writing results "
                f"{lp['commit']:.0f} s, progress messages "
                f"{lp['events']:.0f} s ({lp['events_n']} messages), waiting "
                f"for workers {lp['wait']:.0f} s; worker processes busy on "
                f"average {lp['busy'] / total:.1f} of {self.workers}")

    def cancel(self):
        self._cancel = True

    def terminate(self):
        """Stop at once (the application is closing): no more commits, and
        the worker processes are ended. Work not yet committed is lost, as
        when closing during a sequential run."""
        self._cancel = True
        self._terminated = True
        pool = getattr(self, "_pool", None)
        procs = getattr(pool, "_processes", None) or {}
        for proc in list(procs.values()):
            try:
                proc.terminate()
            except Exception:
                pass

    def _log(self, msg, level="info"):
        if self.session:
            self.session.log(msg, level)

    def _new_pool(self, n):
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor
        ctx = mp.get_context("spawn")
        if not hasattr(self, "_events"):
            self._mgr_ctx = ctx
            self._events = ctx.Queue()
        return ProcessPoolExecutor(max_workers=n, mp_context=ctx,
                                   initializer=_init_worker,
                                   initargs=(self._events,))

    def _spec(self, t):
        import copy
        return {"uid": t.uid, "path": t.path, "stem": t.stem,
                "db_path": self.db_path, "out_dir": self.out_dir,
                "stage_root": self.stage_root,
                "store_images": self.store_images,
                "extract_versions": self.extract_versions,
                "versions_out": self.versions_out,
                "password": ((t.probe or {}).get("result") or {}).get(
                    "password"),
                "password_manager": copy.deepcopy(self.mgr),
                "compute_fn": self.compute_fn,
                "session_info": session_info(self.session)}

    def _probe(self, t):
        from pdf_forensics import passwords as _pw
        t0 = time.perf_counter()
        t.probe = _pw.probe_file_password(t.path, self.mgr)
        t.enc_seconds += time.perf_counter() - t0
        res = t.probe.get("result")
        return not (res and not res["opened"])

    def _dispatch(self, t):
        t.state = "running"
        t.attempts += 1
        t.future = self._pool.submit(_worker_entry, self._spec(t))

    def _unwrap(self, t, raw):
        """A worker's result: unpickle it, or, if the worker could not
        return it, analyse the lineage in this process instead."""
        import pickle
        if isinstance(raw, (bytes, bytearray)):
            return pickle.loads(raw)
        if isinstance(raw, dict) and raw.get("unpicklable"):
            self._log(f"Results for {os.path.basename(t.path)} could not be "
                      f"passed back from a worker process "
                      f"({raw['unpicklable']}); analysed again in the main "
                      f"process", "warning")
            self.pf.note("lineage re-run in the main process (results not "
                         "transferable)")
            for d in (os.listdir(self.stage_root)
                      if self.stage_root and os.path.isdir(self.stage_root)
                      else []):
                if d.startswith(t.uid + "_"):
                    _discard_staged(os.path.join(self.stage_root, d))
            return _run_lineage(self._spec(t))
        return raw

    def _prepare(self, t, inflight_md5):
        """Main-side checks before a lineage is sent to a worker. Only
        decisions that cannot change by commit time are taken here."""
        from pdf_forensics.database import check_pdf_already_analyzed
        if not os.path.isfile(t.path):
            t.state = "not_found"
            return
        try:
            t.md5 = _md5_of(t.path)
        except OSError:
            t.md5 = None
        if self.skip_duplicates:
            already, _ = check_pdf_already_analyzed(self.conn, t.path)
            if already:                       # the database only grows
                t.state = "dup_known"
                return
            if t.md5 and t.md5 in inflight_md5:
                t.state = "await"             # decided when its turn comes
                return
        if t.md5:
            inflight_md5.add(t.md5)
        if not self._probe(t):
            t.state = "unopened"
            return
        t.state = "ready"

    def _drain_events(self):
        import queue as _q
        n = 0
        while n < 500:
            try:
                evt = self._events.get_nowait()
            except (_q.Empty, OSError, ValueError, EOFError):
                break
            n += 1
            kind = evt[0]
            # Workers name a file by its lineage uid ("00012", version);
            # results use the submission index (12, version). One key for
            # both, so a file's start and result are the same line and it
            # leaves the "running" count when written (build 2026-11-19b;
            # before, the count only grew).
            try:
                evt = (kind, (int(evt[1][0]), evt[1][1])) + tuple(evt[2:])
            except (TypeError, ValueError, IndexError):
                pass
            self._note_progress(evt)
            if kind == "start":
                self.on_event({"type": "start", "key": evt[1],
                               "name": evt[2], "version": evt[3]})
            elif kind == "page":
                self.on_event({"type": "progress", "key": evt[1],
                               "page": evt[2], "pages": evt[3]})
            elif kind == "images":
                self.on_event({"type": "images", "key": evt[1],
                               "images": evt[2]})
            elif kind == "finished":
                self.on_event({"type": "finished", "key": evt[1]})


    # -- watchdog and skipping (build 2026-11-23) ------------------------
    def _note_progress(self, evt):
        try:
            idx = int(evt[1][0])
        except (TypeError, ValueError, IndexError):
            return
        kind = evt[0]
        now = time.monotonic()
        p = self._progress.get(idx)
        if kind == "start":
            self._progress[idx] = {
                "t": now, "page": 0, "pages": None,
                "pid": evt[4] if len(evt) > 4 else None,
                "name": evt[2], "v": evt[3]}
        elif p is not None and kind in ("page", "images"):
            p["t"] = now
            if kind == "page":
                p["page"], p["pages"] = evt[2], evt[3]
        elif p is not None and kind == "finished":
            p["t"] = now

    def running_files(self):
        """[(task idx, file name, seconds since its last progress, page,
        pages)] for files a worker has started: for the GUI's Skip."""
        now = time.monotonic()
        return [(i, p["name"], now - p["t"], p["page"], p["pages"])
                for i, p in self._progress.items()]

    def skip(self, idx):
        """The examiner asks to stop the file at task idx: it is recorded
        as failed ("skipped by the examiner") and the run continues."""
        if idx in self._progress:
            self._stop_req[idx] = "skip"
            return True
        return False

    def _where(self, p):
        if p.get("pages"):
            return f"after page {p['page']} of {p['pages']}"
        return "before its first page was finished"

    def _check_watchdog(self, running):
        """Stop the worker of every running file that has made no progress
        for watchdog_s, or that the examiner asked to skip. Returns True if
        a worker was stopped (the pool then breaks and _recover runs)."""
        now = time.monotonic()
        stopped = False
        for x in running:
            p = self._progress.get(x.idx)
            if p is None or x.idx in self._stopped or p.get("pid") is None:
                continue
            req = self._stop_req.pop(x.idx, None)
            idle = now - p["t"]
            if req is None and not (self.watchdog_s and
                                    idle >= self.watchdog_s):
                continue
            which = (f"prior version {p['v']}" if p.get("v") else "the file")
            if req == "skip":
                msg = (f"Skipped by the examiner during analysis "
                       f"({which}, {self._where(p)})")
                label = "skipped by the examiner"
                self.stats["skipped"] += 1
            else:
                mins = self.watchdog_s / 60.0
                msg = (f"No progress for {mins:g} minutes ({which}, "
                       f"{self._where(p)}); the analysis was stopped")
                label = "timed out"
                self.stats["timed_out"] += 1
            self._stopped[x.idx] = (msg, label)
            self._log(f"{os.path.basename(x.path)}: {msg}", "warning")
            self.pf.note(f"analysis stopped for one file ({label}, "
                         f"{self._where(p)}, {idle:.0f} s without progress)")
            if self._kill(p["pid"]):
                stopped = True
        return stopped

    def _kill(self, pid):
        procs = getattr(self._pool, "_processes", None) or {}
        proc = procs.get(pid)
        try:
            if proc is not None:
                proc.terminate()
                return True
            import psutil
            psutil.Process(pid).terminate()
            return True
        except Exception:
            return False

    # -- committing (main process, submission order) --------------------
    def _result(self, key, path, version, outcome, **kw):
        evt = {"type": "result", "key": key, "name": os.path.basename(path),
               "path": path, "version": version, "outcome": outcome}
        evt.update(kw)
        self.on_event(evt)

    def _commit_duplicate(self, key, path, version, is_version, kind, of):
        """Duplicate check at commit time: the database now holds exactly
        what a sequential run would hold at this point."""
        from pdf_forensics.database import (check_pdf_already_analyzed,
                                            record_submission)
        if not self.skip_duplicates:
            return False
        already, dup = check_pdf_already_analyzed(self.conn, path)
        if not already:
            return False
        basename = os.path.basename(path)
        record_submission(self.conn, path, "duplicate", session=self.session,
                          analysis_id=dup.get("id"),
                          duplicate_of=dup.get("pdf_filename"),
                          is_version=is_version)
        self._log(f"Skipped: {basename} is byte-identical to "
                  f"{dup['pdf_filename']} (already analysed "
                  f"{dup['analyzed_at']}); not re-analysed")
        self.pf.file_begin(kind, of=of)
        if dup.get("pdf_md5"):
            self.pf.set("md5", dup["pdf_md5"])
        self.pf.file_end("skipped (identical copy)")
        self.stats["duplicates"] += 1
        self._result(key, path, version, "duplicate",
                     duplicate_of=dup["pdf_filename"])
        return True

    def _commit_password(self, key, path, version, probe, is_version, kind,
                         of, enc_seconds):
        from pdf_forensics import passwords as _pw
        enc = _pw.record_file_password(self.conn, path, probe or {},
                                       session=self.session, quiet=True,
                                       is_version=is_version)
        if enc["skip"]:
            self.pf.file_begin(kind, of=of)
            self.pf.file_end("encrypted, not opened")
            self.stats["encrypted"] += 1
            self.stats["encrypted_paths"].append(path)
            self._result(key, path, version, "encrypted",
                         scheme=enc.get("scheme"))
        return enc

    def _commit_entry(self, t, e, kind, of, parent_aid):
        """Commit one analysed entry; returns its analysis summary or
        None."""
        from pdf_forensics.analysis.commit import commit_analysis
        from pdf_forensics.database import record_submission
        is_version = e["version_number"] is not None
        key = (t.idx, e["version_number"] or 0)
        path = e["path"]
        no = self.pf.file_resume(e.get("perf"), kind=kind, of=of)
        if e.get("enc_seconds"):
            self.pf.stage_add("encryption", e["enc_seconds"])
        if self.session and e.get("logs"):
            self.session.replay(e["logs"])
        self.pf.lap_reset()
        status = "ok"
        summary = None
        try:
            if e["status"] == "ok":
                _move_staged(e.get("stage_dir"), e.get("extract_dir"))
                payload = e["payload"]
                payload["extract_dir"] = e.get("extract_dir")
                if is_version:
                    payload["source_analysis_id"] = parent_aid
                summary = commit_analysis(self.conn, payload,
                                          session=self.session, quiet=True)
                if (self.link_encryption and summary
                        and summary.get("analysis_id")):
                    try:
                        self.conn.execute(
                            "UPDATE encryption SET analysis_id=? WHERE "
                            "id=(SELECT MAX(id) FROM encryption WHERE "
                            "pdf_path=?)",
                            (summary["analysis_id"], os.path.abspath(path)))
                        self.conn.commit()
                    except Exception:
                        pass
            elif e["status"] == "no_result":
                _discard_staged(e.get("stage_dir"))
                status = "failed (no result)"
                record_submission(self.conn, path, "failed",
                                  session=self.session,
                                  reason="analysis returned no result",
                                  is_version=is_version)
            else:
                # Images written before the error are kept, as in a
                # sequential run.
                _move_staged(e.get("stage_dir"), e.get("extract_dir"))
                status = f"failed ({e.get('error_label') or 'error'})"
                record_submission(self.conn, path, "failed",
                                  session=self.session,
                                  reason=e.get("error"),
                                  is_version=is_version)
        except Exception as exc:
            summary = None
            status = f"failed ({_perf.error_label(exc)})"
            if self.session:
                self.session.log_pdf_error(path, exc)
            record_submission(self.conn, path, "failed", session=self.session,
                              reason=exc, is_version=is_version)
            e = dict(e, error=str(exc))
        if summary:
            self.stats["analysed"] += 1
            if is_version:
                self.stats["versions"] += 1
            self.stats["images"] += summary["total_extracted"]
            self.stats["findings"] += summary["total_findings"]
            if self.session and e.get("post_logs"):
                self.session.replay(e["post_logs"])
            self._result(key, path, e["version_number"], "analysed",
                         images=summary["total_extracted"],
                         findings=summary["total_findings"],
                         analysis_id=summary.get("analysis_id"),
                         versions=e.get("versions", 0))
        else:
            self.stats["failed"] += 1
            self._result(key, path, e["version_number"], "failed",
                         error=e.get("error") or "no result")
        self.pf.file_end(status)
        return summary, no

    def _commit(self, t):
        from pdf_forensics.database import record_submission
        key = (t.idx, 0)
        if t.state == "not_found":
            record_submission(self.conn, t.path, "not_found",
                              session=self.session)
            self._log(f"Not found: {t.path}", "warning")
            self.stats["failed"] += 1
            self.stats["not_found"] += 1
            self._result(key, t.path, None, "not_found")
            return
        if self._commit_duplicate(key, t.path, None, False, "submitted",
                                  None):
            if t.result:
                for e in t.result["entries"]:
                    _discard_staged(e.get("stage_dir"))
                _undo_versions(t.result.get("written", []))
            return
        if t.state == "unopened":
            self._commit_password(key, t.path, None, t.probe, False,
                                  "submitted", None, t.enc_seconds)
            return
        enc = self._commit_password(key, t.path, None, t.probe, False,
                                    "submitted", None, t.enc_seconds)
        if enc["skip"]:                 # cannot happen for a dispatched task
            return
        entries = t.result["entries"]
        parent = dict(entries[0])
        parent["enc_seconds"] = t.enc_seconds
        summary, parent_no = self._commit_entry(t, parent, "submitted",
                                                None, None)
        if not summary:
            return
        nv = parent.get("versions", 0)
        if nv:
            self.on_event({"type": "versions", "key": key,
                           "name": os.path.basename(t.path), "count": nv})
            self.on_event({"type": "queued", "count": nv})
        parent_aid = summary.get("analysis_id")
        for e in entries[1:]:
            vkey = (t.idx, e["version_number"] or 0)
            kind = f"version {e['version_number']}"
            if not os.path.isfile(e["path"]):
                record_submission(self.conn, e["path"], "not_found",
                                  session=self.session, is_version=True)
                self._log(f"Not found: {e['path']}", "warning")
                self.stats["failed"] += 1
                self.stats["not_found"] += 1
                self._result(vkey, e["path"], e["version_number"],
                             "not_found")
                continue
            if self._commit_duplicate(vkey, e["path"], e["version_number"],
                                      True, kind, parent_no):
                _discard_staged(e.get("stage_dir"))
                continue
            enc = self._commit_password(vkey, e["path"], e["version_number"],
                                        e.get("probe"), True, kind,
                                        parent_no, e.get("enc_seconds", 0))
            if enc["skip"] or e["status"] == "unopened":
                continue
            self._commit_entry(t, e, kind, parent_no, parent_aid)

    # -- the loop ------------------------------------------------------
    def _size(self, t):
        try:
            return os.path.getsize(t.path)
        except OSError:
            return 0

    def _hold(self, t, raw):
        """Keep a finished lineage's result (as the worker sent it: pickled
        bytes) until its turn to be written: in memory within the budget,
        otherwise in a file in the staging folder."""
        if isinstance(raw, (bytes, bytearray)):
            n = len(raw)
            if self._held + n > self.memory_budget and self.stage_root:
                path = os.path.join(self.stage_root, f"result_{t.uid}.pkl")
                with open(path, "wb") as fh:
                    fh.write(raw)
                t.result = ("file", path, n)
                self.stats["results_spilled"] += 1
            else:
                t.result = ("mem", raw, n)
                self._held += n
                self.stats["peak_held_mb"] = max(
                    self.stats["peak_held_mb"], self._held / 1048576.0)
        else:
            t.result = ("obj", raw, 0)
        t.state = "done"

    def _take(self, t):
        """The held result of a lineage, ready to be written."""
        kind, val, n = t.result
        t.result = None
        if kind == "mem":
            self._held -= n
            raw = val
        elif kind == "file":
            with open(val, "rb") as fh:
                raw = fh.read()
            try:
                os.remove(val)
            except OSError:
                pass
        else:
            raw = val
        return self._unwrap(t, raw)

    def _collect(self, running):
        """Hold the results of lineages that have finished, in any order.
        Returns False if the worker pool broke."""
        from concurrent.futures.process import BrokenProcessPool
        for x in list(running):
            if not x.future.done():
                continue
            try:
                raw = x.future.result()
            except BrokenProcessPool:
                return False
            except Exception as exc:               # worker-side bug
                raw = {"uid": x.uid, "written": [], "entries": [
                    {"path": x.path, "version_number": None,
                     "status": "failed", "error": str(exc),
                     "error_label": _perf.error_label(exc),
                     "logs": [], "perf": None}]}
            self._hold(x, raw)
            self._progress.pop(x.idx, None)
            running.remove(x)
        return True

    # -- the loop ------------------------------------------------------
    def run(self):
        """
        1. Main-process checks for every file, in submission order (exists,
           MD5, already in the database or an identical copy of an earlier
           file, password).
        2. Lineages are sent to workers largest file first (build
           2026-11-19), so the longest ones do not start last; at most
           `window` are sent but unfinished.
        3. Results are written strictly in submission order. A lineage whose
           turn has come but which has not been sent yet is sent at once.
           Finished results wait as pickled bytes, in memory within
           memory_budget, otherwise in the staging folder.
        """
        from concurrent.futures import wait, FIRST_COMPLETED

        stems = unique_stems(self.paths)
        tasks = [_Task(i, p, s) for i, (p, s) in
                 enumerate(zip(self.paths, stems))]
        self._log(f"Parallel analysis: {self.workers} worker process(es); "
                  f"results are written in submission order")
        if self.stage_root:
            os.makedirs(self.stage_root, exist_ok=True)
        self._pool = self._new_pool(self.workers)
        inflight_md5 = set()
        self._loop["start"] = time.perf_counter()
        _tp = time.perf_counter()
        for t in tasks:
            if self._cancel:
                break
            self._prepare(t, inflight_md5)
        self._loop["prepare"] += time.perf_counter() - _tp
        queue = [t for t in tasks if t.state == "ready"]
        if self.order == "largest":
            queue.sort(key=lambda t: (-self._size(t), t.idx))
        running = []
        cptr = 0         # next task to write
        try:
            while cptr < len(tasks):
                if getattr(self, "_terminated", False):
                    break
                self._busy_tick(len(running))
                # 1. keep the workers busy
                while (not self._cancel and queue
                       and len(running) < self.window):
                    x = queue.pop(0)
                    self._dispatch(x)
                    running.append(x)
                self._drain_events()
                self._check_watchdog(running)
                if not self._collect(running):
                    if getattr(self, "_terminated", False):
                        break
                    again = self._recover(running)
                    running = []
                    for x in reversed(again):
                        queue.insert(0, x)
                    continue

                t = tasks[cptr]
                # 2. a task waiting on an identical earlier file: decide now
                if t.state == "await":
                    from pdf_forensics.database import \
                        check_pdf_already_analyzed
                    already, _ = check_pdf_already_analyzed(self.conn,
                                                            t.path)
                    if already:
                        t.state = "dup_known"
                    elif self._probe(t):
                        t.state = "ready"
                        queue.insert(0, t)
                    else:
                        t.state = "unopened"
                if t.state == "ready":          # its turn: send it now
                    if self._cancel:
                        break
                    if t in queue:
                        queue.remove(t)
                    self._dispatch(t)
                    running.append(t)
                    continue
                if t.state == "new":            # cancelled before checks
                    break
                # 3. write the next task once it has finished
                if t.state == "running":
                    _tw = time.perf_counter()
                    wait([x.future for x in running], timeout=0.2,
                         return_when=FIRST_COMPLETED)
                    self._loop["wait"] += time.perf_counter() - _tw
                    continue
                _tc = time.perf_counter()
                _ev = self._loop["events"]
                if t.state == "done":
                    t.result = self._take(t)
                self._commit(t)
                # writing time, without the progress messages it sends
                self._loop["commit"] += ((time.perf_counter() - _tc)
                                         - (self._loop["events"] - _ev))
                t.result = None                  # release memory
                cptr += 1
                self._drain_events()
        finally:
            self._drain_events()
            done_wait = not getattr(self, "_terminated", False)
            try:
                self._pool.shutdown(wait=done_wait, cancel_futures=True)
            except TypeError:                    # Python < 3.9
                self._pool.shutdown(wait=done_wait)
            if self.stage_root:
                shutil.rmtree(self.stage_root, ignore_errors=True)
        self.stats["cancelled"] = cptr < len(tasks)
        self._busy_tick(0)
        summary = self.loop_summary()
        if summary:
            self.pf.note(summary)
        self.pf.note(f"parallel analysis: largest files first="
                     f"{self.order == 'largest'}, window={self.window}, "
                     f"results held in memory peak "
                     f"{self.stats['peak_held_mb']:.0f} MB, written to disk "
                     f"{self.stats['results_spilled']}")
        return self.stats

    def _recover(self, running):
        """A worker process died. Every lineage that was running is re-run
        alone (one process each), so the one that kills its worker cannot
        take others with it; if it fails alone, it is recorded as failed.

        When the watchdog or the examiner stopped a worker (build
        2026-11-23), the file to blame is known: it is recorded as failed
        with the reason, and the other files that were running are sent
        again as usual. Returns the tasks to send again."""
        from concurrent.futures.process import BrokenProcessPool
        if any(x.idx in self._stopped for x in running):
            return self._recover_stopped(running)
        self.stats["worker_restarts"] += 1
        self._log("A worker process stopped unexpectedly; the files it was "
                  "analysing are re-run one at a time", "warning")
        self.pf.note("worker process stopped unexpectedly; lineages re-run "
                     "in isolation")
        try:
            self._pool.shutdown(wait=False)
        except Exception:
            pass
        for x in list(running):
            if x.future.done():
                try:
                    self._hold(x, x.future.result())
                    continue
                except BrokenProcessPool:
                    pass
                except Exception:
                    pass
            if self.stage_root and os.path.isdir(self.stage_root):
                for d in os.listdir(self.stage_root):
                    if d.startswith(x.uid + "_"):
                        _discard_staged(os.path.join(self.stage_root, d))
            solo = self._new_pool(1)
            try:
                self._hold(x, solo.submit(_worker_entry,
                                          self._spec(x)).result())
            except Exception as exc:
                self._log(f"Analysis process failed for "
                          f"{os.path.basename(x.path)} on its own as well "
                          f"({type(exc).__name__}); recorded as failed",
                          "error")
                self._hold(x, {"uid": x.uid, "written": [], "entries": [
                    {"path": x.path, "version_number": None,
                     "status": "failed",
                     "error": "analysis process terminated unexpectedly",
                     "error_label": "worker process terminated",
                     "logs": [], "perf": None}]})
            finally:
                solo.shutdown(wait=True)
        self._pool = self._new_pool(self.workers)
        return []

    def _recover_stopped(self, running):
        from concurrent.futures.process import BrokenProcessPool
        try:
            self._pool.shutdown(wait=False)
        except Exception:
            pass
        again = []
        for x in list(running):
            self._progress.pop(x.idx, None)
            if x.idx in self._stopped:
                msg, label = self._stopped[x.idx]
                self._discard_stage_of(x)
                self._hold(x, {"uid": x.uid, "written": [], "entries": [
                    {"path": x.path, "version_number": None,
                     "status": "failed", "error": msg,
                     "error_label": label, "logs": [], "perf": None}]})
                continue
            if x.future is not None and x.future.done():
                try:
                    self._hold(x, x.future.result())
                    continue
                except BrokenProcessPool:
                    pass
                except Exception:
                    pass
            self._discard_stage_of(x)
            x.state = "ready"
            x.future = None
            again.append(x)
        self._pool = self._new_pool(self.workers)
        return again

    def _discard_stage_of(self, x):
        if self.stage_root and os.path.isdir(self.stage_root):
            for d in os.listdir(self.stage_root):
                if d.startswith(x.uid + "_"):
                    _discard_staged(os.path.join(self.stage_root, d))
