"""
Forensic finding detectors: Form XObject analysis, overlap detection,
soft mask checks, off-page image detection.
"""

import pymupdf
import pikepdf
from pikepdf import Name
from itertools import combinations


OVERLAP_THRESHOLD_SQPTS = 1.0
OFFPAGE_THRESHOLD_PTS = 1.0
HIDDEN_THRESHOLD_PTS = 0.5


def _page_content_locator(page_pk):
    """
    Build a human-readable locator for a page's content stream(s),
    listing the PDF object number(s) of the /Contents stream(s) so a
    forensic examiner can open them in peepdf / qpdf / mutool and validate
    a content-stream overlay finding. Returns a string, or None on failure.

    A page's /Contents may be a single stream object or an array of stream
    objects (the rendered content is their concatenation); both are
    reported.
    """
    try:
        contents = page_pk.get("/Contents")
    except Exception:
        contents = None
    if contents is None:
        return None

    objs = []
    try:
        if isinstance(contents, pikepdf.Array):
            for item in contents:
                try:
                    objs.append(item.objgen)
                except Exception:
                    pass
        else:
            objs.append(contents.objgen)
    except Exception:
        return None

    if not objs:
        return None

    refs = ", ".join(f"{n} {g} R" for (n, g) in objs)
    if len(objs) > 1:
        return (f"Page content stream array (objects {refs}); "
                f"overlay operators are in the concatenated stream")
    return f"Page content stream object {refs}"


def _page_content_objgen(page_pk):
    """Return (obj_num, obj_gen) of the first /Contents stream, or
    (None, None). Used to populate the structured locator columns."""
    try:
        contents = page_pk.get("/Contents")
        if isinstance(contents, pikepdf.Array):
            return contents[0].objgen
        return contents.objgen
    except Exception:
        return (None, None)


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


def check_offpage_images(page_mu, page_num, findings, label_to_info):
    """
    Detect images that extend beyond the page's visible boundary.

    Uses the page's CropBox (the visible area for typical viewers)
    rather than the MediaBox, because a PDF's MediaBox can include
    bleed area that viewers crop away. If CropBox is not defined,
    falls back to MediaBox.

    Each image is checked against the page rectangle. If any portion
    of the image extends beyond an edge by more than
    OFFPAGE_THRESHOLD_PTS, an OFFPAGE finding is raised with the
    hidden percentage and per-edge breakdown.
    """
    # Get the page boundary - prefer CropBox over MediaBox
    try:
        page_rect = page_mu.cropbox
    except AttributeError:
        page_rect = page_mu.rect

    # Some PDFs have a degenerate cropbox; fall back to mediabox/rect
    if (page_rect is None or page_rect.is_empty
            or page_rect.is_infinite):
        page_rect = page_mu.rect

    image_list = page_mu.get_images(full=True)

    # Build label -> rect mapping using the same algorithm as
    # check_overlapping_images so labels stay consistent.
    xref_rects_cache = {}
    for label, info in sorted(label_to_info.items()):
        xref = info["xref"]
        if xref not in xref_rects_cache:
            try:
                xref_rects_cache[xref] = list(
                    page_mu.get_image_rects(xref))
            except Exception:
                xref_rects_cache[xref] = []

    xref_rect_idx = {}
    label_rects = []  # (label, rect)
    for label in sorted(label_to_info.keys()):
        info = label_to_info[label]
        xref = info["xref"]
        available = xref_rects_cache.get(xref, [])
        idx = xref_rect_idx.get(xref, 0)
        if idx < len(available):
            rect = available[idx]
            xref_rect_idx[xref] = idx + 1
            if not rect.is_infinite and not rect.is_empty:
                label_rects.append((label, rect))

    # PDF coordinate convention: y increases UPWARD. PyMuPDF's Rect
    # uses y0 (top in PDF space) and y1 (bottom). For comparison
    # we just use the numeric values consistently.
    px0 = page_rect.x0
    py0 = page_rect.y0
    px1 = page_rect.x1
    py1 = page_rect.y1

    for label, rect in label_rects:
        # How far does each edge of the image extend past the
        # corresponding edge of the page?
        off_left   = max(0, px0 - rect.x0)
        off_right  = max(0, rect.x1 - px1)
        off_top    = max(0, py0 - rect.y0)
        off_bottom = max(0, rect.y1 - py1)

        if not any(o > OFFPAGE_THRESHOLD_PTS for o in
                   (off_left, off_right, off_top, off_bottom)):
            continue

        # Compute hidden percentage of the image
        img_w = rect.x1 - rect.x0
        img_h = rect.y1 - rect.y0
        img_area = img_w * img_h

        visible_x0 = max(rect.x0, px0)
        visible_x1 = min(rect.x1, px1)
        visible_y0 = max(rect.y0, py0)
        visible_y1 = min(rect.y1, py1)
        visible_w = max(0, visible_x1 - visible_x0)
        visible_h = max(0, visible_y1 - visible_y0)
        visible_area = visible_w * visible_h
        hidden_pct = (((img_area - visible_area) / img_area * 100)
                      if img_area > 0 else 0)

        edges = []
        if off_left > OFFPAGE_THRESHOLD_PTS:
            edges.append(f"Left: {off_left:.2f} pts off page")
        if off_right > OFFPAGE_THRESHOLD_PTS:
            edges.append(f"Right: {off_right:.2f} pts off page")
        if off_top > OFFPAGE_THRESHOLD_PTS:
            edges.append(f"Top: {off_top:.2f} pts off page")
        if off_bottom > OFFPAGE_THRESHOLD_PTS:
            edges.append(f"Bottom: {off_bottom:.2f} pts off page")

        findings.append({
            "image": label,
            "type": "OFFPAGE",
            "detail": (
                f"Image extends beyond page boundary. "
                f"~{hidden_pct:.1f}% of image is off-page (clipped "
                f"by viewer to page bounds).\n"
                f"    Image rect: ({rect.x0:.2f}, {rect.y0:.2f}) to "
                f"({rect.x1:.2f}, {rect.y1:.2f})\n"
                f"    Page rect:  ({px0:.2f}, {py0:.2f}) to "
                f"({px1:.2f}, {py1:.2f})\n"
                f"    Off-page edges:\n"
                + "\n".join(f"      - {ed}" for ed in edges)
            ),
        })


# ===================================================================
# DPI Anomaly Detection (document-level)
# ===================================================================

DPI_STRETCH_THRESHOLD_PCT = 10   # flag if X/Y DPI differ by > 10%
DPI_OUTLIER_SPREAD = 50          # flag outliers if DPI range > 50
DPI_OUTLIER_DEVIATION_PCT = 30   # flag if > 30% from median


def check_dpi_anomalies(page_data):
    """
    Detect DPI anomalies across the entire document.

    Checks for:
    1. Stretched images (dpi_x != dpi_y by > threshold)
    2. Mixed-source indicators (images with very different DPIs)

    Parameters:
      page_data: {page_num: {"label_to_info": {...}, ...}}

    Returns a list of finding dicts to be added to the appropriate
    page's findings. Each has an extra "page_num" key.
    """
    findings = []

    # Collect all DPI values across the document
    all_dpis = []  # (page_num, label, dpi_x, dpi_y)
    for page_num, pd in page_data.items():
        label_to_info = pd.get("label_to_info", {})
        for label, info in label_to_info.items():
            dpi_x = info.get("dpi_x")
            dpi_y = info.get("dpi_y")
            if dpi_x and dpi_y and dpi_x > 0 and dpi_y > 0:
                all_dpis.append((page_num, label, dpi_x, dpi_y))

    if not all_dpis:
        return findings

    # Check 1: Stretched images (X/Y DPI mismatch)
    for page_num, label, dpi_x, dpi_y in all_dpis:
        avg_dpi = (dpi_x + dpi_y) / 2.0
        if avg_dpi > 0:
            diff_pct = abs(dpi_x - dpi_y) / avg_dpi * 100
            if diff_pct > DPI_STRETCH_THRESHOLD_PCT:
                findings.append({
                    "page_num": page_num,
                    "type": "DPI_ANOMALY",
                    "image": label,
                    "detail": (
                        f"Image is stretched/distorted: "
                        f"horizontal DPI={dpi_x}, "
                        f"vertical DPI={dpi_y} "
                        f"({diff_pct:.1f}% difference)"),
                })

    # Check 2: Mixed-source DPI outliers
    if len(all_dpis) < 2:
        return findings

    # Use the average of X and Y DPI as the effective DPI per image
    eff_dpis = [(pg, lbl, (dx + dy) / 2.0)
                for pg, lbl, dx, dy in all_dpis]

    dpis_only = sorted(d for _, _, d in eff_dpis)
    dpi_min = dpis_only[0]
    dpi_max = dpis_only[-1]
    dpi_spread = dpi_max - dpi_min

    if dpi_spread < DPI_OUTLIER_SPREAD:
        return findings

    # Compute median
    n = len(dpis_only)
    if n % 2 == 0:
        median_dpi = (dpis_only[n//2 - 1] + dpis_only[n//2]) / 2.0
    else:
        median_dpi = dpis_only[n//2]

    if median_dpi <= 0:
        return findings

    # Flag images that deviate significantly from the median
    for page_num, label, eff_dpi in eff_dpis:
        deviation_pct = abs(eff_dpi - median_dpi) / median_dpi * 100
        if deviation_pct > DPI_OUTLIER_DEVIATION_PCT:
            # Classify the source type
            if eff_dpi < 100:
                source_hint = "likely screenshot or web image"
            elif eff_dpi < 200:
                source_hint = "likely low-resolution or resized"
            elif eff_dpi < 350:
                source_hint = "likely standard scan or print"
            else:
                source_hint = "likely high-resolution photo or scan"

            findings.append({
                "page_num": page_num,
                "type": "DPI_ANOMALY",
                "image": label,
                "detail": (
                    f"Image DPI ({eff_dpi:.0f}) deviates from "
                    f"document median ({median_dpi:.0f}) by "
                    f"{deviation_pct:.0f}%. "
                    f"Document DPI range: {dpi_min:.0f}–{dpi_max:.0f}. "
                    f"Source: {source_hint}"),
            })

    return findings


# ===================================================================
# Text Overlay Detection (annotation-based and content-stream-based)
# ===================================================================

TEXT_OVERLAY_OPACITY_THRESHOLD = 0.95   # near-opaque background
TEXT_OVERLAY_MIN_AREA_SQPTS   = 4.0    # ignore tiny annotations


def _rect_to_fitz(rect_raw):
    """Convert a pikepdf /Rect array to (x0,y0,x1,y1) floats."""
    try:
        vals = [float(v) for v in rect_raw]
        if len(vals) == 4:
            x0, y0, x1, y1 = vals
            # Normalise (some PDFs have flipped corners)
            return (min(x0, x1), min(y0, y1),
                    max(x0, x1), max(y0, y1))
    except Exception:
        pass
    return None


def _rects_overlap(r1, r2):
    """Return True when two (x0,y0,x1,y1) rectangles intersect."""
    return (r1[0] < r2[2] and r1[2] > r2[0] and
            r1[1] < r2[3] and r1[3] > r2[1])


def _overlap_area(r1, r2):
    """Return the intersection area of two rectangles (0 if none)."""
    ix = max(0, min(r1[2], r2[2]) - max(r1[0], r2[0]))
    iy = max(0, min(r1[3], r2[3]) - max(r1[1], r2[1]))
    return ix * iy


def _has_opaque_background(annot_obj):
    """
    Return True when an annotation has an opaque or near-opaque
    background fill that would paint over content beneath it.

    Checks /MK dictionary (widget appearances) and /IC / /BG
    (FreeText annotations). White [1,1,1] and solid-colour fills
    both qualify.
    """
    # FreeText / general: /IC (interior colour)
    for key in ("/IC", "/BG"):
        try:
            val = annot_obj.get(key)
            if val is not None:
                # Any colour entry means a background is drawn
                return True
        except Exception:
            pass

    # Widget annotations: /MK dictionary
    try:
        mk = annot_obj.get("/MK")
        if mk:
            # /BG inside /MK = background colour
            bg = mk.get("/BG")
            if bg is not None:
                return True
    except Exception:
        pass

    # Check appearance stream for rectangle-fill operators
    # (re f or re B pattern before text drawing)
    try:
        ap = annot_obj.get("/AP")
        if ap:
            n_stream = ap.get("/N")
            if n_stream:
                ops = pikepdf.parse_content_stream(n_stream.obj
                      if hasattr(n_stream, "obj") else n_stream)
                has_rect = False
                for operands, operator in ops:
                    op = str(operator)
                    if op == "re":
                        has_rect = True
                    elif op in ("f", "F", "B", "B*", "b", "b*") \
                            and has_rect:
                        return True
                    elif op in ("BT", "Tj", "TJ", "\"", "'"):
                        # Text without preceding fill — no background
                        break
    except Exception:
        pass

    return False


def check_text_overlays(page_pk, page_mu, page_num, findings):
    """
    Detect text boxes / annotations placed over existing page text.

    Checks every annotation on the page with subtypes:
      /FreeText  — text box added by a PDF editor
      /Widget    — form field (may have opaque background)
      /Square    — filled rectangle (can cover text)
      /Redact    — redaction annotation (marks text for removal)

    An annotation is flagged as TEXT_OVERLAY when:
      1. Its /Rect overlaps with one or more text spans on the page
      2. It has an opaque/solid background (or is a Redact/Square)

    Findings are added to the `findings` list in-place.
    Returns the number of findings added.
    """
    added = 0

    # Get annotation array from pikepdf page
    try:
        annots_raw = page_pk.get("/Annots")
        if not annots_raw:
            return 0
        annots = list(annots_raw)
    except Exception:
        return 0

    if not annots:
        return 0

    # Collect text bounding boxes from PyMuPDF
    try:
        blocks = page_mu.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
        text_rects = []
        for block in blocks.get("blocks", []):
            if block.get("type") != 0:   # type 0 = text
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    bbox = span.get("bbox")
                    txt  = span.get("text", "").strip()
                    if bbox and txt:
                        # PyMuPDF uses top-left origin; PDF uses
                        # bottom-left. Convert for comparison.
                        x0, y0_pdf_top, x1, y1_pdf_top = bbox
                        text_rects.append((x0, y0_pdf_top,
                                           x1, y1_pdf_top, txt))
    except Exception:
        return 0

    if not text_rects:
        return 0

    # Page height for coordinate system conversion
    try:
        page_h = float(page_mu.rect.height)
    except Exception:
        page_h = 792.0

    for annot_ref in annots:
        try:
            annot_obj = (annot_ref.obj
                         if hasattr(annot_ref, "obj")
                         else annot_ref)
            if not hasattr(annot_obj, "get"):
                continue

            subtype = str(annot_obj.get("/Subtype") or "")

            # Only examine annotation types that can overlay text
            if subtype not in ("/FreeText", "/Widget",
                               "/Square", "/Redact"):
                continue

            rect_raw = annot_obj.get("/Rect")
            if rect_raw is None:
                continue

            annot_rect = _rect_to_fitz(rect_raw)
            if annot_rect is None:
                continue

            area = ((annot_rect[2] - annot_rect[0]) *
                    (annot_rect[3] - annot_rect[1]))
            if area < TEXT_OVERLAY_MIN_AREA_SQPTS:
                continue

            # Convert annotation rect from PDF coords (bottom-left
            # origin) to PyMuPDF coords (top-left origin)
            ax0 = annot_rect[0]
            ay0 = page_h - annot_rect[3]
            ax1 = annot_rect[2]
            ay1 = page_h - annot_rect[1]
            annot_mu_rect = (ax0, ay0, ax1, ay1)

            # Check for opaque background (mandatory for FreeText /
            # Widget; Redact and Square are always opaque by nature)
            if subtype in ("/FreeText", "/Widget"):
                if not _has_opaque_background(annot_obj):
                    continue

            # Check for overlap with page text
            overlapping_text = []
            for tr in text_rects:
                tx0, ty0, tx1, ty1, txt = tr
                if _rects_overlap(annot_mu_rect, (tx0, ty0, tx1, ty1)):
                    overlap = _overlap_area(
                        annot_mu_rect, (tx0, ty0, tx1, ty1))
                    if overlap >= TEXT_OVERLAY_MIN_AREA_SQPTS:
                        overlapping_text.append(txt[:80])

            if not overlapping_text:
                continue

            # Build detail string
            annot_contents = ""
            try:
                c = annot_obj.get("/Contents")
                if c:
                    annot_contents = str(c)[:120]
            except Exception:
                pass

            subtype_label = {
                "/FreeText": "FreeText annotation (text box)",
                "/Widget":   "Widget annotation (form field)",
                "/Square":   "Square/rectangle annotation",
                "/Redact":   "Redaction annotation",
            }.get(subtype, subtype)

            covered = "; ".join(
                f'"{t}"' for t in overlapping_text[:5])
            if len(overlapping_text) > 5:
                covered += f" (+{len(overlapping_text)-5} more)"

            detail = (
                f"{subtype_label} at "
                f"({annot_rect[0]:.1f}, {annot_rect[1]:.1f}) to "
                f"({annot_rect[2]:.1f}, {annot_rect[3]:.1f}) "
                f"overlaps existing page text: {covered}."
            )
            if annot_contents:
                detail += f" Annotation text: \"{annot_contents}\"."

            obj_num = obj_gen = None
            locator = None
            try:
                ref = (annot_ref if hasattr(annot_ref, "objgen")
                       else annot_obj)
                obj_num, obj_gen = ref.objgen
                locator = (f"Annotation object {obj_num} {obj_gen} R "
                           f"(/Subtype {subtype})")
            except Exception:
                pass

            findings.append({
                "type":   "TEXT_OVERLAY",
                "detail": detail,
                "image":  None,   # not image-specific
                "bbox":   annot_mu_rect,   # (x0,y0,x1,y1) top-left origin
                "overlay_kind": "annotation",
                "obj_num": obj_num,
                "obj_gen": obj_gen,
                "obj_locator": locator,
            })
            added += 1

        except Exception:
            continue

    return added


def check_content_stream_text_overlay(page_pk, page_mu, page_num, findings):
    """
    Detect text overlays implemented directly in the content stream:
    white (or near-white) filled rectangles followed by text drawn
    in the same region.

    This is Method 2 of text-based document alteration — the altering
    application paints a white box over existing text using the re/f
    operators, then draws new text on top. No annotation is created,
    so check_text_overlays() will not catch it.

    The detection logic:
      1. Parse the content stream tracking the CTM and fill colour.
      2. Record every white-filled rectangle (re + f/F with fill colour
         close to white: R,G,B all ≥ 0.9).
      3. Track BT/ET blocks with their text matrix (Tm/Td/TD) to
         compute each text glyph's position in page space.
      4. Flag any text glyph position that falls within a white
         rectangle that was drawn earlier in the same content stream.

    Returns the number of findings added.
    """
    import math

    WHITE_THRESHOLD = 0.9       # per-channel min to be "white"
    NEAR_RECT_TOLERANCE = 15.0  # points tolerance for position match

    added = 0

    cs_locator = _page_content_locator(page_pk)
    cs_objnum, cs_objgen = _page_content_objgen(page_pk)

    try:
        ops = list(pikepdf.parse_content_stream(page_pk))
        operators = [(str(op), operands) for operands, op in ops]
    except Exception:
        return 0

    # ── Pass 1: collect white filled rectangles ──────────────────────
    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    ctm_stack = []
    fill_color = (0.0, 0.0, 0.0)   # default black
    white_rects = []                # list of (x0,y0,x1,y1) in page space

    def transform_point(ctm, x, y):
        a,b,c,d,e,f = ctm
        return a*x + c*y + e, b*x + d*y + f

    def rect_to_page(ctm, rx, ry, rw, rh):
        corners = [(rx,ry),(rx+rw,ry),(rx,ry+rh),(rx+rw,ry+rh)]
        xs = [transform_point(ctm,cx,cy)[0] for cx,cy in corners]
        ys = [transform_point(ctm,cx,cy)[1] for cx,cy in corners]
        return min(xs), min(ys), max(xs), max(ys)

    def multiply_ctm(m1, m2):
        a1,b1,c1,d1,e1,f1 = m1
        a2,b2,c2,d2,e2,f2 = m2
        return (a1*a2+b1*c2, a1*b2+b1*d2,
                c1*a2+d1*c2, c1*b2+d1*d2,
                e1*a2+f1*c2+e2, e1*b2+f1*d2+f2)

    for i, (op, operands) in enumerate(operators):
        if op == 'q':
            ctm_stack.append(ctm)
        elif op == 'Q':
            if ctm_stack:
                ctm = ctm_stack.pop()
        elif op == 'cm':
            try:
                vals = tuple(float(str(x)) for x in operands)
                ctm = multiply_ctm(vals, ctm)
            except Exception:
                pass
        elif op in ('rg', 'g'):
            try:
                if op == 'g':
                    v = float(str(operands[0]))
                    fill_color = (v, v, v)
                else:
                    fill_color = tuple(
                        float(str(x)) for x in operands[:3])
            except Exception:
                pass
        elif op in ('RG', 'G'):
            pass  # stroke colour — not fill
        elif op == 'sc' or op == 'SC':
            try:
                vals = [float(str(x)) for x in operands]
                if len(vals) == 1:
                    fill_color = (vals[0],) * 3
                elif len(vals) >= 3:
                    fill_color = tuple(vals[:3])
            except Exception:
                pass
        elif op == 're':
            if i + 1 < len(operators):
                next_op = operators[i + 1][0]
                if next_op in ('f', 'F', 'B', 'B*', 'b', 'b*'):
                    # Check fill colour is white
                    if (fill_color and
                            len(fill_color) >= 3 and
                            all(v >= WHITE_THRESHOLD
                                for v in fill_color[:3])):
                        try:
                            rx,ry,rw,rh = tuple(
                                float(str(x)) for x in operands[:4])
                            area = abs(rw * rh)
                            if area >= TEXT_OVERLAY_MIN_AREA_SQPTS:
                                x0,y0,x1,y1 = rect_to_page(
                                    ctm, rx, ry, rw, rh)
                                white_rects.append(
                                    (x0, y0, x1, y1, i))
                        except Exception:
                            pass

    if not white_rects:
        return 0

    # ── Pass 2: find text drawn at positions within white rects ──────
    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    ctm_stack = []
    Tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    Tlm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    in_bt = False
    flagged_rects = set()  # avoid duplicate findings for same rect

    for i, (op, operands) in enumerate(operators):
        if op == 'q':
            ctm_stack.append(ctm)
        elif op == 'Q':
            if ctm_stack:
                ctm = ctm_stack.pop()
        elif op == 'cm':
            try:
                vals = tuple(float(str(x)) for x in operands)
                ctm = multiply_ctm(vals, ctm)
            except Exception:
                pass
        elif op == 'BT':
            in_bt = True
            Tm  = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            Tlm = list(Tm)
        elif op == 'ET':
            in_bt = False
        elif in_bt:
            if op == 'Tm':
                try:
                    vals = [float(str(x)) for x in operands]
                    Tm  = vals
                    Tlm = list(vals)
                except Exception:
                    pass
            elif op in ('Td', 'TD'):
                try:
                    tx = float(str(operands[0]))
                    ty = float(str(operands[1]))
                    Tlm[4] += tx * Tlm[0] + ty * Tlm[2]
                    Tlm[5] += tx * Tlm[1] + ty * Tlm[3]
                    Tm = list(Tlm)
                except Exception:
                    pass
            elif op == 'T*':
                Tlm[5] -= 0   # simplified (would need Tl state)
                Tm = list(Tlm)
            elif op in ('Tj', 'TJ', '"', "'"):
                # Compute text position in page space
                tm_x, tm_y = Tm[4], Tm[5]
                a, b, c, d, e, f = ctm
                px = a * tm_x + c * tm_y + e
                py = b * tm_x + d * tm_y + f

                # Check against each white rect drawn BEFORE this op
                for ri, (rx0, ry0, rx1, ry1, rect_op_idx) in \
                        enumerate(white_rects):
                    # Only flag if this text op comes AFTER the rect
                    if i <= rect_op_idx:
                        continue
                    if ri in flagged_rects:
                        continue

                    # Check if text position is within rect
                    # (with tolerance because text baseline may be
                    # slightly outside the rect's visual bounds)
                    tol = NEAR_RECT_TOLERANCE
                    if (rx0 - tol <= px <= rx1 + tol and
                            ry0 - tol <= py <= ry1 + tol):
                        # Get surrounding page text for context
                        try:
                            page_h = float(page_mu.rect.height)
                            # Convert rect to PyMuPDF coords (top-left origin)
                            mu_x0 = rx0
                            mu_y0 = page_h - ry1
                            mu_x1 = rx1
                            mu_y1 = page_h - ry0
                            clip = pymupdf.Rect(mu_x0-5, mu_y0-5,
                                                mu_x1+5, mu_y1+5)
                            # Don't extract text from under the white rect
                            # — it's already covered. But the surrounding
                            # page text gives context.
                            area_sqpts = abs(
                                (rx1-rx0) * (ry1-ry0))
                            detail = (
                                f"White-filled rectangle at "
                                f"({rx0:.1f},{ry0:.1f}) to "
                                f"({rx1:.1f},{ry1:.1f}) "
                                f"(area {area_sqpts:.0f} sq pts) "
                                f"covers existing page content; "
                                f"new text painted on top at "
                                f"({px:.1f},{py:.1f}). "
                                f"This pattern is characteristic of "
                                f"in-place text alteration without "
                                f"using an annotation."
                            )
                            # Store rect in PyMuPDF top-left coords
                            findings.append({
                                "type":   "TEXT_OVERLAY",
                                "detail": detail,
                                "image":  None,
                                "bbox":   (mu_x0, mu_y0, mu_x1, mu_y1),
                                "overlay_kind": "white_box",
                                "obj_num": cs_objnum,
                                "obj_gen": cs_objgen,
                                "obj_locator": cs_locator,
                            })
                            flagged_rects.add(ri)
                            added += 1
                        except Exception:
                            flagged_rects.add(ri)
                            added += 1

    return added


def check_text_over_text(page_mu, page_num, findings, page_pk=None):
    """
    Detect text drawn directly on top of other text (text-over-text
    overlay) — a manipulation method that does not use a covering
    rectangle. The altering application simply paints new glyphs in
    the same position as the original text, relying on the new text
    being opaque enough to hide what is beneath.

    This is distinct from check_content_stream_text_overlay (which
    requires a white masking rectangle) and check_text_overlays
    (which requires an annotation).

    Detection uses PyMuPDF's rawdict text extraction, which provides
    accurate per-character bounding boxes derived from real font
    metrics. Two character bounding boxes that overlap by more than
    TEXT_OVER_TEXT_OVERLAP_RATIO of the smaller box, and that come
    from different characters, indicate stacked text.

    To avoid false positives from normal typography (kerning,
    diacritics, ligatures), the detector requires:
      - Both characters are non-whitespace
      - The overlap is substantial (high ratio)
      - The characters differ OR are positioned almost exactly
        on top of each other (near-identical origin)

    Returns the number of findings added.
    """
    TEXT_OVER_TEXT_OVERLAP_RATIO = 0.55
    NEAR_IDENTICAL_PTS = 1.5

    added = 0

    cs_locator = _page_content_locator(page_pk) if page_pk is not None \
        else None
    if cs_locator:
        cs_locator = (cs_locator +
                      " (overlying glyphs may be nested in a Form XObject "
                      "drawn by this stream)")
    cs_objnum, cs_objgen = (_page_content_objgen(page_pk)
                            if page_pk is not None else (None, None))

    try:
        raw = page_mu.get_text("rawdict")
    except Exception:
        return 0

    # Collect every character with its bbox and metadata
    chars = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:   # text blocks only
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                span_font = span.get("font", "")
                span_color = span.get("color", 0)
                span_origin = span.get("origin", (0, 0))
                for ch in span.get("chars", []):
                    bbox = ch.get("bbox")
                    c = ch.get("c", "")
                    if not bbox or not c or c.isspace():
                        continue
                    chars.append({
                        "c": c,
                        "bbox": bbox,
                        "font": span_font,
                        "color": span_color,
                        "origin": ch.get("origin", span_origin),
                    })

    if len(chars) < 2:
        return 0

    def bbox_area(b):
        return max(0, b[2] - b[0]) * max(0, b[3] - b[1])

    def intersection_ratio(b1, b2):
        ix = max(0, min(b1[2], b2[2]) - max(b1[0], b2[0]))
        iy = max(0, min(b1[3], b2[3]) - max(b1[1], b2[1]))
        inter = ix * iy
        if inter <= 0:
            return 0.0
        smaller = min(bbox_area(b1), bbox_area(b2))
        return inter / smaller if smaller > 0 else 0.0

    # Spatial bucketing to avoid O(n²) on large pages: bucket chars
    # by a coarse grid, only compare within / adjacent buckets.
    BUCKET = 20.0
    grid = {}
    for idx, ch in enumerate(chars):
        bx = int(ch["bbox"][0] // BUCKET)
        by = int(ch["bbox"][1] // BUCKET)
        grid.setdefault((bx, by), []).append(idx)

    overlay_regions = []   # collected overlap locations
    reported_pairs = set()

    for idx1, ch1 in enumerate(chars):
        b1 = ch1["bbox"]
        bx = int(b1[0] // BUCKET)
        by = int(b1[1] // BUCKET)
        # Check this bucket and the 8 neighbours
        candidates = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                candidates.extend(grid.get((bx + dx, by + dy), []))

        for idx2 in candidates:
            if idx2 <= idx1:
                continue
            ch2 = chars[idx2]
            b2 = ch2["bbox"]

            ratio = intersection_ratio(b1, b2)
            if ratio < TEXT_OVER_TEXT_OVERLAP_RATIO:
                continue

            # Distinguish genuine overlay from typographic effects.
            ox1, oy1 = ch1["origin"]
            ox2, oy2 = ch2["origin"]
            same_origin = (abs(ox1 - ox2) < NEAR_IDENTICAL_PTS and
                           abs(oy1 - oy2) < NEAR_IDENTICAL_PTS)
            different_char = ch1["c"] != ch2["c"]
            different_font = ch1["font"] != ch2["font"]
            different_color = ch1["color"] != ch2["color"]

            # Faux-bold / drop-shadow effects stamp the SAME character
            # in the SAME font at a near-identical origin. Exclude those:
            # if the character and font are identical, this is almost
            # certainly a rendering effect, not a manipulation — even if
            # the colour differs (drop shadow uses a darker copy).
            if same_origin and not different_char and not different_font:
                continue

            # Require a substantive signal of distinct text being
            # stacked: the overlying text differs in content or font.
            # (Different colour alone, with same char+font, is a shadow.)
            if not (different_char or different_font):
                continue

            # Record the overlap region (cluster nearby reports)
            cx = (max(b1[0], b2[0]) + min(b1[2], b2[2])) / 2
            cy = (max(b1[1], b2[1]) + min(b1[3], b2[3])) / 2
            # Union bbox of both characters (for visual highlighting)
            ub = (min(b1[0], b2[0]), min(b1[1], b2[1]),
                  max(b1[2], b2[2]), max(b1[3], b2[3]))
            overlay_regions.append({
                "x": cx, "y": cy,
                "c1": ch1["c"], "c2": ch2["c"],
                "font1": ch1["font"], "font2": ch2["font"],
                "color1": ch1["color"], "color2": ch2["color"],
                "ratio": ratio,
                "ubbox": ub,
            })

    if not overlay_regions:
        return 0

    # Cluster overlap points that are close together into single
    # findings (one manipulated field may have many overlapping chars).
    CLUSTER_DIST = 25.0
    clusters = []
    for region in overlay_regions:
        placed = False
        for cl in clusters:
            if (abs(cl["x"] - region["x"]) < CLUSTER_DIST and
                    abs(cl["y"] - region["y"]) < CLUSTER_DIST):
                cl["points"].append(region)
                cl["x"] = sum(p["x"] for p in cl["points"]) / len(cl["points"])
                cl["y"] = sum(p["y"] for p in cl["points"]) / len(cl["points"])
                placed = True
                break
        if not placed:
            clusters.append({
                "x": region["x"], "y": region["y"],
                "points": [region],
            })

    for cl in clusters:
        n = len(cl["points"])
        max_ratio = max(p["ratio"] for p in cl["points"])
        # Build a sample of the overlapping characters
        over_chars = "".join(
            p["c2"] for p in cl["points"][:12])
        under_chars = "".join(
            p["c1"] for p in cl["points"][:12])
        fonts = set()
        colors = set()
        for p in cl["points"]:
            fonts.add(p["font1"]); fonts.add(p["font2"])
            colors.add(p["color1"]); colors.add(p["color2"])

        # Union bounding box of all overlapping characters in cluster
        cl_x0 = min(p["ubbox"][0] for p in cl["points"])
        cl_y0 = min(p["ubbox"][1] for p in cl["points"])
        cl_x1 = max(p["ubbox"][2] for p in cl["points"])
        cl_y1 = max(p["ubbox"][3] for p in cl["points"])

        detail = (
            f"Text drawn directly over other text at "
            f"(~{cl['x']:.0f}, {cl['y']:.0f}) on page {page_num}: "
            f"{n} overlapping character pair(s), "
            f"max overlap {max_ratio*100:.0f}%. "
            f"Underlying glyphs: \"{under_chars}\"; "
            f"overlying glyphs: \"{over_chars}\". "
        )
        if len(fonts) > 1:
            detail += f"Multiple fonts involved ({len(fonts)}). "
        if len(colors) > 1:
            detail += f"Different text colours involved. "
        detail += ("This pattern is characteristic of in-place text "
                   "alteration where new text is painted over the "
                   "original without a masking rectangle.")

        findings.append({
            "type":   "TEXT_OVERLAY",
            "detail": detail,
            "image":  None,
            "bbox":   (cl_x0, cl_y0, cl_x1, cl_y1),
            "overlay_kind": "text_over_text",
            "obj_num": cs_objnum,
            "obj_gen": cs_objgen,
            "obj_locator": cs_locator,
        })
        added += 1

    return added
