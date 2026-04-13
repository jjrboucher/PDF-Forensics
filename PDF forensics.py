"""
PDF Forensics

A forensic analysis tool for PDF documents. Examines images and
extracts metadata, flagging:
  1. Images cropped via Form XObject BBox boundaries
  2. Images offset to hide content beyond the BBox
  3. Explicit clipping paths applied to images
  4. Overlapping images with transparency-aware concealment assessment
  5. Soft masks applied to images or Form XObjects
  6. Complex (rotated/skewed) transforms requiring manual review

Additional features:
  - PDF metadata extraction (Info Dict, XMP, Catalog)
  - Prior version detection via %%EOF markers (incremental updates)
  - Image metadata extraction (EXIF, GPS, format info via Pillow)
  - MD5 hashing of the PDF and each unique image
  - Optional storage of image bytes inside the database
  - Disk extraction of images using <page>_<num>.<ext> naming
  - GUI mode (--gui) for interactive batch processing

Results are stored in an SQLite database in third normal form.
If the database already exists, new analysis results are appended.

Usage:
  CLI:  python "PDF forensics.py" file1.pdf [file2.pdf ...]
              [-d output.db] [-e output_folder] [--no-store-images]
  GUI:  python "PDF forensics.py" --gui

Dependencies: PyMuPDF, pikepdf, Pillow (optional, for image metadata)
"""

import sys
import os
import sqlite3
import hashlib
from datetime import datetime, timezone
import pymupdf
import pikepdf
from pikepdf import Name
from itertools import combinations


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
HIDDEN_THRESHOLD_PTS = 0.5
OVERLAP_THRESHOLD_SQPTS = 1.0

FINDING_TYPE_DEFS = {
    "BBOX_CROP": ("Image cropped by BBox boundary", "HIGH"),
    "EXPLICIT_CLIP": ("Explicit clipping path applied", "HIGH"),
    "OVERLAP": ("Overlapping images", "HIGH"),
    "SOFT_MASK": ("Soft mask on Form XObject", "INFO"),
    "IMAGE_SMASK": ("Soft mask on Image XObject", "INFO"),
    "COMPLEX_TRANSFORM": ("Complex transform (manual review needed)", "INFO"),
    "PARSE_ERROR": ("Stream parse error", "INFO"),
}


# ===================================================================
# DATABASE
# ===================================================================

def init_db(db_path):
    """Create database and tables if they don't exist."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS analyses (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            pdf_filename  TEXT    NOT NULL,
            pdf_path      TEXT    NOT NULL,
            pdf_size_bytes INTEGER NOT NULL,
            pdf_md5       TEXT    NOT NULL,
            total_pages   INTEGER NOT NULL,
            analyzed_at   TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pages (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id   INTEGER NOT NULL
                          REFERENCES analyses(id) ON DELETE CASCADE,
            page_number   INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS image_data (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id   INTEGER NOT NULL
                          REFERENCES analyses(id) ON DELETE CASCADE,
            xref          INTEGER NOT NULL,
            format_ext    TEXT,
            width_px      INTEGER,
            height_px     INTEGER,
            image_bytes   BLOB,
            byte_size     INTEGER NOT NULL,
            md5_hash      TEXT    NOT NULL,
            UNIQUE(analysis_id, xref)
        );

        CREATE TABLE IF NOT EXISTS images (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id               INTEGER NOT NULL
                                  REFERENCES pages(id) ON DELETE CASCADE,
            image_data_id         INTEGER
                                  REFERENCES image_data(id) ON DELETE SET NULL,
            label                 TEXT    NOT NULL,
            z_order               INTEGER,
            opacity               REAL    DEFAULT 1.0,
            blend_mode            TEXT    DEFAULT '/Normal',
            has_smask             INTEGER DEFAULT 0,
            in_transparency_group INTEGER DEFAULT 0,
            form_xobject_xref    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS finding_types (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            code     TEXT    NOT NULL UNIQUE,
            label    TEXT    NOT NULL,
            severity TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS findings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id         INTEGER NOT NULL
                            REFERENCES pages(id) ON DELETE CASCADE,
            finding_type_id INTEGER NOT NULL
                            REFERENCES finding_types(id),
            detail          TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS finding_images (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            finding_id INTEGER NOT NULL
                       REFERENCES findings(id) ON DELETE CASCADE,
            image_id   INTEGER NOT NULL
                       REFERENCES images(id) ON DELETE CASCADE,
            role       TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS overlap_details (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            finding_id             INTEGER NOT NULL UNIQUE
                                   REFERENCES findings(id) ON DELETE CASCADE,
            front_image_id         INTEGER NOT NULL
                                   REFERENCES images(id) ON DELETE CASCADE,
            back_image_id          INTEGER NOT NULL
                                   REFERENCES images(id) ON DELETE CASCADE,
            overlap_area_sqpts     REAL,
            overlap_pct            REAL,
            front_opacity          REAL,
            front_blend_mode       TEXT,
            front_has_smask        INTEGER,
            concealment_assessment TEXT
        );

        CREATE TABLE IF NOT EXISTS pdf_metadata (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id  INTEGER NOT NULL
                         REFERENCES analyses(id) ON DELETE CASCADE,
            source       TEXT    NOT NULL,
            key          TEXT    NOT NULL,
            value        TEXT
        );

        CREATE TABLE IF NOT EXISTS pdf_versions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id     INTEGER NOT NULL
                            REFERENCES analyses(id) ON DELETE CASCADE,
            version_number  INTEGER NOT NULL,
            eof_offset      INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS image_metadata (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            image_data_id  INTEGER NOT NULL
                           REFERENCES image_data(id) ON DELETE CASCADE,
            source         TEXT    NOT NULL,
            key            TEXT    NOT NULL,
            value          TEXT
        );
    """)

    for code, (label, severity) in FINDING_TYPE_DEFS.items():
        cur.execute("""
            INSERT OR IGNORE INTO finding_types (code, label, severity)
            VALUES (?, ?, ?)
        """, (code, label, severity))

    conn.commit()
    return conn


def get_finding_type_id(cur, code):
    cur.execute("SELECT id FROM finding_types WHERE code = ?", (code,))
    row = cur.fetchone()
    return row[0] if row else None


# ===================================================================
# PDF METADATA EXTRACTION
# ===================================================================

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


# ===================================================================
# IMAGE METADATA EXTRACTION
# ===================================================================

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


# ===================================================================
# CONTENT STREAM IMAGE ENUMERATION
# ===================================================================

def find_images_in_form(form_obj):
    """
    Parse a Form XObject's content stream and return a list of
    Image XObject xrefs referenced inside it.
    """
    image_xrefs = []
    inner_xobjects = form_obj.get("/Resources", {}).get("/XObject", {})
    if not inner_xobjects:
        return image_xrefs

    inner_lookup = {}
    for name, ref in inner_xobjects.items():
        try:
            objnum = ref.objgen[0] if hasattr(ref, "objgen") else None
            resolved = ref.resolve() if hasattr(ref, "resolve") else ref
            inner_lookup[str(name)] = (objnum, resolved)
        except Exception:
            continue

    try:
        ops = pikepdf.parse_content_stream(form_obj)
    except Exception:
        return image_xrefs

    for operands, operator in ops:
        if str(operator) != "Do":
            continue
        inner_name = str(operands[0])
        if inner_name not in inner_lookup:
            continue
        objnum, resolved = inner_lookup[inner_name]
        if resolved.get("/Subtype") == Name("/Image"):
            image_xrefs.append(objnum)
        elif resolved.get("/Subtype") == Name("/Form"):
            image_xrefs.extend(find_images_in_form(resolved))

    return image_xrefs


def find_image_placements(page_pk):
    """
    Parse the page content stream and return a list of image placements
    in painting order. Each placement is a dict:
      - xobj_name: resource name from Do operator
      - xref: Image XObject object number
      - is_form: True if image is inside a Form XObject
      - form_xref: the Form XObject's object number (if is_form)
      - z_order: painting sequence number (1-based)
    """
    placements = []
    xobjects = page_pk.get("/Resources", {}).get("/XObject", {})
    if not xobjects:
        return placements

    name_to_obj = {}
    for name, ref in xobjects.items():
        try:
            objnum = ref.objgen[0] if hasattr(ref, "objgen") else None
            resolved = ref.resolve() if hasattr(ref, "resolve") else ref
            name_to_obj[str(name)] = (objnum, resolved)
        except Exception:
            continue

    try:
        ops = pikepdf.parse_content_stream(page_pk)
    except Exception:
        return placements

    z_order = 0
    for operands, operator in ops:
        if str(operator) != "Do":
            continue

        xobj_name = str(operands[0])
        if xobj_name not in name_to_obj:
            continue

        z_order += 1
        objnum, resolved = name_to_obj[xobj_name]
        subtype = resolved.get("/Subtype")

        if subtype == Name("/Image"):
            placements.append({
                "xobj_name": xobj_name,
                "xref": objnum,
                "is_form": False,
                "form_xref": None,
                "z_order": z_order,
            })
        elif subtype == Name("/Form"):
            form_xref = objnum
            inner_images = find_images_in_form(resolved)
            for img_xref in inner_images:
                placements.append({
                    "xobj_name": xobj_name,
                    "xref": img_xref,
                    "is_form": True,
                    "form_xref": form_xref,
                    "z_order": z_order,
                })

    return placements


# ===================================================================
# IMAGE MAP BUILDING (uses content stream enumeration)
# ===================================================================

def build_image_map(page_pk, page_num, page_pad, doc_mu):
    """
    Build image naming map by parsing the content stream, matching
    the enumeration order used by extract_pdf_images.py.

    Returns:
        placements     : list of placement dicts (from find_image_placements)
        label_to_info  : {"01_1": {xref, width, height, ext, form_xref, z_order}}
        xref_to_labels : {xref: ["01_1", "01_2"]}  (xref may map to multiple labels)
        form_xref_to_labels : {form_xref: ["01_1"]}
    """
    placements = find_image_placements(page_pk)

    label_to_info = {}
    xref_to_labels = {}
    form_xref_to_labels = {}
    xref_extract_cache = {}  # avoid re-extracting same xref

    img_count = 0
    for p in placements:
        xref = p["xref"]
        if xref is None:
            continue

        img_count += 1
        label = f"{str(page_num).zfill(page_pad)}_{img_count}"

        # Get image data from PyMuPDF (cached per xref)
        if xref not in xref_extract_cache:
            try:
                extracted = doc_mu.extract_image(xref)
                xref_extract_cache[xref] = extracted
            except Exception:
                xref_extract_cache[xref] = None

        extracted = xref_extract_cache[xref]
        width = extracted["width"] if extracted else 0
        height = extracted["height"] if extracted else 0
        ext = extracted["ext"] if extracted else "unknown"
        image_bytes = extracted["image"] if extracted else None

        label_to_info[label] = {
            "xref": xref,
            "width": width,
            "height": height,
            "ext": ext,
            "image_bytes": image_bytes,
            "form_xref": p["form_xref"] or 0,
            "z_order": p["z_order"],
        }

        xref_to_labels.setdefault(xref, []).append(label)

        if p["form_xref"]:
            form_xref_to_labels.setdefault(
                p["form_xref"], []).append(label)

    return placements, label_to_info, xref_to_labels, form_xref_to_labels


# ===================================================================
# Z-ORDER AND TRANSPARENCY ANALYSIS
# ===================================================================

def parse_ext_gstates(page_pk):
    """Extract opacity, blend mode, and SMask from ExtGState resources."""
    resources = page_pk.get("/Resources", {})
    ext_gstates = resources.get("/ExtGState", {})
    gstate_props = {}

    for gs_name, gs_ref in ext_gstates.items():
        try:
            gs = gs_ref.resolve() if hasattr(gs_ref, "resolve") else gs_ref
        except Exception:
            continue

        ca_val = gs.get("/ca")
        ca = float(ca_val) if ca_val is not None else 1.0

        bm_val = gs.get("/BM")
        bm = str(bm_val) if bm_val is not None else "/Normal"

        has_smask = "/SMask" in gs and str(gs.get("/SMask")) != "/None"

        gstate_props[str(gs_name)] = {
            "ca": ca, "BM": bm, "SMask": has_smask,
        }

    return gstate_props


def get_zorder_and_graphics_state(page_pk):
    """
    Parse the page content stream to determine the active graphics
    state (opacity, blend mode, SMask) at each Do operator.

    Returns a list of dicts in painting order, one per Do:
      {xobj_name, z_order, ca, BM, gstate_smask}
    """
    gstate_props = parse_ext_gstates(page_pk)

    try:
        ops = pikepdf.parse_content_stream(page_pk)
    except Exception:
        return []

    default_gstate = {"ca": 1.0, "BM": "/Normal", "SMask": False}
    current_gstate = dict(default_gstate)
    gstate_stack = []
    z_order = 0
    results = []

    for operands, operator in ops:
        op = str(operator)
        if op == "q":
            gstate_stack.append(dict(current_gstate))
        elif op == "Q":
            if gstate_stack:
                current_gstate = gstate_stack.pop()
        elif op == "gs":
            gs_name = str(operands[0])
            if gs_name in gstate_props:
                props = gstate_props[gs_name]
                current_gstate["ca"] = props["ca"]
                current_gstate["BM"] = props["BM"]
                if props["SMask"]:
                    current_gstate["SMask"] = True
        elif op == "Do":
            z_order += 1
            results.append({
                "xobj_name": str(operands[0]),
                "z_order": z_order,
                "ca": current_gstate["ca"],
                "BM": current_gstate["BM"],
                "gstate_smask": current_gstate["SMask"],
            })

    return results


def enrich_image_transparency(label_to_info, placements,
                              gstate_per_do, page_pk):
    """
    Enrich each image's info with transparency properties.

    Returns: {label: {z_order, opacity, blend_mode,
                      has_smask, in_transparency_group}}
    """
    transparency = {}
    xobjects = page_pk.get("/Resources", {}).get("/XObject", {})

    # gstate_per_do is a list aligned with placements by z_order.
    # Build lookup: z_order -> gstate info
    gstate_by_z = {g["z_order"]: g for g in gstate_per_do}

    labels_in_order = sorted(label_to_info.keys())
    for label in labels_in_order:
        info = label_to_info[label]

        t = {
            "z_order": info["z_order"],
            "opacity": 1.0,
            "blend_mode": "/Normal",
            "has_smask": False,
            "in_transparency_group": False,
        }

        # Look up the graphics state at the time of this Do
        gs = gstate_by_z.get(info["z_order"])
        if gs:
            t["opacity"] = gs["ca"]
            t["blend_mode"] = gs["BM"]
            if gs["gstate_smask"]:
                t["has_smask"] = True

        # Check Form XObject for transparency group and SMask
        form_xref = info.get("form_xref", 0)
        if form_xref:
            for xname, xref_ref in xobjects.items():
                try:
                    if xref_ref.objgen[0] != form_xref:
                        continue
                    resolved = (xref_ref.resolve()
                                if hasattr(xref_ref, "resolve")
                                else xref_ref)
                    if "/Group" in resolved:
                        group = resolved["/Group"]
                        if hasattr(group, "resolve"):
                            group = group.resolve()
                        if group.get("/S") == Name("/Transparency"):
                            t["in_transparency_group"] = True
                    if "/SMask" in resolved:
                        t["has_smask"] = True
                    break
                except Exception:
                    continue

        # Check Image XObject itself for SMask
        img_xref = info["xref"]
        for xname, xref_ref in xobjects.items():
            try:
                if xref_ref.objgen[0] != img_xref:
                    continue
                resolved = (xref_ref.resolve()
                            if hasattr(xref_ref, "resolve")
                            else xref_ref)
                if (resolved.get("/Subtype") == Name("/Image")
                        and "/SMask" in resolved):
                    t["has_smask"] = True
                break
            except Exception:
                continue

        transparency[label] = t

    return transparency


# ===================================================================
# FORM XOBJECT ANALYSIS (cropping / clipping / offset)
# ===================================================================

def analyze_form_xobject(form_xobj, xobj_name, page_num, findings,
                         image_labels):
    """Analyze a Form XObject for image cropping/clipping/offset."""
    label_str = ", ".join(image_labels) if image_labels else str(xobj_name)

    bbox_raw = form_xobj.get("/BBox")
    if not bbox_raw:
        return
    bbox = [float(x) for x in bbox_raw]
    bbox_x0, bbox_y0, bbox_x1, bbox_y1 = bbox

    try:
        ops = pikepdf.parse_content_stream(form_xobj)
    except Exception as e:
        findings.append({
            "image": label_str,
            "type": "PARSE_ERROR",
            "detail": f"Could not parse Form XObject stream: {e}",
        })
        return

    clip_rects = []
    cm_matrices = []
    has_clip = False
    current_rect = None
    image_refs = []

    for operands, operator in ops:
        op = str(operator)
        if op == "cm":
            cm_matrices.append([float(x) for x in operands])
        elif op == "re":
            current_rect = [float(x) for x in operands]
        elif op in ("W", "W*"):
            has_clip = True
            if current_rect:
                clip_rects.append(current_rect)
        elif op == "Do":
            image_refs.append(str(operands[0]))

    if not image_refs:
        return

    # --- Explicit clipping paths ---
    if has_clip:
        for cr in clip_rects:
            findings.append({
                "image": label_str,
                "type": "EXPLICIT_CLIP",
                "detail": (
                    f"Clipping rectangle applied before image is painted.\n"
                    f"    Clip rect: x={cr[0]:.3f} y={cr[1]:.3f} "
                    f"w={cr[2]:.3f} h={cr[3]:.3f}\n"
                    f"    BBox:      ({bbox_x0:.3f}, {bbox_y0:.3f}) to "
                    f"({bbox_x1:.3f}, {bbox_y1:.3f})\n"
                    f"    Content outside the clip rectangle is hidden."
                ),
            })

    # --- Transformation matrix vs BBox ---
    for cm in cm_matrices:
        a, b, c, d, e, f = cm

        if b == 0.0 and c == 0.0:
            img_x0, img_y0 = e, f
            img_x1, img_y1 = e + a, f + d

            hidden_left = max(0, bbox_x0 - img_x0)
            hidden_right = max(0, img_x1 - bbox_x1)
            hidden_bottom = max(0, bbox_y0 - img_y0)
            hidden_top = max(0, img_y1 - bbox_y1)

            if any(h > HIDDEN_THRESHOLD_PTS
                   for h in (hidden_left, hidden_right,
                             hidden_bottom, hidden_top)):

                edge_details = []
                if hidden_bottom > HIDDEN_THRESHOLD_PTS:
                    edge_details.append(
                        f"Bottom: {hidden_bottom:.3f} pts hidden "
                        f"(image starts at y={img_y0:.3f}, "
                        f"BBox starts at y={bbox_y0:.3f})")
                if hidden_top > HIDDEN_THRESHOLD_PTS:
                    edge_details.append(
                        f"Top: {hidden_top:.3f} pts hidden "
                        f"(image ends at y={img_y1:.3f}, "
                        f"BBox ends at y={bbox_y1:.3f})")
                if hidden_left > HIDDEN_THRESHOLD_PTS:
                    edge_details.append(
                        f"Left: {hidden_left:.3f} pts hidden "
                        f"(image starts at x={img_x0:.3f}, "
                        f"BBox starts at x={bbox_x0:.3f})")
                if hidden_right > HIDDEN_THRESHOLD_PTS:
                    edge_details.append(
                        f"Right: {hidden_right:.3f} pts hidden "
                        f"(image ends at x={img_x1:.3f}, "
                        f"BBox ends at x={bbox_x1:.3f})")

                img_area = abs(a * d)
                visible_w = min(img_x1, bbox_x1) - max(img_x0, bbox_x0)
                visible_h = min(img_y1, bbox_y1) - max(img_y0, bbox_y0)
                visible_area = max(0, visible_w) * max(0, visible_h)
                hidden_pct = ((img_area - visible_area) / img_area * 100
                              if img_area > 0 else 0)

                findings.append({
                    "image": label_str,
                    "type": "BBOX_CROP",
                    "detail": (
                        f"Image extends beyond Form XObject BBox. "
                        f"~{hidden_pct:.1f}% of image is hidden.\n"
                        f"    Transformation matrix: "
                        f"[{a:.3f}, {b:.3f}, {c:.3f}, "
                        f"{d:.3f}, {e:.3f}, {f:.3f}]\n"
                        f"    Image area:  ({img_x0:.3f}, {img_y0:.3f}) to "
                        f"({img_x1:.3f}, {img_y1:.3f})\n"
                        f"    BBox area:   ({bbox_x0:.3f}, {bbox_y0:.3f}) to "
                        f"({bbox_x1:.3f}, {bbox_y1:.3f})\n"
                        f"    Hidden edges:\n"
                        + "\n".join(f"      - {ed}" for ed in edge_details)
                    ),
                })
        else:
            findings.append({
                "image": label_str,
                "type": "COMPLEX_TRANSFORM",
                "detail": (
                    f"Non-trivial transformation matrix detected: "
                    f"[{a:.3f}, {b:.3f}, {c:.3f}, "
                    f"{d:.3f}, {e:.3f}, {f:.3f}].\n"
                    f"    Image may be rotated or skewed. "
                    f"Manual review recommended."
                ),
            })

    # --- Soft mask on Form XObject ---
    if "/SMask" in form_xobj:
        findings.append({
            "image": label_str,
            "type": "SOFT_MASK",
            "detail": (
                "Form XObject has a soft mask (SMask) applied. "
                "This may partially or fully obscure portions of "
                "the contained image."
            ),
        })


# ===================================================================
# OVERLAP ANALYSIS (transparency-aware)
# ===================================================================

def assess_concealment(front_opacity, front_blend_mode, front_has_smask):
    """Assess concealment level based on front image transparency."""
    if front_has_smask:
        return ("VARIABLE — front image has a soft mask; concealment "
                "varies per-pixel. Manual review required.")
    if front_blend_mode != "/Normal":
        if front_opacity >= 1.0:
            return (f"PARTIAL — front image uses blend mode "
                    f"{front_blend_mode}; back image content bleeds "
                    f"through despite full opacity.")
        else:
            return (f"PARTIAL — front image uses blend mode "
                    f"{front_blend_mode} at {front_opacity:.0%} opacity; "
                    f"back image partially visible.")
    if front_opacity >= 1.0:
        return ("FULL — front image is fully opaque with normal blend "
                "mode. Back image is completely hidden in overlap region.")
    elif front_opacity > 0.0:
        return (f"PARTIAL — front image is {front_opacity:.0%} opaque. "
                f"Back image is partially visible through the overlap.")
    else:
        return "NONE — front image is fully transparent."


def check_overlapping_images(page_mu, page_num, findings,
                             label_to_info, transparency):
    """
    Detect overlapping images with transparency-aware concealment.
    Uses PyMuPDF get_image_rects for rendered positions, then maps
    back to our label system.
    """
    # Build list of (label, xref, rect) for every placement
    rects = []
    mu_images = page_mu.get_images(full=True)

    # For images where the same xref appears multiple times in our
    # label_to_info, we need to match by xref AND position.
    # get_image_rects(xref) returns all rendered positions for that xref.
    xref_rects_cache = {}

    for label, info in sorted(label_to_info.items()):
        xref = info["xref"]
        if xref not in xref_rects_cache:
            try:
                xref_rects_cache[xref] = list(
                    page_mu.get_image_rects(xref))
            except Exception:
                xref_rects_cache[xref] = []

    # Assign rects to labels. When multiple labels share the same xref,
    # assign rects in order.
    xref_rect_idx = {}  # tracks next rect index per xref
    for label in sorted(label_to_info.keys()):
        info = label_to_info[label]
        xref = info["xref"]
        available = xref_rects_cache.get(xref, [])
        idx = xref_rect_idx.get(xref, 0)

        if idx < len(available):
            rect = available[idx]
            xref_rect_idx[xref] = idx + 1
            if not rect.is_infinite and not rect.is_empty:
                rects.append((label, rect))

    # Check all pairs for overlap
    for (label_a, rect_a), (label_b, rect_b) in combinations(rects, 2):
        intersection = rect_a & rect_b
        if intersection.is_empty:
            continue
        overlap_area = intersection.get_area()
        if overlap_area < OVERLAP_THRESHOLD_SQPTS:
            continue

        smaller_area = min(rect_a.get_area(), rect_b.get_area())
        overlap_pct = (overlap_area / smaller_area * 100
                       if smaller_area > 0 else 0)

        # Determine front / back from z-order
        t_a = transparency.get(label_a, {})
        t_b = transparency.get(label_b, {})
        z_a = t_a.get("z_order", 0)
        z_b = t_b.get("z_order", 0)

        if z_a >= z_b:
            front_label, back_label = label_a, label_b
            front_t = t_a
        else:
            front_label, back_label = label_b, label_a
            front_t = t_b

        front_opacity = front_t.get("opacity", 1.0)
        front_bm = front_t.get("blend_mode", "/Normal")
        front_smask = front_t.get("has_smask", False)

        concealment = assess_concealment(front_opacity, front_bm,
                                         front_smask)

        findings.append({
            "image": f"{front_label} / {back_label}",
            "type": "OVERLAP",
            "detail": (
                f"Two images overlap on the page.\n"
                f"    Front image: {front_label} "
                f"(z-order {front_t.get('z_order', '?')}, "
                f"opacity {front_opacity:.0%}, "
                f"blend mode {front_bm}"
                f"{', has SMask' if front_smask else ''})\n"
                f"    Back image:  {back_label}\n"
                f"    Overlap region: {intersection}\n"
                f"    Overlap covers ~{overlap_pct:.1f}% of the "
                f"smaller image.\n"
                f"    Concealment: {concealment}"
            ),
            "_overlap": {
                "front_label": front_label,
                "back_label": back_label,
                "overlap_area": overlap_area,
                "overlap_pct": overlap_pct,
                "front_opacity": front_opacity,
                "front_blend_mode": front_bm,
                "front_has_smask": front_smask,
                "concealment": concealment,
            },
        })


# ===================================================================
# IMAGE SMASK CHECK
# ===================================================================

def check_image_smasks(page_pk, page_num, findings, label_to_info):
    """Check for soft masks directly on Image XObjects."""
    xobjects = page_pk.get("/Resources", {}).get("/XObject", {})

    # Collect image xrefs that have SMask
    smask_xrefs = set()
    for xobj_name, xobj_ref in xobjects.items():
        try:
            resolved = (xobj_ref.resolve()
                        if hasattr(xobj_ref, "resolve") else xobj_ref)
        except Exception:
            continue
        if (resolved.get("/Subtype") == Name("/Image")
                and "/SMask" in resolved):
            try:
                smask_xrefs.add(xobj_ref.objgen[0])
            except Exception:
                continue

    # Map back to labels
    for label, info in sorted(label_to_info.items()):
        if info["xref"] in smask_xrefs:
            findings.append({
                "image": label,
                "type": "IMAGE_SMASK",
                "detail": (
                    "Image XObject has a soft mask (SMask) directly "
                    "applied. This may make portions of the image "
                    "transparent or partially obscured."
                ),
            })


# ===================================================================
# CONSOLE REPORTING
# ===================================================================

def print_report(all_findings):
    """Print findings to console."""
    print()
    print("=" * 60)
    print("FINDINGS")
    print("=" * 60)
    print()

    findings = []
    for page_findings in all_findings.values():
        findings.extend(page_findings)

    if not findings:
        print("No image manipulation indicators detected.")
        return

    type_counts = {}
    for f in findings:
        type_counts[f["type"]] = type_counts.get(f["type"], 0) + 1

    print(f"{len(findings)} finding(s) across "
          f"{len(type_counts)} category/categories:\n")
    for t, count in type_counts.items():
        label = FINDING_TYPE_DEFS.get(t, (t, ""))[0]
        print(f"  [{t}] {label}: {count}")
    print()

    high_severity = {"BBOX_CROP", "EXPLICIT_CLIP", "OVERLAP"}
    idx = 0
    for page_num in sorted(all_findings.keys()):
        for f in all_findings[page_num]:
            idx += 1
            severity = "!!!" if f["type"] in high_severity else " ! "
            print(f"--- Finding {idx} [{severity}] ---")
            print(f"  Page:    {page_num}")
            print(f"  Image:   {f['image']}")
            print(f"  Type:    {f['type']} - "
                  f"{FINDING_TYPE_DEFS.get(f['type'], ('',''))[0]}")
            print(f"  Detail:  {f['detail']}")
            print()


# ===================================================================
# DATABASE INSERTION
# ===================================================================

def save_to_db(conn, pdf_path, total_pages, page_data,
               pdf_metadata=None, pdf_versions=None,
               store_images=True):
    """Write all analysis results to the SQLite database."""
    cur = conn.cursor()

    # Compute MD5 of the PDF file
    pdf_md5 = hashlib.md5()
    with open(pdf_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            pdf_md5.update(chunk)
    pdf_md5_hex = pdf_md5.hexdigest()

    cur.execute("""
        INSERT INTO analyses (pdf_filename, pdf_path, pdf_size_bytes,
                              pdf_md5, total_pages, analyzed_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        os.path.basename(pdf_path),
        os.path.abspath(pdf_path),
        os.path.getsize(pdf_path),
        pdf_md5_hex,
        total_pages,
        datetime.now(timezone.utc).isoformat(),
    ))
    analysis_id = cur.lastrowid

    # Insert PDF metadata
    if pdf_metadata:
        for source, key, value in pdf_metadata:
            cur.execute("""
                INSERT INTO pdf_metadata (analysis_id, source, key, value)
                VALUES (?, ?, ?, ?)
            """, (analysis_id, source, key, value))

    # Insert PDF versions (%%EOF markers)
    if pdf_versions:
        for version_num, offset in pdf_versions:
            cur.execute("""
                INSERT INTO pdf_versions
                    (analysis_id, version_number, eof_offset)
                VALUES (?, ?, ?)
            """, (analysis_id, version_num, offset))

    ft_ids = {}
    for code in FINDING_TYPE_DEFS:
        ft_ids[code] = get_finding_type_id(cur, code)

    for page_num in sorted(page_data.keys()):
        pd = page_data[page_num]

        cur.execute("""
            INSERT INTO pages (analysis_id, page_number) VALUES (?, ?)
        """, (analysis_id, page_num))
        page_id = cur.lastrowid

        label_to_info = pd["label_to_info"]
        transparency = pd["transparency"]

        # Insert unique image blobs into image_data (one per xref)
        xref_to_image_data_id = {}
        for label in sorted(label_to_info.keys()):
            info = label_to_info[label]
            xref = info["xref"]

            if xref in xref_to_image_data_id:
                continue  # already stored this xref

            image_bytes = info.get("image_bytes")
            if image_bytes:
                img_md5 = hashlib.md5(image_bytes).hexdigest()
                # Store blob only if requested; always store the
                # metadata row so findings can reference the image.
                blob_to_store = (sqlite3.Binary(image_bytes)
                                 if store_images else None)
                cur.execute("""
                    INSERT OR IGNORE INTO image_data
                        (analysis_id, xref, format_ext, width_px,
                         height_px, image_bytes, byte_size, md5_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    analysis_id,
                    xref,
                    info["ext"],
                    info["width"],
                    info["height"],
                    blob_to_store,
                    len(image_bytes),
                    img_md5,
                ))
                # Retrieve the id (INSERT OR IGNORE may not set lastrowid)
                cur.execute("""
                    SELECT id FROM image_data
                    WHERE analysis_id = ? AND xref = ?
                """, (analysis_id, xref))
                row = cur.fetchone()
                image_data_id = row[0] if row else None
                xref_to_image_data_id[xref] = image_data_id

                # Extract and store image metadata (EXIF, format info)
                if image_data_id is not None:
                    img_meta = extract_image_metadata(
                        image_bytes, info["ext"])
                    for source, mkey, mvalue in img_meta:
                        cur.execute("""
                            INSERT INTO image_metadata
                                (image_data_id, source, key, value)
                            VALUES (?, ?, ?, ?)
                        """, (image_data_id, source, mkey, mvalue))
            else:
                xref_to_image_data_id[xref] = None

        # Insert images
        label_to_image_id = {}
        for label in sorted(label_to_info.keys()):
            info = label_to_info[label]
            t = transparency.get(label, {})
            image_data_id = xref_to_image_data_id.get(info["xref"])

            cur.execute("""
                INSERT INTO images
                    (page_id, image_data_id, label,
                     z_order, opacity, blend_mode,
                     has_smask, in_transparency_group,
                     form_xobject_xref)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                page_id,
                image_data_id,
                label,
                t.get("z_order", info.get("z_order", 0)),
                t.get("opacity", 1.0),
                t.get("blend_mode", "/Normal"),
                1 if t.get("has_smask") else 0,
                1 if t.get("in_transparency_group") else 0,
                info.get("form_xref", 0),
            ))
            label_to_image_id[label] = cur.lastrowid

        # Insert findings
        for f in pd["findings"]:
            ft_id = ft_ids.get(f["type"])
            if ft_id is None:
                continue

            cur.execute("""
                INSERT INTO findings (page_id, finding_type_id, detail)
                VALUES (?, ?, ?)
            """, (page_id, ft_id, f["detail"]))
            finding_id = cur.lastrowid

            image_str = f.get("image", "")
            labels_in_finding = [
                lbl.strip() for lbl in image_str.split("/")
            ]

            if f["type"] == "OVERLAP" and "_overlap" in f:
                ol = f["_overlap"]
                front_id = label_to_image_id.get(ol["front_label"])
                back_id = label_to_image_id.get(ol["back_label"])

                if front_id:
                    cur.execute("""
                        INSERT INTO finding_images
                            (finding_id, image_id, role)
                        VALUES (?, ?, 'front')
                    """, (finding_id, front_id))
                if back_id:
                    cur.execute("""
                        INSERT INTO finding_images
                            (finding_id, image_id, role)
                        VALUES (?, ?, 'back')
                    """, (finding_id, back_id))

                if front_id and back_id:
                    cur.execute("""
                        INSERT INTO overlap_details
                            (finding_id, front_image_id, back_image_id,
                             overlap_area_sqpts, overlap_pct,
                             front_opacity, front_blend_mode,
                             front_has_smask, concealment_assessment)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        finding_id,
                        front_id,
                        back_id,
                        ol["overlap_area"],
                        ol["overlap_pct"],
                        ol["front_opacity"],
                        ol["front_blend_mode"],
                        1 if ol["front_has_smask"] else 0,
                        ol["concealment"],
                    ))
            else:
                for lbl in labels_in_finding:
                    for sub_lbl in lbl.split(","):
                        sub_lbl = sub_lbl.strip()
                        img_id = label_to_image_id.get(sub_lbl)
                        if img_id:
                            cur.execute("""
                                INSERT INTO finding_images
                                    (finding_id, image_id, role)
                                VALUES (?, ?, 'subject')
                            """, (finding_id, img_id))

    conn.commit()


# ===================================================================
# MAIN ANALYSIS
# ===================================================================

def analyze_pdf(pdf_path, db_path, extract_dir=None,
                store_images=True, conn=None):
    """
    Analyze a single PDF.

    Parameters:
      pdf_path     : path to the PDF file
      db_path      : SQLite database file (created if missing)
      extract_dir  : directory to write extracted image files to;
                     None means do not write images to disk
      store_images : whether to store image bytes inside the database
      conn         : optional pre-opened sqlite connection (for batch
                     processing); if None, one is opened and closed

    Returns a dict summarising the run.
    """
    if not os.path.isfile(pdf_path):
        print(f"Error: File not found: {pdf_path}")
        return None

    print("PDF Forensics")
    print("=" * 60)
    print(f"  File:     {os.path.basename(pdf_path)}")
    print(f"  Path:     {os.path.abspath(pdf_path)}")
    print(f"  Size:     {os.path.getsize(pdf_path):,} bytes")
    print(f"  Database: {os.path.abspath(db_path)}")
    print(f"  Store images in DB: {'yes' if store_images else 'no'}")

    if extract_dir:
        os.makedirs(extract_dir, exist_ok=True)
        print(f"  Extract:  {os.path.abspath(extract_dir)}")
    else:
        print(f"  Extract:  (disk extraction disabled)")

    own_conn = False
    if conn is None:
        conn = init_db(db_path)
        own_conn = True

    doc_mu = pymupdf.open(pdf_path)
    doc_pk = pikepdf.open(pdf_path)

    total_pages = len(doc_mu)
    page_pad = len(str(total_pages))
    print(f"  Pages:    {total_pages}")

    # Extract PDF metadata and detect prior versions
    pdf_metadata = extract_pdf_metadata(doc_pk, doc_mu)
    pdf_versions = detect_pdf_versions(pdf_path)
    print(f"  Metadata: {len(pdf_metadata)} entries")
    print(f"  Versions: {len(pdf_versions)} %%EOF marker(s)"
          + (" — incremental updates present!"
             if len(pdf_versions) > 1 else ""))
    print()

    all_findings = {}
    page_data = {}
    total_extracted = 0

    for page_idx in range(total_pages):
        page_num = page_idx + 1
        page_mu = doc_mu[page_idx]
        page_pk = doc_pk.pages[page_idx]

        # Build image map from content stream
        placements, label_to_info, xref_to_labels, \
            form_xref_to_labels = \
            build_image_map(page_pk, page_num, page_pad, doc_mu)

        img_count = len(label_to_info)
        print(f"  Page {page_num}: {img_count} image(s)")
        for label in sorted(label_to_info.keys()):
            info = label_to_info[label]
            print(f"    {label}.{info['ext']}")

            # Write image to extraction directory (if requested)
            if extract_dir and info.get("image_bytes"):
                filename = f"{label}.{info['ext']}"
                filepath = os.path.join(extract_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(info["image_bytes"])
                total_extracted += 1

        # Z-order and graphics state
        gstate_per_do = get_zorder_and_graphics_state(page_pk)
        transparency = enrich_image_transparency(
            label_to_info, placements, gstate_per_do, page_pk
        )

        # Print transparency info
        for label, t in sorted(transparency.items()):
            parts = [f"z={t['z_order']}"]
            if t["opacity"] < 1.0:
                parts.append(f"opacity={t['opacity']:.0%}")
            if t["blend_mode"] != "/Normal":
                parts.append(f"blend={t['blend_mode']}")
            if t["has_smask"]:
                parts.append("SMask")
            if t["in_transparency_group"]:
                parts.append("TransparencyGroup")
            if len(parts) > 1 or t["opacity"] < 1.0 or t["has_smask"]:
                print(f"      {label}: {', '.join(parts)}")

        findings = []

        # Analyze Form XObjects for cropping / clipping
        xobjects = page_pk.get("/Resources", {}).get("/XObject", {})
        analyzed_forms = set()
        for xobj_name, xobj_ref in xobjects.items():
            try:
                resolved = (xobj_ref.resolve()
                            if hasattr(xobj_ref, "resolve")
                            else xobj_ref)
            except Exception:
                continue
            if resolved.get("/Subtype") != Name("/Form"):
                continue

            form_objnum = (xobj_ref.objgen[0]
                           if hasattr(xobj_ref, "objgen") else None)

            if form_objnum in analyzed_forms:
                continue
            analyzed_forms.add(form_objnum)

            image_labels = form_xref_to_labels.get(form_objnum, [])
            analyze_form_xobject(resolved, xobj_name, page_num,
                                 findings, image_labels)

        check_overlapping_images(page_mu, page_num, findings,
                                 label_to_info, transparency)
        check_image_smasks(page_pk, page_num, findings, label_to_info)

        all_findings[page_num] = findings
        page_data[page_num] = {
            "label_to_info": label_to_info,
            "transparency": transparency,
            "findings": findings,
        }

    doc_mu.close()
    doc_pk.close()

    print_report(all_findings)

    save_to_db(conn, pdf_path, total_pages, page_data,
               pdf_metadata=pdf_metadata,
               pdf_versions=pdf_versions,
               store_images=store_images)
    if own_conn:
        conn.close()

    total_findings = sum(len(f) for f in all_findings.values())
    print(f"Results saved to: {os.path.abspath(db_path)}")
    print(f"  {total_findings} finding(s) recorded.")
    if extract_dir:
        print(f"  {total_extracted} image(s) extracted to: "
              f"{os.path.abspath(extract_dir)}")
    print(f"  {len(pdf_metadata)} metadata entries stored.")
    print(f"  {len(pdf_versions)} version marker(s) stored.")

    return {
        "pdf": pdf_path,
        "db": os.path.abspath(db_path),
        "extract_dir": (os.path.abspath(extract_dir)
                        if extract_dir else None),
        "total_pages": total_pages,
        "total_findings": total_findings,
        "total_extracted": total_extracted,
        "metadata_count": len(pdf_metadata),
        "version_count": len(pdf_versions),
    }


def process_pdfs(pdf_paths, db_path, output_dir=None,
                 store_images=True, extract_to_disk=True):
    """
    Process one or more PDFs in a single batch.

    For each PDF, an extraction subfolder is created under
    output_dir (named after the PDF basename without extension).
    If output_dir is None and extract_to_disk is True, defaults to
    a per-PDF folder in the current working directory.
    """
    conn = init_db(db_path)
    summaries = []

    for pdf_path in pdf_paths:
        if not os.path.isfile(pdf_path):
            print(f"Skipping (not found): {pdf_path}")
            continue

        if extract_to_disk:
            base = os.path.splitext(os.path.basename(pdf_path))[0]
            if output_dir:
                pdf_extract_dir = os.path.join(output_dir, base)
            else:
                pdf_extract_dir = base + "_images"
        else:
            pdf_extract_dir = None

        summary = analyze_pdf(
            pdf_path, db_path,
            extract_dir=pdf_extract_dir,
            store_images=store_images,
            conn=conn,
        )
        if summary:
            summaries.append(summary)
        print()

    conn.close()
    return summaries


# ===================================================================
# OS HELPERS
# ===================================================================

def open_in_file_manager(path):
    """Open a file or folder in the host's file manager."""
    import subprocess
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        print(f"Could not open {path}: {e}")


# ===================================================================
# GUI
# ===================================================================

def launch_gui(initial_pdfs=None, initial_db=None,
               initial_output=None, initial_store_images=True):
    """Launch the tkinter GUI with an Adobe-inspired theme."""
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    # ----- Color palette (inspired by Adobe Acrobat) -----
    BG_DARK     = "#1B1B1B"   # window background
    BG_PANEL    = "#252525"   # panel/frame background
    BG_INPUT    = "#363636"   # input fields
    BG_HOVER    = "#3A3A3A"
    BORDER      = "#3D3D3D"
    TEXT_PRIM   = "#F0F0F0"
    TEXT_SEC    = "#A8A8A8"
    TEXT_DIM    = "#7A7A7A"
    ACCENT      = "#ED1C24"   # Adobe red
    ACCENT_HVR  = "#FA0F00"
    ACCENT_PRSS = "#B30B00"
    SUCCESS     = "#4CAF50"

    if sys.platform == "win32":
        FONT_FAMILY = "Segoe UI"
    elif sys.platform == "darwin":
        FONT_FAMILY = "SF Pro Text"
    else:
        FONT_FAMILY = "DejaVu Sans"

    FONT_BASE = (FONT_FAMILY, 10)
    FONT_BOLD = (FONT_FAMILY, 10, "bold")
    FONT_TITLE = (FONT_FAMILY, 22, "bold")
    FONT_SUBTITLE = (FONT_FAMILY, 9)
    FONT_SECTION = (FONT_FAMILY, 11, "bold")

    root = tk.Tk()
    root.title("PDF Forensics")
    root.geometry("900x780")
    root.minsize(860, 720)
    root.configure(bg=BG_DARK)

    style = ttk.Style(root)
    style.theme_use("clam")

    # ----- Base widget styles -----
    style.configure(".",
                    background=BG_DARK, foreground=TEXT_PRIM,
                    fieldbackground=BG_INPUT, font=FONT_BASE,
                    borderwidth=0, focuscolor=ACCENT)
    style.configure("TFrame", background=BG_DARK)
    style.configure("Panel.TFrame", background=BG_PANEL)
    style.configure("TLabel", background=BG_DARK,
                    foreground=TEXT_PRIM, font=FONT_BASE)
    style.configure("Panel.TLabel", background=BG_PANEL,
                    foreground=TEXT_PRIM, font=FONT_BASE)
    style.configure("Section.TLabel", background=BG_PANEL,
                    foreground=TEXT_SEC, font=FONT_SECTION)
    style.configure("Hint.TLabel", background=BG_PANEL,
                    foreground=TEXT_DIM, font=FONT_SUBTITLE)
    style.configure("Status.TLabel", background=BG_DARK,
                    foreground=TEXT_SEC, font=FONT_SUBTITLE)

    # ----- Entry -----
    style.configure("TEntry",
                    fieldbackground=BG_INPUT, foreground=TEXT_PRIM,
                    bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, insertcolor=TEXT_PRIM,
                    padding=6)
    style.map("TEntry",
              bordercolor=[("focus", ACCENT)],
              lightcolor=[("focus", ACCENT)],
              darkcolor=[("focus", ACCENT)])

    # ----- Buttons -----
    style.configure("TButton",
                    background=BG_INPUT, foreground=TEXT_PRIM,
                    bordercolor=BORDER, lightcolor=BG_INPUT,
                    darkcolor=BG_INPUT, focusthickness=0,
                    padding=(14, 8), font=FONT_BASE,
                    relief="flat")
    style.map("TButton",
              background=[("active", BG_HOVER),
                          ("pressed", BG_DARK)],
              bordercolor=[("active", ACCENT)],
              foreground=[("disabled", TEXT_DIM)])

    style.configure("Accent.TButton",
                    background=ACCENT, foreground="#FFFFFF",
                    bordercolor=ACCENT, lightcolor=ACCENT,
                    darkcolor=ACCENT, padding=(20, 10),
                    font=FONT_BOLD, relief="flat")
    style.map("Accent.TButton",
              background=[("active", ACCENT_HVR),
                          ("pressed", ACCENT_PRSS),
                          ("disabled", "#5A2020")],
              bordercolor=[("active", ACCENT_HVR),
                           ("pressed", ACCENT_PRSS)],
              foreground=[("disabled", "#A89090")])

    style.configure("Danger.TButton",
                    background=BG_INPUT, foreground="#E68080",
                    bordercolor=BORDER, lightcolor=BG_INPUT,
                    darkcolor=BG_INPUT, padding=(14, 8),
                    font=FONT_BASE, relief="flat")
    style.map("Danger.TButton",
              background=[("active", "#3A2222"),
                          ("pressed", BG_DARK)],
              bordercolor=[("active", ACCENT)])

    # ----- Checkbutton -----
    style.configure("TCheckbutton",
                    background=BG_PANEL, foreground=TEXT_PRIM,
                    indicatorcolor=BG_INPUT, focuscolor=ACCENT,
                    font=FONT_BASE, padding=4)
    style.map("TCheckbutton",
              indicatorcolor=[("selected", ACCENT),
                              ("active", BG_HOVER)],
              background=[("active", BG_PANEL)])

    # ===================================================================
    # Header bar with logo/title
    # ===================================================================
    header = tk.Frame(root, bg=BG_DARK, height=80)
    header.pack(fill="x", side="top")
    header.pack_propagate(False)

    header_inner = tk.Frame(header, bg=BG_DARK)
    header_inner.pack(side="left", padx=24, pady=14)

    # "PDF" badge in red square
    badge = tk.Frame(header_inner, bg=ACCENT, width=52, height=52)
    badge.pack(side="left")
    badge.pack_propagate(False)
    tk.Label(badge, text="PDF", bg=ACCENT, fg="#FFFFFF",
             font=(FONT_FAMILY, 14, "bold")).place(
        relx=0.5, rely=0.5, anchor="center")

    # Title beside badge
    title_block = tk.Frame(header_inner, bg=BG_DARK)
    title_block.pack(side="left", padx=(14, 0))
    tk.Label(title_block, text="PDF FORENSICS", bg=BG_DARK,
             fg=TEXT_PRIM, font=(FONT_FAMILY, 18, "bold")).pack(
        anchor="w")
    tk.Label(title_block,
             text="Image and metadata analysis for PDF documents",
             bg=BG_DARK, fg=TEXT_SEC,
             font=(FONT_FAMILY, 9)).pack(anchor="w")

    # Red accent line under header
    tk.Frame(root, bg=ACCENT, height=2).pack(fill="x")

    # ===================================================================
    # State
    # ===================================================================
    pdf_files = list(initial_pdfs) if initial_pdfs else []
    db_path_var = tk.StringVar(
        value=initial_db or "pdf_forensics.db")
    output_dir_var = tk.StringVar(value=initial_output or "")
    store_images_var = tk.BooleanVar(value=initial_store_images)

    # ===================================================================
    # Main content area
    # ===================================================================
    content = tk.Frame(root, bg=BG_DARK)
    # Note: content.pack is deferred until after the bottom bars
    # are packed, so they reserve their space first.

    def make_panel(parent, label_text):
        """Create a styled panel with a section heading."""
        outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        outer.pack(fill="x", pady=(0, 12))
        inner = tk.Frame(outer, bg=BG_PANEL)
        inner.pack(fill="x", padx=0, pady=0)
        ttk.Label(inner, text=label_text.upper(),
                  style="Section.TLabel").pack(
            anchor="w", padx=14, pady=(10, 4))
        body = tk.Frame(inner, bg=BG_PANEL)
        body.pack(fill="x", padx=14, pady=(0, 12))
        return body

    # ----- PDF files panel -----
    pdf_body = make_panel(content, "PDF files")

    list_container = tk.Frame(pdf_body, bg=BORDER, padx=1, pady=1)
    list_container.pack(fill="x", pady=(0, 8))
    pdf_listbox = tk.Listbox(
        list_container, height=6,
        bg=BG_INPUT, fg=TEXT_PRIM,
        selectbackground=ACCENT, selectforeground="#FFFFFF",
        highlightthickness=0, borderwidth=0,
        font=FONT_BASE, activestyle="none",
    )
    pdf_listbox.pack(fill="x", expand=True)
    for p in pdf_files:
        pdf_listbox.insert("end", p)

    def add_pdfs():
        paths = filedialog.askopenfilenames(
            title="Select PDF file(s)",
            filetypes=[("PDF files", "*.pdf"),
                       ("All files", "*.*")],
        )
        for p in paths:
            if p not in pdf_files:
                pdf_files.append(p)
                pdf_listbox.insert("end", p)

    def remove_pdfs():
        selected = list(pdf_listbox.curselection())
        for idx in reversed(selected):
            del pdf_files[idx]
            pdf_listbox.delete(idx)

    pdf_btns = tk.Frame(pdf_body, bg=BG_PANEL)
    pdf_btns.pack(fill="x")
    ttk.Button(pdf_btns, text="Add PDFs",
               command=add_pdfs).pack(side="left")
    ttk.Button(pdf_btns, text="Remove selected",
               command=remove_pdfs).pack(side="left", padx=(8, 0))

    # ----- Database panel -----
    db_body = make_panel(content, "Database")
    db_row = tk.Frame(db_body, bg=BG_PANEL)
    db_row.pack(fill="x")
    db_entry = ttk.Entry(db_row, textvariable=db_path_var)
    db_entry.pack(side="left", fill="x", expand=True,
                  padx=(0, 8))

    def choose_db():
        path = filedialog.asksaveasfilename(
            title="Select or create database file",
            defaultextension=".db",
            filetypes=[("SQLite database",
                        "*.db *.sqlite *.sqlite3"),
                       ("All files", "*.*")],
            confirmoverwrite=False,
        )
        if path:
            db_path_var.set(path)

    ttk.Button(db_row, text="Browse",
               command=choose_db).pack(side="left")
    ttk.Label(db_body,
              text="Existing databases will be appended to.",
              style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

    # ----- Output folder panel -----
    out_body = make_panel(content, "Output folder")
    out_row = tk.Frame(out_body, bg=BG_PANEL)
    out_row.pack(fill="x")
    out_entry = ttk.Entry(out_row, textvariable=output_dir_var)
    out_entry.pack(side="left", fill="x", expand=True,
                   padx=(0, 8))

    def choose_output():
        while True:
            path = filedialog.askdirectory(
                title="Select output folder (must be empty)")
            if not path:
                return
            try:
                contents = os.listdir(path)
            except Exception as e:
                messagebox.showerror(
                    "Error", f"Could not read folder:\n{e}")
                continue
            if contents:
                messagebox.showwarning(
                    "Folder not empty",
                    "The selected folder is not empty.\n\n"
                    "Please choose an empty folder to avoid "
                    "naming conflicts with the per-PDF "
                    "subfolders that will be created.")
                continue
            output_dir_var.set(path)
            return

    ttk.Button(out_row, text="Browse",
               command=choose_output).pack(side="left")
    ttk.Label(out_body,
              text="One subfolder per PDF will be created here.",
              style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

    # ----- Options panel -----
    opt_body = make_panel(content, "Options")
    ttk.Checkbutton(
        opt_body,
        text="Store extracted images inside the database",
        variable=store_images_var,
    ).pack(anchor="w")

    # ----- Status bar -----
    status_var = tk.StringVar(value="Ready")
    status_frame = tk.Frame(root, bg=BG_PANEL, height=32)
    status_frame.pack(fill="x", side="bottom")
    status_frame.pack_propagate(False)
    tk.Frame(status_frame, bg=BORDER, height=1).pack(fill="x",
                                                     side="top")
    status_label = tk.Label(status_frame, textvariable=status_var,
                            bg=BG_PANEL, fg=TEXT_SEC,
                            font=FONT_SUBTITLE, anchor="w")
    status_label.pack(side="left", padx=14, fill="y")

    # ----- Action button row (above status) -----
    action_row = tk.Frame(root, bg=BG_DARK)
    action_row.pack(fill="x", side="bottom", padx=20, pady=(0, 12))

    def exit_app():
        root.destroy()

    exit_btn = ttk.Button(action_row, text="Exit",
                          style="Danger.TButton", command=exit_app)
    exit_btn.pack(side="left")

    def run_analysis():
        if not pdf_files:
            messagebox.showerror(
                "No PDFs selected",
                "Please add at least one PDF file.")
            return
        if not db_path_var.get():
            messagebox.showerror(
                "No database selected",
                "Please choose a database file.")
            return
        if not output_dir_var.get():
            messagebox.showerror(
                "No output folder",
                "Please choose an output folder.")
            return

        run_btn.config(state="disabled")
        exit_btn.config(state="disabled")
        status_var.set("Processing...")
        status_label.config(fg=ACCENT)
        root.update_idletasks()

        try:
            summaries = process_pdfs(
                list(pdf_files),
                db_path_var.get(),
                output_dir=output_dir_var.get(),
                store_images=store_images_var.get(),
                extract_to_disk=True,
            )
            status_var.set(
                f"Done. Processed {len(summaries)} PDF(s).")
            status_label.config(fg=SUCCESS)
            show_summary(summaries)
        except Exception as e:
            status_var.set(f"Error: {e}")
            status_label.config(fg=ACCENT)
            messagebox.showerror(
                "Error", f"{type(e).__name__}: {e}")
        finally:
            run_btn.config(state="normal")
            exit_btn.config(state="normal")

    run_btn = ttk.Button(action_row, text="Run analysis",
                         style="Accent.TButton",
                         command=run_analysis)
    run_btn.pack(side="right")

    # Now pack the content frame — fills remaining space between
    # the header and the action/status bars.
    content.pack(fill="both", expand=True, padx=20, pady=16)

    # ===================================================================
    # Summary window
    # ===================================================================
    def show_summary(summaries):
        win = tk.Toplevel(root)
        win.title("Analysis complete")
        win.geometry("680x500")
        win.configure(bg=BG_DARK)
        win.transient(root)

        # Header
        sm_header = tk.Frame(win, bg=BG_DARK, height=70)
        sm_header.pack(fill="x")
        sm_header.pack_propagate(False)
        tk.Label(sm_header, text="✓",
                 bg=BG_DARK, fg=SUCCESS,
                 font=(FONT_FAMILY, 28, "bold")).pack(
            side="left", padx=(20, 12), pady=14)
        title_blk = tk.Frame(sm_header, bg=BG_DARK)
        title_blk.pack(side="left", pady=14)
        tk.Label(title_blk, text="Analysis complete",
                 bg=BG_DARK, fg=TEXT_PRIM,
                 font=(FONT_FAMILY, 16, "bold")).pack(anchor="w")
        tk.Label(title_blk,
                 text=f"Processed {len(summaries)} PDF(s)",
                 bg=BG_DARK, fg=TEXT_SEC,
                 font=FONT_SUBTITLE).pack(anchor="w")

        tk.Frame(win, bg=ACCENT, height=2).pack(fill="x")

        # Stats row
        total_findings = sum(s["total_findings"] for s in summaries)
        total_extracted = sum(s["total_extracted"] for s in summaries)
        total_metadata = sum(s["metadata_count"] for s in summaries)

        stats_row = tk.Frame(win, bg=BG_DARK)
        stats_row.pack(fill="x", padx=20, pady=(16, 8))

        def stat_box(parent, label, value):
            box = tk.Frame(parent, bg=BG_PANEL, padx=16, pady=12)
            box.pack(side="left", fill="x", expand=True, padx=4)
            tk.Label(box, text=str(value), bg=BG_PANEL,
                     fg=ACCENT,
                     font=(FONT_FAMILY, 18, "bold")).pack(anchor="w")
            tk.Label(box, text=label, bg=BG_PANEL, fg=TEXT_SEC,
                     font=FONT_SUBTITLE).pack(anchor="w")

        stat_box(stats_row, "FINDINGS", total_findings)
        stat_box(stats_row, "IMAGES EXTRACTED", total_extracted)
        stat_box(stats_row, "METADATA ENTRIES", total_metadata)

        # Detail text
        detail_outer = tk.Frame(win, bg=BORDER, padx=1, pady=1)
        detail_outer.pack(fill="both", expand=True,
                          padx=20, pady=8)
        txt = tk.Text(detail_outer, wrap="word",
                      bg=BG_PANEL, fg=TEXT_PRIM,
                      insertbackground=TEXT_PRIM,
                      highlightthickness=0, borderwidth=0,
                      font=(FONT_FAMILY, 9), padx=14, pady=12,
                      relief="flat")
        txt.pack(fill="both", expand=True)
        txt.tag_configure("heading", foreground=ACCENT,
                          font=(FONT_FAMILY, 10, "bold"))
        txt.tag_configure("dim", foreground=TEXT_SEC)

        for s in summaries:
            txt.insert("end",
                       f"{os.path.basename(s['pdf'])}\n",
                       "heading")
            txt.insert("end",
                       f"  Pages: {s['total_pages']}    "
                       f"Findings: {s['total_findings']}    "
                       f"Images: {s['total_extracted']}\n",
                       "dim")
            txt.insert("end",
                       f"  Metadata: {s['metadata_count']}    "
                       f"Versions: {s['version_count']}\n",
                       "dim")
            txt.insert("end",
                       f"  Output: {s['extract_dir']}\n\n",
                       "dim")
        txt.config(state="disabled")

        # Button row
        btn_row = tk.Frame(win, bg=BG_DARK)
        btn_row.pack(fill="x", padx=20, pady=(8, 16))

        db_dir = os.path.dirname(
            os.path.abspath(db_path_var.get())) or "."
        ttk.Button(
            btn_row, text="Open database folder",
            command=lambda: open_in_file_manager(db_dir),
        ).pack(side="left")
        ttk.Button(
            btn_row, text="Open output folder",
            command=lambda: open_in_file_manager(
                output_dir_var.get()),
        ).pack(side="left", padx=8)
        ttk.Button(
            btn_row, text="Close", style="Accent.TButton",
            command=win.destroy
        ).pack(side="right")

    root.mainloop()


# ===================================================================
# CLI ENTRY POINT
# ===================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="PDF Image Forensic Analyzer")
    parser.add_argument("pdf", nargs="*",
                        help="Input PDF file(s)")
    parser.add_argument("-d", "--database",
                        default="pdf_forensics.db",
                        help="SQLite database path "
                             "(default: pdf_forensics.db)")
    parser.add_argument("-e", "--extract-dir",
                        default=None,
                        help="Output directory. For multiple PDFs, "
                             "a subfolder per PDF is created here. "
                             "Default: per-PDF folder in CWD.")
    parser.add_argument("--no-store-images",
                        action="store_true",
                        help="Do not store image blobs inside the "
                             "database (default is to store them).")
    parser.add_argument("--gui", action="store_true",
                        help="Launch the graphical interface. "
                             "Other CLI options are passed in as "
                             "initial values.")
    args = parser.parse_args()

    store_images = not args.no_store_images

    if args.gui:
        launch_gui(
            initial_pdfs=args.pdf,
            initial_db=args.database,
            initial_output=args.extract_dir,
            initial_store_images=store_images,
        )
    else:
        if not args.pdf:
            parser.error("at least one PDF is required (or use --gui)")

        summaries = process_pdfs(
            args.pdf,
            args.database,
            output_dir=args.extract_dir,
            store_images=store_images,
            extract_to_disk=True,
        )

        print()
        print("=" * 60)
        print("Batch summary")
        print("=" * 60)
        print(f"Database: {os.path.abspath(args.database)}")
        for s in summaries:
            print(f"  {os.path.basename(s['pdf'])}: "
                  f"{s['total_findings']} finding(s), "
                  f"{s['total_extracted']} image(s) -> "
                  f"{s['extract_dir']}")
