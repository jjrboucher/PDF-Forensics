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

    if info_producer and xmp_producer and \
            info_producer.strip() != xmp_producer.strip():
        findings.append({
            "image": None,
            "type": "METADATA_MISMATCH",
            "detail": (
                "Document-level finding: Info dictionary and XMP stream "
                "disagree on Producer. Legitimate producers write both "
                "in sync; manual editing of one source frequently "
                "leaves the other unchanged.\n"
                f"    Info dictionary: {info_producer}\n"
                f"    XMP stream:      {xmp_producer}"
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
