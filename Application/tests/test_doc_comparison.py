"""The Document Comparison Matrix (build 2026-11-20b): the same pairs as the
SQL it replaced, at most a set number listed with the total stated, and
the notice in the written report. Synthetic database only."""
import os
import random
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pdf_forensics.database import init_db  # noqa: E402
from pdf_forensics.reports import queries as Q  # noqa: E402

OLD_SQL = """
    SELECT a1.pdf_filename, a2.pdf_filename, COUNT(DISTINCT id1.md5_hash)
    FROM images i1
    JOIN pages p1          ON p1.id = i1.page_id
    JOIN analyses a1       ON a1.id = p1.analysis_id
    JOIN image_data id1    ON id1.id = i1.image_data_id
    JOIN image_data id2    ON id2.md5_hash = id1.md5_hash
                          AND id2.id != id1.id
    JOIN images i2         ON i2.image_data_id = id2.id
    JOIN pages p2          ON p2.id = i2.page_id
    JOIN analyses a2       ON a2.id = p2.analysis_id AND a2.id > a1.id
    GROUP BY a1.id, a2.id
    ORDER BY COUNT(DISTINCT id1.md5_hash) DESC
"""


def make_case(path, ndocs, logo=True, seed=3):
    """Documents of three pages; a logo on every page (twice) if `logo`,
    and images drawn from a shared pool, some used on several pages."""
    r = random.Random(seed)
    conn = init_db(path)
    pool = [f"{k:032x}" for k in range(ndocs * 2)]
    for a in range(ndocs):
        aid = conn.execute(
            "INSERT INTO analyses (pdf_filename, pdf_path, pdf_size_bytes, "
            "pdf_md5, total_pages, analyzed_at) VALUES (?,?,?,?,?,?)",
            (f"doc{a:03d}.pdf", f"/x/doc{a}.pdf", 1, f"{a:032x}", 3,
             "2026-01-01")).lastrowid
        ids = {}
        for pn in range(1, 4):
            pid = conn.execute("INSERT INTO pages (analysis_id, page_number) "
                               "VALUES (?,?)", (aid, pn)).lastrowid
            use = (["logo", "logo"] if logo else []) + [
                r.choice(pool) for _ in range(3)]
            for k in use:
                if k not in ids:
                    ids[k] = conn.execute(
                        "INSERT INTO image_data (analysis_id, xref, "
                        "byte_size, md5_hash) VALUES (?,?,?,?)",
                        (aid, len(ids) + 1, 10, k)).lastrowid
                conn.execute("INSERT INTO images (page_id, label, "
                             "image_data_id) VALUES (?,?,?)",
                             (pid, "x", ids[k]))
    conn.commit()
    return conn


class DocComparisonTest(unittest.TestCase):
    def test_same_pairs_as_before(self):
        for logo in (True, False):
            with tempfile.TemporaryDirectory() as tmp:
                conn = make_case(os.path.join(tmp, "c.db"), 60, logo=logo)
                old = conn.execute(OLD_SQL).fetchall()
                cols, data, notice = Q._query_doc_comparison(conn)
                conn.close()
            new = [(d["Document A"], d["Document B"], d["Shared Images"])
                   for d in data]
            self.assertEqual(sorted(old), sorted(new))
            # most shared first, as before (ties are now in document order)
            self.assertEqual([x[2] for x in old], [x[2] for x in new])
            tied = {}
            for a, b, n in new:
                tied.setdefault(n, []).append((a, b))
            for pairs in tied.values():
                self.assertEqual(pairs, sorted(pairs))
            self.assertIsNone(notice)
            self.assertEqual([c["name"] for c in cols],
                             ["Document A", "Document B", "Shared Images"])

    def test_cap_and_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = make_case(os.path.join(tmp, "c.db"), 60)
            full = Q._query_doc_comparison(conn)[1]
            cols, data, notice = Q._query_doc_comparison(conn, max_rows=25)
            conn.close()
        self.assertEqual(len(full), 60 * 59 // 2)          # the logo
        self.assertEqual(data, full[:25])                   # the top 25
        self.assertIn("Showing the 25 pairs", notice)
        self.assertIn(f"of {len(full):,} pairs", notice)

    def test_report_states_the_cap(self):
        from pdf_forensics.reports.renderer import generate_report
        saved = Q.DOC_COMPARISON_MAX_ROWS
        Q.DOC_COMPARISON_MAX_ROWS = 10
        try:
            with tempfile.TemporaryDirectory() as tmp:
                db = os.path.join(tmp, "c.db")
                make_case(db, 20).close()
                out = os.path.join(tmp, "r.html")
                n = generate_report(db, Q.get_report_by_id("doc_comparison"),
                                    out)
                with open(out, encoding="utf-8") as fh:
                    html = fh.read()
        finally:
            Q.DOC_COMPARISON_MAX_ROWS = saved
        self.assertEqual(n, 10)
        self.assertIn("Showing the 10 pairs", html)
        self.assertIn("of 190 pairs", html)


if __name__ == "__main__":
    unittest.main()
