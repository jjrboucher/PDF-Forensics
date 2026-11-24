"""One encryption check for triage and analysis (build 2026-11-23).

In a 12,745-file case, four permissions-only files that pikepdf could not
read (page tree without /Kids) were "not encrypted" in triage (bytes) and
"password required" in analysis (path), and were not analysed; the
Encrypted Files report showed no scheme and no MD5 for locked files.
Synthetic files only; MuPDF is a stand-in where needed.
"""
import contextlib
import io
import os
import sqlite3
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pikepdf                                                  # noqa: E402

from pdf_forensics import passwords as P                       # noqa: E402


def _enc(user, R=6, owner="owner", damaged=False):
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.add_blank_page()
    b = io.BytesIO()
    pdf.save(b, encryption=pikepdf.Encryption(user=user, owner=owner, R=R,
                                              metadata=R >= 4, aes=R >= 4),
             object_stream_mode=pikepdf.ObjectStreamMode.disable)
    data = b.getvalue()
    if damaged:
        data = data.replace(b"/Kids", b"/Kidz")
    return data


class _Doc:
    def __init__(self, needs_pass, password=None, scheme="AES-256"):
        self.needs_pass = needs_pass
        self._pw = password
        self.metadata = None if needs_pass else {"encryption": scheme}

    def authenticate(self, pw):
        if pw == self._pw:
            self.needs_pass = False
            return 1
        return 0

    def close(self):
        pass


@contextlib.contextmanager
def _mupdf(doc):
    saved = P._mupdf_doc
    P._mupdf_doc = lambda pdf: doc
    try:
        yield
    finally:
        P._mupdf_doc = saved


class EncryptionCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _file(self, name, data):
        p = os.path.join(self.tmp.name, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_same_answer_for_path_and_bytes(self):
        cases = {"perm": _enc(""), "locked": _enc("u"),
                 "perm_damaged": _enc("", damaged=True),
                 "plain_damaged": _enc("", damaged=True).replace(
                     b"/Encrypt", b"/Encrypz")}
        with _mupdf(None):                       # no MuPDF: trailer check
            for name, data in cases.items():
                path = self._file(name + ".pdf", data)
                self.assertEqual(P.is_encrypted(path),
                                 P.is_encrypted(data), name)
        self.assertTrue(P.is_encrypted(cases["perm_damaged"]))
        self.assertFalse(P.is_encrypted(cases["plain_damaged"]))

    def test_scheme_without_password(self):
        for R, want in ((2, "RC4-40"), (3, "RC4-128"), (4, "AES-128"),
                        (6, "AES-256")):
            data = _enc("u", R=R)
            path = self._file(f"r{R}.pdf", data)
            got = P.encryption_scheme(path)              # no password
            self.assertTrue(got.startswith(want), (R, got))
            self.assertEqual(got, P.encryption_scheme(path, "u"), R)

    def test_unreadable_permissions_only_file_opens(self):
        path = self._file("d.pdf", _enc("", damaged=True))
        with self.assertRaises(Exception):
            pikepdf.open(path, password="")
        with _mupdf(_Doc(needs_pass=False)):
            res = P.try_open(path, P.PasswordManager())
        self.assertTrue(res["opened"])
        self.assertEqual(res["password"], "")
        self.assertIn("MuPDF", res["label"])

    def test_unreadable_locked_file_uses_list(self):
        path = self._file("l.pdf", _enc("secret", damaged=True))
        mgr = P.PasswordManager()
        mgr._supplied = ["nope", "secret"]
        with _mupdf(_Doc(needs_pass=True, password="secret")):
            res = P.try_open(path, mgr)
        self.assertTrue(res["opened"])
        self.assertEqual(res["password"], "secret")
        with _mupdf(_Doc(needs_pass=True, password="other")):
            res = P.try_open(path, P.PasswordManager())
        self.assertFalse(res["opened"])

    def test_report_md5_scheme_and_copies(self):
        from pdf_forensics.database import init_db
        from pdf_forensics.reports.queries import _query_encrypted_files
        db = os.path.join(self.tmp.name, "case.db")
        conn = init_db(db)
        locked = _enc("u", R=4)
        paths = [self._file("a.pdf", locked), self._file("b.pdf", locked),
                 self._file("c.pdf", _enc(""))]
        with _mupdf(None):
            for p in paths:
                probe = P.probe_file_password(p, P.PasswordManager())
                P.record_file_password(conn, p, probe, quiet=True,
                                       record_unopened_submission=False)
        cols, data, notice = _query_encrypted_files(conn)
        conn.close()
        rows = {r["Filename"]: r for r in data}
        self.assertTrue(rows["a.pdf"]["PDF MD5"])
        self.assertEqual(rows["a.pdf"]["PDF MD5"], rows["b.pdf"]["PDF MD5"])
        self.assertEqual(rows["a.pdf"]["Copies"], 2)
        self.assertTrue(rows["a.pdf"]["Scheme"].startswith("AES-128"))
        self.assertIn("3 encrypted file(s), 2 distinct", notice)
        self.assertIn("2 not opened (1 distinct)", notice)


if __name__ == "__main__":
    unittest.main()
