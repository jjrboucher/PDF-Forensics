"""Processor load in the performance log (build 2026-11-19e): the summary
arithmetic, the sampler (this application's share includes its worker
processes), and the NOTE written for a step. Numbers only, no names."""
import multiprocessing as mp
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pdf_forensics import perf  # noqa: E402

try:
    import psutil  # noqa: F401
    HAVE_PSUTIL = True
except ImportError:
    HAVE_PSUTIL = False


def _spin(seconds):
    end = time.time() + seconds
    while time.time() < end:
        pass


class SummaryTest(unittest.TestCase):
    def test_summary(self):
        samples = [(50, 40)] * 5 + [(90, 10)] * 5      # others busy later
        text = perf.load_summary(samples, interval=2.0)
        self.assertIn("machine average 70%, highest 90%", text)
        self.assertIn("this application average 25%", text)
        self.assertIn("other programs average 45%, highest 80% over 10 s",
                      text)
        self.assertIn("10 samples every 2 s", text)
        self.assertIsNone(perf.load_summary([]))
        # fewer samples than the window
        self.assertIn("over 4 s", perf.load_summary([(10, 5), (20, 5)]))


@unittest.skipUnless(HAVE_PSUTIL, "psutil not installed")
class SamplerTest(unittest.TestCase):
    def test_counts_worker_processes(self):
        ls = perf.LoadSampler(interval=0.25)
        ctx = mp.get_context("spawn")
        p = ctx.Process(target=_spin, args=(2.5,))
        p.start()
        p.join()
        samples = ls.stop()
        self.assertGreaterEqual(len(samples), 4)
        self.assertTrue(all(0 <= m <= 100 and 0 <= o <= m
                            for m, o in samples))
        # the spinning child is this application's work
        self.assertGreater(max(o for _, o in samples), 0)
        self.assertFalse(ls._t.is_alive())

    def test_note_for_a_step(self):
        real = perf.LoadSampler
        perf.LoadSampler = lambda: real(interval=0.2)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                pl = perf.PerfLog(os.path.join(tmp, "perf.log"))
                pl.run_begin("triage", 1)
                _spin(0.8)
                pl.run_end()
                pl.load_begin()
                _spin(0.5)
                pl.load_end("graphs")
                pl.load_begin()             # left running: closed with log
                pl.close()
                with open(pl.path, encoding="utf-8") as fh:
                    text = fh.read()
        finally:
            perf.LoadSampler = real
        self.assertIn("NOTE\tprocessor load during triage: machine "
                      "average", text)
        self.assertIn("NOTE\tprocessor load during graphs:", text)
        self.assertEqual(text.count("processor load during"), 2)
        # a speed check before each step (build 2026-11-20)
        self.assertEqual(text.count("NOTE\tspeed check: python "), 3)


class SpeedAndLoopTest(unittest.TestCase):
    def test_speed_check(self):
        py, zc = perf.speed_check()
        self.assertGreater(py, 0)
        self.assertGreater(zc, 0)

    def test_runner_loop_summary(self):
        """The analysis runner reports where its main loop's time went and
        how many workers were busy on average (build 2026-11-20)."""
        from pdf_forensics.analysis.parallel import ParallelRunner
        from pdf_forensics.database import init_db
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for k in range(6):
                p = os.path.join(tmp, f"doc{k}.pdf")
                with open(p, "w") as f:
                    f.write(f"file {k}\nSLEEP 0.3\n")
                paths.append(p)
            db = os.path.join(tmp, "case.db")
            conn = init_db(db)
            seen = []

            def slow_handler(evt):          # a slow progress handler
                seen.append(evt)
                time.sleep(0.01)
            r = ParallelRunner(paths, conn, db, workers=3,
                               compute_fn="tests.stub_compute.compute",
                               on_event=slow_handler)
            r.run()
            conn.close()
        text = r.loop_summary()
        self.assertIn("progress messages", text)
        self.assertIn("worker processes busy on average", text)
        lp = r._loop
        self.assertEqual(lp["events_n"], len(seen))
        self.assertGreaterEqual(lp["events"], 0.01 * len(seen) * 0.9)
        busy = lp["busy"] / (time.perf_counter() - lp["start"])
        self.assertTrue(0 < busy <= 3)


if __name__ == "__main__":
    unittest.main()
