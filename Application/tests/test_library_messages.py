"""Library messages go to the session log, not the console (builds
2026-11-23 and 2026-11-23b): pikepdf's warnings (Python logging) and
PyMuPDF's own messages, such as "unhandled font type ''" from
get_fonts(), which bypass MuPDF's warning store. Stand-in for PyMuPDF."""
import io
import logging
import os
import sys
import types
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pdf_forensics import _mupdf as M                           # noqa: E402


class _Session:
    def __init__(self):
        self.lines = []

    def log(self, msg, level="info"):
        self.lines.append((level, msg))


def _fake(with_set_messages):
    m = types.ModuleType("pymupdf")

    class _Tools:
        def mupdf_display_errors(self, on):
            pass

        def mupdf_warnings(self, reset=True):
            return ""
    m.TOOLS = _Tools()
    m._g_out_message = sys.stdout
    m._logger = None

    def message(text):
        if m._logger is not None:
            m._logger.log(m._level, text)
        else:
            print(text, file=m._g_out_message)
    m.message = message
    if with_set_messages:
        def set_messages(*, pylogging_logger=None, pylogging_level=None,
                         **kw):
            m._logger, m._level = pylogging_logger, pylogging_level
        m.set_messages = set_messages
    return m


class LibraryMessagesTest(unittest.TestCase):
    def setUp(self):
        self.saved = (sys.modules.get("pymupdf"), M._silenced)
        del M._PK_BUF[:]

    def tearDown(self):
        old, sil = self.saved
        if old is None:
            sys.modules.pop("pymupdf", None)
        else:
            sys.modules["pymupdf"] = old
        M._silenced = sil
        del M._PK_BUF[:]

    def _run(self, fake):
        sys.modules["pymupdf"] = fake
        M._silenced = False
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            M.silence()
            fake.message("unhandled font type ''")
            logging.getLogger("pikepdf._core").warning("damaged stream")
        s = _Session()
        M.drain(s, "doc.pdf")
        return out.getvalue() + err.getvalue(), [m for _, m in s.lines]

    def test_set_messages(self):
        console, lines = self._run(_fake(True))
        self.assertEqual(console, "")
        self.assertIn("PyMuPDF: unhandled font type '' [doc.pdf]", lines)
        self.assertIn("pikepdf: damaged stream [doc.pdf]", lines)

    def test_older_pymupdf_output_stream(self):
        fake = _fake(False)
        console, lines = self._run(fake)
        self.assertEqual(console, "")
        self.assertIn("PyMuPDF: unhandled font type '' [doc.pdf]", lines)


if __name__ == "__main__":
    unittest.main()
