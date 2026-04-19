"""
NetworkX graph construction and metadata builders.
"""

from collections import defaultdict

try:
    import networkx as nx
except ImportError:
    pass


# ===================================================================
# Color palette
# ===================================================================

COLOR_DOC          = "#378ADD"  # blue
COLOR_PAGE         = "#1D9E75"  # teal-green
COLOR_RISK_LOW   = "#5DCAA5"   # green
COLOR_RISK_MID   = "#EF9F27"   # amber
COLOR_RISK_HIGH  = "#E24B4A"   # red
COLOR_CROSS_DOC_BORDER = "#FA0F00"

RISK_THRESHOLD_MID  = 15
RISK_THRESHOLD_HIGH = 35


def risk_tier(score):
    """Return 'low' | 'mid' | 'high' based on the numeric score."""
    if score is None:
        return "low"
    if score >= RISK_THRESHOLD_HIGH:
        return "high"
    if score >= RISK_THRESHOLD_MID:
        return "mid"
    return "low"


def risk_color(score):
    """Return the fill color for a given risk score."""
    tier = risk_tier(score)
    return {
        "low":  COLOR_RISK_LOW,
        "mid":  COLOR_RISK_MID,
        "high": COLOR_RISK_HIGH,
    }[tier]


def build_graph(rows, thumbnails):
    """
    Build a NetworkX graph from duplicate image rows.

    Each row tuple now includes risk_score as its 11th column.
    Image color is based on the maximum risk score of any
    placement of that image. Cross-document images get an orange
    border drawn on top of the risk-tier fill color.
    """
    G = nx.Graph()

    md5_doc_count = defaultdict(set)
    md5_placements = defaultdict(int)
    md5_max_risk = defaultdict(int)
    for row in rows:
        analysis_id = row[0]
        md5 = row[6]
        risk = row[10] if len(row) > 10 else 0
        md5_doc_count[md5].add(analysis_id)
        md5_placements[md5] += 1
        if risk > md5_max_risk[md5]:
            md5_max_risk[md5] = risk

    for row in rows:
        (analysis_id, pdf_filename, page_id, page_number,
         image_id, image_label, md5, ext, width, height,
         risk_score) = row

        doc_node = f"doc_{analysis_id}"
        page_node = f"page_{page_id}"
        image_node = f"img_{md5}"

        if not G.has_node(doc_node):
            G.add_node(
                doc_node,
                label=pdf_filename,
                color=COLOR_DOC,
                shape="box",
                size=25,
                node_type="document",
                pdf_filename=pdf_filename,
            )

        if not G.has_node(page_node):
            G.add_node(
                page_node,
                label=f"p.{page_number}",
                color=COLOR_PAGE,
                shape="ellipse",
                size=15,
                node_type="page",
                page_number=page_number,
                pdf_filename=pdf_filename,
            )

        if not G.has_node(image_node):
            doc_count = len(md5_doc_count[md5])
            placements = md5_placements[md5]
            is_cross_doc = doc_count > 1
            max_risk = md5_max_risk[md5]
            fill = risk_color(max_risk)
            size = min(20 + placements * 3, 60)

            # vis.js color object: separate background and border.
            # Cross-doc images get a thick orange border on top of
            # whatever risk-tier fill they have.
            if is_cross_doc:
                color_obj = {
                    "background": fill,
                    "border": COLOR_CROSS_DOC_BORDER,
                    "highlight": {
                        "background": fill,
                        "border": COLOR_CROSS_DOC_BORDER,
                    },
                }
            else:
                color_obj = fill

            # Note: image tooltips are built as real DOM elements on
            # the JS side (see inject_custom_ui) because vis.js will
            # HTML-escape string titles. We omit the title here and
            # have the JS setupCustomUI function populate it.

            node_attrs = {
                "label": md5[:8],
                "color": color_obj,
                "shape": "dot",
                "size": size,
                "node_type": "image",
                "md5": md5,
                "risk_score": int(max_risk),
                "is_cross_doc": is_cross_doc,
            }
            if is_cross_doc:
                # Visible border width — applied to all cross-doc nodes
                node_attrs["borderWidth"] = 4
                node_attrs["borderWidthSelected"] = 6

            G.add_node(image_node, **node_attrs)

        G.add_edge(doc_node, page_node)
        G.add_edge(
            page_node, image_node,
            title=f"{image_label} on page {page_number}",
        )

    return G


def build_image_metadata(rows, findings_by_md5=None):
    """
    Build a metadata dict keyed by md5 for the JavaScript side.

    findings_by_md5 (optional): dict from load_findings_for_md5s,
    used to attach the per-image finding list to the JS metadata.
    """
    findings_by_md5 = findings_by_md5 or {}
    meta = {}
    usage = defaultdict(list)
    md5_max_risk = defaultdict(int)
    md5_doc_set = defaultdict(set)

    for row in rows:
        analysis_id = row[0]
        pdf_filename = row[1]
        page_number = row[3]
        image_label = row[5]
        md5 = row[6]
        ext = row[7]
        width = row[8]
        height = row[9]
        risk = row[10] if len(row) > 10 else 0

        usage[md5].append({
            "pdf": pdf_filename,
            "page": page_number,
            "label": image_label,
            "risk": int(risk),
        })
        md5_doc_set[md5].add(analysis_id)
        if risk > md5_max_risk[md5]:
            md5_max_risk[md5] = risk

        if md5 not in meta:
            meta[md5] = {
                "md5": md5,
                "format": ext,
                "width": width,
                "height": height,
                "usage": [],
            }

    for md5, entries in usage.items():
        meta[md5]["usage"] = entries
        meta[md5]["risk_score"]  = int(md5_max_risk[md5])
        meta[md5]["risk_tier"]   = risk_tier(md5_max_risk[md5])
        meta[md5]["is_cross_doc"] = len(md5_doc_set[md5]) > 1
        meta[md5]["findings"]     = findings_by_md5.get(md5, [])

    return meta


def build_document_metadata(rows):
    """
    Build a metadata dict keyed by analysis_id describing each
    document represented in the graph. Used for the excluded
    documents panel and for restoration.
    """
    meta = {}
    image_set_by_doc = defaultdict(set)
    page_set_by_doc = defaultdict(set)

    for row in rows:
        analysis_id = row[0]
        pdf_filename = row[1]
        page_id = row[2]
        md5 = row[6]
        page_set_by_doc[analysis_id].add(page_id)
        image_set_by_doc[analysis_id].add(md5)
        if analysis_id not in meta:
            meta[analysis_id] = {
                "analysis_id": analysis_id,
                "pdf_filename": pdf_filename,
            }

    for aid in meta:
        meta[aid]["page_count"]  = len(page_set_by_doc[aid])
        meta[aid]["image_count"] = len(image_set_by_doc[aid])

    return meta


def graph_print_summary(rows, G, thumbnail_count):
    md5_set = {row[6] for row in rows}
    doc_set = {row[0] for row in rows}
    page_set = {row[2] for row in rows}

    cross_doc_md5s = [
        node for node, data in G.nodes(data=True)
        if data.get("node_type") == "image"
        and data.get("is_cross_doc")
    ]

    # Tally risk tiers
    tier_counts = {"low": 0, "mid": 0, "high": 0}
    for node, data in G.nodes(data=True):
        if data.get("node_type") != "image":
            continue
        tier_counts[risk_tier(data.get("risk_score", 0))] += 1

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Unique duplicate images:  {len(md5_set)}")
    print(f"  Documents involved:       {len(doc_set)}")
    print(f"  Pages involved:           {len(page_set)}")
    print(f"  Total placements:         {len(rows)}")
    print(f"  Cross-document images:    {len(cross_doc_md5s)}")
    print(f"  Risk tier breakdown:")
    print(f"    HIGH (>={RISK_THRESHOLD_HIGH}):       "
          f"{tier_counts['high']}")
    print(f"    MID  ({RISK_THRESHOLD_MID}-{RISK_THRESHOLD_HIGH-1}):"
          f"{'':>5}{tier_counts['mid']}")
    print(f"    LOW  (<{RISK_THRESHOLD_MID}):        "
          f"{tier_counts['low']}")
    print(f"  Thumbnails embedded:      "
          f"{thumbnail_count} / {len(md5_set)}")
    if thumbnail_count < len(md5_set):
        print("    (missing thumbnails = images not stored in DB)")
