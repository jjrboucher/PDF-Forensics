"""
Path normalisation at the points where paths enter the application.

On Windows, Tk's file dialogs return forward slashes ("O:/case/work") and
os.path.join then adds backslashes, so a recorded path could mix both
("O:/case/work\\extracted_images"). Windows accepts either, but paths are
part of the forensic record (session logs, reports, the case index, the
output manifest, "Copy path"), so each is written one consistent way.

Paths are normalised once, where they enter (file and folder dialogs,
typed path fields when read, command-line arguments, path-list files, the
session's case folder), so every path built from them is consistent too.

norm_path() returns an absolute path with the platform's separators
(os.path.abspath, which applies os.path.normpath). Note that normpath
collapses ".." textually, without consulting the disk: if a folder in the
path is a link or junction, "a\\link\\..\\b" can resolve differently from
the original. Case is preserved; use os.path.normcase only to compare
paths, never for anything displayed or recorded.
"""

import os


def norm_path(p):
    """Absolute path with native separators. Empty or None is returned
    unchanged (e.g. a cancelled dialog)."""
    if not p:
        return p
    return os.path.abspath(os.path.expanduser(str(p).strip()))


class NormalisingDialogs:
    """Wraps tkinter.filedialog so that every dialog returns normalised
    paths. Attributes other than the four ask* functions pass through."""

    def __init__(self, filedialog):
        self._fd = filedialog

    def askopenfilename(self, *a, **k):
        return norm_path(self._fd.askopenfilename(*a, **k))

    def asksaveasfilename(self, *a, **k):
        return norm_path(self._fd.asksaveasfilename(*a, **k))

    def askdirectory(self, *a, **k):
        return norm_path(self._fd.askdirectory(*a, **k))

    def askopenfilenames(self, *a, **k):
        r = self._fd.askopenfilenames(*a, **k)
        return tuple(norm_path(p) for p in r) if r else r

    def __getattr__(self, name):
        return getattr(self._fd, name)


# ---------------------------------------------------------------------
# Folder and file names made from document names
# ---------------------------------------------------------------------
import hashlib as _hashlib
import re as _re

_BAD_CHARS = _re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}
# Windows' classic path limit is 260 characters; leave room for the files
# written inside the folder (e.g. 123_45.jpeg).
MAX_FOLDER_PATH = 220


def safe_name(name, parent=None, max_path=MAX_FOLDER_PATH, reserve=0):
    """A file or folder name derived from a document name that Windows
    can create as given:
      * characters Windows forbids are replaced with _;
      * trailing spaces and full stops are removed (Windows drops them
        silently, so the folder would get a different name than the one
        the application then writes into);
      * reserved device names (CON, NUL, COM1, ...) get a trailing _;
      * if parent + name (+ reserve characters for what goes inside) would
        exceed max_path, the name is shortened and a short hash of the
        original added, so different long names cannot collide.
    Names that are already safe are returned unchanged."""
    original = str(name)
    out = _BAD_CHARS.sub("_", original).rstrip(" .")
    if not out:
        out = "_"
    stem, dot, ext = out.partition(".")
    if stem.upper() in _RESERVED:      # NUL.txt is reserved as well as NUL
        out = stem + "_" + dot + ext
    if parent is not None:
        room = max_path - len(os.path.abspath(parent)) - 1 - reserve
        if len(out) > room:
            tag = "~" + _hashlib.md5(
                original.encode("utf-8", "replace")).hexdigest()[:6]
            keep = max(8, room - len(tag))
            out = out[:keep].rstrip(" .") + tag
    return out
