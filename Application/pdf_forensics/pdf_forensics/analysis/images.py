"""
Image discovery, placement parsing, and image map construction.
"""

import os
import hashlib
import pymupdf
import pikepdf
from pikepdf import Name


HIDDEN_THRESHOLD_PTS = 0.5


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
      - ctm: (a, b, c, d, e, f) current transformation matrix at
              the point the image is drawn, or None if unavailable

    The CTM is tracked by following q/Q (save/restore graphics state)
    and cm (concatenate matrix) operators in the content stream.
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

    # Track the current transformation matrix (CTM).
    # Identity matrix: a=1, b=0, c=0, d=1, e=0, f=0
    # When cm is encountered, we multiply:
    #   new_CTM = cm_matrix × current_CTM
    # q/Q save and restore the graphics state including CTM.
    def _identity():
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    def _multiply(m1, m2):
        """Multiply two 2D affine matrices (a,b,c,d,e,f)."""
        a1, b1, c1, d1, e1, f1 = m1
        a2, b2, c2, d2, e2, f2 = m2
        return (
            a1*a2 + b1*c2,
            a1*b2 + b1*d2,
            c1*a2 + d1*c2,
            c1*b2 + d1*d2,
            e1*a2 + f1*c2 + e2,
            e1*b2 + f1*d2 + f2,
        )

    ctm = _identity()
    ctm_stack = []

    z_order = 0
    for operands, operator in ops:
        op = str(operator)

        if op == "q":
            ctm_stack.append(ctm)
        elif op == "Q":
            if ctm_stack:
                ctm = ctm_stack.pop()
        elif op == "cm":
            try:
                vals = [float(x) for x in operands]
                if len(vals) == 6:
                    ctm = _multiply(tuple(vals), ctm)
            except (ValueError, TypeError):
                pass
        elif op == "Do":
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
                    "ctm": ctm,
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
                        "ctm": ctm,
                    })

    return placements


def _compute_effective_dpi(pixel_w, pixel_h, ctm):
    """
    Compute effective DPI from pixel dimensions and the CTM.

    The CTM maps the image's 1×1 unit square to page space.
    The display dimensions in points are the magnitudes of the
    transformed basis vectors:
      display_width_pts  = sqrt(a² + b²)
      display_height_pts = sqrt(c² + d²)

    Then: dpi = pixel_dim × 72 / display_dim_pts

    Returns (dpi_x, dpi_y, display_w_pts, display_h_pts) or
    (None, None, None, None) if computation isn't possible.
    """
    if not ctm or pixel_w <= 0 or pixel_h <= 0:
        return None, None, None, None

    import math
    a, b, c, d, e, f = ctm

    # Display dimensions in points (length of transformed basis vectors)
    display_w = math.sqrt(a*a + b*b)
    display_h = math.sqrt(c*c + d*d)

    if display_w < 0.01 or display_h < 0.01:
        return None, None, None, None

    dpi_x = round(pixel_w * 72.0 / display_w, 1)
    dpi_y = round(pixel_h * 72.0 / display_h, 1)

    return dpi_x, dpi_y, round(display_w, 2), round(display_h, 2)


def build_image_map(page_pk, page_num, page_pad, doc_mu):
    """
    Build image naming map by parsing the content stream, matching
    the enumeration order used by extract_pdf_images.py.

    Returns:
        placements     : list of placement dicts (from find_image_placements)
        label_to_info  : {"01_1": {xref, width, height, ext, form_xref,
                          z_order, dpi_x, dpi_y, display_w, display_h, ctm}}
        xref_to_labels : {xref: ["01_1", "01_2"]}  (xref may map to multiple labels)
        form_xref_to_labels : {form_xref: ["01_1"]}
    """
    placements = find_image_placements(page_pk)

    label_to_info = {}
    xref_to_labels = {}
    form_xref_to_labels = {}
    xref_extract_cache = {}

    img_count = 0
    for p in placements:
        xref = p["xref"]
        if xref is None:
            continue

        img_count += 1
        label = f"{str(page_num).zfill(page_pad)}_{img_count}"

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

        # Compute effective DPI from CTM
        ctm = p.get("ctm")
        dpi_x, dpi_y, display_w, display_h = \
            _compute_effective_dpi(width, height, ctm)

        label_to_info[label] = {
            "xref": xref,
            "width": width,
            "height": height,
            "ext": ext,
            "image_bytes": image_bytes,
            "form_xref": p["form_xref"] or 0,
            "z_order": p["z_order"],
            "dpi_x": dpi_x,
            "dpi_y": dpi_y,
            "display_w_pts": display_w,
            "display_h_pts": display_h,
            "ctm": ctm,
        }

        xref_to_labels.setdefault(xref, []).append(label)

        if p["form_xref"]:
            form_xref_to_labels.setdefault(
                p["form_xref"], []).append(label)

    return placements, label_to_info, xref_to_labels, form_xref_to_labels
