"""Keep PyMuPDF's C-level messages (e.g. "corrupt object stream") out of
the console, and route them to the session log instead. These are
warnings emitted while parsing imperfect-but-readable PDFs; they are not
fatal, but printing them to the terminal alarms the examiner and clutters
scripted runs. They remain part of the record via the log."""

_silenced = False

# pikepdf (and qpdf through it) reports problems through Python logging;
# with no handler configured, Python prints them to the console (in a
# 12,745-file case: XMP that could not be parsed, damaged streams). Build
# 2026-11-23: they are collected here and written to the session log with
# the document, as MuPDF's are.
_PK_BUF = []
_PK_MAX = 2000
_pk_installed = False


def _install_pikepdf_handler():
    global _pk_installed
    if _pk_installed:
        return
    import logging

    class _Collect(logging.Handler):
        def emit(self, record):
            if len(_PK_BUF) < _PK_MAX:
                try:
                    _PK_BUF.append(record.getMessage())
                except Exception:
                    pass
    lg = logging.getLogger("pikepdf")
    lg.addHandler(_Collect(level=logging.WARNING))
    lg.propagate = False
    _pk_installed = True


class _MessageSink:
    """A file-like target for PyMuPDF's own messages: each line goes to
    the buffer the session log is filled from."""
    def __init__(self, source):
        self._source = source
        self._part = ""

    def write(self, text):
        self._part += str(text)
        while "\n" in self._part:
            line, self._part = self._part.split("\n", 1)
            if line.strip() and len(_PK_BUF) < _PK_MAX:
                _PK_BUF.append((self._source, line.strip()))
        return len(text)

    def flush(self):
        pass


def _route_pymupdf_messages(pymupdf):
    """PyMuPDF prints some messages itself, outside MuPDF's warning store:
    "unhandled font type ''" when get_fonts() meets an embedded font
    program (/FontFile3) whose subtype is missing or unknown. Build
    2026-11-23b: they go to the session log with the document. PyMuPDF's
    set_messages() sends them to a logger; older versions keep the output
    stream in pymupdf._g_out_message."""
    import logging
    lg = logging.getLogger("pdf_forensics.pymupdf")
    if not getattr(lg, "_pf_collect", False):
        class _Collect(logging.Handler):
            def emit(self, record):
                if len(_PK_BUF) < _PK_MAX:
                    try:
                        _PK_BUF.append(("PyMuPDF", record.getMessage()))
                    except Exception:
                        pass
        lg.addHandler(_Collect(level=logging.DEBUG))
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        lg._pf_collect = True
    try:
        pymupdf.set_messages(pylogging_logger=lg,
                             pylogging_level=logging.WARNING)
        return
    except Exception:
        pass
    if hasattr(pymupdf, "_g_out_message"):
        pymupdf._g_out_message = _MessageSink("PyMuPDF")


def silence():
    """Stop PyMuPDF (and pikepdf) printing messages to the console
    (idempotent)."""
    global _silenced
    try:
        _install_pikepdf_handler()
    except Exception:
        pass
    if _silenced:
        return
    try:
        import pymupdf
        pymupdf.TOOLS.mupdf_display_errors(False)
        _silenced = True
    except Exception:
        return
    try:
        # Warnings stay in MuPDF's store (drained to the session log).
        pymupdf.TOOLS.mupdf_display_warnings(False)
    except Exception:
        pass
    try:
        _route_pymupdf_messages(pymupdf)
    except Exception:
        pass


def drain(session, context=""):
    """Write any accumulated PyMuPDF and pikepdf warnings to the session
    log and clear them. Safe to call when PyMuPDF is unavailable or has
    none."""
    pk = _PK_BUF[:]
    del _PK_BUF[:]
    if session is None:
        return
    for item in pk:
        source, line = item if isinstance(item, tuple) else ("pikepdf", item)
        line = str(line).strip()
        if line:
            session.log(f"{source}: {line}"
                        + (f" [{context}]" if context else ""), "warning")
    try:
        import pymupdf
        warns = pymupdf.TOOLS.mupdf_warnings(reset=True)
    except Exception:
        return
    if not warns:
        return
    for line in str(warns).splitlines():
        line = line.strip()
        if line:
            session.log(f"PyMuPDF: {line}"
                        + (f" [{context}]" if context else ""), "warning")
