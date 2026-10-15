"""Keep PyMuPDF's C-level messages (e.g. "corrupt object stream") out of
the console, and route them to the session log instead. These are
warnings emitted while parsing imperfect-but-readable PDFs; they are not
fatal, but printing them to the terminal alarms the examiner and clutters
scripted runs. They remain part of the record via the log."""

_silenced = False


def silence():
    """Stop PyMuPDF printing messages to stderr (idempotent)."""
    global _silenced
    if _silenced:
        return
    try:
        import pymupdf
        pymupdf.TOOLS.mupdf_display_errors(False)
        _silenced = True
    except Exception:
        pass


def drain(session, context=""):
    """Write any accumulated PyMuPDF warnings to the session log and clear
    them. Safe to call when PyMuPDF is unavailable or has none."""
    if session is None:
        return
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
