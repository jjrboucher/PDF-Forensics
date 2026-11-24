"""The visual overlay reports made several at a time must give the same
index, the same log entries in the same order and the same performance-log
events as one at a time. Without PyMuPDF installed each document's report
records "requires PyMuPDF" and is not made, which still exercises the
worker processes, the grouping by lineage, the ordering and the index."""
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pdf_forensics.database import init_db               # noqa: E402


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _make_db(path):
    conn = init_db(path)
    ft = conn.execute("SELECT id FROM finding_types WHERE code="
                      "'TEXT_OVERLAY'").fetchone()[0]
    ids = {}
    docs = [("bravo.pdf", None, None), ("alpha.pdf", None, None),
            ("alpha_version1.pdf", "alpha.pdf", 1),
            ("charlie.pdf", None, None),
            ("alpha_version2.pdf", "alpha.pdf", 2)]
    for name, parent, v in docs:
        cur = conn.execute(
            "INSERT INTO analyses (pdf_filename, pdf_path, pdf_size_bytes, "
            "pdf_md5, total_pages, analyzed_at, source_analysis_id, "
            "version_number) VALUES (?,?,?,?,?,?,?,?)",
            (name, f"/nonexistent/{name}", 1, f"{len(ids):032d}", 1,
             "2026-01-01", ids.get(parent), v))
        ids[name] = cur.lastrowid
        pid = conn.execute("INSERT INTO pages (analysis_id, page_number) "
                           "VALUES (?,1)", (ids[name],)).lastrowid
        conn.execute("INSERT INTO findings (page_id, finding_type_id, detail,"
                     " bbox_x0, bbox_y0, bbox_x1, bbox_y1, overlay_kind) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     (pid, ft, "x", 1, 1, 50, 20, "white_box"))
    conn.commit()
    conn.close()


class VisualParallelTest(unittest.TestCase):
    def test_same_output_one_or_many(self):
        from pdf_forensics import session as _session
        from pdf_forensics.session import Session
        from pdf_forensics.reports.visual import generate_visual_reports
        out = {}
        with tempfile.TemporaryDirectory() as tmp:
            _session.CONFIG_FILE = os.path.join(tmp, "config.json")
            db = os.path.join(tmp, "case.db")
            _make_db(db)
            for workers in (1, 3):
                case = os.path.join(tmp, f"w{workers}")
                s = Session("T-2")
                s.set_db_dir(case)
                idx = os.path.join(case, "visual.html")
                generate_visual_reports(db, idx, session=s, workers=workers)
                s.perf.close()
                for h in list(s.logger.handlers):
                    h.close()
                log = _read(s.log_path)
                body = [re.sub(r"^\S+ \S+ ", "", l) for l in log.splitlines()
                        if "Visual" in l or "visual" in l]
                body = [l for l in body if "Visual overlay reports: " not in l
                        or "worker process" not in l]
                perf = [l.split("\t")[:3] for l in
                        _read(s.perf.path).splitlines()
                    if l.startswith("EVENT\tvisual_overlay_document")]
                html = _read(idx)
                html = re.sub(r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d(:\d\d)?", "T",
                              html)
                html = re.sub(r"[0-9a-f]{32}", "H", html)
                out[workers] = (body, [p[:2] for p in perf], html)
        self.assertTrue(out[1][0])
        self.assertEqual(out[1][0], out[3][0])
        self.assertEqual(out[1][1], out[3][1])
        self.assertEqual(out[1][2], out[3][2])


class PlanTest(unittest.TestCase):
    def test_largest_first_and_split(self):
        from pdf_forensics.reports.visual import _plan_visual_tasks
        it = lambda i, n: {"i": i, "n_over": n}            # noqa: E731
        groups = [[it(1, 5)], [it(2, 40), it(3, 30), it(4, 30)],
                  [it(5, 2), it(6, 3)], [it(7, 20)]]
        tasks = _plan_visual_tasks(groups, workers=4)       # share = 32.5
        self.assertEqual([[x["i"] for x in t] for t in tasks],
                         [[2], [3], [4], [7], [1], [5, 6]])  # above half a share (16.25),
        # largest first; then the rest in listed order (build 2026-11-20)
        tasks = _plan_visual_tasks(groups, workers=1)       # never split
        self.assertEqual([[x["i"] for x in t] for t in tasks],
                         [[2, 3, 4], [1], [5, 6], [7]])
        flat = sorted(x["i"] for t in _plan_visual_tasks(groups, 12)
                      for x in t)
        self.assertEqual(flat, list(range(1, 8)))


if __name__ == "__main__":
    unittest.main()
