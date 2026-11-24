"""Documents pikepdf cannot read are analysed from MuPDF's repaired copy
(build 2026-11-23).

In a 12,745-file case, 88 documents were not analysed: pikepdf reported
"root of pages tree has no /Kids array", or found fewer pages than MuPDF
(IndexError), although MuPDF opened them. engine.open_documents now
analyses such a document from a copy MuPDF has repaired (decrypted if
needed), with a structural warning that says so and gives both page
counts. Real pikepdf on synthetic damaged files; MuPDF is a stand-in here
(its repaired copy is a valid synthetic PDF), since PyMuPDF is not
installed where these tests are written.
"""
import contextlib
import io
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pikepdf                                                  # noqa: E402


def _pdf_bytes(pages):
    pdf = pikepdf.new()
    for _ in range(pages):
        pdf.add_blank_page()
    b = io.BytesIO()
    pdf.save(b, object_stream_mode=pikepdf.ObjectStreamMode.disable)
    return b.getvalue()


class _FakeDoc:
    def __init__(self, pages, repaired_bytes=None, needs_pass=False,
                 encryption=None, is_repaired=True, xrefs=None,
                 save_error=None):
        self._pages, self.needs_pass = pages, needs_pass
        self._xrefs = xrefs
        self._save_error = save_error
        self.metadata = {"encryption": encryption}
        self.is_repaired = is_repaired
        self._copy = repaired_bytes
        self.closed = False
        self.saved_with = None
        self.selected = None

    def select(self, pages):
        self.selected = list(pages)

    def __len__(self):
        return self._pages

    def authenticate(self, pw):
        self.needs_pass = False
        return 1

    def tobytes(self, **kw):
        self.saved_with = kw
        if self._save_error:
            raise self._save_error
        return self._copy

    def page_xref(self, i):
        if self._xrefs is None:
            raise RuntimeError("no page objects in this stand-in")
        return self._xrefs[i]

    def close(self):
        self.closed = True


def _fake_mupdf(original, copies, copy_pages=None, reopen=None):
    m = types.ModuleType("pymupdf")
    m.PDF_ENCRYPT_NONE = 1

    def _open(path=None, stream=None, filetype=None):
        if stream is not None:
            pk = pikepdf.open(io.BytesIO(stream))
            xr = [pg.obj.objgen[0] for pg in pk.pages]
            n = len(xr) if copy_pages is None else copy_pages
            # pages beyond pikepdf's: objects pikepdf does not list
            xr += [90000 + k for k in range(n - len(xr))]
            return _FakeDoc(n, xrefs=xr)
        if original.closed and reopen is not None:
            return reopen
        return original
    m.open = _open
    return m


try:
    import pymupdf as _REAL  # noqa: F401
except ImportError:
    _REAL = None

_had = "pymupdf" in sys.modules
if _REAL is None:
    sys.modules["pymupdf"] = types.ModuleType("pymupdf")
try:
    from pdf_forensics.analysis import engine as _ENGINE        # noqa: E402
finally:
    if _REAL is None and not _had:
        sys.modules.pop("pymupdf", None)


@contextlib.contextmanager
def _engine_with(fake):
    """The engine with its PyMuPDF reference replaced for the block."""
    saved = _ENGINE.pymupdf
    _ENGINE.pymupdf = fake
    try:
        yield _ENGINE
    finally:
        _ENGINE.pymupdf = saved


class RepairedCopyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _file(self, name, data):
        p = os.path.join(self.tmp.name, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_no_kids_is_analysed_from_repaired_copy(self):
        good = _pdf_bytes(2)
        bad = self._file("secret-name.pdf", good.replace(b"/Kids", b"/Kidz"))
        with self.assertRaises(Exception):
            pikepdf.open(bad)
        orig = _FakeDoc(2, repaired_bytes=good, encryption="Standard V5 R6"
                        " 256-bit AES")
        with _engine_with(_fake_mupdf(orig, None)) as engine:
            mu, pk, findings = engine.open_documents(bad, password="")
        self.assertEqual(len(pk.pages), 2)
        self.assertEqual(len(mu), 2)
        self.assertTrue(orig.closed)
        self.assertEqual(orig.saved_with.get("garbage"), 0)
        self.assertEqual(len(findings), 1)
        d = findings[0]["detail"]
        self.assertEqual(findings[0]["type"], "STRUCTURAL_WARNING")
        self.assertIn("root of pages tree has no /Kids array", d)
        self.assertIn("repaired and decrypted by MuPDF", d)
        self.assertNotIn("secret-name", d)           # no file name

    def test_page_count_disagreement(self):
        two = self._file("two.pdf", _pdf_bytes(2))
        orig = _FakeDoc(3, repaired_bytes=_pdf_bytes(3), is_repaired=False)
        with _engine_with(_fake_mupdf(orig, None)) as engine:
            mu, pk, findings = engine.open_documents(two)
        self.assertEqual(len(pk.pages), 3)
        d = findings[0]["detail"]
        self.assertIn("MuPDF finds 3, pikepdf finds 2", d)
        self.assertNotIn("after repairing", d)

    def test_page_tree_rewritten_before_saving(self):
        good = _pdf_bytes(2)
        bad = self._file("k.pdf", good.replace(b"/Kids", b"/Kidz"))
        orig = _FakeDoc(2, repaired_bytes=good)
        with _engine_with(_fake_mupdf(orig, None)) as engine:
            engine.open_documents(bad)
        self.assertEqual(orig.selected, [0, 1])

    def test_inconsistent_copy_used_for_shared_pages(self):
        # Build 2026-11-24b: MuPDF 3 pages, pikepdf 2, and the copy still
        # disagrees: the copy is analysed for the 2 pages both readers
        # have (a 100/99-page file failed outright in build 2026-11-24).
        bad = self._file("k.pdf", _pdf_bytes(2).replace(b"/Kids", b"/Kidz"))
        orig = _FakeDoc(3, repaired_bytes=_pdf_bytes(2))
        with _engine_with(_fake_mupdf(orig, None, copy_pages=3)) as engine:
            mu, pk, findings = engine.open_documents(bad)
            pairs = engine.page_pairs(mu, pk)
        self.assertEqual(len(pk.pages), 2)
        self.assertEqual(pairs, [(0, 0), (1, 1)])
        d = findings[0]["detail"]
        self.assertIn("Pages not fully analysed", d)
        self.assertIn("MuPDF still finds 3 page(s) and pikepdf 2", d)
        self.assertIn("the 2 page(s) both readers find", d)
        self.assertIn("MuPDF's page(s) 3 could not be paired", d)

    def test_original_analysed_when_no_copy_can_be_made(self):
        # pikepdf reads 2 pages, MuPDF 3 with an extra page in the middle,
        # and MuPDF cannot save a copy: the original is analysed, pages
        # paired by object number, not by position.
        path = self._file("two.pdf", _pdf_bytes(2))
        with pikepdf.open(path) as _pdf:
            xr = [pg.obj.objgen[0] for pg in _pdf.pages]
        mid = [xr[0], 90001, xr[1]]
        orig = _FakeDoc(3, save_error=RuntimeError("invalid key in dict"),
                        xrefs=mid)
        again = _FakeDoc(3, xrefs=mid)
        with _engine_with(_fake_mupdf(orig, None, reopen=again)) as engine:
            mu, pk, findings = engine.open_documents(path)
            pairs = engine.page_pairs(mu, pk)
        self.assertIs(mu, again)
        self.assertEqual(pairs, [(0, 0), (2, 1)])
        d = findings[0]["detail"]
        self.assertIn("could not be made (invalid key in dict)", d)
        self.assertIn("MuPDF's page(s) 2 could not be paired", d)

    def test_zero_pages_in_mupdf(self):
        # MuPDF finds no pages and pikepdf reads 2: nothing to analyse,
        # said plainly (build 2026-11-20b reported such a file as analysed).
        two = self._file("z.pdf", _pdf_bytes(2))
        orig = _FakeDoc(0)
        again = _FakeDoc(0)
        with _engine_with(_fake_mupdf(orig, None, reopen=again)) as engine:
            mu, pk, findings = engine.open_documents(two)
        self.assertIn("(none)", findings[0]["detail"])
        self.assertIn("MuPDF finds no pages", findings[0]["detail"])

    def test_neither_reader(self):
        bad = self._file("n.pdf", _pdf_bytes(2).replace(b"/Kids", b"/Kidz"))
        with _engine_with(_fake_mupdf(_FakeDoc(0), None)) as engine:
            with self.assertRaises(RuntimeError) as cm:
                engine.open_documents(bad)
        msg = str(cm.exception)
        self.assertIn("neither PDF reader", msg)
        self.assertIn("no /Kids", msg)
        self.assertIn("MuPDF finds no pages", msg)
        self.assertNotIn("n.pdf", msg)

    def test_readable_file_unchanged(self):
        two = self._file("ok.pdf", _pdf_bytes(2))
        orig = _FakeDoc(2)
        with _engine_with(_fake_mupdf(orig, None)) as engine:
            mu, pk, findings = engine.open_documents(two)
        self.assertIs(mu, orig)
        self.assertEqual(findings, [])
        self.assertFalse(orig.closed)

    def test_wrong_password_still_raises(self):
        pdf = pikepdf.new()
        pdf.add_blank_page()
        b = io.BytesIO()
        pdf.save(b, encryption=pikepdf.Encryption(user="u", owner="o"))
        locked = self._file("locked.pdf", b.getvalue())
        orig = _FakeDoc(1, needs_pass=True)
        with _engine_with(_fake_mupdf(orig, None)) as engine:
            with self.assertRaises(pikepdf.PasswordError):
                engine.open_documents(locked, password="wrong")
        self.assertTrue(orig.closed)


if __name__ == "__main__":
    unittest.main()
