"""Real analyses, one file at a time against several at once, compared with
compare_databases.py. Needs PyMuPDF (skipped otherwise).

Sequential references: process_pdfs (the command line's batch engine) for
runs without prior versions; and ParallelRunner with one worker for runs
with prior versions (the GUI's own loop cannot run without a display; to
compare against it, analyse the same files in the GUI with 'Files analysed
at once' set to 1 and to Auto, and run compare_databases.py on the two
databases)."""
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from tests.synthetic import simple_pdf, append_info_update       # noqa: E402
from tests.compare_databases import compare                      # noqa: E402

try:
    import pymupdf  # noqa: F401
    HAVE_MUPDF = True
except ImportError:
    HAVE_MUPDF = False


def _white_box_pdf():
    """A page with text and a white rectangle painted over part of it."""
    import pikepdf
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    font = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
        BaseFont=pikepdf.Name.Helvetica))
    page = pdf.pages[0]
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    page.Contents = pdf.make_stream(
        b"BT /F1 14 Tf 72 700 Td (Amount due: 1,250.00) Tj ET\n"
        b"1 1 1 rg 150 695 80 20 re f\n"
        b"BT /F1 14 Tf 152 700 Td (9,999.00) Tj ET\n")
    b = io.BytesIO()
    pdf.save(b, object_stream_mode=pikepdf.ObjectStreamMode.disable)
    return b.getvalue()


def _corpus(folder):
    os.makedirs(folder, exist_ok=True)
    files = {
        "statement.pdf": _white_box_pdf(),
        "copy_of_statement.pdf": _white_box_pdf(),
        "letter.pdf": append_info_update(
            append_info_update(simple_pdf(2, {"Title": "Letter"}),
                               {"Title": "Letter v2"}),
            {"Title": "Letter v3", "Author": "A. Example"}),
        "memo.pdf": simple_pdf(3, {"Title": "Memo"}),
    }
    paths = []
    for name, data in files.items():
        p = os.path.join(folder, name)
        with open(p, "wb") as fh:
            fh.write(data)
        paths.append(p)
    os.makedirs(os.path.join(folder, "other"), exist_ok=True)
    p = os.path.join(folder, "other", "memo.pdf")          # same name
    with open(p, "wb") as fh:
        fh.write(simple_pdf(1, {"Title": "Another memo"}))
    paths.append(p)
    return paths


@unittest.skipUnless(HAVE_MUPDF, "PyMuPDF not installed")
class Equivalence(unittest.TestCase):

    def test_without_prior_versions(self):
        from pdf_forensics.analysis.engine import process_pdfs
        from pdf_forensics.analysis.parallel import ParallelRunner
        from pdf_forensics.database import init_db
        with tempfile.TemporaryDirectory() as tmp:
            paths = _corpus(os.path.join(tmp, "src"))
            seq = os.path.join(tmp, "seq.db")
            process_pdfs(paths, seq, output_dir=os.path.join(tmp, "i1"),
                         quiet=True)
            par = os.path.join(tmp, "par.db")
            conn = init_db(par)
            ParallelRunner(paths, conn, par, workers=3,
                           out_dir=os.path.join(tmp, "i2")).run()
            conn.close()
            self.assertTrue(compare(seq, par, out=lambda *_: None))

    def test_with_prior_versions(self):
        from pdf_forensics.analysis.parallel import ParallelRunner
        from pdf_forensics.database import init_db
        with tempfile.TemporaryDirectory() as tmp:
            paths = _corpus(os.path.join(tmp, "src"))
            dbs = []
            for w in (1, 4):
                db = os.path.join(tmp, f"w{w}.db")
                conn = init_db(db)
                case = os.path.join(tmp, f"case{w}")
                ParallelRunner(paths, conn, db, workers=w,
                               out_dir=os.path.join(case, "images"),
                               extract_versions=True,
                               versions_out=os.path.join(case, "versions")
                               ).run()
                conn.close()
                dbs.append(db)
            self.assertTrue(compare(dbs[0], dbs[1], out=lambda *_: None))

    def test_triage_spreadsheets(self):
        """Triage one at a time and three at a time: every sheet, every
        cell (1.3.0, build 2026-11-19)."""
        from openpyxl import load_workbook
        from pdf_forensics.analysis.triage import run_triage
        with tempfile.TemporaryDirectory() as tmp:
            paths = _corpus(os.path.join(tmp, "src"))
            books = []
            for w in (1, 3):
                out = os.path.join(tmp, f"triage_{w}.xlsx")
                run_triage(paths, out, workers=w)
                wb = load_workbook(out)
                books.append({ws.title: [[c.value for c in row]
                                         for row in ws.iter_rows()]
                              for ws in wb.worksheets})
                wb.close()
            self.assertEqual(books[0], books[1])


if __name__ == "__main__":
    unittest.main()
