"""Build 2026-11-19b: live log lines, the adaptive Auto, the analysis
"finished" event, the visual reports' status callback and the case index's
threaded hashing. All synthetic; no Tk needed (a stand-in Text widget)."""
import hashlib
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def _live():
    """gui/live.py on its own (the gui package imports tkinter)."""
    import importlib.util
    path = os.path.join(os.path.dirname(HERE), "pdf_forensics", "gui",
                        "live.py")
    spec = importlib.util.spec_from_file_location("_live_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -- a stand-in for tk.Text: indices are character offsets ---------------
class FakeText:
    def __init__(self):
        self.chars = []                     # [(char, frozenset(tags))]

    def config(self, **kw):
        pass

    def _idx(self, where):
        return len(self.chars) if where == "end" else int(where)

    def insert(self, where, text, tags=()):
        if isinstance(tags, str):
            tags = (tags,)
        i = self._idx(where)
        self.chars[i:i] = [(c, frozenset(tags)) for c in text]

    def delete(self, a, b):
        del self.chars[self._idx(a):self._idx(b)]

    def tag_ranges(self, tag):
        pos = [i for i, (_, t) in enumerate(self.chars) if tag in t]
        return (pos[0], pos[-1] + 1) if pos else ()

    def tag_delete(self, tag):
        self.chars = [(c, t - {tag}) for c, t in self.chars]

    def tags(self):
        return {x for _, t in self.chars for x in t}

    def compare(self, a, op, b):
        return {">": a > b, "<": a < b, "==": a == b}[op]

    def see(self, where):
        pass

    def value(self):
        return "".join(c for c, _ in self.chars)


class FakeRoot:
    def __init__(self):
        self.calls = []

    def after(self, ms, fn):
        self.calls.append(fn)
        return len(self.calls)

    def after_cancel(self, ident):
        pass


class LiveLinesTest(unittest.TestCase):
    def test_lines_children_done_remove(self):
        LiveLines = _live().LiveLines
        t, r = FakeText(), FakeRoot()
        live = LiveLines(r, t)
        t.insert("end", "header\n")
        live.set("a", "A running")
        live.set("b", "B running", clock=False)
        live.start()
        lines = t.value().splitlines()
        self.assertEqual(lines[0], "header")
        self.assertTrue(lines[1].startswith("A running · "))
        self.assertEqual(lines[2], "B running")
        live.set(("c", 1), "  child 1", parent="a")
        live.set(("c", 2), "  child 2", parent="a")
        live._redraw()
        lines = t.value().splitlines()
        self.assertTrue(lines[2].startswith("  child 1"))
        self.assertTrue(lines[3].startswith("  child 2"))
        self.assertEqual(lines[4], "B running")
        live.done("a", "A done")
        live.remove("b")
        live._redraw()
        lines = t.value().splitlines()
        self.assertEqual(lines[1], "A done")
        self.assertNotIn("B running", lines)
        # lines written after keep their place below the live lines
        t.insert("end", "after\n")
        live.done(("c", 1), "  child 1 done")
        live._redraw()
        self.assertEqual(t.value().splitlines()[-1], "after")
        self.assertIn("  child 1 done", t.value().splitlines())

    def test_finished_lines_are_retired(self):
        """Build 2026-11-20b: a line done() is drawn, then its tag and its
        entry are dropped, so finished lines cost nothing later; a
        child added in the same pass still goes under its parent."""
        LiveLines = _live().LiveLines
        t, r = FakeText(), FakeRoot()
        live = LiveLines(r, t)
        live.start()
        for k in range(300):
            live.set(k, f"file {k}")
        live._redraw()
        for k in range(300):
            live.done(k, f"done {k}")
        live.set(("v", 5), "  versions of 5", clock=False, parent=5)
        live.done(("v", 5), "  versions of 5")
        live._redraw()
        self.assertEqual(len(live.items), 0)
        self.assertFalse({x for x in t.tags() if x.startswith("live")})
        lines = t.value().splitlines()
        self.assertEqual(len(lines), 301)
        self.assertEqual(lines[5], "done 5")
        self.assertEqual(lines[6], "  versions of 5")
        self.assertEqual(lines[-1], "done 299")
        # a line still being changed is not retired
        live.set("x", "running")
        live._redraw()
        live.set("x", "still running")
        live._redraw()
        self.assertIn("x", live.items)

    def test_started_and_fmt(self):
        import time
        _m = _live()
        LiveLines, fmt_elapsed = _m.LiveLines, _m.fmt_elapsed
        self.assertEqual(fmt_elapsed(5), "5 s")
        self.assertEqual(fmt_elapsed(125), "2 min 05 s")
        self.assertEqual(fmt_elapsed(3725), "1 h 02 min")
        t, r = FakeText(), FakeRoot()
        live = LiveLines(r, t)
        live.set("x", "doc", started=time.monotonic() - 90)
        live._redraw()
        self.assertIn("1 min 30 s", t.value())


class AutoTest(unittest.TestCase):
    def test_auto_lowers_for_memory_and_busy_cpus(self):
        from pdf_forensics.analysis.parallel import auto_choice, describe_auto
        # cores not known: logical processors less one (build 2026-11-20:
        # at most 24, was 12)
        big = {"cpus": 16, "ram_gb": 64, "free_gb": 40, "busy_pct": 5}
        n, why = auto_choice(state=big)
        self.assertEqual((n, why["limit"]), (15, "machine"))
        n, why = auto_choice(state=dict(big, free_gb=5))
        self.assertEqual((n, why["limit"]), (2, "free memory"))
        n, why = auto_choice(state=dict(big, busy_pct=75))
        self.assertEqual((n, why["limit"]), (6, "busy processors"))
        n, why = auto_choice(state=dict(big, free_gb=None, busy_pct=None))
        self.assertEqual(n, 15)
        # cores known (build 2026-11-20): one per physical core
        ws = {"cpus": 36, "cores": 18, "ram_gb": 127.7, "free_gb": 110,
              "busy_pct": 2}
        self.assertEqual(auto_choice(state=ws)[0], 18)
        # light background load is not counted (build 2026-11-20b)
        for pct in (3, 9, 10):
            self.assertEqual(auto_choice(state=dict(ws, busy_pct=pct))[0],
                             18)
        self.assertEqual(auto_choice(state=dict(ws, busy_pct=60))[0], 9)
        self.assertEqual(auto_choice(state=dict(ws, ram_gb=32))[0], 8)
        self.assertEqual(auto_choice(state={"cpus": 128, "cores": 64,
                                            "ram_gb": 512, "free_gb": 400,
                                            "busy_pct": 0})[0], 24)
        self.assertIn("18 cores", describe_auto(*auto_choice(state=ws)))
        n, _ = auto_choice(state={"cpus": 1, "ram_gb": 2, "free_gb": 0.5,
                                  "busy_pct": 100})
        self.assertEqual(n, 1)
        line = describe_auto(*auto_choice(state=big))
        self.assertIn("16 logical CPU(s)", line)
        self.assertNotIn(os.sep, line)

    def test_machine_state(self):
        from pdf_forensics.analysis.parallel import machine_state
        st = machine_state(sample_seconds=0.05)
        self.assertGreaterEqual(st["cpus"], 1)


class FinishedEventTest(unittest.TestCase):
    def test_finished_reported_for_analysed_files(self):
        from pdf_forensics.analysis.parallel import ParallelRunner
        from pdf_forensics.database import init_db
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for k in range(4):
                p = os.path.join(tmp, f"doc{k}.pdf")
                with open(p, "w") as f:
                    f.write(f"file {k}\n" + ("SLEEP 0.3\n" if k == 0 else ""))
                paths.append(p)
            db = os.path.join(tmp, "case.db")
            conn = init_db(db)
            events = []
            ParallelRunner(paths, conn, db, workers=2,
                           compute_fn="tests.stub_compute.compute",
                           on_event=events.append).run()
            conn.close()
        results = {e["key"] for e in events if e["type"] == "result"
                   and e["outcome"] == "analysed"}
        finished = {e["key"] for e in events if e["type"] == "finished"}
        started = {e["key"] for e in events if e["type"] == "start"}
        self.assertEqual(len(results), 4)
        self.assertTrue(finished)
        # one key per file for its start, finish and result (before build
        # 2026-11-19b a worker's start used another key, so the GUI's
        # "running" count never went down)
        self.assertTrue(finished <= results)
        self.assertEqual(started, results)


class VisualStatusTest(unittest.TestCase):
    def test_status_callback(self):
        from pdf_forensics import session as _session
        from pdf_forensics.session import Session
        from pdf_forensics.reports.visual import generate_visual_reports
        from tests.test_visual_parallel import _make_db
        with tempfile.TemporaryDirectory() as tmp:
            _session.CONFIG_FILE = os.path.join(tmp, "config.json")
            db = os.path.join(tmp, "case.db")
            _make_db(db)
            for workers in (1, 3):
                seen = []
                s = Session("T-3")
                s.set_db_dir(os.path.join(tmp, f"w{workers}"))
                generate_visual_reports(
                    db, os.path.join(tmp, f"w{workers}", "v.html"),
                    session=s, workers=workers, status=seen.append)
                s.perf.close()
                for h in list(s.logger.handlers):
                    h.close()
                self.assertTrue(seen, workers)
                self.assertEqual(seen[-1]["done"], seen[-1]["total"])
                self.assertEqual(seen[-1]["running"], {})
                self.assertEqual(seen[-1]["total"], 5)
                with open(s.perf.path, encoding="utf-8") as fh:
                    ev = [l for l in fh if l.startswith(
                        "EVENT\tvisual_overlay_document")]
                self.assertEqual(len(ev), 5)
                self.assertTrue(all("start=" in l and "end=" in l
                                    for l in ev))


class CaseIndexHashTest(unittest.TestCase):
    def test_threaded_hashes_match(self):
        from pdf_forensics.reports import case_index as ci
        from pdf_forensics.database import init_db
        with tempfile.TemporaryDirectory() as root:
            init_db(os.path.join(root, "case_20260101_000000.db")).close()
            os.makedirs(os.path.join(root, "logs"))
            os.makedirs(os.path.join(root, "reports"))
            vdir = os.path.join(root, "pdf_versions", "sample_versions")
            os.makedirs(vdir)
            files = []
            for k in range(12):
                p = os.path.join(vdir, f"sample_version{k + 1}.pdf")
                with open(p, "wb") as f:
                    f.write(os.urandom(50000 + k))
                files.append(p)
            with open(os.path.join(root, "logs", "a.log"), "w") as f:
                f.write("log\n")

            def md5s(data):
                out = {}
                for key, val in data.items():
                    recs = (val.values() if isinstance(val, dict) else val)
                    for rec in recs:
                        for r in rec.get("files", [rec]):
                            out[r["rel"]] = r["md5"]
                return out

            first = md5s(ci._scan_case(root))
            for p in files:
                rel = os.path.relpath(p, root).replace(os.sep, "/")
                with open(p, "rb") as f:
                    self.assertEqual(first[rel],
                                     hashlib.md5(f.read()).hexdigest())
            self.assertEqual(md5s(ci._scan_case(root)), first)   # cached
            os.remove(os.path.join(root, ci.CACHE_NAME))
            old = ci.HASH_THREADS
            ci.HASH_THREADS = 1
            try:
                self.assertEqual(md5s(ci._scan_case(root)), first)
            finally:
                ci.HASH_THREADS = old


if __name__ == "__main__":
    unittest.main()
