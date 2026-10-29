"""
Reading a list of PDF paths from a text file ("From list" in the GUI,
-l / --pdf-list on the command line).

Accepts lists as examiners actually produce them:
  * one path per line; blank lines and lines starting with # are ignored
  * paths wrapped in quotation marks (File Explorer's "Copy as path"
    wraps each path in double quotes), including typographic quotes
  * several tab-separated cells on a line (copying more than one column
    from the triage spreadsheet): the first cell that is an existing file
    is used
  * UTF-8 (with or without a byte-order mark), UTF-16 (e.g. Excel's
    "Unicode Text"), or the Windows legacy encoding, detected from the
    file's bytes, so paths with accented characters are read correctly
  * the same file listed twice (exactly, or with different slashes or
    letter case on Windows) is added once

Every path that cannot be found is returned by name so it can be shown
and logged, and the list file's own MD5 is recorded, so the selection
that went into an analysis can be reproduced.
"""
import os
import hashlib

_OPEN_Q = "\"'\u201c\u2018"
_CLOSE_Q = "\"'\u201d\u2019"


def _decode(raw):
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace"), "UTF-8 with BOM"
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16"), "UTF-16"
    if raw[:400].count(b"\x00") > len(raw[:400]) // 4:     # BOM-less UTF-16
        try:
            return raw.decode("utf-16-le"), "UTF-16 LE (no BOM)"
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("utf-8"), "UTF-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace"), "Windows-1252"


def _clean(field):
    f = field.strip()
    while len(f) >= 2 and f[0] in _OPEN_Q and f[-1] in _CLOSE_Q:
        f = f[1:-1].strip()
    return f.strip(_OPEN_Q + _CLOSE_Q).strip()


def path_key(p):
    """Comparison key: same file regardless of slashes / case on Windows."""
    return os.path.normcase(os.path.abspath(p))


def read_path_list(list_path):
    """
    Returns a dict:
      paths      : existing files, in list order, each once
      missing    : entries that are not existing files (as written)
      duplicates : entries skipped because the file was already listed
      entries    : non-blank, non-comment lines read
      encoding   : detected text encoding
      md5        : MD5 of the list file's bytes
      list_path  : absolute path of the list file
    Raises OSError if the list file itself cannot be read.
    """
    with open(list_path, "rb") as fh:
        raw = fh.read()
    text, enc = _decode(raw)
    found, missing, seen = [], [], set()
    dups = entries = 0
    for line in text.splitlines():
        s = line.strip().lstrip("\ufeff")
        if not s or s.startswith("#"):
            continue
        entries += 1
        fields = [f for f in (_clean(x) for x in s.split("\t")) if f]
        if not fields:
            continue
        hit = next((f for f in fields if os.path.isfile(f)), None)
        if hit is None:
            missing.append(fields[0] if len(fields) == 1 else s.strip())
            continue
        key = path_key(hit)
        if key in seen:
            dups += 1
            continue
        seen.add(key)
        found.append(os.path.abspath(hit))  # native separators (pathutil)
    return {"paths": found, "missing": missing, "duplicates": dups,
            "entries": entries, "encoding": enc,
            "md5": hashlib.md5(raw).hexdigest(),
            "list_path": os.path.abspath(list_path)}


def log_list(session, res, added=None):
    """Record the list in the session log: which file (with MD5), how it
    was read, the outcome, and every path that could not be found."""
    if not session:
        return
    added = len(res["paths"]) if added is None else added
    try:
        session.log(
            f"PDF list loaded: {res['list_path']} (MD5 {res['md5']}, "
            f"{res['encoding']}): {res['entries']} entries, {added} added, "
            f"{res['duplicates']} duplicate(s) ignored, "
            f"{len(res['missing'])} not found")
        for m in res["missing"]:
            session.log(f"  Not found (from list): {m}", "warning")
    except Exception:
        pass
