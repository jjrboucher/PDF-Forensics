"""
Graphics state parsing, z-order extraction, and transparency
enrichment for image placements.
"""

import pikepdf
from pikepdf import Name


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
