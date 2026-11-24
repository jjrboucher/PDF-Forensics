"""Image boxes read once per page; overlap pairs found by a sweep
(build 2026-11-23).

get_image_rects(xref) decodes every image on the page to find one
image's boxes; called per image, the overlap and off-page checks took
8,661 s and 1,218 s on a 29-page document with 28,260 images. The boxes
now come from one get_image_info call per page, checked against
get_image_rects on each process's first pages, and overlapping pairs are
found by a sweep instead of testing every pair. Both must give the same
findings, in the same order, as before. Uses a stand-in for PyMuPDF
(tests/fake_mupdf_boxes.py); before release the checks were also
compared with build 2026-11-20b on six such pages (21,328 findings):
identical.
"""
import contextlib
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
sys.path.insert(0, HERE)

import fake_mupdf_boxes as fm                                   # noqa: E402

_FAKE = mock.MagicMock()
_FAKE.Rect = fm.Rect
_FAKE.Matrix = lambda t: tuple(t)


@contextlib.contextmanager
def _mupdf_as(stub):
    """sys.modules["pymupdf"] is stub inside the block, and as before
    after it (other tests check whether PyMuPDF is installed)."""
    had = "pymupdf" in sys.modules
    old = sys.modules.get("pymupdf")
    sys.modules["pymupdf"] = stub
    try:
        yield
    finally:
        if had:
            sys.modules["pymupdf"] = old
        else:
            sys.modules.pop("pymupdf", None)


try:
    import pymupdf as _REAL  # noqa: F401
except ImportError:
    _REAL = None
with _mupdf_as(_REAL or _FAKE):
    from pdf_forensics.analysis import detectors as _D         # noqa: E402


def _detectors():
    return _D


def _run(D, page):
    labels = {f"p1_img{i + 1:04d}": {"xref": im["xref"]}
              for i, im in enumerate(page.info)}
    tr = {l: {"z_order": i, "opacity": 0.5 if i % 7 == 0 else 1.0,
              "blend_mode": "/Normal", "has_smask": i % 11 == 0}
          for i, l in enumerate(sorted(labels))}
    f = []
    with _mupdf_as(_FAKE):
        D.check_overlapping_images(page, 1, f, labels, tr)
        D.check_offpage_images(page, 1, f, labels)
    return f


PAGES = [(1, 30, 10), (2, 120, 40), (3, 400, 400), (4, 600, 200),
         (5, 60, 2)]


class ImageBoxesTest(unittest.TestCase):
    def setUp(self):
        self.D = _detectors()
        self.state = dict(self.D._RECT_STATE)
        self.sweep = self.D.OVERLAP_SWEEP_MIN

    def tearDown(self):
        self.D._RECT_STATE.update(self.state)
        self.D.OVERLAP_SWEEP_MIN = self.sweep
        self.D._RECT_CACHE["page"] = self.D._RECT_CACHE["boxes"] = None

    def _old_way(self, page):
        """get_image_rects per image and every pair tested."""
        self.D._RECT_STATE["ok"] = False
        self.D.OVERLAP_SWEEP_MIN = 10 ** 9
        try:
            return _run(self.D, page)
        finally:
            self.D._RECT_STATE["ok"] = True
            self.D.OVERLAP_SWEEP_MIN = self.sweep

    def test_same_findings(self):
        total = 0
        for seed, n, nx in PAGES:
            old = self._old_way(fm.Page(seed, n, nx))
            self.D._RECT_STATE.update(ok=True, left=0)
            page = fm.Page(seed, n, nx)
            new = _run(self.D, page)
            self.assertEqual([str(x) for x in old], [str(x) for x in new],
                             f"page {seed}")
            self.assertEqual(page.calls, 1, "one get_image_info per page")
            total += len(new)
        self.assertGreater(total, 1000)

    def test_self_check_counts_and_falls_back(self):
        D = self.D
        D._RECT_STATE.update(ok=True, left=5)
        before = dict(D.RECT_STATS)
        _run(D, fm.Page(1, 30, 10))
        self.assertEqual(D.RECT_STATS["verified"], before["verified"] + 1)

        class Shifted(fm.Page):
            def get_image_info(self, xrefs=False, hashes=False):
                out = super().get_image_info(xrefs, hashes)
                out[0] = dict(out[0], bbox=(0, 0, 1, 1))
                return out

            def get_image_rects(self, xref, transform=False):
                got = [i for i in fm.Page.get_image_info(self)
                       if i["xref"] == xref]
                if transform:
                    return [(fm.Rect(i["bbox"]), i["transform"])
                            for i in got]
                return [fm.Rect(i["bbox"]) for i in got]

        expected = self._old_way(Shifted(2, 40, 10))
        D._RECT_STATE.update(ok=True, left=5)
        got = _run(D, Shifted(2, 40, 10))
        self.assertEqual(D.RECT_STATS["mismatch"], before["mismatch"] + 1)
        self.assertFalse(D._RECT_STATE["ok"])
        self.assertEqual([str(x) for x in expected], [str(x) for x in got])

    def test_sweep_pairs(self):
        import random
        R = random.Random(7)
        for n in (50, 200, 700):
            rects = []
            for _ in range(n):
                x, y = R.uniform(0, 600), R.uniform(0, 800)
                rects.append(("l", fm.Rect(x, y, x + R.uniform(0, 80),
                                            y + R.uniform(0, 80)), None))
            got = list(self.D._overlap_candidates(rects))
            want = [(i, j) for i in range(n) for j in range(i + 1, n)
                    if not (rects[i][1] & rects[j][1]).is_empty]
            got_set = set(got)
            self.assertTrue(all(p in got_set for p in want))
            self.assertEqual(got, sorted(got))
            self.assertLess(len(got), n * (n - 1) // 2)


if __name__ == "__main__":
    unittest.main()
