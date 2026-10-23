"""
Timeline analysis (schema revision 10).

Collects every timestamp a PDF carries, in every revision (each prior
version recovered from an incremental update, plus the current file),
normalises each to UTC, and checks that they make chronological sense.

Sources:
  * Document Information dictionary: CreationDate, ModDate
  * XMP metadata: xmp:CreateDate, xmp:ModifyDate, xmp:MetadataDate, and
    the xmpMM:History events (stEvt:when)
  * Annotations (comments, markup, stamps...): /CreationDate and /M
  * Digital signatures: signing time /M
  * Embedded files: /Params /CreationDate and /ModDate
  * Photographs: EXIF DateTimeOriginal and DateTimeDigitized (current
    file only; the engine supplies them from the extracted images)

Normalisation: values with an explicit offset are converted to UTC.
Values with no timezone designator are ASSUMED to be UTC (examiner
decision): they are compared like any other value and any resulting
ordering problem is flagged, but every such value is marked
"none (assumed UTC)" in the report so the assumption is visible.

Every revision's timestamps are recorded, including values unchanged
from the revision before, so each prior version's place in the timeline
is explicit. A problem that persists across revisions is reported once.
"""

import io
import re
from datetime import datetime, timezone, timedelta

from pdf_forensics.analysis.doc_checks import parse_pdf_date, _has_explicit_tz

# Cross-source comparisons allow for producers writing two related
# timestamps a few seconds apart. Same-field comparisons (a value against
# its own earlier revision, created vs modified in one source) are strict.
TOLERANCE = timedelta(seconds=60)
# PDF 1.0 was published in 1993; no PDF can be older. A conservative
# start-of-year bound is used rather than the exact release date.
PDF_EPOCH = datetime(1993, 1, 1, tzinfo=timezone.utc)

_EXIF_RE = re.compile(r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})")
_OFFSET_RE = re.compile(r"^([+-])(\d{2}):?(\d{2})$")

CATEGORY_DOC = "document"
CATEGORY_HISTORY = "history"
CATEGORY_ANNOT = "annotation"
CATEGORY_SIG = "signature"
CATEGORY_EMBED = "embedded file"
CATEGORY_EXIF = "photo EXIF"


# ---------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------

def _parse(raw):
    """(utc_datetime or None, has_tz)."""
    if raw is None:
        return None, False
    s = str(raw).strip()
    m = _EXIF_RE.match(s)
    if m and not s.startswith("D:"):
        try:
            dt = datetime(*[int(g) for g in m.groups()], tzinfo=timezone.utc)
        except ValueError:
            return None, False
        return dt, False
    dt = parse_pdf_date(s)
    if dt is None:
        return None, False
    return dt.astimezone(timezone.utc), _has_explicit_tz(s)


def _exif_with_offset(value, offset):
    """EXIF date plus optional OffsetTime* tag -> (utc, has_tz, raw)."""
    raw = str(value).strip().rstrip("\x00")
    dt, _ = _parse(raw)
    if dt is None:
        return None, False, raw
    if offset:
        om = _OFFSET_RE.match(str(offset).strip().rstrip("\x00"))
        if om:
            sign = -1 if om.group(1) == "-" else 1
            delta = timedelta(hours=int(om.group(2)), minutes=int(om.group(3)))
            local = dt.replace(tzinfo=timezone(sign * delta))
            return local.astimezone(timezone.utc), True, f"{raw} {offset}"
    return dt, False, raw


def exif_dates(label, image_bytes, ext=None):
    """Capture dates from a photo's EXIF sub-IFD: a list of
    (label, field, raw, utc, has_tz). DateTimeOriginal (0x9003) and
    DateTimeDigitized (0x9004) live in the Exif sub-IFD (0x8769), with
    their offsets in OffsetTimeOriginal (0x9011) / OffsetTimeDigitized
    (0x9012)."""
    out = []
    if not image_bytes:
        return out
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        exif = img.getexif()
        sub = exif.get_ifd(0x8769) if exif else {}
        for tag, otag, name in ((0x9003, 0x9011, "DateTimeOriginal"),
                                (0x9004, 0x9012, "DateTimeDigitized")):
            v = sub.get(tag) if sub else None
            if v:
                utc, tz, raw = _exif_with_offset(v, sub.get(otag))
                out.append((label, name, raw, utc, tz))
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------
# Collection, one revision at a time
# ---------------------------------------------------------------------

def _s(v):
    try:
        return str(v) if v is not None else None
    except Exception:
        return None


def _objref(obj):
    try:
        n, g = obj.objgen
        return f"{n} {g} R" if n else ""
    except Exception:
        return ""


_HIST_RE = re.compile(
    r"<rdf:li\b[^>]*?(?:/>|>.*?</rdf:li>)", re.S)


def _history(xmp_bytes):
    """xmpMM:History events as (index, when, action, agent)."""
    out = []
    if not xmp_bytes:
        return out
    try:
        text = xmp_bytes.decode("utf-8", errors="replace")
    except Exception:
        return out
    hm = re.search(r"<xmpMM:History>(.*?)</xmpMM:History>", text, re.S)
    if not hm:
        return out
    for i, li in enumerate(_HIST_RE.findall(hm.group(1)), 1):
        def field(name):
            m = (re.search(rf'stEvt:{name}="([^"]*)"', li)
                 or re.search(rf"<stEvt:{name}>([^<]*)</stEvt:{name}>", li))
            return m.group(1).strip() if m else None
        when = field("when")
        if when:
            out.append((i, when, field("action") or "",
                        field("softwareAgent") or ""))
    return out


def _collect_revision(pdf):
    """All timestamps in one opened revision: a list of
    (category, source, field, obj, raw)."""
    ts = []
    try:
        info = pdf.trailer.get("/Info")
        if info is not None:
            for k in ("/CreationDate", "/ModDate"):
                v = info.get(k)
                if v is not None:
                    ts.append((CATEGORY_DOC, "Info dictionary", k[1:], "", _s(v)))
    except Exception:
        pass
    xmp_bytes = None
    try:
        md = pdf.Root.get("/Metadata")
        if md is not None:
            xmp_bytes = md.read_bytes()
    except Exception:
        xmp_bytes = None
    if xmp_bytes:
        text = xmp_bytes.decode("utf-8", errors="replace")
        for field in ("CreateDate", "ModifyDate", "MetadataDate"):
            m = (re.search(rf'xmp:{field}="([^"]*)"', text)
                 or re.search(rf"<xmp:{field}>([^<]*)</xmp:{field}>", text))
            if m and m.group(1).strip():
                ts.append((CATEGORY_DOC, "XMP", f"xmp:{field}", "",
                           m.group(1).strip()))
        for i, when, action, agent in _history(xmp_bytes):
            label = f"xmpMM:History #{i}"
            if action:
                label += f" ({action}"
                label += f", {agent})" if agent else ")"
            ts.append((CATEGORY_HISTORY, "XMP history", label, "", when))
    # Annotations, page by page.
    try:
        for pno, page in enumerate(pdf.pages, 1):
            annots = page.obj.get("/Annots")
            if annots is None:
                continue
            for a in annots:
                try:
                    sub = _s(a.get("/Subtype")) or "/Annot"
                    if sub == "/Popup":
                        continue  # carries its parent's dates
                    who = _s(a.get("/T"))
                    desc = f"{sub[1:]} annotation, page {pno}"
                    if who:
                        desc += f", by {who}"
                    obj = _objref(a)
                    if sub == "/Widget" and _s(a.get("/FT")) == "/Sig":
                        continue  # handled with signatures
                    for k, f in (("/CreationDate", "CreationDate"),
                                 ("/M", "M (modified)")):
                        v = a.get(k)
                        if v is not None:
                            ts.append((CATEGORY_ANNOT, desc, f, obj, _s(v)))
                except Exception:
                    continue
    except Exception:
        pass
    # Signatures (AcroForm fields, recursively).
    try:
        acro = pdf.Root.get("/AcroForm")
        stack = list(acro.get("/Fields") or []) if acro is not None else []
        seen = set()
        while stack:
            f = stack.pop()
            key = _objref(f)
            if key and key in seen:
                continue
            seen.add(key)
            kids = f.get("/Kids")
            if kids is not None:
                stack.extend(list(kids))
            if _s(f.get("/FT")) == "/Sig" and f.get("/V") is not None:
                v = f.get("/V")
                m = v.get("/M")
                name = _s(f.get("/T")) or "signature"
                if m is not None:
                    who = _s(v.get("/Name"))
                    desc = f"Signature field {name}" + (f", by {who}" if who else "")
                    ts.append((CATEGORY_SIG, desc, "M (signing time)",
                               _objref(v), _s(m)))
    except Exception:
        pass
    # Embedded files (name tree, recursively).
    try:
        names = pdf.Root.get("/Names")
        ef = names.get("/EmbeddedFiles") if names is not None else None
        stack = [ef] if ef is not None else []
        while stack:
            node = stack.pop()
            if node.get("/Kids") is not None:
                stack.extend(list(node.get("/Kids")))
            arr = node.get("/Names")
            if arr is None:
                continue
            arr = list(arr)
            for j in range(0, len(arr) - 1, 2):
                fname = _s(arr[j])
                spec = arr[j + 1]
                try:
                    stream = spec.get("/EF").get("/F")
                    params = stream.get("/Params")
                except Exception:
                    params = None
                if params is None:
                    continue
                for k, f in (("/CreationDate", "CreationDate"),
                             ("/ModDate", "ModDate")):
                    v = params.get(k)
                    if v is not None:
                        ts.append((CATEGORY_EMBED, f"Embedded file {fname}", f,
                                   _objref(stream), _s(v)))
    except Exception:
        pass
    return ts


def _revisions(data, password=None, include_history=True):
    """Revisions to examine, oldest first, and notes on %%EOF markers that
    are not revisions. Returns ([(label, end)], [note, ...])."""
    revs, skipped = [], []
    if include_history:
        try:
            from pdf_forensics.analysis.metadata import classify_prior_versions
            for c in classify_prior_versions(data, password=password):
                n = c["version_number"]
                if c.get("status") in ("valid", "encrypted"):
                    revs.append((f"revision {n}", c["end"]))
                else:
                    why = (c.get("reason") or c.get("status") or "").strip()
                    skipped.append(f"%%EOF marker {n} is not a revision "
                                   f"({c.get('status')}: {why})")
        except Exception:
            pass
    revs.append(("current", len(data)))
    return revs, skipped


# ---------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------

def build_timeline(pdf_path, password=None, exif=None, include_history=True,
                   now=None):
    """Collect, normalise and check every timestamp, in every revision.

    Every revision's timestamps are kept, including values unchanged from
    the revision before, so each prior version's place in the timeline is
    explicit. Returns a dict:

      occurrences : one entry per timestamp per revision, chronological
                    (unparseable values last)
      issues      : list of {rule, message, duplicate}, each message once
      revisions   : labels of the revisions examined, oldest first
      skipped     : notes on %%EOF markers that are not revisions, and on
                    revisions that could not be opened
      assumed_utc : occurrences whose value had no timezone
    """
    import pikepdf
    now = now or datetime.now(timezone.utc)
    with open(pdf_path, "rb") as fh:
        data = fh.read()
    revs, skipped = _revisions(data, password=password,
                               include_history=include_history)
    per_rev = []          # [(label, items)]
    for label, end in revs:
        try:
            kw = {"password": password} if password else {}
            src = io.BytesIO(data[:end]) if end < len(data) else io.BytesIO(data)
            with pikepdf.open(src, **kw) as pdf:
                per_rev.append((label, _collect_revision(pdf)))
        except Exception as e:
            skipped.append(f"{label} could not be opened ({e})")
    if not per_rev:
        return {"occurrences": [], "issues": [], "revisions": [],
                "skipped": skipped, "assumed_utc": 0}
    labels = [p[0] for p in per_rev]
    last = len(per_rev) - 1

    parsed = {}

    def _p(raw):
        if raw not in parsed:
            parsed[raw] = _parse(raw)
        return parsed[raw]

    occs, index = [], {}
    for pos, (label, items) in enumerate(per_rev):
        for cat, source, field, obj, raw in items:
            key = (cat, source, field, obj)
            if (key, pos) in index:
                continue
            utc, tz = _p(raw)
            prev = index.get((key, pos - 1))
            intro = prev is None or prev["raw"] != raw
            o = {"category": cat, "source": source, "field": field,
                 "obj": obj, "raw": raw, "utc": utc, "has_tz": tz,
                 "pos": pos, "key": key, "issues": [], "introduced": intro,
                 "since": pos if intro else prev["since"]}
            index[(key, pos)] = o
            occs.append(o)
    for label, field, raw, utc, tz in (exif or []):
        key = (CATEGORY_EXIF, f"Photo EXIF, image {label}", field, "")
        o = {"category": CATEGORY_EXIF, "source": key[1], "field": field,
             "obj": "", "raw": raw, "utc": utc, "has_tz": tz, "pos": last,
             "key": key, "issues": [], "introduced": True, "since": last}
        index[(key, last)] = o
        occs.append(o)

    issues, seen = [], {}

    def flag(rule, message, os_, duplicate=False):
        if message not in seen:
            seen[message] = {"rule": rule, "message": message,
                             "duplicate": duplicate}
            issues.append(seen[message])
        for o in os_:
            if o is not None and message not in o["issues"]:
                o["issues"].append(message)

    def val(pos, key):
        o = index.get((key, pos))
        return o if o is not None and o["utc"] is not None else None

    def fmt(o, where=True):
        rev = f" ({labels[o['pos']]})" if where else ""
        return (f"{o['source']} {o['field']}{rev} = {o['raw']} "
                f"({o['utc'].strftime('%Y-%m-%d %H:%M:%S')} UTC"
                f"{'' if o['has_tz'] else ', no timezone: assumed UTC'})")

    DOC = CATEGORY_DOC
    ic = (DOC, "Info dictionary", "CreationDate", "")
    im = (DOC, "Info dictionary", "ModDate", "")
    xc = (DOC, "XMP", "xmp:CreateDate", "")
    xm = (DOC, "XMP", "xmp:ModifyDate", "")
    xd = (DOC, "XMP", "xmp:MetadataDate", "")

    def latest_mod(pos):
        c = [o for o in (val(pos, im), val(pos, xm), val(pos, xd)) if o]
        return max(c, key=lambda o: o["utc"]) if c else None

    # Rule 1: within each revision, created <= modified (each source).
    for pos in range(len(per_rev)):
        for a, b, what in ((ic, im, "Info ModDate"), (xc, xm, "XMP ModifyDate"),
                           (xc, xd, "XMP MetadataDate")):
            ea, eb = val(pos, a), val(pos, b)
            if ea and eb and eb["utc"] < ea["utc"]:
                flag("created_after_modified",
                     f"{what} is earlier than the creation date in "
                     f"{labels[pos]}: {fmt(eb, False)} precedes "
                     f"{fmt(ea, False)}.", [ea, eb],
                     duplicate=(a == ic and pos == last))
    # Rules 2-3: from each revision to the next.
    for pos in range(1, len(per_rev)):
        for key, name in ((ic, "Info CreationDate"), (xc, "XMP CreateDate")):
            ea, eb = val(pos - 1, key), val(pos, key)
            if ea and eb and ea["raw"] != eb["raw"] and ea["utc"] != eb["utc"]:
                flag("creation_changed",
                     f"{name} changed between {labels[pos - 1]} and "
                     f"{labels[pos]}: a document's creation date does not "
                     f"change when it is updated. {fmt(ea)} became {fmt(eb)}.",
                     [ea, eb])
        for key, name in ((im, "Info ModDate"), (xm, "XMP ModifyDate"),
                          (xd, "XMP MetadataDate")):
            ea, eb = val(pos - 1, key), val(pos, key)
            if ea and eb and ea["raw"] != eb["raw"] and eb["utc"] < ea["utc"]:
                flag("modification_backwards",
                     f"{name} goes backwards: {labels[pos]} records an "
                     f"earlier modification than {labels[pos - 1]}. "
                     f"{fmt(ea)}, then {fmt(eb)}.", [ea, eb])

    created = min([o for pos in range(len(per_rev))
                   for o in (val(pos, ic), val(pos, xc)) if o],
                  key=lambda o: o["utc"], default=None)

    # Rule 4: XMP history in order, and not after the revision's save.
    for pos in range(len(per_rev)):
        hist = sorted([o for o in occs if o["pos"] == pos
                       and o["category"] == CATEGORY_HISTORY and o["utc"]],
                      key=lambda o: int(re.search(r"#(\d+)", o["field"]).group(1)))
        for a, b in zip(hist, hist[1:]):
            if b["utc"] < a["utc"]:
                flag("history_out_of_order",
                     f"XMP history events are out of order in {labels[pos]}: "
                     f"{a['field']} at {a['utc']:%Y-%m-%d %H:%M:%S} UTC is "
                     f"followed by {b['field']} at "
                     f"{b['utc']:%Y-%m-%d %H:%M:%S} UTC.", [a, b])
        lm = latest_mod(pos)
        for h in hist:
            if lm and h["utc"] > lm["utc"] + TOLERANCE:
                flag("history_after_modification",
                     f"{h['field']} is dated after the last modification "
                     f"recorded in {labels[pos]}: {fmt(h, False)} is later "
                     f"than {fmt(lm, False)}.", [h, lm])

    # Rules 5-7: annotations, signatures, embedded files, revision by revision.
    groups = {}
    for o in occs:
        if o["category"] in (CATEGORY_ANNOT, CATEGORY_SIG, CATEGORY_EMBED):
            groups.setdefault((o["category"], o["source"], o["obj"]),
                              {}).setdefault(o["pos"], []).append(o)
    for (cat, source, obj), by_pos in groups.items():
        for pos, os_ in by_pos.items():
            c = next((o for o in os_ if o["field"].startswith("CreationDate")
                      and o["utc"]), None)
            for m in os_:
                if m is c or not m["utc"]:
                    continue
                if c and m["utc"] < c["utc"]:
                    flag("created_after_modified",
                         f"{source}: modified date precedes its creation "
                         f"date. {fmt(m, False)} precedes {fmt(c, False)}.",
                         [c, m])
            for o in os_:
                if not o["utc"]:
                    continue
                if cat in (CATEGORY_ANNOT, CATEGORY_SIG) and created and \
                        o["utc"] < created["utc"] - TOLERANCE:
                    flag("before_document_created",
                         f"{source} is dated before the document was "
                         f"created: {fmt(o, False)} precedes "
                         f"{fmt(created, False)}.", [o, created])
                if cat == CATEGORY_ANNOT and o["introduced"]:
                    lm = latest_mod(pos)
                    if lm and o["utc"] > lm["utc"] + TOLERANCE:
                        flag("after_revision_saved",
                             f"{source} {o['field']} = {o['raw']} first "
                             f"appears in {labels[pos]}, but is dated after "
                             f"that revision's last recorded modification "
                             f"({fmt(lm, False)}).", [o, lm])
                if cat == CATEGORY_SIG and o["introduced"]:
                    for q in range(pos + 1, len(per_rev)):
                        lm = latest_mod(q)
                        if lm and lm["since"] > pos and \
                                lm["utc"] < o["utc"] - TOLERANCE:
                            flag("modified_before_signature",
                                 f"{labels[q]} was saved after {source} was "
                                 f"applied in {labels[pos]}, but records a "
                                 f"modification before the signing time: "
                                 f"{fmt(lm)} precedes {fmt(o)}.", [o, lm])

    # Rule 8: photos (current file).
    final_mod = latest_mod(last)
    photo = [o for o in occs if o["category"] == CATEGORY_EXIF and o["utc"]]
    for o in photo:
        if final_mod and o["utc"] > final_mod["utc"] + TOLERANCE:
            flag("photo_after_document",
                 f"A photograph in the document was taken after the "
                 f"document's last recorded modification: {fmt(o, False)} is "
                 f"later than {fmt(final_mod, False)}.", [o, final_mod])
    by_img = {}
    for o in photo:
        by_img.setdefault(o["source"], {})[o["field"]] = o
    for src, f in by_img.items():
        a, d = f.get("DateTimeOriginal"), f.get("DateTimeDigitized")
        if a and d and d["utc"] < a["utc"]:
            flag("created_after_modified",
                 f"{src}: digitised before it was taken. {fmt(d, False)} "
                 f"precedes {fmt(a, False)}.", [a, d])

    # Rule 9: impossible dates (every revision's copy is marked).
    for o in occs:
        if not o["utc"]:
            continue
        if o["utc"] > now + timedelta(minutes=5):
            flag("in_future",
                 f"{o['source']} {o['field']} is in the future relative to "
                 f"the analysis ({now:%Y-%m-%d %H:%M} UTC): "
                 f"{fmt(o, False)}.", [o])
        elif o["category"] not in (CATEGORY_EXIF, CATEGORY_EMBED) and \
                o["utc"] < PDF_EPOCH:
            flag("before_pdf_existed",
                 f"{o['source']} {o['field']} predates the PDF format "
                 f"(published 1993): {fmt(o, False)}.", [o])

    occs.sort(key=lambda o: (o["utc"] is None,
                             o["utc"] or datetime.max.replace(tzinfo=timezone.utc),
                             o["pos"]))
    for o in occs:
        o["revision"] = labels[o["pos"]]
    return {"occurrences": occs, "issues": issues, "revisions": labels,
            "skipped": skipped,
            "assumed_utc": sum(1 for o in occs
                               if o["utc"] is not None and not o["has_tz"])}


def timeline_findings(tl):
    """TIMELINE_INCONSISTENT finding (at most one) for the risk score.
    An Info ModDate earlier than the Info CreationDate in the current
    revision is already scored as METADATA_DATE_ANOMALY, so on its own it
    is listed in the report but does not produce this finding."""
    if not tl or not tl["issues"]:
        return []
    if not [i for i in tl["issues"] if not i["duplicate"]]:
        return []
    lines = [f"    - {i['message']}" for i in tl["issues"][:15]]
    if len(tl["issues"]) > 15:
        lines.append(f"    - ... and {len(tl['issues']) - 15} more (see the "
                     f"Timeline Analysis report)")
    note = ""
    if tl["assumed_utc"]:
        note = ("\n    Some timestamps carry no timezone and were assumed to "
                "be UTC; an ordering problem involving one of them could "
                "reflect an unknown local offset (up to 14 hours). Check the "
                "raw values.")
    return [{
        "image": None,
        "type": "TIMELINE_INCONSISTENT",
        "detail": (
            f"Document-level finding: {len(tl['issues'])} chronological "
            f"inconsistency(ies) across {len(tl['revisions'])} revision(s) "
            f"({', '.join(tl['revisions'])}). All timestamps were "
            f"normalised to UTC for comparison.\n" + "\n".join(lines) + note +
            "\n    See the Timeline Analysis report for every timestamp of "
            "every revision in order."
        ),
    }]


def timeline_rows(tl):
    """Rows for the timeline_events table: a coverage row (status META,
    seq 0) recording the revisions examined and the %%EOF markers that are
    not revisions, then one row per timestamp per revision."""
    rows = [(0, ", ".join(tl.get("revisions", [])), "coverage", "coverage",
             "revisions examined", "", None, "", None, "META",
             "\n".join(tl.get("skipped", [])) or None)]
    for seq, o in enumerate(tl.get("occurrences", []), 1):
        if o["utc"] is None:
            tzs, utc, status = "unparseable", None, "UNPARSEABLE"
        else:
            tzs = "explicit" if o["has_tz"] else "none (assumed UTC)"
            utc = o["utc"].strftime("%Y-%m-%d %H:%M:%S")
            status = "FLAGGED" if o["issues"] else "OK"
        rows.append((seq, o["revision"], o["category"], o["source"],
                     o["field"], o["obj"], o["raw"], tzs, utc, status,
                     "\n".join(o["issues"]) or None))
    return rows
