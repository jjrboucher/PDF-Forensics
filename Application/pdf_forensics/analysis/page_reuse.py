"""
Reuse of unchanged pages in prior versions (1.2.0).

A prior version recovered from an incremental update usually shares most of
its pages with the submitted file: an update rewrites only the objects that
change, and every other object keeps its number and its bytes. Analysing
those pages again repeats the most expensive work (content parsing, image
mapping, transparency and the page detectors) for identical results.

Each analysed page is fingerprinted: a hash of the page object and every
object it reaches (content streams, resources, fonts, images, annotations,
form XObjects), plus the attributes it inherits from the page tree. If a
prior version's page has the same fingerprint, the same page number and the
same label numbering as a page already analysed in the same lineage, its
results are reused. Any change anywhere in what the page uses gives a
different fingerprint, and the page is analysed in full.

Results are snapshotted (deep-copied) as soon as a page is finished, before
any document-level step could modify them, and copied again when reused.
The cache holds one lineage at a time: it is cleared when a submitted file
starts, and prior versions are processed straight after their parent.

Switches (environment variables):
  PDF_FORENSICS_PAGE_REUSE=0    analyse every page of every version in full
  PDF_FORENSICS_VERIFY_REUSE=1  analyse reused pages in full as well and
                                compare; mismatches are counted in the
                                performance log and noted in the session log
"""

import os
import copy
import json
import hashlib

try:
    import pikepdf
except Exception:          # pragma: no cover
    pikepdf = None

# Links back up or across the document: following them would hash the whole
# file (or loop), and they do not affect what a page shows or contains.
_SKIP_KEYS = {"/Parent", "/P", "/StructParents", "/StructParent",
              "/First", "/Last", "/Next", "/Prev", "/Dest", "/D"}
_INHERITABLE = ("/Resources", "/MediaBox", "/CropBox", "/Rotate")
_CACHE_BUDGET = 1536 * 1024 * 1024   # image bytes held by the cache

_cache = {}
_cache_bytes = [0, set()]            # total, ids of byte objects counted


def enabled():
    return os.environ.get("PDF_FORENSICS_PAGE_REUSE", "1") != "0"


def verify_mode():
    return os.environ.get("PDF_FORENSICS_VERIFY_REUSE", "0") == "1"


def clear():
    _cache.clear()
    _cache_bytes[0] = 0
    _cache_bytes[1] = set()


# ---------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------

def _is_page_node(o):
    try:
        t = o.get("/Type")
        return t is not None and str(t) in ("/Page", "/Pages")
    except Exception:
        return False


def _digest(o, memo, path, top=False):
    """Bytes digest of a PDF object and everything it reaches. Indirect
    objects are memoised per document by object number and generation."""
    indirect = False
    try:
        indirect = bool(getattr(o, "is_indirect", False))
    except Exception:
        indirect = False
    if indirect:
        key = o.objgen
        if key in memo:
            return memo[key]
        if key in path:
            return b"cycle:%d:%d" % key
        if not top and _is_page_node(o):
            # Another page (e.g. a link target): identity only.
            return b"page:%d:%d" % key
        path.add(key)
        try:
            d = _direct(o, memo, path)
        finally:
            path.discard(key)
        memo[key] = d
        return d
    return _direct(o, memo, path)


def _direct(o, memo, path):
    h = hashlib.md5()
    if pikepdf is not None and isinstance(o, (pikepdf.Dictionary,
                                              pikepdf.Stream)):
        h.update(b"D")
        for k in sorted(o.keys()):
            if k in _SKIP_KEYS:
                continue
            h.update(k.encode("latin-1", "replace"))
            h.update(_digest(o.get(k), memo, path))
        if isinstance(o, pikepdf.Stream):
            h.update(b"S")
            try:
                h.update(hashlib.md5(o.read_raw_bytes()).digest())
            except Exception:
                h.update(b"?")
    elif pikepdf is not None and isinstance(o, pikepdf.Array):
        h.update(b"A")
        for item in o:
            h.update(_digest(item, memo, path))
    elif pikepdf is not None and isinstance(o, pikepdf.String):
        h.update(b"s")
        h.update(bytes(o))
    else:
        h.update(b"v")
        h.update(repr(o).encode("utf-8", "replace"))
    return h.digest()


def _inherited(page_obj, key):
    node, seen = page_obj, set()
    while node is not None:
        try:
            if key in node:
                return node.get(key)
            node = node.get("/Parent")
            og = getattr(node, "objgen", None)
            if og in seen:
                return None
            seen.add(og)
        except Exception:
            return None
    return None


def fingerprint(page_pk, memo):
    """Fingerprint of one page (hex), or None if it cannot be computed."""
    if pikepdf is None:
        return None
    try:
        obj = page_pk.obj
        h = hashlib.md5()
        for k in _INHERITABLE:
            v = _inherited(obj, k)
            h.update(k.encode())
            h.update(b"-" if v is None else _digest(v, memo, set()))
        h.update(_digest(obj, memo, set(), top=True))
        return h.hexdigest()
    except Exception:
        return None


# ---------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------

def get(key):
    """A deep copy of the cached page results, or None."""
    hit = _cache.get(key) if key is not None else None
    if hit is None:
        return None
    try:
        return copy.deepcopy(hit)
    except Exception:
        return None


def put(key, results):
    """Snapshot one page's results: (label_to_info, transparency, findings,
    risk_scores, font_spans). Pages whose results cannot be copied are
    simply not cached."""
    if key is None or key in _cache:
        return False
    label_to_info = results[0] or {}
    new_bytes = 0
    for info in label_to_info.values():
        b = info.get("image_bytes")
        if b and id(b) not in _cache_bytes[1]:
            new_bytes += len(b)
    if _cache_bytes[0] + new_bytes > _CACHE_BUDGET:
        return False
    try:
        snap = copy.deepcopy(results)
    except Exception:
        return False
    _cache[key] = snap
    for info in snap[0].values():
        b = info.get("image_bytes")
        if b and id(b) not in _cache_bytes[1]:
            _cache_bytes[1].add(id(b))
            _cache_bytes[0] += len(b)
    return True


def _projection(results):
    """Comparable form of page results (image bytes by hash)."""
    label_to_info, transparency, findings, risk_scores, fonts = results

    def clean(o):
        if isinstance(o, (bytes, bytearray)):
            return "md5:" + hashlib.md5(o).hexdigest()
        if isinstance(o, dict):
            return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple, set)):
            seq = [clean(v) for v in o]
            return sorted(seq, key=repr) if isinstance(o, set) else seq
        if isinstance(o, float):
            return round(o, 6)
        if isinstance(o, (str, int, bool)) or o is None:
            return o
        return str(o)
    return json.dumps(clean({"images": label_to_info,
                             "transparency": transparency,
                             "findings": findings,
                             "risk": risk_scores, "fonts": fonts}),
                      sort_keys=True, default=str)


def same(a, b):
    """True if two page results are equivalent (verification mode)."""
    try:
        return _projection(a) == _projection(b)
    except Exception:
        return False


def same_findings(a, b):
    """True if two lists of findings are equivalent (verification mode)."""
    try:
        return (_projection(({}, {}, a, {}, [])) ==
                _projection(({}, {}, b, {}, [])))
    except Exception:
        return False
