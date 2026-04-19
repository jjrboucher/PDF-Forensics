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
