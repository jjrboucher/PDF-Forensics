"""
analysis/comments.py
Extraction of reviewer comments / markup annotations from a PDF.

A "comment" here means a markup annotation that carries user-authored text
or marks up the page for review: sticky notes (/Text), typed text boxes
(/FreeText), and text-markup annotations (/Highlight, /Underline,
/StrikeOut, /Squiggly) as well as drawing markups that authors use to
comment (/Square, /Circle, /Line, /Polygon, /PolyLine, /Ink, /Stamp,
/Caret, /FileAttachment). Auto-generated /Popup and navigational /Link
annotations are ignored -- a Popup only holds the on-screen bubble for
another annotation and carries no independent authored content.

Each extracted comment is a dict with:
    page_number    1-based page the annotation sits on
    annot_subtype  human-readable annotation type (e.g. "FreeText")
    author         /T (title / author) value
    contents       /Contents text (falls back to stripped /RC rich text)
    created_date   /CreationDate, normalised to ISO-ish text
    modified_date  /M (modification date), normalised
    obj_num        PDF object number of the annotation
    obj_gen        PDF generation number of the annotation

This module depends only on pikepdf.
"""

import re

# Markup annotation subtypes we treat as "comments".
_COMMENT_SUBTYPES = {
    "/Text": "Sticky note",
    "/FreeText": "FreeText",
    "/Highlight": "Highlight",
    "/Underline": "Underline",
    "/StrikeOut": "StrikeOut",
    "/Squiggly": "Squiggly",
    "/Square": "Square",
    "/Circle": "Circle",
    "/Line": "Line",
    "/Polygon": "Polygon",
    "/PolyLine": "PolyLine",
    "/Ink": "Ink",
    "/Stamp": "Stamp",
    "/Caret": "Caret",
    "/FileAttachment": "File attachment",
    "/Sound": "Sound",
}

# Subtypes that are never user comments.
_IGNORED_SUBTYPES = {"/Popup", "/Link"}


def _pdf_date_to_iso(raw):
    """
    Convert a PDF date string (e.g. "D:20260604083118-04'00'") to a more
    readable ISO-like form ("2026-06-04 08:31:18-04:00"). Returns the
    original string if it cannot be parsed, or "" for empty input.
    """
    if not raw:
        return ""
    s = str(raw).strip()
    if s.startswith("D:"):
        s = s[2:]
    m = re.match(
        r"(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?"
        r"([Zz]|[+\-]\d{2}'?\d{2}'?)?", s)
    if not m:
        return str(raw)
    year, mon, day, hh, mm, ss, tz = m.groups()
    mon = mon or "01"
    day = day or "01"
    hh = hh or "00"
    mm = mm or "00"
    ss = ss or "00"
    out = f"{year}-{mon}-{day} {hh}:{mm}:{ss}"
    if tz:
        tz = tz.replace("'", "")
        if tz in ("Z", "z"):
            out += "Z"
        elif len(tz) == 5:   # +HHMM / -HHMM
            out += f"{tz[:3]}:{tz[3:]}"
        else:
            out += tz
    return out


def _strip_rich_text(rc):
    """Strip XHTML tags from an /RC rich-text value to recover plain text."""
    if not rc:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(rc))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_comments(pdf_pk):
    """
    Extract comment/markup annotations from an open pikepdf PDF.

    Returns a list of comment dicts (see module docstring). The list is
    ordered by page, then by the order annotations appear on the page.
    """
    comments = []
    try:
        pages = list(pdf_pk.pages)
    except Exception:
        return comments

    for page_index, page in enumerate(pages):
        page_number = page_index + 1
        try:
            annots = page.get("/Annots")
        except Exception:
            annots = None
        if not annots:
            continue

        for annot_ref in list(annots):
            try:
                obj = (annot_ref.obj if hasattr(annot_ref, "obj")
                       else annot_ref)
                if not hasattr(obj, "get"):
                    continue
                subtype = str(obj.get("/Subtype") or "")
                if subtype in _IGNORED_SUBTYPES:
                    continue
                if subtype not in _COMMENT_SUBTYPES:
                    continue

                contents = obj.get("/Contents")
                contents = str(contents) if contents is not None else ""
                if not contents.strip():
                    contents = _strip_rich_text(obj.get("/RC"))

                # Markups with neither contents nor an author are usually
                # decorative (e.g. an empty highlight); skip those, since a
                # "comment" should carry authored information.
                author = obj.get("/T")
                author = str(author) if author is not None else ""
                if not contents.strip() and not author.strip():
                    continue

                obj_num = obj_gen = None
                try:
                    ref = (annot_ref if hasattr(annot_ref, "objgen")
                           else obj)
                    obj_num, obj_gen = ref.objgen
                except Exception:
                    pass

                comments.append({
                    "page_number": page_number,
                    "annot_subtype": _COMMENT_SUBTYPES.get(
                        subtype, subtype.lstrip("/")),
                    "author": author,
                    "contents": contents,
                    "created_date": _pdf_date_to_iso(
                        obj.get("/CreationDate")),
                    "modified_date": _pdf_date_to_iso(obj.get("/M")),
                    "obj_num": obj_num,
                    "obj_gen": obj_gen,
                })
            except Exception:
                continue

    return comments
