"""Graphs made several at once (1.3.0, build 2026-11-19) give the same
files, reported in the same order, as one at a time. The full comparison
needs pyvis; the ordering, no-data and error handling run without it."""
import io
import os
import re
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pdf_forensics.database import init_db                       # noqa: E402
from pdf_forensics.graph.generate import generate_scopes         # noqa: E402

try:
    import pyvis  # noqa: F401
    import networkx  # noqa: F401
    HAVE_PYVIS = True
except ImportError:
    HAVE_PYVIS = False

SCOPES = ("all_placements", "cross_page", "cross_document")


def _png(colour):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (20, 20), colour).save(b, "PNG")
    return b.getvalue()


def _db(path, with_images=True):
    """Three documents; one logo on every page, a stamp on two pages of
    one document, a photo used once."""
    conn = init_db(path)
    if with_images:
        import hashlib
        imgs = {k: _png(c) for k, c in (("logo", "red"), ("stamp", "blue"),
                                        ("photo", "green"))}
        for d in range(3):
            aid = conn.execute(
                "INSERT INTO analyses (pdf_filename, pdf_path, "
                "pdf_size_bytes, pdf_md5, total_pages, analyzed_at) "
                "VALUES (?,?,?,?,?,?)",
                (f"doc{d}.pdf", f"/x/doc{d}.pdf", 1, f"{d:032d}", 2,
                 "2026-01-01")).lastrowid
            stored = {}         # one image_data row per image and document
            for pnum in (1, 2):
                pid = conn.execute("INSERT INTO pages (analysis_id, "
                                   "page_number) VALUES (?,?)",
                                   (aid, pnum)).lastrowid
                use = ["logo"] + (["stamp"] if d == 0 else []) + \
                      (["photo"] if (d, pnum) == (2, 1) else [])
                for z, k in enumerate(use):
                    data = imgs[k]
                    if k not in stored:
                        stored[k] = conn.execute(
                            "INSERT INTO image_data (analysis_id, xref, "
                            "format_ext, width_px, height_px, image_bytes, "
                            "byte_size, md5_hash) VALUES (?,?,?,?,?,?,?,?)",
                            (aid, len(stored) + 1, "png", 20, 20, data,
                             len(data), hashlib.md5(data).hexdigest())
                        ).lastrowid
                    iid = stored[k]
                    conn.execute(
                        "INSERT INTO images (page_id, image_data_id, label, "
                        "z_order) VALUES (?,?,?,?)",
                        (pid, iid, f"Im{z}", z))
        conn.commit()
    conn.close()


def _specs(db, out):
    return [{"db": db, "scope": s, "group_versions": True,
             "out_path": os.path.join(out, f"graph-{s}.html"),
             "case_number": "T-3"} for s in SCOPES]


class GraphParallelTest(unittest.TestCase):

    def test_order_and_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "empty.db")
            _db(db, with_images=False)
            for w in (1, 3):
                got = [(s["scope"], r["rows"]) for s, r in
                       generate_scopes(_specs(db, tmp), workers=w)]
                self.assertEqual(got, [(s, 0) for s in SCOPES])

    def test_errors_are_reported_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            specs = _specs(os.path.join(tmp, "missing", "none.db"), tmp)
            for w in (1, 3):
                got = list(generate_scopes(specs, workers=w))
                self.assertEqual([s["scope"] for s, _ in got], list(SCOPES))
                self.assertTrue(all(isinstance(r, Exception)
                                    for _, r in got))

    @unittest.skipUnless(HAVE_PYVIS, "pyvis/networkx not installed")
    def test_same_files_one_or_several(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "case.db")
            _db(db)
            outs = {}
            for w in (1, 3):
                out = os.path.join(tmp, f"w{w}")
                os.makedirs(out)
                res = list(generate_scopes(_specs(db, out), workers=w))
                outs[w] = []
                for spec, r in res:
                    self.assertNotIsInstance(r, Exception)
                    with open(spec["out_path"], encoding="utf-8") as fh:
                        html = fh.read()
                    # times and the output folder differ between runs
                    html = re.sub(r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d(:\d\d)?",
                                  "T", html)
                    outs[w].append((r["rows"], r["digest"],
                                    html.replace(out, "OUT")))
            self.assertEqual(outs[1], outs[3])
            self.assertGreater(outs[1][0][0], 0)


if __name__ == "__main__":
    unittest.main()
