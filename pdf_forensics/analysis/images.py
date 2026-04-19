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
