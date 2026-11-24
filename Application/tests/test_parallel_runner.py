"""Tests for analysis/parallel.py with a stand-in analysis (no PyMuPDF
needed). Run: python -m pytest tests  (or python tests/test_parallel_runner.py)"""
import os
import sys
import sqlite3
import time
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pdf_forensics.database import init_db                     # noqa: E402
from pdf_forensics.analysis.parallel import (ParallelRunner,   # noqa: E402
                                             unique_stems)

STUB = "tests.stub_compute.compute"


def _write(folder, name, text):
    os.makedirs(folder, exist_ok=True)
    p = os.path.join(folder, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


class RunnerTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.src = os.path.join(self.root, "src")
        self.out = os.path.join(self.root, "case", "extracted_images")
        self.vout = os.path.join(self.root, "case", "pdf_versions")
        self.db = os.path.join(self.root, "case", "case.db")
        os.makedirs(self.out)
        os.makedirs(self.vout)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, paths, workers=3, window=None, **kw):
        conn = init_db(self.db)
        events = []
        r = ParallelRunner(paths, conn, self.db, workers=workers,
                           out_dir=self.out, extract_versions=True,
                           versions_out=self.vout, compute_fn=STUB,
                           on_event=events.append, window=window, **kw)
        stats = r.run()
        conn.close()
        return stats, events

    def _rows(self, sql):
        c = sqlite3.connect(self.db)
        try:
            return c.execute(sql).fetchall()
        finally:
            c.close()

    def test_order_duplicates_versions(self):
        a = _write(self.src, "alpha.pdf", "A\nVERSIONS 2\nIMAGES 2\n")
        b = _write(self.src, "bravo.pdf", "A\nVERSIONS 2\nIMAGES 2\n")  # = a
        c = _write(self.src, "charlie.pdf", "C\nIMAGES 1\n")
        miss = os.path.join(self.src, "missing.pdf")
        d = _write(self.src, "delta.pdf", "A-v1\n")       # = alpha's version 1
        f = _write(self.src, "fail.pdf", "FAIL\n")
        e = _write(os.path.join(self.src, "sub"), "alpha.pdf",
                   "E\nVERSIONS 1\nIMAGES 1\n")           # same name as a
        stats, events = self._run([a, b, c, miss, d, f, e], window=8)

        # analyses in submission order, versions straight after parents
        names = [r[0] for r in self._rows(
            "SELECT pdf_filename FROM analyses ORDER BY id")]
        self.assertEqual(names, ["alpha.pdf", "alpha_version1.pdf",
                                 "alpha_version2.pdf", "charlie.pdf",
                                 "alpha.pdf", "alpha_2_version1.pdf"])
        # lineage recorded against the right parent
        rows = self._rows("SELECT id, source_analysis_id, version_number "
                          "FROM analyses ORDER BY id")
        self.assertEqual(rows[1][1], rows[0][0])
        self.assertEqual(rows[5][1], rows[4][0])
        # submissions, in order, with outcomes
        subs = [(r[0], r[1]) for r in self._rows(
            "SELECT pdf_filename, outcome FROM submissions ORDER BY id")]
        self.assertEqual(subs, [
            ("alpha.pdf", "analysed"), ("alpha_version1.pdf", "analysed"),
            ("alpha_version2.pdf", "analysed"), ("bravo.pdf", "duplicate"),
            ("charlie.pdf", "analysed"), ("missing.pdf", "not_found"),
            ("delta.pdf", "duplicate"), ("fail.pdf", "failed"),
            ("alpha.pdf", "analysed"), ("alpha_2_version1.pdf", "analysed")])
        # images moved into per-document folders; same-name files separated
        self.assertEqual(sorted(os.listdir(os.path.join(self.out, "alpha"))),
                         ["img0.png", "img1.png"])
        self.assertTrue(os.path.isdir(os.path.join(self.out, "alpha_2")))
        # nothing left of the duplicate's work, nor the staging folder
        self.assertFalse(os.path.exists(os.path.join(self.out, "bravo")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "delta")))
        self.assertFalse(os.path.exists(os.path.join(self.vout,
                                                     "bravo_versions")))
        self.assertEqual([d for d in os.listdir(self.out)
                          if d.startswith(".pending")], [])
        self.assertEqual(stats["analysed"], 6)
        self.assertEqual(stats["versions"], 3)
        self.assertEqual(stats["duplicates"], 2)
        self.assertEqual(stats["failed"], 2)
        self.assertEqual(stats["not_found"], 1)
        results = [ev for ev in events if ev["type"] == "result"]
        self.assertEqual(len(results), 10)

    def test_same_result_any_worker_count_and_window(self):
        paths = [_write(self.src, f"f{i:02d}.pdf",
                        f"F{i % 4}\nVERSIONS {i % 3}\n") for i in range(12)]
        seen = []
        for workers, window in ((1, 1), (4, 2), (6, 12)):
            if os.path.exists(self.db):
                os.remove(self.db)
            for p in ("-wal", "-shm"):
                if os.path.exists(self.db + p):
                    os.remove(self.db + p)
            self._run(paths, workers=workers, window=window)
            seen.append(self._rows(
                "SELECT pdf_filename, outcome, is_version, analysis_id "
                "FROM submissions ORDER BY id"))
        self.assertEqual(seen[0], seen[1])
        self.assertEqual(seen[0], seen[2])

    def test_worker_crash_is_isolated(self):
        a = _write(self.src, "a.pdf", "A\n")
        crash = _write(self.src, "crash.pdf", "CRASH\n")
        # runs alongside the crash; must be re-run and succeed
        once = _write(self.src, "bystander.pdf", "BYSTANDER\n")
        b = _write(self.src, "b.pdf", "B\n")
        stats, _ = self._run([a, crash, once, b], workers=2, window=4)
        subs = dict(self._rows("SELECT pdf_filename, outcome FROM submissions"))
        self.assertEqual(subs["a.pdf"], "analysed")
        self.assertEqual(subs["b.pdf"], "analysed")
        self.assertEqual(subs["crash.pdf"], "failed")
        self.assertEqual(subs["bystander.pdf"], "analysed")
        self.assertGreaterEqual(stats["worker_restarts"], 1)

    def test_encrypted_files(self):
        import pikepdf
        from pdf_forensics.passwords import PasswordManager

        def make(name, pw):
            pdf = pikepdf.new()
            pdf.add_blank_page()
            p = os.path.join(self.src, name)
            os.makedirs(self.src, exist_ok=True)
            pdf.save(p, encryption=pikepdf.Encryption(user=pw, owner="own"))
            return p
        locked = make("locked.pdf", "secret1")
        opened = make("opened.pdf", "letmein")
        perms = make("perms.pdf", "")
        mgr = PasswordManager(["nope", "letmein"])
        stats, events = self._run([locked, opened, perms],
                                  password_manager=mgr)
        subs = dict(self._rows("SELECT pdf_filename, outcome FROM submissions"))
        self.assertEqual(subs, {"locked.pdf": "encrypted_unopened",
                                "opened.pdf": "analysed",
                                "perms.pdf": "analysed"})
        enc = self._rows("SELECT pdf_path, opened, password FROM encryption "
                         "ORDER BY id")
        self.assertEqual([(os.path.basename(r[0]), r[1], r[2]) for r in enc],
                         [("locked.pdf", 0, None), ("opened.pdf", 1, "letmein"),
                          ("perms.pdf", 1, "")])
        self.assertEqual(stats["encrypted"], 1)

    def test_logs_are_replayed_in_order(self):
        from pdf_forensics import session as _session
        from pdf_forensics.session import Session
        # keep the user's own settings file untouched
        _session.CONFIG_FILE = os.path.join(self.root, "config.json")
        case = os.path.join(self.root, "case")
        s = Session("T-1")
        s.set_db_dir(case)
        conn = init_db(self.db, session=s)
        paths = [_write(self.src, f"g{i}.pdf", f"G{i}\nVERSIONS 1\n")
                 for i in range(4)]
        s.perf.run_begin("analysis", len(paths), workers=3)
        r = ParallelRunner(paths, conn, self.db, session=s, workers=3,
                           out_dir=self.out, extract_versions=True,
                           versions_out=self.vout, compute_fn=STUB)
        r.run()
        s.perf.run_end()
        conn.close()
        s.perf.close()
        with open(s.log_path, encoding="utf-8") as fh:
            log = fh.read()
        order = [log.index(f"stub g{i}") for i in range(4)]
        self.assertEqual(order, sorted(order))
        with open(s.perf.path, encoding="utf-8") as fh:
            perf = fh.read().splitlines()
        rows = [l.split("\t") for l in perf if l[:1].isdigit()]
        self.assertEqual([r[1] for r in rows],
                         ["submitted", "version 1"] * 4)
        self.assertEqual([r[2] for r in rows if r[1] != "submitted"],
                         ["1", "3", "5", "7"])
        for h in list(s.logger.handlers):
            h.close()

    def test_terminate_stops_quickly(self):
        import threading
        paths = [_write(self.src, f"s{i}.pdf", f"S{i}\nSLEEP 30\n")
                 for i in range(4)]
        box = {}

        def run():                     # as in the GUI: one thread throughout
            conn = init_db(self.db)
            box["r"] = ParallelRunner(paths, conn, self.db, workers=2,
                                      out_dir=self.out, compute_fn=STUB)
            try:
                box["r"].run()
            finally:
                conn.close()
        th = threading.Thread(target=run)
        t0 = time.time()
        th.start()
        time.sleep(1.5)
        box["r"].terminate()
        th.join(20)
        self.assertFalse(th.is_alive())
        self.assertLess(time.time() - t0, 15)

    def test_compare_databases_tool(self):
        from tests.compare_databases import compare
        paths = [_write(self.src, f"h{i}.pdf", f"H{i % 3}\nVERSIONS 2\n")
                 for i in range(6)]
        dbs = []
        for w in (1, 4):
            db = os.path.join(self.root, f"case{w}", "case.db")
            os.makedirs(os.path.dirname(db))
            conn = init_db(db)
            ParallelRunner(paths, conn, db, workers=w,
                           out_dir=os.path.join(self.root, f"case{w}", "img"),
                           extract_versions=True,
                           versions_out=os.path.join(self.root, f"case{w}",
                                                     "ver"),
                           compute_fn=STUB).run()
            conn.close()
            dbs.append(db)
        quiet = lambda *_: None                      # noqa: E731
        self.assertTrue(compare(dbs[0], dbs[1], out=quiet))
        self.assertFalse(compare(dbs[0], dbs[1], paths="full", out=quiet))
        c = sqlite3.connect(dbs[1])
        c.execute("UPDATE analyses SET total_pages = 9 WHERE id = 2")
        c.commit()
        c.close()
        lines = []
        self.assertFalse(compare(dbs[0], dbs[1], out=lines.append))
        self.assertIn("Table analyses, id 2, column total_pages: 1 != 9",
                      lines)

    def test_unpicklable_result_is_analysed_in_main_process(self):
        os.environ["PDF_FORENSICS_TEST_MAIN"] = str(os.getpid())
        try:
            a = _write(self.src, "a.pdf", "A\n")
            u = _write(self.src, "u.pdf", "U\nUNPICKLABLE\n")
            stats, _ = self._run([a, u], workers=2)
        finally:
            del os.environ["PDF_FORENSICS_TEST_MAIN"]
        subs = dict(self._rows("SELECT pdf_filename, outcome FROM submissions"))
        self.assertEqual(subs, {"a.pdf": "analysed", "u.pdf": "analysed"})

    def test_largest_first_written_in_order(self):
        # sizes chosen so the largest is in the middle of the selection
        paths = [_write(self.src, f"s{i}.pdf", f"S{i}\n" + "x" * size + "\n")
                 for i, size in enumerate((10, 5000, 300, 20000, 50))]
        stats, events = self._run(paths, workers=1, window=1)
        started = [e["name"] for e in events if e["type"] == "start"]
        # the largest first; with a window of one, s3's result then waits
        # for s0, whose turn has come, so s0 is sent next; then by size
        self.assertEqual(started, ["s3.pdf", "s0.pdf", "s1.pdf",
                                   "s2.pdf", "s4.pdf"])
        written = [e["name"] for e in events if e["type"] == "result"]
        self.assertEqual(written, [f"s{i}.pdf" for i in range(5)])
        subs = [r[0] for r in self._rows(
            "SELECT pdf_filename FROM submissions ORDER BY id")]
        self.assertEqual(subs, [f"s{i}.pdf" for i in range(5)])

    def test_same_result_any_order_and_memory_budget(self):
        from tests.compare_databases import compare
        paths = [_write(self.src, f"m{i:02d}.pdf",
                        f"M{i % 5}\nVERSIONS {i % 3}\nIMAGES {i % 4}\n"
                        + "y" * (i * 97 % 700))
                 for i in range(15)]
        dbs = []
        for k, kw in enumerate(({"order": "submission", "workers": 1,
                                 "window": 1},
                                {"order": "largest", "workers": 4},
                                {"order": "largest", "workers": 3,
                                 "memory_budget": 1},      # all to disk
                                {"order": "largest", "workers": 6,
                                 "window": 30})):
            case = os.path.join(self.root, f"run{k}")
            db = os.path.join(case, "case.db")
            os.makedirs(case)
            conn = init_db(db)
            r = ParallelRunner(paths, conn, db,
                               out_dir=os.path.join(case, "img"),
                               extract_versions=True,
                               versions_out=os.path.join(case, "ver"),
                               compute_fn=STUB, **kw)
            st = r.run()
            conn.close()
            if kw.get("memory_budget") == 1:
                self.assertGreater(st["results_spilled"], 0)
                self.assertEqual(st["peak_held_mb"], 0)
            self.assertEqual(
                [d for d in os.listdir(os.path.join(case, "img"))
                 if d.startswith(".pending")], [])
            dbs.append(db)
        quiet = lambda *_: None                      # noqa: E731
        for db in dbs[1:]:
            self.assertTrue(compare(dbs[0], db, out=quiet), db)

    def test_unique_stems(self):
        self.assertEqual(
            unique_stems(["x/A.pdf", "y/a.pdf", "z/A.pdf", "w/A_2.pdf",
                          "b.pdf"]),
            ["A", "a_2", "A_3", "A_2_2", "b"])


class WorkerSessionTest(unittest.TestCase):
    """Code that runs in worker processes gets a RecordingSession, not the
    real Session (1.3.0 build 2026-11-15b: the visual reports read
    session.case_number and called session.register_output, which the
    stand-in lacked, so every report failed in parallel)."""

    WORKER_CODE = [os.path.join("analysis", f) for f in os.listdir(
        os.path.join(os.path.dirname(HERE), "pdf_forensics", "analysis"))
        if f.endswith(".py") and f != "parallel.py"] + [
        os.path.join("reports", "visual.py"),
        os.path.join("reports", "reveal.py"), "passwords.py", "_mupdf.py",
        "branding.py", "database.py"]
    MAIN_ONLY = {"replay"}      # reports/visual.py, in the main process

    def test_stand_in_has_every_attribute_worker_code_uses(self):
        import re
        from pdf_forensics.analysis.parallel import RecordingSession
        rs = RecordingSession({"case_number": "C-1"})
        pkg = os.path.join(os.path.dirname(HERE), "pdf_forensics")
        missing = set()
        for rel in self.WORKER_CODE:
            with open(os.path.join(pkg, rel), encoding="utf-8") as fh:
                src = fh.read()
            for name in re.findall(r"(?<![\w.])session\.([A-Za-z_]+)", src):
                if name not in self.MAIN_ONLY and not hasattr(rs, name):
                    missing.add(f"{rel}: session.{name}")
        self.assertEqual(sorted(missing), [])

    def test_visual_report_page_with_stand_in(self):
        import tempfile
        from pdf_forensics.analysis.parallel import RecordingSession
        from pdf_forensics.reports.visual import _assemble_html
        from pdf_forensics.session import Session
        from pdf_forensics import session as _session
        with tempfile.TemporaryDirectory() as tmp:
            _session.CONFIG_FILE = os.path.join(tmp, "config.json")
            db = os.path.join(tmp, "c.db")
            init_db(db).close()
            real = Session("CASE-77")
            rs = RecordingSession({"case_number": "CASE-77",
                                   "timestamp": real.timestamp})
            html = _assemble_html([], db, 0, session=rs)
            self.assertIn("CASE-77", html)
            rs.register_output("report", os.path.join(tmp, "x.html"))
            rs.log("made")
            real.replay(rs.take())
            self.assertEqual(real.outputs,
                             [("report", os.path.join(tmp, "x.html"))])


if __name__ == "__main__":
    unittest.main()
