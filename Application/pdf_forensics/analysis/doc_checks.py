"""
Document-level forensic checks.

These detectors operate on the document as a whole (metadata, signature
structure, file integrity, cross-image EXIF consistency) rather than on
any single page or image. Their findings feed the document-level risk
dimension. Where a determination cannot be made accurately, the finding
says so explicitly instead of guessing.
"""

import os
import re
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------
# PDF / XMP date parsing
# ---------------------------------------------------------------------

_PDF_DATE_RE = re.compile(
    r"^D?:?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?"
    r"(?:([Zz])|([+\-])(\d{2})'?(\d{2})?'?)?")

_ISO_DATE_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?"
    r"(?:([Zz])|([+\-])(\d{2}):?(\d{2}))?)?")


def parse_pdf_date(value):
    """
    Parse a PDF date string (D:YYYYMMDDHHmmSSOHH'mm') or an XMP/ISO-8601
    date string into a timezone-aware datetime.

    Returns None when the string cannot be parsed — callers must treat
    None as 'indeterminate' and refrain from drawing comparisons.
    Dates with no timezone designator are treated as UTC for comparison
    purposes only; this assumption is stated in any finding built from
    them.
    """
    if not value:
        return None
    s = str(value).strip()

    m = _ISO_DATE_RE.match(s)
    if m and "-" in s[:8]:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh = int(m.group(4) or 0)
        mi = int(m.group(5) or 0)
        ss = int(m.group(6) or 0)
        tz = timezone.utc
        if m.group(8):
            sign = -1 if m.group(8) == "-" else 1
            tz = timezone(sign * timedelta(hours=int(m.group(9)),
                                           minutes=int(m.group(10) or 0)))
        try:
            return datetime(y, mo, d, hh, mi, ss, tzinfo=tz)
        except ValueError:
            return None

    m = _PDF_DATE_RE.match(s)
    if not m or not m.group(1):
        return None
    try:
        y = int(m.group(1))
        mo = int(m.group(2) or 1)
        d = int(m.group(3) or 1)
        hh = int(m.group(4) or 0)
        mi = int(m.group(5) or 0)
        ss = int(m.group(6) or 0)
        tz = timezone.utc
        if m.group(8):
            sign = -1 if m.group(8) == "-" else 1
            tz = timezone(sign * timedelta(hours=int(m.group(9)),
                                           minutes=int(m.group(10) or 0)))
        return datetime(y, mo, d, hh, mi, ss, tzinfo=tz)
    except ValueError:
        return None


def _has_explicit_tz(value):
    s = str(value or "").strip()
    return bool(re.search(r"([Zz]|[+\-]\d{2}[':]?\d{0,2}'?)\s*$", s))


# ---------------------------------------------------------------------
# Metadata consistency (guide §4.1, §4.2.1, §4.2.2, §4.3)
# ---------------------------------------------------------------------

def _meta_lookup(pdf_metadata, source, key_suffix):
    """Find a metadata value by source and case-insensitive key suffix.
    Returns the first matching value or None."""
    suffix = key_suffix.lower()
    for (src, key, value) in pdf_metadata:
        if src == source and str(key).lower().endswith(suffix):
            if value and str(value).strip():
                return str(value).strip()
    return None


def _norm_text(v):
    """Compare text fields loosely: case, whitespace and list separators
    (Info "A; B" vs XMP list "A, B") are not differences."""
    t = re.sub(r"[;,]", ",", str(v or "")).lower()
    return ",".join(x.strip() for x in t.split(",") if x.strip())


def check_metadata_consistency(pdf_metadata):
    """
    Automated cross-checks over the extracted (source, key, value)
    metadata tuples:

      METADATA_DATE_ANOMALY — Info-dictionary ModDate earlier than
        CreationDate. Structurally impossible in a truthful document.
      METADATA_MISMATCH     — Info dictionary and XMP stream disagree on
        Producer, CreationDate, or ModDate. Legitimate producers keep
        both in sync; manual editing of one typically leaves the other.
      VERSION_MISMATCH      — header %PDF-N.M differs from the Document
        Catalog /Version entry.
      XMP_ID_ANOMALY        — xmpMM:DocumentID equals xmpMM:InstanceID.

    Comparisons are only made when both operands exist and are
    parseable; nothing is inferred from absent or unparseable values.
    Returns a list of document-level finding dicts.
    """
    findings = []

    info_created = _meta_lookup(pdf_metadata, "info_dict", "creationdate")
    info_mod = _meta_lookup(pdf_metadata, "info_dict", "moddate")
    info_producer = _meta_lookup(pdf_metadata, "info_dict", "producer")

    xmp_created = _meta_lookup(pdf_metadata, "xmp", "createdate")
    xmp_mod = _meta_lookup(pdf_metadata, "xmp", "modifydate")
    xmp_producer = _meta_lookup(pdf_metadata, "xmp", "producer")

    # --- ModDate < CreationDate ---
    dt_created = parse_pdf_date(info_created)
    dt_mod = parse_pdf_date(info_mod)
    if dt_created and dt_mod and dt_mod < dt_created:
        tz_note = ""
        if not (_has_explicit_tz(info_created) and _has_explicit_tz(info_mod)):
            tz_note = ("\n    Note: one or both dates carry no timezone "
                       "designator and were compared as UTC; if the "
                       "true offsets differ, the ordering could change. "
                       "Verify the raw values.")
        findings.append({
            "image": None,
            "type": "METADATA_DATE_ANOMALY",
            "detail": (
                "Document-level finding: Info dictionary ModDate "
                "precedes CreationDate — structurally impossible for a "
                "truthfully-dated document and a strong indicator of "
                "manual metadata editing.\n"
                f"    CreationDate: {info_created}\n"
                f"    ModDate:      {info_mod}" + tz_note
            ),
        })

    # --- Info vs XMP disagreements ---
    def _cmp_dates(label, a_raw, b_raw):
        a, b = parse_pdf_date(a_raw), parse_pdf_date(b_raw)
        if a is None or b is None:
            return  # indeterminate — do not fabricate a comparison
        if abs((a - b).total_seconds()) > 60:
            findings.append({
                "image": None,
                "type": "METADATA_MISMATCH",
                "detail": (
                    f"Document-level finding: Info dictionary and XMP "
                    f"stream disagree on {label}. Legitimate producers "
                    f"write both in sync; manual editing of one source "
                    f"frequently leaves the other unchanged.\n"
                    f"    Info dictionary: {a_raw}\n"
                    f"    XMP stream:      {b_raw}"
                ),
            })

    # Text fields that the Info dictionary and XMP both carry. ISO 32000-2
    # (14.3.3) pairs them: Creator ~ xmp:CreatorTool, Author ~ dc:creator,
    # Title ~ dc:title, Subject ~ dc:description, Keywords ~ pdf:Keywords,
    # Producer ~ pdf:Producer. Legitimate producers write both in step; a
    # metadata editor that updates one (or maps a field onto the wrong
    # counterpart, as ExifTool does when -Creator writes both Info Creator
    # and dc:creator) leaves them disagreeing.
    pairs = []
    for label, info_suffix, xmp_suffix in (
            ("Producer", "producer", "}producer"),
            ("Creator (creating application)", "creator", "creatortool"),
            ("Author", "author", "elements/1.1/}creator"),
            ("Title", "title", "elements/1.1/}title"),
            ("Subject", "subject", "elements/1.1/}description"),
            ("Keywords", "keywords", "}keywords")):
        iv = _meta_lookup(pdf_metadata, "info_dict", info_suffix)
        xv = _meta_lookup(pdf_metadata, "xmp", xmp_suffix)
        if iv and xv and _norm_text(iv) != _norm_text(xv):
            pairs.append((label, iv, xv))
    # One finding per disagreeing field, as for the date fields: each
    # scores separately (Technical Reference Guide, risk weights).
    for lbl, iv, xv in pairs:
        findings.append({
            "image": None,
            "type": "METADATA_MISMATCH",
            "detail": (
                f"Document-level finding: Info dictionary and XMP stream "
                f"disagree on {lbl}. Legitimate producers write both in "
                f"sync; editing one source with a metadata tool frequently "
                f"leaves the other unchanged or maps a field onto the wrong "
                f"counterpart.\n"
                f"    Info dictionary: {iv}\n"
                f"    XMP stream:      {xv}"
            ),
        })
    _cmp_dates("CreationDate", info_created, xmp_created)
    _cmp_dates("ModDate", info_mod, xmp_mod)

    # --- Header version vs Catalog /Version ---
    header_v = _meta_lookup(pdf_metadata, "catalog", "pdf_version_header")
    catalog_v = None
    for (src, key, value) in pdf_metadata:
        if src == "catalog" and str(key) == "Version":
            catalog_v = str(value).strip()
            break
    if header_v and catalog_v:
        hm = re.search(r"(\d+\.\d+)", header_v)
        cm = re.search(r"(\d+\.\d+)", catalog_v)
        if hm and cm and hm.group(1) != cm.group(1):
            findings.append({
                "image": None,
                "type": "VERSION_MISMATCH",
                "detail": (
                    "Document-level finding: the PDF header version and "
                    "the Document Catalog /Version entry differ.\n"
                    f"    Header:  {hm.group(1)}\n"
                    f"    Catalog: {cm.group(1)}\n"
                    "    A Catalog /Version above the header is a "
                    "legitimate override mechanism, but its presence "
                    "means a tool modified the document without "
                    "rewriting the header — corroborate with the "
                    "%%EOF analysis."
                ),
            })

    # --- DocumentID == InstanceID ---
    doc_id = _meta_lookup(pdf_metadata, "xmp", "documentid")
    inst_id = _meta_lookup(pdf_metadata, "xmp", "instanceid")
    if doc_id and inst_id and doc_id == inst_id:
        findings.append({
            "image": None,
            "type": "XMP_ID_ANOMALY",
            "detail": (
                "Document-level finding: xmpMM:DocumentID equals "
                "xmpMM:InstanceID. The DocumentID is assigned once at "
                "creation and the InstanceID updated on each save, so "
                "identical values suggest the document was created as a "
                "direct copy of another document or that the metadata "
                "was reconstructed.\n"
                f"    Value: {doc_id}"
            ),
        })

    return findings


# ---------------------------------------------------------------------
# Digital signature coverage (structural only — no PKI validation)
# ---------------------------------------------------------------------

def _iter_acroform_fields(doc_pk):
    """Yield all AcroForm field dictionaries, descending /Kids."""
    try:
        fields = doc_pk.Root["/AcroForm"]["/Fields"]
    except Exception:
        return
    stack = list(fields)
    seen = 0
    while stack and seen < 10000:
        seen += 1
        fld = stack.pop()
        try:
            kids = fld.get("/Kids")
            if kids is not None:
                stack.extend(list(kids))
        except Exception:
            pass
        yield fld


def check_signature_coverage(doc_pk, pdf_path):
    """
    Structural check of digital signature ByteRange coverage. This does
    NOT validate the signature cryptographically (out of scope); it
    checks a purely structural property: a signature's /ByteRange
    records exactly which file bytes it covers, so if the file extends
    beyond the coverage of the LAST signature, bytes were appended
    (incrementally saved) after signing.

    Emits:
      SIGNED_THEN_MODIFIED — file content extends beyond the last
        signature's ByteRange coverage.
      STRUCTURAL_WARNING   — a signature exists but its ByteRange could
        not be evaluated (explicitly indeterminate).

    Post-signing updates can be legitimate (a second signature, form
    fill-in permitted by DocMDP); the finding states what was appended
    and directs the examiner to determine what changed.
    """
    findings = []
    try:
        file_size = os.path.getsize(pdf_path)
    except Exception:
        return findings

    coverage_ends = []
    indeterminate = 0
    sig_count = 0

    for fld in _iter_acroform_fields(doc_pk):
        try:
            ft = str(fld.get("/FT", ""))
        except Exception:
            continue
        if ft != "/Sig":
            continue
        try:
            v = fld.get("/V")
            if v is None:
                continue   # unsigned signature field — nothing to check
            sig_count += 1
            br = v.get("/ByteRange")
            vals = [int(x) for x in br]
            if len(vals) != 4 or any(x < 0 for x in vals):
                raise ValueError("malformed ByteRange")
            coverage_ends.append(vals[2] + vals[3])
        except Exception:
            indeterminate += 1

    if indeterminate:
        findings.append({
            "image": None,
            "type": "STRUCTURAL_WARNING",
            "detail": (
                f"Document-level finding: {indeterminate} digital "
                f"signature(s) are present whose /ByteRange could not "
                f"be read or was malformed. Whether the file was "
                f"modified after signing is INDETERMINATE by automated "
                f"analysis for these signatures — verify the signature "
                f"dictionaries manually (e.g. qpdf --show-object)."
            ),
        })

    if not coverage_ends:
        return findings

    last_covered = max(coverage_ends)
    # A signed file's last signature should cover to end-of-file. Allow
    # a small slack for a trailing newline after %%EOF.
    SLACK = 16
    if file_size > last_covered + SLACK:
        appended = file_size - last_covered
        findings.append({
            "image": None,
            "type": "SIGNED_THEN_MODIFIED",
            "detail": (
                "Document-level finding: the file extends beyond the "
                "byte range covered by the last digital signature — "
                f"{appended} byte(s) were appended after signing.\n"
                f"    Signatures found:        {sig_count}\n"
                f"    Last signature covers to byte {last_covered}\n"
                f"    Current file size:       {file_size} bytes\n"
                "    The signed revision does not cover the current "
                "file content. Post-signing updates can be legitimate "
                "(e.g. an additional signature or permitted form "
                "fill-in); extract the prior version at the signature "
                "boundary and compare to determine what changed. This "
                "check is structural only — it does not validate the "
                "signature cryptographically."
            ),
        })

    return findings


# ---------------------------------------------------------------------
# Structural integrity (qpdf/pikepdf check)
# ---------------------------------------------------------------------

def check_structural_integrity(doc_pk):
    """
    Surface structural warnings from pikepdf/qpdf's file check (stream
    /Length discrepancies, xref damage, recovered objects, and similar
    indicators of post-creation manipulation or corruption).

    Aggregated into a single STRUCTURAL_WARNING finding listing up to
    ten warnings. Absence of warnings is NOT reported (a clean check is
    not evidence of an unmodified file).
    """
    try:
        problems = doc_pk.check()
    except Exception:
        return []   # check unavailable or failed — nothing reliable to say
    if not problems:
        return []

    shown = [str(p).strip() for p in problems[:10] if str(p).strip()]
    more = len(problems) - len(shown)
    detail = (
        "Document-level finding: the qpdf structural check reported "
        f"{len(problems)} warning(s) for this file. Structural "
        "irregularities (e.g. stream /Length discrepancies, damaged or "
        "rebuilt cross-reference data) can indicate post-creation "
        "manipulation, but also occur in files written by "
        "non-conformant producers — corroborate before relying on "
        "this.\n"
        + "\n".join(f"    - {p}" for p in shown)
    )
    if more > 0:
        detail += f"\n    ... and {more} more (see session log)."
    return [{
        "image": None,
        "type": "STRUCTURAL_WARNING",
        "detail": detail,
        "_all_warnings": [str(p) for p in problems],
    }]


# ---------------------------------------------------------------------
# Mixed-camera EXIF indicator (guide §8.3)
# ---------------------------------------------------------------------

def extract_camera_info(image_bytes, ext):
    """
    Read only the EXIF Make (271) and Model (272) tags from JPEG/TIFF
    image bytes. Returns (make, model) with at least one non-empty
    component, or None. PNG/JBIG2/CCITT/JPX streams carry no EXIF in
    their native format and return None.
    """
    if not image_bytes or str(ext).lower() not in (
            "jpg", "jpeg", "jfif", "tif", "tiff"):
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    import io
    try:
        img = Image.open(io.BytesIO(image_bytes))
        exif = img.getexif()
        if not exif:
            return None
        make = str(exif.get(271, "") or "").strip()
        model = str(exif.get(272, "") or "").strip()
        if not make and not model:
            return None
        return (make, model)
    except Exception:
        return None


def check_mixed_cameras(camera_by_label):
    """
    Flag documents whose images carry EXIF Make/Model values from two
    or more distinct capture devices. In a legitimately scanned
    document all pages bear the same device; heterogeneous devices
    indicate content assembled from multiple sources.

    camera_by_label: {image_label: (make, model)} for images with EXIF.
    Images without EXIF are not counted either way; the finding states
    how many images could be assessed.
    """
    if not camera_by_label:
        return []
    devices = {}
    for label, (make, model) in camera_by_label.items():
        key = (make.strip().lower(), model.strip().lower())
        devices.setdefault(key, {"display": f"{make} {model}".strip(),
                                 "labels": []})
        devices[key]["labels"].append(label)
    if len(devices) < 2:
        return []

    lines = []
    for dev in devices.values():
        labels = dev["labels"]
        shown = ", ".join(sorted(labels)[:5])
        if len(labels) > 5:
            shown += f", ... ({len(labels)} total)"
        lines.append(f"    - {dev['display']}: {shown}")
    return [{
        "image": None,
        "type": "MIXED_CAMERA",
        "detail": (
            "Document-level finding: images in this document carry "
            f"EXIF Make/Model values from {len(devices)} distinct "
            "capture devices. A legitimately scanned document bears a "
            "single device; mixed devices indicate content assembled "
            "from multiple sources (which may itself be legitimate — "
            "e.g. an inserted photograph in a scanned contract).\n"
            + "\n".join(lines) + "\n"
            f"    Images with readable EXIF device data: "
            f"{len(camera_by_label)}. Images without EXIF are not "
            f"counted either way."
        ),
    }]


# ---------------------------------------------------------------------
# Unapplied redaction annotations (guide §2.5, /Redact)
# ---------------------------------------------------------------------

## ---------------------------------------------------------------------
## Version anachronism (features exceeding the declared PDF version)
## ---------------------------------------------------------------------

# Publication year of each PDF version, used to turn a required-feature
# floor into an earliest-possible date for the temporal check.
PDF_VERSION_YEAR = {
    (1, 0): 1993, (1, 1): 1996, (1, 2): 1996, (1, 3): 2000,
    (1, 4): 2001, (1, 5): 2003, (1, 6): 2004, (1, 7): 2006,
    (2, 0): 2017,
}

# Some features ride on a base version through an extension published
# later than that base version, so their earliest-possible YEAR is later
# than the base version's publication year. The version floor is left
# unchanged (the feature is valid at that base version); only the
# temporal year differs. Keyed by feature name (as it appears below).
_FEATURE_YEAR_OVERRIDE = {
    # AES-256 shipped in Acrobat 9 / "Extension Level 3" (2008) on top of
    # PDF 1.7 (2006), and was only folded into the core standard in PDF
    # 2.0 (2017). Its true earliest date is therefore 2008, not 2006.
    "AES-256 encryption (/AESV3)": 2008,
}


def _feature_year(min_version, name):
    """Earliest-possible year a feature could have existed: an explicit
    per-feature override when the feature post-dates its base version
    (e.g. AES-256), otherwise the base version's publication year."""
    if name in _FEATURE_YEAR_OVERRIDE:
        return _FEATURE_YEAR_OVERRIDE[name]
    return PDF_VERSION_YEAR.get(min_version, 0)


def _parse_pdf_version(value):
    """Parse a version string ('1.7', 'PDF 1.5', '%PDF-1.4', '/1.6') into
    a (major, minor) tuple, or None if it cannot be parsed. Multi-digit
    parts are read whole ('1.10' is (1, 10), not (1, 1))."""
    if value is None:
        return None
    m = re.search(r"(\d+)\.(\d+)", str(value))
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


# The PDF versions that exist: 1.0-1.7 (Adobe, ISO 32000-1 for 1.7) and
# 2.0 (ISO 32000-2). Anything else (0.3, 1.8, 1.10, 3.0, ...) has never
# been published, so no conforming software writes it.
VALID_PDF_VERSIONS = frozenset([(1, n) for n in range(8)] + [(2, 0)])


def _version_valid(v):
    return v in VALID_PDF_VERSIONS


# A declared version must be written as one digit, a dot and one digit
# (ISO 32000: "1.N"; "2.0"). "1.05", "1.4.0" or "01.4" are not valid ways
# to write a version even where the numbers could be read as one, and a
# lenient reading would let them pass (ExifTool accepts "1.05" and writes
# it to XMP; read as 1.5 it masked a genuine 1.5 anachronism).
_CANON_VERSION_RE = re.compile(r"^\s*/?(\d)\.(\d)\s*$")


def _declared_ok(raw):
    """True only for a canonically written, published PDF version."""
    if raw is None:
        return False
    m = _CANON_VERSION_RE.match(str(raw))
    return bool(m) and (int(m.group(1)), int(m.group(2))) in VALID_PDF_VERSIONS


def _revision_declarations(data, password=None):
    """Version declarations in each revision of the file, oldest first:
    a list of (label, end_offset, catalog_version, xmp_version), where
    the versions are raw strings or None. Only revisions that open as a
    PDF (valid or encrypted prior versions, and the current file) are
    included. The header is shared by every revision (it is the first
    bytes of the file), so it is not listed per revision."""
    import io
    try:
        import pikepdf
        from pdf_forensics.analysis.metadata import classify_prior_versions
    except Exception:
        return []
    ends = []
    try:
        for c in classify_prior_versions(data, password=password):
            if c.get("status") in ("valid", "encrypted"):
                ends.append((f"revision {c['version_number']}", c["end"]))
    except Exception:
        pass
    ends.append(("current", len(data)))
    out = []
    for label, end in ends:
        try:
            kw = {"password": password} if password else {}
            with pikepdf.open(io.BytesIO(data[:end]), **kw) as pdf:
                cv = pdf.Root.get("/Version")
                cv = str(cv).lstrip("/") if cv is not None else None
                try:
                    xv = pdf.open_metadata().get("pdf:PDFVersion")
                    xv = str(xv).strip() if xv is not None and str(xv).strip() else None
                except Exception:
                    xv = None
            out.append((label, end, cv, xv))
        except Exception:
            continue
    return out


def _ver_str(v):
    return f"{v[0]}.{v[1]}" if v else "unknown"


# Raw-byte feature signatures. Each: (compiled regex, min_version,
# feature name, reliability, basis).
#
# Two sub-classes with different detection guarantees:
#   * Storage / cross-reference / encryption markers (/ObjStm, /XRef,
#     /AESV2, /AESV3) live in structures that MUST be plaintext -- the
#     xref stream is how the file is navigated, and the /Encrypt dict
#     must be readable to decrypt anything -- so a raw scan sees them
#     reliably with no false negatives.
#   * Image filter names (/JBIG2Decode, /JPXDecode) are names in an
#     image XObject dictionary. The stream DATA cannot live in a
#     compressed object stream, but the XObject DICTIONARY can, in
#     which case the filter name is itself compressed and a raw scan
#     will not see it. Detection is therefore best-effort: a positive
#     match is definitive (the name only appears when the filter is
#     used), but the scan may UNDER-report (never over-report) when the
#     dictionary sits inside an /ObjStm. This is a conservative,
#     safe-direction limitation.
_RAW_FEATURE_SIGS = [
    (re.compile(rb"/Type\s*/ObjStm"), (1, 5),
     "Compressed object streams (/ObjStm)", "high",
     "Objects are packed into 1.5 compressed object streams; the file "
     "cannot be parsed without supporting them."),
    (re.compile(rb"/Type\s*/XRef"), (1, 5),
     "Cross-reference streams (/Type /XRef)", "high",
     "The file is navigated through a 1.5 cross-reference stream rather "
     "than a classic xref table."),
    (re.compile(rb"/JBIG2Decode"), (1, 4),
     "JBIG2 image compression", "high",
     "A JBIG2-compressed image is present; the filter was introduced in "
     "1.4 and cannot be decoded by an earlier reader."),
    (re.compile(rb"/JPXDecode"), (1, 5),
     "JPEG2000 image compression (JPXDecode)", "high",
     "A JPEG2000-compressed image is present; the filter was introduced "
     "in 1.5."),
    (re.compile(rb"/AESV3"), (1, 7),
     "AES-256 encryption (/AESV3)", "high",
     "The file is encrypted with AES-256 (PDF 1.7 Extension Level 3, "
     "standardised in 2.0); it cannot be decrypted by an earlier "
     "scheme."),
    (re.compile(rb"/AESV2"), (1, 6),
     "AES-128 encryption (/AESV2)", "high",
     "The file is encrypted with AES-128 crypt filters, introduced in "
     "1.6."),
]


def _scan_catalog_features(doc_pk):
    """Catalog-level features whose presence requires a minimum version.
    Returns a list of (min_version, name, reliability, basis)."""
    found = []
    try:
        root = doc_pk.Root
    except Exception:
        return found
    try:
        if root.get("/OCProperties") is not None:
            found.append(((1, 5), "Optional content / layers (/OCProperties)",
                          "high",
                          "The document defines optional-content groups "
                          "(layers), a 1.5 feature."))
    except Exception:
        pass
    try:
        if root.get("/Collection") is not None:
            found.append(((1, 7), "Portfolio / collection (/Collection)",
                          "high",
                          "The document is a 1.7 portfolio (collection)."))
    except Exception:
        pass
    try:
        acro = root.get("/AcroForm")
        if acro is not None and acro.get("/XFA") is not None:
            found.append(((1, 5), "XFA forms (/AcroForm /XFA)", "medium",
                          "The form uses XFA, introduced in 1.5."))
    except Exception:
        pass
    return found


def check_version_anachronism(doc_pk, pdf_path, pdf_metadata, password=None,
                              history=True):
    """
    Detect PDF features that require a newer version than the file
    declares. The declared version can be edited trivially (the header
    string, the Catalog /Version, XMP pdf:PDFVersion); the structural
    features actually present cannot be lowered without re-authoring the
    file, so they establish a hard minimum version -- and, via each
    feature's publication year, an earliest-possible date.

    Comparison is conservative: the effective floor is compared against
    the HIGHEST version the file declares anywhere (header, Catalog
    /Version, XMP), so a finding fires only when the structure exceeds
    every declared value. A single VERSION_ANACHRONISM finding is
    emitted, listing the declared versions, the effective floor, and the
    feature(s) forcing it with their reliability, plus an explicit
    temporal contradiction when the claimed creation date predates the
    feature's introduction.

    Note: this is distinct from VERSION_MISMATCH (header vs Catalog).
    """
    # --- declared versions ---
    header_v = None
    try:
        with open(pdf_path, "rb") as f:
            head = f.read(1024)
        m = re.match(rb"%PDF-(\d+)\.(\d+)", head)
        if m:
            header_v = (int(m.group(1)), int(m.group(2)))
        header_raw = (re.match(rb"%PDF-([^\s%]{0,12})", head).group(1)
                      .decode("latin-1") if head.startswith(b"%PDF-")
                      else None)
    except Exception:
        header_v = None
        header_raw = None

    catalog_v = None
    try:
        cv = doc_pk.Root.get("/Version")
        catalog_v = _parse_pdf_version(str(cv)) if cv is not None else None
    except Exception:
        catalog_v = None

    xmp_raw = _meta_lookup(pdf_metadata, "xmp", "pdfversion")
    if xmp_raw is None:
        try:
            xr = doc_pk.open_metadata().get("pdf:PDFVersion")
            xmp_raw = str(xr).strip() if xr is not None and str(xr).strip() else None
        except Exception:
            xmp_raw = None
    xmp_v = _parse_pdf_version(xmp_raw)
    try:
        cv_obj = doc_pk.Root.get("/Version")
        catalog_raw = str(cv_obj).lstrip("/") if cv_obj is not None else None
    except Exception:
        catalog_raw = None

    results = []

    # --- VERSION_INVALID: a declared version that does not exist ---
    invalid = []
    if header_raw is not None and not _declared_ok(header_raw):
        invalid.append(f"header %PDF-{header_raw}")
    if catalog_raw is not None and not _declared_ok(catalog_raw):
        invalid.append(f"Catalog /Version {catalog_raw}")
    if xmp_raw is not None and not _declared_ok(xmp_raw):
        invalid.append(f"XMP pdf:PDFVersion {xmp_raw}")
    if invalid:
        results.append({
            "image": None,
            "type": "VERSION_INVALID",
            "detail": (
                "Document-level finding: the file declares a PDF version "
                "that does not exist.\n"
                f"    Invalid declaration(s): {'; '.join(invalid)}\n"
                "    The published PDF versions are 1.0 to 1.7 and 2.0. No "
                "conforming software writes any other value, so an "
                "invalid version is a strong indicator that the "
                "declaration was edited by hand (for example with a hex "
                "editor or a metadata tool). Invalid values are excluded "
                "when comparing the declared version against the "
                "features present (see any Version Anachronism finding)."
            ),
        })

    # --- VERSION_CONFLICT: XMP disagrees, or a declaration changed ---
    results.extend(_version_conflicts(
        doc_pk, pdf_path, header_v, catalog_v, catalog_raw, xmp_v, xmp_raw,
        password=password, history=history, header_raw=header_raw))

    # Only real versions take part in the anachronism comparison, so an
    # invalid value (e.g. a fake 9.9) cannot mask a genuine gap.
    declared_candidates = [v for raw, v in ((header_raw, header_v),
                                            (catalog_raw, catalog_v),
                                            (xmp_raw, xmp_v))
                           if v is not None and _declared_ok(raw)]
    if not declared_candidates:
        # No valid declaration to compare against; do not guess.
        return results
    declared = max(declared_candidates)

    # --- detected features ---
    features = []  # (min_version, name, reliability, basis)
    try:
        with open(pdf_path, "rb") as f:
            data = f.read()
        for rx, minv, name, rel, basis in _RAW_FEATURE_SIGS:
            if rx.search(data):
                features.append((minv, name, rel, basis))
    except Exception:
        pass
    features.extend(_scan_catalog_features(doc_pk))

    # Keep only features that EXCEED the declared version.
    exceeding = [(minv, name, rel, basis)
                 for (minv, name, rel, basis) in features
                 if minv > declared]
    if not exceeding:
        return results

    effective = max(minv for (minv, _, _, _) in exceeding)
    # Order the evidence strongest/highest-version first.
    rel_rank = {"high": 0, "medium": 1, "low": 2}
    exceeding.sort(key=lambda t: (-( t[0][0]*10 + t[0][1]),
                                  rel_rank.get(t[2], 3)))

    # --- temporal contradiction ---
    created_raw = (_meta_lookup(pdf_metadata, "info_dict", "creationdate")
                   or _meta_lookup(pdf_metadata, "xmp", "createdate"))
    created = parse_pdf_date(created_raw)
    temporal_note = ""
    feature_year = max(
        (_feature_year(minv, name) for (minv, name, _, _) in exceeding),
        default=0)
    if created is not None and feature_year and created.year < feature_year:
        temporal_note = (
            f"\n    TEMPORAL CONTRADICTION: the document's declared "
            f"creation date ({created_raw}) is {feature_year - created.year} "
            f"year(s) before the required feature(s) could have existed "
            f"(~{feature_year}; PDF {_ver_str(effective)}), so the content "
            f"could not have been produced on that date regardless of the "
            f"version string. This is independent of the version "
            f"declaration and is a strong indicator that the creation "
            f"date, the version, or both were altered.")

    # --- compose ---
    decl_lines = [
        f"header {_ver_str(header_v)}" if header_v else "header (unreadable)",
        f"Catalog /Version {_ver_str(catalog_v)}" if catalog_v
        else "no Catalog /Version",
        f"XMP pdf:PDFVersion {_ver_str(xmp_v)}" if xmp_v
        else "no XMP version",
    ]
    feat_lines = []
    for (minv, name, rel, basis) in exceeding:
        fy = _feature_year(minv, name)
        feat_lines.append(
            f"    - requires \u2265 {_ver_str(minv)} "
            f"(~{fy or '?'}, {rel} reliability): "
            f"{name}. {basis}")

    detail = (
        "Document-level finding: the file uses features that require a "
        f"newer PDF version ({_ver_str(effective)}) than it declares "
        f"({_ver_str(declared)}).\n"
        f"    Declared: {'; '.join(decl_lines)}\n"
        f"    Effective minimum from structure: {_ver_str(effective)}\n"
        "    Features exceeding the declared version:\n"
        + "\n".join(feat_lines)
        + temporal_note
        + "\n    Caveat: a version gap on its own is not proof of "
        "tampering. Some producers emit a fixed or conservative version "
        "string (for example a tool hard-coded to an older header that "
        "was never updated when its engine was upgraded) while writing "
        "newer structures, so a small gap with no temporal contradiction "
        "is common in benign files and should be treated as "
        "requires-review. The finding is strongest when the gap is large, "
        "the version was lowered in more than one place, or the claimed "
        "creation date predates the required feature (see above)."
    )

    results.append({
        "image": None,
        "type": "VERSION_ANACHRONISM",
        "detail": detail,
        "_temporal": bool(temporal_note),
    })
    return results


def _version_conflicts(doc_pk, pdf_path, header_v, catalog_v, catalog_raw,
                       xmp_v, xmp_raw, password=None, history=True,
                       header_raw=None):
    """VERSION_CONFLICT findings (at most one, listing every reason):

    * the XMP pdf:PDFVersion disagrees with the version in effect (the
      later of the header and the Catalog /Version, per ISO 32000);
    * a version declaration (XMP pdf:PDFVersion or Catalog /Version) was
      added, changed or removed by a later incremental update. Metadata
      tools such as ExifTool append a new revision rather than editing
      the original bytes, so the header keeps its original value and the
      earlier declarations remain in the file.
    """
    reasons = []
    header_ok = header_raw is None or _declared_ok(header_raw)
    effective = max([v for v, ok in ((header_v, header_ok),
                                     (catalog_v, _declared_ok(catalog_raw)))
                     if v is not None and ok], default=None)
    # An invalid XMP value is reported by VERSION_INVALID; comparing it
    # here as well would count the same edit twice.
    if (xmp_v is not None and _declared_ok(xmp_raw)
            and effective is not None and xmp_v != effective):
        reasons.append(
            f"The XMP pdf:PDFVersion ({xmp_raw}) disagrees with the version "
            f"in effect ({_ver_str(effective)}: the later of the header "
            f"{_ver_str(header_v) if header_v else '(none)'} and the "
            f"Catalog /Version {catalog_raw or '(none)'}). Producers write "
            f"these in agreement; a mismatch means one was edited "
            f"separately.")

    hist = []
    if history:
        try:
            with open(pdf_path, "rb") as f:
                data = f.read()
            hist = _revision_declarations(data, password=password)
        except Exception:
            hist = []
    changes = []
    for i in range(1, len(hist)):
        prev, cur = hist[i - 1], hist[i]
        for idx, name in ((3, "XMP pdf:PDFVersion"), (2, "Catalog /Version")):
            a, b = prev[idx], cur[idx]
            if a == b:
                continue
            if idx == 2:
                # Raising the Catalog /Version in an update is the
                # standard way to upgrade a file (reported separately as
                # VERSION_MISMATCH); only a lowered, removed or invalid
                # Catalog version counts here.
                pa, pb = _parse_pdf_version(a), _parse_pdf_version(b)
                if (b is not None and _declared_ok(b)
                        and (a is None or (pa is not None and pb > pa))):
                    continue
            else:
                # An XMP pdf:PDFVersion written by an update is consistent
                # when it equals the version in effect for that revision
                # (the later of the header and that revision's Catalog
                # /Version) and does not lower an earlier value: that is
                # what a genuine upgrade or re-save writes.
                pa, pb = _parse_pdf_version(a), _parse_pdf_version(b)
                cat_v = _parse_pdf_version(cur[2])
                eff_rev = max([v for v, ok in ((header_v, header_ok),
                                               (cat_v, _declared_ok(cur[2])))
                               if v is not None and ok],
                              default=None)
                if (b is not None and _declared_ok(b)
                        and eff_rev is not None and pb == eff_rev
                        and (a is None or (pa is not None and pb >= pa))):
                    continue
            what = ("added" if a is None else "removed" if b is None
                    else "changed")
            changes.append(
                f"{name} {what} in {cur[0]} (update ending at byte "
                f"{cur[1]:,}): {a or '(absent)'} \u2192 {b or '(absent)'}")
    if changes:
        reasons.append(
            "A version declaration was altered by a later incremental "
            "update:\n      - " + "\n      - ".join(changes))

    if not reasons:
        return []
    table = ""
    if len(hist) > 1:
        table = ("\n    Declarations by revision (oldest first): "
                 + "; ".join(f"{h[0]}: Catalog {h[2] or '-'}, XMP {h[3] or '-'}"
                             for h in hist))
    return [{
        "image": None,
        "type": "VERSION_CONFLICT",
        "detail": (
            "Document-level finding: the file's PDF version declarations "
            "disagree or were changed after the file was created.\n"
            f"    Header: {_ver_str(header_v) if header_v else '(unreadable)'}"
            f"; Catalog /Version: {catalog_raw or '(none)'}"
            f"; XMP pdf:PDFVersion: {xmp_raw or '(none)'}\n    "
            + "\n    ".join(reasons)
            + table
            + "\n    The header is the first bytes of the file, shared by "
            "every revision, so a metadata tool cannot change it with an "
            "incremental update; an altered declaration in a later "
            "revision alongside an unchanged header is a typical trace of "
            "an attempt to misstate the version. A Catalog /Version raised "
            "above the header by a later update is also the legitimate "
            "way to upgrade a file's version; corroborate with the "
            "Incremental Updates report and the producer of that update."
        ),
    }]


def check_unapplied_redactions(page_pk, page_num):
    """
    Detect /Redact annotations. A redaction annotation only MARKS
    content for removal; until the redaction is applied, the covered
    content remains fully present and recoverable in the file. The
    presence of an unapplied redaction is therefore both a strong
    signal of intent to conceal and a recoverable-content lead.

    Page-level findings (one per redaction annotation).
    """
    findings = []
    try:
        annots = page_pk.get("/Annots")
        if annots is None:
            return findings
        annot_list = list(annots)
    except Exception:
        return findings

    for annot in annot_list:
        try:
            resolved = annot
            subtype = str(resolved.get("/Subtype", ""))
            if subtype != "/Redact":
                continue
            rect_raw = resolved.get("/Rect")
            rect_str = ""
            if rect_raw is not None:
                try:
                    r = [float(x) for x in rect_raw]
                    rect_str = (f"({r[0]:.1f}, {r[1]:.1f}) to "
                                f"({r[2]:.1f}, {r[3]:.1f})")
                except Exception:
                    rect_str = str(rect_raw)
            try:
                objnum, objgen = annot.objgen
            except Exception:
                objnum, objgen = None, None
            locator = (f"annotation object {objnum} {objgen} R"
                       if objnum is not None else "annotation object")
            findings.append({
                "image": None,
                "type": "REDACT_UNAPPLIED",
                "detail": (
                    f"Unapplied redaction annotation on page "
                    f"{page_num}"
                    + (f" at {rect_str}" if rect_str else "") + ".\n"
                    "    A /Redact annotation only marks content for "
                    "removal; the redaction has NOT been applied, so "
                    "the covered content remains present and "
                    "recoverable in the file (extract the page text or "
                    "underlying objects to recover it). This indicates "
                    "an intent to conceal that was not carried "
                    "through — or a redaction workflow error."
                ),
                "obj_num": objnum,
                "obj_gen": objgen,
                "obj_locator": locator,
            })
        except Exception:
            continue
    return findings


# ---------------------------------------------------------------------
# Metadata history across revisions; ExifTool update markers
# ---------------------------------------------------------------------

# XMP properties compared across revisions (local names, case-insensitive).
# Dates are covered by the timeline, pdf:PDFVersion by VERSION_CONFLICT,
# and xmpMM IDs change legitimately on every save.
_XMP_TEXT_FIELDS = {"creatortool", "creator", "title", "description",
                    "subject", "keywords", "producer", "author", "rights"}
_DATE_KEYS = {"CreationDate", "ModDate"}
_EXIFTOOL_RE = re.compile(rb"%EndExifToolUpdate[ \t]+(\d+)")


def revision_metadata(pdf):
    """Text metadata of one opened revision, and its modification dates:
    ({"Info /Creator": value, "XMP xmp:CreatorTool": value, ...},
     (Info ModDate, XMP ModifyDate, XMP MetadataDate))."""
    fields = {}
    try:
        info = pdf.trailer.get("/Info")
        if info is not None:
            for k, v in info.items():
                name = str(k).lstrip("/")
                if name not in _DATE_KEYS:
                    fields[f"Info /{name}"] = str(v)
            mod = info.get("/ModDate")
            mod = str(mod) if mod is not None else None
        else:
            mod = None
    except Exception:
        mod = None
    xmod = xmd = None
    try:
        meta = pdf.open_metadata()
        for k, v in meta.items():
            key = str(k)
            local = key.rsplit("}", 1)[-1] if "}" in key else key.split(":")[-1]
            if local.lower() in _XMP_TEXT_FIELDS:
                prefix = {"http://purl.org/dc/elements/1.1/": "dc",
                          "http://ns.adobe.com/xap/1.0/": "xmp",
                          "http://ns.adobe.com/pdf/1.3/": "pdf"}.get(
                    key[1:].split("}")[0] if key.startswith("{") else "", "")
                label = f"{prefix}:{local}" if prefix else local
                if isinstance(v, (set, frozenset)):
                    val = ", ".join(sorted(str(x) for x in v))
                elif isinstance(v, (list, tuple)):
                    val = ", ".join(str(x) for x in v)
                else:
                    val = str(v)
                fields[f"XMP {label}"] = val
            elif local == "ModifyDate":
                xmod = str(v)
            elif local == "MetadataDate":
                xmd = str(v)
    except Exception:
        pass
    return fields, (mod, xmod, xmd)


ATTRIBUTION_CAVEAT = (
    "Attribution to ExifTool rests on the marker ExifTool writes at the end "
    "of its update. The marker is ordinary text and could have been added, "
    "removed or altered by anyone, so it corroborates, rather than proves, "
    "which tool made a change.")


def exiftool_attribution(data, revision_ends):
    """Check each %EndExifToolUpdate marker against the file's structure.

    revision_ends: [(label, end_offset)] for the revisions, oldest first
    (the current file last). ExifTool writes "%EndExifToolUpdate N" at
    the end of its update, where N is the length of the file before the
    edit. A genuine marker therefore (a) has an N equal to the end of a
    revision, and (b) sits inside the update that follows that revision.
    Returns [{marker, offset, base, attributed, consistent, reason}],
    where attributed is the label of the revision ExifTool wrote (only
    when consistent)."""
    out = []
    ends = [(lbl, end) for lbl, end in revision_ends]
    for m in _EXIFTOOL_RE.finditer(data):
        n, at = int(m.group(1)), m.start()
        base = next((i for i, (_, e) in enumerate(ends) if e == n), None)
        rec = {"marker": n, "offset": at, "base": None, "attributed": None,
               "consistent": False, "reason": ""}
        if base is None:
            rec["reason"] = (f"its number ({n:,}) does not match the end of "
                             f"any revision of the file")
        elif base + 1 >= len(ends):
            rec["base"] = ends[base][0]
            rec["reason"] = (f"it names {ends[base][0]} as the original file, "
                             f"but no later update follows it")
        else:
            nxt_lbl, nxt_end = ends[base + 1]
            rec["base"] = ends[base][0]
            if n < at < nxt_end:
                rec["attributed"], rec["consistent"] = nxt_lbl, True
                rec["reason"] = (f"its number matches the end of "
                                 f"{ends[base][0]} exactly, and it sits inside "
                                 f"the update that follows ({nxt_lbl})")
            else:
                rec["reason"] = (f"its number matches the end of "
                                 f"{ends[base][0]}, but the marker lies at byte "
                                 f"{at:,}, outside the update that follows it")
        out.append(rec)
    return out


def check_metadata_history(pdf_path, password=None):
    """METADATA_REVISED: text metadata (Info dictionary or XMP) added,
    changed or removed by a later incremental update; a revision that
    changes metadata without changing any modification date is called
    out as a silent edit. EXIFTOOL_EDIT: ExifTool's own update marker."""
    import io
    try:
        import pikepdf
        from pdf_forensics.analysis.metadata import classify_prior_versions
        with open(pdf_path, "rb") as fh:
            data = fh.read()
    except Exception:
        return []
    revs = []
    try:
        for c in classify_prior_versions(data, password=password):
            if c.get("status") in ("valid", "encrypted"):
                revs.append((f"revision {c['version_number']}", c["end"]))
    except Exception:
        pass
    revs.append(("current", len(data)))
    states = []
    for label, end in revs:
        try:
            kw = {"password": password} if password else {}
            with pikepdf.open(io.BytesIO(data[:end]), **kw) as pdf:
                states.append((label, end) + revision_metadata(pdf))
        except Exception:
            continue

    results = []
    attrib = exiftool_attribution(data, [(lbl, end) for lbl, end, *_ in states])
    by_tool = {a["attributed"]: a for a in attrib if a["consistent"]}
    changes, silent = [], []
    for (la, ea, fa, da), (lb, eb, fb, db) in zip(states, states[1:]):
        diff = []
        for k in sorted(set(fa) | set(fb)):
            a, b = fa.get(k), fb.get(k)
            if a != b:
                what = ("added" if a is None else "removed" if b is None
                        else "changed")
                diff.append(f"{k} {what}: {a if a is not None else '(absent)'}"
                            f" \u2192 {b if b is not None else '(absent)'}")
        if not diff:
            continue
        dates_same = any(x is not None for x in da + db) and da == db
        if dates_same:
            silent.append(lb)
        changes.append(f"In {lb} (update ending at byte {eb:,})"
                       + (", written by ExifTool per its update marker"
                          if lb in by_tool else "")
                       + (", WITHOUT any change to the modification dates"
                          if dates_same else "") + ":\n        - "
                       + "\n        - ".join(diff))
    if changes:
        detail = ("Document-level finding: document metadata was changed by "
                  "a later incremental update.\n    " + "\n    ".join(changes))
        if silent:
            detail += ("\n    Silent edit: " + ", ".join(silent)
                       + " changed metadata but kept the previous "
                       "revision's Info ModDate and XMP ModifyDate/"
                       "MetadataDate. Software that saves a document "
                       "normally updates its modification date; a metadata "
                       "editor such as ExifTool does not, so the document "
                       "still claims to have been last modified before the "
                       "edit (see the Timeline Analysis report).")
        if any(lbl in by_tool for lbl in silent) or by_tool:
            detail += "\n    " + ATTRIBUTION_CAVEAT
        detail += ("\n    The earlier values remain in the file and are shown "
                   "in each prior version's row of the PDF Metadata report. "
                   "A legitimate re-save can also change metadata (for "
                   "example the Producer); corroborate with the producer of "
                   "the update and the Incremental Updates report.")
        results.append({"image": None, "type": "METADATA_REVISED",
                        "detail": detail})

    if attrib:
        lines = []
        for a in attrib:
            if a["consistent"]:
                lines.append(
                    f"%EndExifToolUpdate {a['marker']} (at byte {a['offset']:,}): "
                    f"consistent with a genuine ExifTool update: {a['reason']}. "
                    f"The update that wrote {a['attributed']} is attributed "
                    f"to ExifTool; the file before the edit is {a['base']} "
                    f"(the first {a['marker']:,} bytes, extracted as a prior "
                    f"version).")
            else:
                lines.append(
                    f"%EndExifToolUpdate {a['marker']} (at byte {a['offset']:,}): "
                    f"NOT consistent with the file's structure: {a['reason']}. "
                    f"No update is attributed to ExifTool on the strength of "
                    f"this marker; it may have been added, copied or altered.")
        results.append({
            "image": None, "type": "EXIFTOOL_EDIT",
            "detail": (
                "Document-level finding: the file carries ExifTool's update "
                "marker. ExifTool writes PDF metadata as an incremental "
                "update and ends it with a %EndExifToolUpdate comment "
                "recording the original file length, so the edit can be "
                "identified and undone. Each marker is checked against the "
                "file's structure: a genuine marker's number equals the end "
                "of a revision and the marker sits inside the update that "
                "follows.\n    " + "\n    ".join(lines) +
                "\n    " + ATTRIBUTION_CAVEAT +
                "\n    ExifTool cannot change the header or page content "
                "this way; compare the prior version's metadata with the "
                "current file's (see METADATA_REVISED and "
                "VERSION_CONFLICT)."),
        })
    return results
