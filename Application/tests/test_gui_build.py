"""The window can be built from start to finish (build 2026-11-19c; see
fake_tk_build.py). Build 2026-11-19b stopped at start-up on a name left
over from an earlier version of a control."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


class GuiBuildTest(unittest.TestCase):
    def test_window_builds(self):
        r = subprocess.run([sys.executable,
                            os.path.join(HERE, "fake_tk_build.py")],
                           capture_output=True, text=True, timeout=300)
        self.assertIn("WINDOW BUILT", r.stdout, r.stderr[-3000:])


if __name__ == "__main__":
    unittest.main()
