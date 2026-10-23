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

Each distinct value is recorded once, with the span of revisions in
which it appears.
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
    """[(label, index, end)] oldest first; the current file is last."""
    revs = []
    if include_history:
        try:
            from pdf_forensics.analysis.metadata import classify_prior_versions
            for c in classify_prior_versions(data, password=password):
                if c.get("status") in ("valid", "encrypted"):
                    revs.append((f"revision {c['version_number']}", c["end"]))
        except Exception:
            pass
    revs.append(("current", len(data)))
    return [(lbl, i, end) for i, (lbl, end) in enumerate(revs)]


# ---------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------

def build_timeline(pdf_path, password=None, exif=None, include_history=True,
                   now=None):
    """Collect, normalise and check every timestamp. Returns a dict:

      events  : list of event dicts, chronological (unparseable last)
      issues  : list of issue dicts {rule, message, events, duplicate}
      revisions : number of revisions examined
      assumed_utc : number of events with no timezone designator
    """
    import pikepdf
    now = now or datetime.now(timezone.utc)
    with open(pdf_path, "rb") as fh:
        data = fh.read()
    revs = _revisions(data, password=password,
                      include_history=include_history)
    per_rev = []          # [(label, index, {key: raw})]
    for label, idx, end in revs:
        try:
            kw = {"password": password} if password else {}
            src = io.BytesIO(data[:end]) if end < len(data) else io.BytesIO(data)
            with pikepdf.open(src, **kw) as pdf:
                items = _collect_revision(pdf)
        except Exception:
            continue
        vals = {}
        for cat, source, field, obj, raw in items:
            vals[(cat, source, field, obj)] = raw
        per_rev.append((label, idx, vals))
    if not per_rev:
        return {"events": [], "issues": [], "revisions": 0,
                "assumed_utc": 0}
    labels = [p[0] for p in per_rev]

    # Collapse identical consecutive values into one event with a span.
    events = []
    index = {}            # (key, rev_position) -> event
    keys = []
    for _, _, vals in per_rev:
        for k in vals:
            if k not in keys:
                keys.append(k)
    for k in keys:
        cur = None
        for pos, (label, _, vals) in enumerate(per_rev):
            raw = vals.get(k)
            if raw is None:
                cur = None
                continue
            if cur is not None and cur["raw"] == raw:
                cur["last"] = pos
            else:
                utc, tz = _parse(raw)
                cur = {"category": k[0], "source": k[1], "field": k[2],
                       "obj": k[3], "raw": raw, "utc": utc, "has_tz": tz,
                       "first": pos, "last": pos, "issues": []}
                events.append(cur)
            index[(k, pos)] = cur
    for label, field, raw, utc, tz in (exif or []):
        ev = {"category": CATEGORY_EXIF, "source": f"Photo EXIF, image {label}",
              "field": field, "obj": "", "raw": raw, "utc": utc, "has_tz": tz,
              "first": len(per_rev) - 1, "last": len(per_rev) - 1,
              "issues": []}
        events.append(ev)

    def span(ev):
        a, b = labels[ev["first"]], labels[ev["last"]]
        return a if a == b else f"{a} to {b}"

    issues = []

    def flag(rule, message, evs, duplicate=False):
        issues.append({"rule": rule, "message": message, "events": evs,
                       "duplicate": duplicate})
        for e in evs:
            if message not in e["issues"]:
                e["issues"].append(message)

    def val(pos, key):
        ev = index.get((key, pos))
        return ev if ev is not None and ev["utc"] is not None else None

    def fmt(e):
        return (f"{e['source']} {e['field']} = {e['raw']} "
                f"({e['utc'].strftime('%Y-%m-%d %H:%M:%S')} UTC"
                f"{'' if e['has_tz'] else ', no timezone: assumed UTC'})")

    DOC = CATEGORY_DOC
    ic, im = (DOC, "Info dictionary", "CreationDate", ""), (DOC, "Info dictionary", "ModDate", "")
    xc, xm, xd = ((DOC, "XMP", "xmp:CreateDate", ""), (DOC, "XMP", "xmp:ModifyDate", ""),
                  (DOC, "XMP", "xmp:MetadataDate", ""))
    last = len(per_rev) - 1

    # Rule 1: within each revision, created <= modified (each source).
    for pos in range(len(per_rev)):
        for a, b, what in ((ic, im, "Info ModDate"), (xc, xm, "XMP ModifyDate"),
                           (xc, xd, "XMP MetadataDate")):
            ea, eb = val(pos, a), val(pos, b)
            if ea and eb and eb["utc"] < ea["utc"]:
                dup = (a == ic and pos == last)
                flag("created_after_modified",
                     f"{what} is earlier than the creation date in "
                     f"{labels[pos]}: {fmt(eb)} precedes {fmt(ea)}.", [ea, eb],
                     duplicate=dup)
    # Rules 2-3: across revisions.
    for pos in range(1, len(per_rev)):
        for key, name in ((ic, "Info CreationDate"), (xc, "XMP CreateDate")):
            ea, eb = val(pos - 1, key), val(pos, key)
            if ea and eb and ea is not eb and ea["utc"] != eb["utc"]:
                flag("creation_changed",
                     f"{name} changed between {labels[pos - 1]} and "
                     f"{labels[pos]}: a document's creation date does not "
                     f"change when it is updated. {fmt(ea)} became {fmt(eb)}.",
                     [ea, eb])
        for key, name in ((im, "Info ModDate"), (xm, "XMP ModifyDate"),
                          (xd, "XMP MetadataDate")):
            ea, eb = val(pos - 1, key), val(pos, key)
            if ea and eb and ea is not eb and eb["utc"] < ea["utc"]:
                flag("modification_backwards",
                     f"{name} goes backwards: {labels[pos]} records an "
                     f"earlier modification than {labels[pos - 1]}. "
                     f"{fmt(ea)}, then {fmt(eb)}.", [ea, eb])

    def doc_latest_mod(pos):
        c = [e for e in (val(pos, im), val(pos, xm), val(pos, xd)) if e]
        return max(c, key=lambda e: e["utc"]) if c else None

    def doc_creation():
        c = [e for pos in range(len(per_rev))
             for e in (val(pos, ic), val(pos, xc)) if e]
        return min(c, key=lambda e: e["utc"]) if c else None

    created = doc_creation()

    # Rule 4: XMP history in order, and not after the revision's save.
    for pos in range(len(per_rev)):
        hist = sorted([e for (k, p), e in index.items()
                       if p == pos and k[0] == CATEGORY_HISTORY and e["utc"]],
                      key=lambda e: int(re.search(r"#(\d+)", e["field"]).group(1)))
        for a, b in zip(hist, hist[1:]):
            if b["utc"] < a["utc"]:
                flag("history_out_of_order",
                     f"XMP history events are out of order in {labels[pos]}: "
                     f"{a['field']} at {a['utc']:%Y-%m-%d %H:%M:%S} UTC is "
                     f"followed by {b['field']} at "
                     f"{b['utc']:%Y-%m-%d %H:%M:%S} UTC.", [a, b])
        lm = doc_latest_mod(pos)
        for h in hist:
            if lm and h["utc"] > lm["utc"] + TOLERANCE:
                flag("history_after_modification",
                     f"{h['field']} is dated after the last modification "
                     f"recorded in {labels[pos]}: {fmt(h)} is later than "
                     f"{fmt(lm)}.", [h, lm])

    # Rule 5: annotations; Rule 6: signatures; Rule 7: embedded files.
    objs = {}
    for e in events:
        if e["category"] in (CATEGORY_ANNOT, CATEGORY_SIG, CATEGORY_EMBED):
            objs.setdefault((e["category"], e["source"], e["obj"]), []).append(e)
    for (cat, source, obj), evs in objs.items():
        c = next((e for e in evs if e["field"].startswith("CreationDate")
                  and e["utc"]), None)
        mods = [e for e in evs if not e["field"].startswith("CreationDate")
                and e["utc"]]
        for m in mods:
            if c and m["utc"] < c["utc"]:
                flag("created_after_modified",
                     f"{source}: modified date precedes its creation date. "
                     f"{fmt(m)} precedes {fmt(c)}.", [c, m])
        if cat in (CATEGORY_ANNOT, CATEGORY_SIG) and created:
            for e in evs:
                if e["utc"] and e["utc"] < created["utc"] - TOLERANCE:
                    flag("before_document_created",
                         f"{source} is dated before the document was "
                         f"created: {fmt(e)} precedes {fmt(created)}.",
                         [e, created])
        if cat == CATEGORY_ANNOT:
            first = min(e["first"] for e in evs)
            lm = doc_latest_mod(first)
            for e in evs:
                if e["first"] == first and e["utc"] and lm and \
                        e["utc"] > lm["utc"] + TOLERANCE:
                    flag("after_revision_saved",
                         f"{source} first appears in {labels[first]}, but is "
                         f"dated after that revision's last recorded "
                         f"modification: {fmt(e)} is later than {fmt(lm)}.",
                         [e, lm])
        if cat == CATEGORY_SIG:
            for s in evs:
                if not s["utc"]:
                    continue
                for pos in range(s["first"] + 1, len(per_rev)):
                    lm = doc_latest_mod(pos)
                    if lm and lm["first"] > s["first"] and \
                            lm["utc"] < s["utc"] - TOLERANCE:
                        flag("modified_before_signature",
                             f"{labels[pos]} was saved after {source} was "
                             f"applied, but records a modification before the "
                             f"signing time: {fmt(lm)} precedes {fmt(s)}.",
                             [s, lm])

    # Rule 8: photos.
    final_mod = doc_latest_mod(last)
    photo = [e for e in events if e["category"] == CATEGORY_EXIF and e["utc"]]
    for e in photo:
        if final_mod and e["utc"] > final_mod["utc"] + TOLERANCE:
            flag("photo_after_document",
                 f"A photograph in the document was taken after the "
                 f"document's last recorded modification: {fmt(e)} is later "
                 f"than {fmt(final_mod)}.", [e, final_mod])
    by_img = {}
    for e in photo:
        by_img.setdefault(e["source"], {})[e["field"]] = e
    for src, f in by_img.items():
        o, d = f.get("DateTimeOriginal"), f.get("DateTimeDigitized")
        if o and d and d["utc"] < o["utc"]:
            flag("created_after_modified",
                 f"{src}: digitised before it was taken. {fmt(d)} precedes "
                 f"{fmt(o)}.", [o, d])

    # Rule 9: impossible dates.
    for e in events:
        if not e["utc"]:
            continue
        if e["utc"] > now + timedelta(minutes=5):
            flag("in_future",
                 f"{e['source']} {e['field']} is in the future relative to "
                 f"the analysis ({now:%Y-%m-%d %H:%M} UTC): {fmt(e)}.", [e])
        elif e["category"] not in (CATEGORY_EXIF, CATEGORY_EMBED) and \
                e["utc"] < PDF_EPOCH:
            flag("before_pdf_existed",
                 f"{e['source']} {e['field']} predates the PDF format "
                 f"(published 1993): {fmt(e)}.", [e])

    for e in events:
        e["revisions"] = span(e)
    events.sort(key=lambda e: (e["utc"] is None,
                               e["utc"] or datetime.max.replace(tzinfo=timezone.utc),
                               e["first"]))
    return {"events": events, "issues": issues, "revisions": len(per_rev),
            "assumed_utc": sum(1 for e in events
                               if e["utc"] is not None and not e["has_tz"])}


def timeline_findings(tl):
    """TIMELINE_INCONSISTENT finding (at most one) for the risk score.
    An Info ModDate earlier than the Info CreationDate in the current
    revision is already scored as METADATA_DATE_ANOMALY, so it is listed
    in the report but does not on its own produce this finding."""
    if not tl or not tl["issues"]:
        return []
    scored = [i for i in tl["issues"] if not i["duplicate"]]
    if not scored:
        return []
    lines = [f"    - {i['message']}" for i in tl["issues"][:15]]
    more = len(tl["issues"]) - 15
    if more > 0:
        lines.append(f"    - ... and {more} more (see the Timeline Analysis "
                     f"report)")
    note = ""
    if tl["assumed_utc"]:
        note = (f"\n    {tl['assumed_utc']} timestamp(s) carry no timezone "
                f"and were assumed to be UTC; an ordering problem involving "
                f"one of them could reflect an unknown local offset (up to "
                f"14 hours). Check the raw values.")
    return [{
        "image": None,
        "type": "TIMELINE_INCONSISTENT",
        "detail": (
            f"Document-level finding: {len(tl['issues'])} timestamp(s) are "
            f"out of chronological order across {tl['revisions']} "
            f"revision(s). All timestamps were normalised to UTC for "
            f"comparison.\n" + "\n".join(lines) + note +
            "\n    See the Timeline Analysis report for every timestamp in "
            "order."
        ),
    }]


def timeline_rows(tl):
    """Rows for the timeline_events table."""
    rows = []
    for seq, e in enumerate(tl.get("events", []), 1):
        if e["utc"] is None:
            tzs, utc, status = "unparseable", None, "UNPARSEABLE"
        else:
            tzs = ("explicit" if e["has_tz"] else "none (assumed UTC)")
            utc = e["utc"].strftime("%Y-%m-%d %H:%M:%S")
            status = "FLAGGED" if e["issues"] else "OK"
        rows.append((seq, e["revisions"], e["category"], e["source"],
                     e["field"], e["obj"], e["raw"], tzs, utc, status,
                     "\n".join(e["issues"]) or None))
    return rows
