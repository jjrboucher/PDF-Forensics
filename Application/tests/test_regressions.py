"""Regression tests for fixes made since 1.0 (see the CHANGELOG). Each test
names the build or release that introduced the fix. Tests needing PyMuPDF
are skipped where it is not installed."""
import glob as _glob
import io
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
PKG = os.path.join(APP, "pdf_forensics")
sys.path.insert(0, APP)

from tests.synthetic import simple_pdf, append_info_update     # noqa: E402

try:
    import pymupdf  # noqa: F401
    HAVE_MUPDF = True
except ImportError:
    HAVE_MUPDF = False


def _src(rel):
    with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
        return fh.read()


class PriorVersions(unittest.TestCase):
    """Build 2026-10-20: prior-version validation."""

    def test_linearized_first_eof_is_not_a_version(self):
        from pdf_forensics.analysis.metadata import classify_prior_versions
        data = simple_pdf(pages=3, linearize=True)
        checks = classify_prior_versions(data)
        self.assertTrue(checks)
        self.assertEqual([c["status"] for c in checks], ["linearization"])

    def test_incremental_update_gives_valid_version(self):
        from pdf_forensics.analysis.metadata import classify_prior_versions
        base = simple_pdf(info={"Title": "Original"})
        data = append_info_update(base, {"Title": "Edited"})
        checks = classify_prior_versions(data)
        self.assertEqual([c["status"] for c in checks], ["valid"])
        # the version ends at its %%EOF (plus the end-of-line after it)
        self.assertTrue(data[:checks[0]["end"]].startswith(base))
        self.assertLessEqual(checks[0]["end"] - len(base), 2)

    def test_both_paths_use_the_classifier(self):
        self.assertIn("classify_prior_versions", _src("analysis/engine.py"))
        self.assertIn("classify_prior_versions", _src("analysis/triage.py"))

    @unittest.skipUnless(HAVE_MUPDF, "PyMuPDF not installed")
    def test_long_paths_and_unique_names(self):
        """Build 2026-10-15 (Windows long paths) and 1.3.0 (separate
        folders for files with the same name)."""
        from pdf_forensics.analysis.engine import extract_prior_versions
        with tempfile.TemporaryDirectory() as tmp:
            deep = os.path.join(tmp, *(["d" * 40] * 3))
            os.makedirs(deep)
            p = os.path.join(deep, "N" * 120 + ".pdf")
            with open(p, "wb") as fh:
                fh.write(append_info_update(simple_pdf(), {"Title": "x"}))
            written = []
            out = extract_prior_versions(p, deep, name="N" * 120,
                                         written=written)
            self.assertEqual(len(out), 1)
            self.assertTrue(out[0].endswith("_version1.pdf"))
            self.assertLessEqual(len(os.path.abspath(out[0])), 260)
            self.assertEqual(written, [(out[0], False)])


class Encryption(unittest.TestCase):
    """Builds 2026-10-14 and 2026-10-20: encryption checks on the bytes
    being triaged; outcomes recorded per file."""

    def _enc(self, pw):
        import pikepdf
        pdf = pikepdf.new()
        pdf.add_blank_page()
        b = io.BytesIO()
        pdf.save(b, encryption=pikepdf.Encryption(user=pw, owner="o"))
        return b.getvalue()

    def test_bytes_are_checked_not_the_parent_path(self):
        from pdf_forensics import passwords as pw
        self.assertTrue(pw.is_encrypted(self._enc("k")))
        self.assertFalse(pw.is_encrypted(simple_pdf()))
        res = pw.try_open(self._enc("k"), pw.PasswordManager(["a", "k"]))
        self.assertTrue(res["opened"])
        self.assertEqual(res["password"], "k")
        src = _src("analysis/triage.py")
        self.assertRegex(src, r"is_encrypted\(\s*data")

    def test_probe_then_record_equals_resolve(self):
        from pdf_forensics import passwords as pw
        from pdf_forensics.database import init_db
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "locked.pdf")
            with open(f, "wb") as fh:
                fh.write(self._enc("zz"))
            rows = []
            for split in (False, True):
                db = os.path.join(tmp, f"{split}.db")
                conn = init_db(db)
                if split:
                    probe = pw.probe_file_password(f, None)
                    out = pw.record_file_password(conn, f, probe, quiet=True)
                else:
                    out = pw.resolve_file_password(conn, f, None, quiet=True)
                rows.append((out, conn.execute(
                    "SELECT opened, password, password_source FROM encryption"
                    ).fetchall(), conn.execute(
                    "SELECT outcome FROM submissions").fetchall()))
                conn.close()
            self.assertEqual(rows[0], rows[1])
            self.assertTrue(rows[0][0]["skip"])

    def test_gui_and_index_wording(self):
        self.assertIn("is_version=this_is_version", _src("gui/app.py"))
        ci = _src("reports/case_index.py")
        self.assertIn("(password required)", ci)


class SquareBrackets(unittest.TestCase):
    """Build 2026-10-15: every glob escapes the folder part."""

    def test_globs_escape_directories(self):
        for rel in ("reports/case_index.py", "gui/app.py"):
            src = _src(rel)
            for m in re.finditer(r"glob\.glob\(", src):
                call = src[m.end():m.end() + 160]
                self.assertIn("glob.escape(", call,
                              f"{rel}: unescaped glob near {call[:60]!r}")

    def test_bracket_folder_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, "[010] exhibit")
            os.makedirs(d)
            open(os.path.join(d, "a.pdf"), "w").close()
            self.assertEqual(_glob.glob(os.path.join(d, "*.pdf")), [])
            self.assertEqual(len(_glob.glob(os.path.join(
                _glob.escape(d), "*.pdf"))), 1)


class DuplicateNotice(unittest.TestCase):
    """Build 2026-10-15: the duplicate notice is computed before the
    connection is closed."""

    def test_order_in_generate_report(self):
        src = _src("reports/renderer.py")
        body = src[src.index("def generate_report("):]
        body = body[:body.index("\ndef ", 1)]
        self.assertIn("_duplicate_notice(", body)
        self.assertLess(body.index("_duplicate_notice("),
                        body.index("conn.close()"))


class Versions(unittest.TestCase):
    """1.1.0: invalid and conflicting PDF versions."""

    def test_strict_version_format(self):
        from pdf_forensics.analysis.doc_checks import _declared_ok
        self.assertTrue(_declared_ok("1.5"))
        self.assertTrue(_declared_ok("/1.7"))
        self.assertTrue(_declared_ok("2.0"))
        for bad in ("1.05", "0.3", "1.8", "15", "", None, "1.5a"):
            self.assertFalse(_declared_ok(bad), bad)


class MetadataHistory(unittest.TestCase):
    """1.1.0: metadata changed by a later revision, and ExifTool's marker
    attributed with its caveat."""

    def test_exiftool_marker_attributed(self):
        from pdf_forensics.analysis.doc_checks import (
            check_metadata_history, exiftool_attribution)
        base = simple_pdf(info={"Author": "Pat Example",
                                "Producer": "Example Writer 1.0"})
        data = append_info_update(
            base, {"Author": "Sam Sample", "Producer": "Example Writer 1.0"},
            marker=f"%EndExifToolUpdate {len(base)}")
        recs = exiftool_attribution(data, [("version 1", len(base)),
                                           ("current file", len(data))])
        self.assertEqual(len(recs), 1)
        self.assertTrue(recs[0]["consistent"])
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "edited.pdf")
            with open(p, "wb") as fh:
                fh.write(data)
            types = [f["type"] for f in check_metadata_history(p)]
        self.assertIn("METADATA_REVISED", types)
        self.assertIn("EXIFTOOL_EDIT", types)


class Timeline(unittest.TestCase):
    """1.1.0: timeline across revisions, normalised to UTC."""

    def test_created_after_modified_is_flagged(self):
        from pdf_forensics.analysis.timeline import (build_timeline,
                                                     timeline_findings)
        data = simple_pdf(info={"CreationDate": "D:20250601120000Z",
                                "ModDate": "D:20250101120000Z"})
        data = append_info_update(data, {"CreationDate": "D:20250601120000Z",
                                         "ModDate": "D:20250701120000Z"})
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "t.pdf")
            with open(p, "wb") as fh:
                fh.write(data)
            tl = build_timeline(p)
        self.assertEqual(len(tl["revisions"]), 2)
        self.assertTrue(tl["issues"])
        self.assertTrue(any(f["type"] == "TIMELINE_INCONSISTENT"
                            for f in timeline_findings(tl)))
        # every revision's timestamps are listed, unchanged ones included
        self.assertGreaterEqual(len(tl["occurrences"]), 4)


class EntryPoints(unittest.TestCase):
    """1.3.0: worker processes need freeze_support in every entry point
    (a packaged executable would otherwise start the application again in
    each worker)."""

    def test_freeze_support(self):
        for rel in ("pdf_forensics.py",
                    os.path.join("pdf_forensics", "__main__.py")):
            with open(os.path.join(APP, rel), encoding="utf-8") as fh:
                self.assertIn("freeze_support()", fh.read(), rel)


if __name__ == "__main__":
    unittest.main()
