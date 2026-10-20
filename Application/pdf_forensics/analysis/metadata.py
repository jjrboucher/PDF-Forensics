"""
PDF and image metadata extraction.
"""

import os

try:
    from PIL import Image, ExifTags
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


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
        with doc_pk.open_metadata() as xmp:
            for k, v in xmp.items():
                key = str(k)
                if isinstance(v, (list, tuple)):
                    value = ", ".join(str(x) for x in v)
                else:
                    value = str(v)
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

    import io
    try:
        img = Image.open(io.BytesIO(image_bytes))
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
