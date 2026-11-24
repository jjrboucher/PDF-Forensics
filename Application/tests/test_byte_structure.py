"""Byte-level structure checks (build 2026-11-23): cross-reference
entries that do not point to the object they name, and zero runs outside
streams (a zero-filled tail). Synthetic files only."""
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pikepdf                                                  # noqa: E402

from pdf_forensics.analysis.doc_checks import (                # noqa: E402
    xref_mismatches, zero_runs, check_byte_structure)


def _pdf():
    pdf = pikepdf.new()
    for _ in range(3):
        pdf.add_blank_page()
    b = io.BytesIO()
    pdf.save(b, object_stream_mode=pikepdf.ObjectStreamMode.disable)
    return b.getvalue()


class ByteStructureTest(unittest.TestCase):
    def test_clean_file(self):
        d = _pdf()
        checked, bad = xref_mismatches(d)
        self.assertGreater(checked, 0)
        self.assertEqual(bad, [])
        self.assertEqual(zero_runs(d), [])

    def test_shifted_bytes_and_zero_tail(self):
        d = _pdf()
        shifted = d.replace(b"%PDF-1.3", b"%PDF-1.3\n% 12 bytes", 1)
        checked, bad = xref_mismatches(shifted)
        self.assertEqual(len(bad), checked)
        cut = d[:len(d) // 2] + b"\x00" * 5000
        self.assertEqual(zero_runs(cut), [(len(d) // 2, 5000)])
        in_stream = d.replace(b"stream\n", b"stream\n" + b"\x00" * 5000, 1)
        self.assertEqual(zero_runs(in_stream), [])
        found = []
        with tempfile.TemporaryDirectory() as t:
            for i, data in enumerate((shifted, cut)):
                p = os.path.join(t, f"x{i}.pdf")
                with open(p, "wb") as f:
                    f.write(data)
                found += check_byte_structure(p)
        kinds = " ".join(f["detail"] for f in found)
        self.assertIn("do not point to the object they name", kinds)
        self.assertIn("to the end of the file", kinds)


if __name__ == "__main__":
    unittest.main()
