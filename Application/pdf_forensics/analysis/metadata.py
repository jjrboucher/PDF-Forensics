"""
PDF and image metadata extraction.
"""

import os

try:
    from PIL import Image, ExifTags
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False



# ---------------------------------------------------------------------
# XMP read without side effects (build 2026-11-23). open_metadata() used
# as a context manager rewrites the document's XMP and Info in memory on
# exit, and an XMP packet that is not well-formed XML was replaced with
# an empty one, with warnings printed to the console and nothing kept.
# The XMP is now read strictly first; if that fails the problem and the
# raw packet are recorded, and the values a repairing parser can still
# recover are listed, labelled as such. Nothing is written back.
# ---------------------------------------------------------------------
XMP_RAW_MAX = 20000


@__import__("contextlib").contextmanager
def _quiet_pikepdf():
    import logging
    import warnings
    lg = logging.getLogger("pikepdf")
    level = lg.level
    lg.setLevel(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            yield
    finally:
        lg.setLevel(level)


def _xmp_value(v):
    if isinstance(v, (set, frozenset)):
        return ", ".join(sorted(str(x) for x in v))
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return str(v)


def raw_xmp(pdf):
    """The document's XMP packet as text, or None."""
    try:
        m = pdf.Root.get("/Metadata")
        if m is None:
            return None
        return m.read_bytes().decode("utf-8", "replace")
    except Exception:
        return None


def read_xmp(pdf):
    """(items, problem, raw): items [(key, text)], problem None or why the
    XMP could not be read as it stands, raw the packet when there was a
    problem."""
    def _items(strict):
        with _quiet_pikepdf():
            meta = pdf.open_metadata(set_pikepdf_as_editor=False,
                                     update_docinfo=False, strict=strict)
            return [(str(k), _xmp_value(v)) for k, v in meta.items()]
    try:
        return _items(True), None, None
    except Exception as e:
        problem = f"{type(e).__name__}: {str(e)[:300]}"
    raw = raw_xmp(pdf)
    if raw is None or not raw.strip():
        return [], None, None
    try:
        items = _items(False)
    except Exception:
        items = []
    if len(raw) > XMP_RAW_MAX:
        raw = (raw[:XMP_RAW_MAX] + f" \u2026 [shortened: {len(raw):,} "
               f"characters in all]")
    return items, problem, raw


def quiet_metadata(pdf):
    """pdf.open_metadata() for reading only: no rewrite, no console
    output (repairing parser, as before)."""
    with _quiet_pikepdf():
        meta = pdf.open_metadata(set_pikepdf_as_editor=False,
                                 update_docinfo=False)
        list(meta.items())                     # parse now, quietly
    return meta


def open_image_info(image_bytes):
    """PIL image opened for its header and EXIF only (pixels are not
    decoded). Build 2026-11-23: PIL's decompression-bomb limit (about 179
    million pixels) is lifted here, since nothing is decoded; very large
    scans raised DecompressionBombWarning on the console, or an error
    above twice the limit, and lost their EXIF."""
    import io as _io
    import warnings
    from PIL import Image
    saved = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            return Image.open(_io.BytesIO(image_bytes))
    finally:
        Image.MAX_IMAGE_PIXELS = saved

def extract_pdf_metadata(doc_pk, doc_mu):
    """
    Extract all available metadata from the PDF.

    Returns a list of (source, key, value) tuples ready for insertion.
    Sources:
      - 'info_dict' : entries from the traditional Info dictionary
                      (Title, Author, Subject, Creator, Producer, etc.)
      - 'xmp'       : entries from the XMP metadata stream
      - 'catalog'   : selected entries from the document Catalog
                      (PDF version, PageMode, PageLayout, Lang)
    """
    metadata = []

    # --- Info Dictionary ---
    try:
        if doc_pk.docinfo:
            for k, v in doc_pk.docinfo.items():
                key = str(k).lstrip("/")
                value = str(v)
                metadata.append(("info_dict", key, value))
    except Exception as e:
        metadata.append(("info_dict", "_error", str(e)))

    # --- XMP Metadata ---
    try:
        # XMP arrays: rdf:Seq/Alt come back as lists, rdf:Bag as a set
        # (e.g. dc:creator, dc:subject); both are joined as text.
        items, problem, raw = read_xmp(doc_pk)
        if problem:
            metadata.append((
                "xmp", "_unparsed",
                f"XMP present but could not be parsed as it stands "
                f"({problem}); any XMP values listed were recovered by a "
                f"repairing parser"))
            metadata.append(("xmp", "_raw", raw))
        for key, value in items:
            metadata.append(("xmp", key, value))
    except Exception as e:
        metadata.append(("xmp", "_error", str(e)))

    # --- Catalog entries of forensic interest ---
    try:
        root = doc_pk.Root
        for key in ("PageMode", "PageLayout", "Lang", "Version",
                    "ViewerPreferences", "PageLabels"):
            ref = root.get(f"/{key}")
            if ref is not None:
                metadata.append(("catalog", key, str(ref)))
    except Exception as e:
        metadata.append(("catalog", "_error", str(e)))

    # --- PyMuPDF supplemental metadata (PDF version, encryption) ---
    try:
        mu_meta = doc_mu.metadata or {}
        # Version comes from the PDF header (e.g. '1.7') and is not in
        # the Info dictionary.
        if "format" in mu_meta and mu_meta["format"]:
            metadata.append(("catalog", "pdf_version_header",
                             str(mu_meta["format"])))
        if doc_mu.is_encrypted:
            metadata.append(("catalog", "encrypted", "True"))
        if doc_mu.needs_pass:
            metadata.append(("catalog", "needs_password", "True"))
    except Exception:
        pass

    return metadata


def detect_linearization(pdf_path):
    """
    Determine whether the PDF is linearized (web-optimized).

    Linearized PDFs contain a /Linearized parameter dictionary within
    the first 1024 bytes of the file (the marker is required to appear
    at the head of the file) and, by specification, carry TWO %%EOF
    markers in a single-generation file. A linearized file with exactly
    two %%EOF markers has therefore NOT been incrementally updated.

    Returns one of:
      True    — /Linearized marker found in the file head
      False   — marker absent
      None    — the file could not be read (indeterminate)
    """
    try:
        with open(pdf_path, "rb") as f:
            head = f.read(1024)
    except Exception:
        return None
    return b"/Linearized" in head


def detect_pdf_versions(pdf_path):
    """
    Scan the PDF file for %%EOF markers. Each marker represents an
    incremental update version. The first %%EOF is the original
    version; subsequent markers indicate the file has been edited
    via incremental save (a forensic indicator of post-creation
    modification).

    Returns a list of (version_number, byte_offset) tuples.
    """
    versions = []
    try:
        with open(pdf_path, "rb") as f:
            data = f.read()
    except Exception:
        return versions

    pos = 0
    version_num = 0
    while True:
        idx = data.find(b"%%EOF", pos)
        if idx == -1:
            break
        version_num += 1
        versions.append((version_num, idx))
        pos = idx + 5

    return versions


def extract_image_metadata(image_bytes, ext):
    """
    Use Pillow to extract EXIF and format-specific metadata from
    image bytes.

    Returns a list of (source, key, value) tuples.
    Sources: 'exif', 'info'
    """
    metadata = []
    if not image_bytes:
        return metadata

    try:
        from PIL import Image, ExifTags
    except ImportError:
        return metadata

    try:
        img = open_image_info(image_bytes)
    except Exception:
        return metadata

    # --- Format-specific info dict (PNG chunks, JPEG markers, etc.) ---
    try:
        for k, v in (img.info or {}).items():
            key = str(k)
            try:
                if isinstance(v, bytes):
                    # Truncate raw binary chunks to avoid bloat
                    if len(v) > 256:
                        value = (v[:256].hex() + "... ("
                                 f"{len(v)} bytes total)")
                    else:
                        value = v.hex()
                elif isinstance(v, (tuple, list)):
                    value = ", ".join(str(x) for x in v)
                else:
                    value = str(v)
                metadata.append(("info", key, value))
            except Exception:
                continue
    except Exception:
        pass

    # --- EXIF data ---
    try:
        exif = img.getexif() if hasattr(img, "getexif") else None
        if exif:
            for tag_id, value in exif.items():
                tag_name = ExifTags.TAGS.get(tag_id, f"Tag_{tag_id}")
                try:
                    if isinstance(value, bytes):
                        try:
                            value = value.decode("utf-8", errors="replace")
                        except Exception:
                            value = value.hex()
                    metadata.append(("exif", str(tag_name), str(value)))
                except Exception:
                    continue

            # GPS sub-IFD
            try:
                gps_ifd = exif.get_ifd(0x8825)  # GPSInfo
                if gps_ifd:
                    for tag_id, value in gps_ifd.items():
                        tag_name = ExifTags.GPSTAGS.get(
                            tag_id, f"GPSTag_{tag_id}")
                        if isinstance(value, bytes):
                            try:
                                value = value.decode("utf-8",
                                                     errors="replace")
                            except Exception:
                                value = value.hex()
                        metadata.append(
                            ("exif_gps", str(tag_name), str(value)))
            except Exception:
                pass

            # Exif sub-IFD: capture time (DateTimeOriginal), digitising
            # time, their timezone offsets, exposure and lens details.
            # These live in IFD 0x8769, not the main IFD read above.
            try:
                exif_ifd = exif.get_ifd(0x8769)
                if exif_ifd:
                    for tag_id, value in exif_ifd.items():
                        tag_name = ExifTags.TAGS.get(tag_id, f"Tag_{tag_id}")
                        if isinstance(value, bytes):
                            if len(value) > 256:
                                continue  # MakerNote and similar blobs
                            try:
                                value = value.decode("utf-8",
                                                     errors="replace")
                            except Exception:
                                value = value.hex()
                        metadata.append(("exif", str(tag_name), str(value)))
            except Exception:
                pass
    except Exception:
        pass

    # --- Basic image properties ---
    try:
        metadata.append(("info", "_pil_format", str(img.format)))
        metadata.append(("info", "_pil_mode", str(img.mode)))
        metadata.append(("info", "_pil_size",
                         f"{img.size[0]}x{img.size[1]}"))
    except Exception:
        pass

    return metadata


# ---------------------------------------------------------------------------
# Prior-version validity
# ---------------------------------------------------------------------------
import io as _io
import re as _re

_STARTXREF_TAIL = _re.compile(rb"startxref\s+(\d+)\s+%%EOF\s*$")
_XREF_STREAM_HEAD = _re.compile(rb"\s*\d+\s+\d+\s+obj\b")


def prior_version_end(data, eof_offset):
    """Byte position where a prior version ends: the %%EOF marker plus any
    trailing CR/LF/space (shared by extraction and triage so both produce
    byte-identical versions)."""
    end = eof_offset + 5
    while end < len(data) and data[end:end + 1] in (b"\r", b"\n", b" "):
        end += 1
    return end


def _check_version_bytes(prefix, password=None):
    """Return (status, reason, pages, needs_password) for the bytes of a
    candidate prior version. status: 'valid', 'encrypted' or 'invalid'."""
    m = _STARTXREF_TAIL.search(prefix[-200:])
    if not m:
        return "invalid", "no startxref before this %%EOF", 0, False
    off = int(m.group(1))
    if off <= 0 or off >= len(prefix):
        return ("invalid",
                f"startxref is {off}, which does not point to a cross-reference "
                f"section within these {len(prefix):,} bytes", 0, False)
    target = prefix[off:off + 64]
    if not (target.lstrip().startswith(b"xref")
            or _XREF_STREAM_HEAD.match(target)):
        return ("invalid", "startxref does not point to a cross-reference "
                "section", 0, False)
    try:
        import pikepdf
    except Exception:
        return "valid", "", 0, False
    tried = [password] if password else []
    tried += [""] if "" not in tried else []
    last_pw_error = False
    for pw in tried:
        try:
            with pikepdf.open(_io.BytesIO(prefix), password=pw,
                              attempt_recovery=False) as pdf:
                n = len(pdf.pages)
                if n < 1:
                    return "invalid", "opens but contains no pages", 0, False
                return "valid", "", n, bool(pdf.is_encrypted and pw)
        except pikepdf.PasswordError:
            last_pw_error = True
            continue
        except Exception as e:
            return ("invalid", f"not a usable PDF ({str(e).split(':')[-1].strip()[:80]})",
                    0, False)
    if last_pw_error:
        return ("encrypted", "structurally valid but password-protected; "
                "the parent document's password did not open it" if password
                else "structurally valid but password-protected", 0, True)
    return "invalid", "could not be opened", 0, False


def classify_prior_versions(data, password=None):
    """
    Decide, for each %%EOF marker except the last, whether the bytes up to
    it form a genuine, usable earlier version of the document.

    A %%EOF marker is not always the end of a saved version:
      * In a linearized ("fast web view") PDF the first %%EOF ends the
        first-page section near the start of the file. It is part of the
        current file's layout, not an earlier version.
      * A marker can also be followed or preceded by bytes that do not
        form a usable PDF on their own (e.g. startxref 0, or pointing
        outside the section).
    Treating such a marker as a version produces a small fragment that is
    not a PDF, which can then be mis-reported (for instance as
    password-protected because it carries the parent's /Encrypt entry).

    password : the password that opened the parent document; tried first,
               since a genuine earlier version of an encrypted file uses
               the same encryption.

    Returns a list of dicts, one per candidate (version_number is the
    ordinal of the %%EOF marker, kept for traceability to the byte offset):
      version_number, eof_offset, end, size,
      status  : 'valid' | 'encrypted' | 'invalid' | 'linearization'
      reason  : why it is not a usable version ('' when valid)
      pages, needs_password
    """
    if not data:
        return []
    offsets = [m.start() for m in _re.finditer(rb"%%EOF", data)]
    if len(offsets) <= 1:
        return []
    linearized = b"/Linearized" in data[:1024]
    out = []
    for vnum, off in enumerate(offsets[:-1], start=1):
        end = prior_version_end(data, off)
        status, reason, pages, needs_pw = _check_version_bytes(
            data[:end], password)
        if linearized and vnum == 1 and status == "invalid":
            status = "linearization"
            reason = ("the file is linearized (fast web view); this %%EOF "
                      "ends the first-page section and is not a prior version")
        out.append({"version_number": vnum, "eof_offset": off, "end": end,
                    "size": end, "status": status, "reason": reason,
                    "pages": pages, "needs_password": needs_pw})
    return out


def describe_version_check(results):
    """Short, human-readable summary of classify_prior_versions() output,
    e.g. for a triage column or a log line."""
    if not results:
        return ""
    parts = []
    for r in results:
        v = r["version_number"]
        if r["status"] == "valid":
            parts.append(f"v{v}: valid prior version"
                         + (" (opened with the document's password)"
                            if r["needs_password"] else ""))
        elif r["status"] == "encrypted":
            parts.append(f"v{v}: password-protected prior version")
        elif r["status"] == "linearization":
            parts.append(f"%%EOF {v}: not a prior version (linearized file, "
                         f"first-page section)")
        else:
            parts.append(f"%%EOF {v}: not a usable prior version ({r['reason']})")
    return "; ".join(parts)
