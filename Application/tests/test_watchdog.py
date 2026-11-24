"""The analysis watchdog and Skip (build 2026-11-23).

A file whose worker reports no progress for the set time is stopped and
recorded as failed ("timed out"); a file the examiner skips likewise
("skipped by the examiner"). The files running alongside are sent again
and analysed as usual, and results are still written in submission
order. Stand-in analysis (tests/stub_compute.py), no PyMuPDF needed.
"""
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pdf_forensics.database import init_db                     # noqa: E402
from pdf_forensics.analysis.parallel import ParallelRunner     # noqa: E402

STUB = "tests.stub_compute.compute"


def _write(folder, name, text):
    os.makedirs(folder, exist_ok=True)
    p = os.path.join(folder, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


class WatchdogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "src")
        self.out = os.path.join(self.tmp.name, "case", "img")
        self.db = os.path.join(self.tmp.name, "case", "case.db")
        os.makedirs(self.out)

    def tearDown(self):
        self.tmp.cleanup()

    def _subs(self):
        c = sqlite3.connect(self.db)
        try:
            return {r[0]: (r[1], r[2]) for r in c.execute(
                "SELECT pdf_filename, outcome, reason FROM submissions")}
        finally:
            c.close()

    def test_stalled_file_times_out_others_complete(self):
        paths = [_write(self.src, "a.pdf", "A\nSLEEP 0.3\n"),
                 _write(self.src, "hang.pdf", "H\nHANG\n"),
                 # busy (with progress) when the stalled file is stopped:
                 # sent again and analysed
                 _write(self.src, "b.pdf", "B\nPROGRESS 12 0.25\n"),
                 _write(self.src, "c.pdf", "C\n")]
        conn = init_db(self.db)
        events = []
        r = ParallelRunner(paths, conn, self.db, workers=3, window=4,
                           out_dir=self.out, compute_fn=STUB,
                           on_event=events.append, watchdog_minutes=0.03)
        t0 = time.time()
        stats = r.run()
        conn.close()
        self.assertLess(time.time() - t0, 60)
        subs = self._subs()
        self.assertEqual(subs["hang.pdf"][0], "failed")
        self.assertIn("No progress", subs["hang.pdf"][1] or "")
        for n in ("a.pdf", "b.pdf", "c.pdf"):
            self.assertEqual(subs[n][0], "analysed", (n, subs))
        self.assertEqual(stats["timed_out"], 1)
        self.assertEqual(stats["worker_restarts"], 0)
        starts = [e["name"] for e in events if e["type"] == "start"]
        self.assertEqual(starts.count("b.pdf"), 2)      # sent again
        order = [e["name"] for e in events if e["type"] == "result"]
        self.assertEqual(order, ["a.pdf", "hang.pdf", "b.pdf", "c.pdf"])

    def test_examiner_skips_a_file(self):
        paths = [_write(self.src, "slow.pdf", "S\nHANG\n"),
                 _write(self.src, "d.pdf", "D\nSLEEP 0.2\n")]
        box = {}

        def run():
            conn = init_db(self.db)
            box["r"] = ParallelRunner(paths, conn, self.db, workers=2,
                                      out_dir=self.out, compute_fn=STUB,
                                      watchdog_minutes=0)
            try:
                box["stats"] = box["r"].run()
            finally:
                conn.close()
        th = threading.Thread(target=run)
        th.start()
        target = None
        for _ in range(200):
            time.sleep(0.1)
            r = box.get("r")
            if r is None:
                continue
            for idx, name, idle, page, pages in r.running_files():
                if name == "slow.pdf":
                    target = idx
            if target is not None:
                break
        self.assertIsNotNone(target)
        self.assertTrue(box["r"].skip(target))
        th.join(60)
        self.assertFalse(th.is_alive())
        subs = self._subs()
        self.assertEqual(subs["slow.pdf"][0], "failed")
        self.assertIn("Skipped by the examiner", subs["slow.pdf"][1] or "")
        self.assertEqual(subs["d.pdf"][0], "analysed")
        self.assertEqual(box["stats"]["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
