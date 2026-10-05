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
COLOR_DOC_VERSION  = "#6C8EBF"  # muted blue - prior-version documents
COLOR_PAGE         = "#1D9E75"  # teal-green
COLOR_RISK_LOW   = "#5DCAA5"   # green
COLOR_RISK_MID   = "#EF9F27"   # amber
COLOR_RISK_HIGH  = "#E24B4A"   # red
COLOR_CROSS_DOC_BORDER = "#FA0F00"       # red - genuine cross-lineage reuse
COLOR_VERSION_REUSE_BORDER = "#8E7CC3"   # violet - within-lineage (version) reuse

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

    Rows carry, after risk_score (index 10): source_analysis_id (11),
    version_number (12), lineage_root (13). Reuse is classified by
    LINEAGE, not raw document count:

      * cross-lineage reuse (image in 2+ distinct lineages) is the
        genuine cross-document signal and keeps the red border.
      * within-lineage reuse (image shared only among a document and
        its own prior versions) gets a violet border and is labelled
        as version reuse, so an expected version overlap is not read
        as independent reuse.

    Placements inside a prior version are drawn with dashed edges (and
    prior-version document nodes use a muted colour) so version content
    is visually separable - including the useful case of an image
    present in a prior version but absent from the current one.
    """
    G = nx.Graph()

    md5_doc_count = defaultdict(set)     # analysis_ids using the image
    md5_lineages = defaultdict(set)      # distinct lineage roots
    md5_placements = defaultdict(int)
    md5_max_risk = defaultdict(int)
    analysis_version = {}                # analysis_id -> version_number
    for row in rows:
        analysis_id = row[0]
        md5 = row[6]
        risk = row[10] if len(row) > 10 else 0
        version_number = row[12] if len(row) > 12 else None
        lineage_root = row[13] if len(row) > 13 else analysis_id
        md5_doc_count[md5].add(analysis_id)
        md5_lineages[md5].add(lineage_root)
        md5_placements[md5] += 1
        if risk > md5_max_risk[md5]:
            md5_max_risk[md5] = risk
        analysis_version[analysis_id] = version_number

    for row in rows:
        (analysis_id, pdf_filename, page_id, page_number,
         image_id, image_label, md5, ext, width, height,
         risk_score) = row[:11]
        version_number = row[12] if len(row) > 12 else None

        doc_node = f"doc_{analysis_id}"
        page_node = f"page_{page_id}"
        image_node = f"img_{md5}"
        is_version_doc = version_number is not None

        if not G.has_node(doc_node):
            doc_label = pdf_filename
            if is_version_doc:
                doc_label = f"{pdf_filename}  (prior v{version_number})"
            G.add_node(
                doc_node,
                label=doc_label,
                color=COLOR_DOC_VERSION if is_version_doc else COLOR_DOC,
                shape="box",
                size=25,
                node_type="document",
                pdf_filename=pdf_filename,
                is_version=is_version_doc,
                version_number=version_number,
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
                is_version=is_version_doc,
            )

        if not G.has_node(image_node):
            doc_count = len(md5_doc_count[md5])
            lineage_count = len(md5_lineages[md5])
            placements = md5_placements[md5]
            # Genuine cross-document reuse spans 2+ lineages. Reuse
            # confined to one lineage (a document and its own versions)
            # is version reuse, not cross-document reuse.
            is_cross_doc = lineage_count > 1
            is_version_reuse = doc_count > 1 and lineage_count == 1
            max_risk = md5_max_risk[md5]
            fill = risk_color(max_risk)
            size = min(20 + placements * 3, 60)

            if is_cross_doc:
                color_obj = {
                    "background": fill,
                    "border": COLOR_CROSS_DOC_BORDER,
                    "highlight": {
                        "background": fill,
                        "border": COLOR_CROSS_DOC_BORDER,
                    },
                }
            elif is_version_reuse:
                color_obj = {
                    "background": fill,
                    "border": COLOR_VERSION_REUSE_BORDER,
                    "highlight": {
                        "background": fill,
                        "border": COLOR_VERSION_REUSE_BORDER,
                    },
                }
            else:
                color_obj = fill

            node_attrs = {
                "label": md5[:8],
                "color": color_obj,
                "shape": "dot",
                "size": size,
                "node_type": "image",
                "md5": md5,
                "risk_score": int(max_risk),
                "is_cross_doc": is_cross_doc,
                "is_version_reuse": is_version_reuse,
                "lineage_count": lineage_count,
            }
            if is_cross_doc:
                node_attrs["borderWidth"] = 4
                node_attrs["borderWidthSelected"] = 6
            elif is_version_reuse:
                node_attrs["borderWidth"] = 3
                node_attrs["borderWidthSelected"] = 5
                node_attrs["shapeProperties"] = {"borderDashes": [6, 4]}

            G.add_node(image_node, **node_attrs)

        # Placements inside a prior version draw dashed, so the version
        # subtree is visually separable from the current one.
        edge_is_version = analysis_version.get(analysis_id) is not None
        edge_title = f"{image_label} on page {page_number}"
        if edge_is_version:
            edge_title += (f" (prior version "
                           f"{analysis_version[analysis_id]})")

        G.add_edge(doc_node, page_node, dashes=bool(edge_is_version))
        G.add_edge(
            page_node, image_node,
            title=edge_title,
            dashes=bool(edge_is_version),
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
    md5_lineage_set = defaultdict(set)

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
        version_number = row[12] if len(row) > 12 else None
        lineage_root = row[13] if len(row) > 13 else analysis_id

        usage[md5].append({
            "pdf": pdf_filename,
            "page": page_number,
            "label": image_label,
            "risk": int(risk),
            "is_version": version_number is not None,
            "version_number": version_number,
        })
        md5_doc_set[md5].add(analysis_id)
        md5_lineage_set[md5].add(lineage_root)
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
        lineage_count = len(md5_lineage_set[md5])
        doc_count = len(md5_doc_set[md5])
        meta[md5]["usage"] = entries
        meta[md5]["risk_score"]  = int(md5_max_risk[md5])
        meta[md5]["risk_tier"]   = risk_tier(md5_max_risk[md5])
        # is_cross_doc now means cross-LINEAGE (genuine reuse).
        meta[md5]["is_cross_doc"] = lineage_count > 1
        meta[md5]["is_version_reuse"] = (
            doc_count > 1 and lineage_count == 1)
        meta[md5]["lineage_count"] = lineage_count
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
        version_number = row[12] if len(row) > 12 else None
        lineage_root = row[13] if len(row) > 13 else analysis_id
        page_set_by_doc[analysis_id].add(page_id)
        image_set_by_doc[analysis_id].add(md5)
        if analysis_id not in meta:
            meta[analysis_id] = {
                "analysis_id": analysis_id,
                "pdf_filename": pdf_filename,
                "is_version": version_number is not None,
                "version_number": version_number,
                "lineage_root": lineage_root,
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
    version_reuse_md5s = [
        node for node, data in G.nodes(data=True)
        if data.get("node_type") == "image"
        and data.get("is_version_reuse")
    ]
    version_docs = [
        node for node, data in G.nodes(data=True)
        if data.get("node_type") == "document"
        and data.get("is_version")
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
    print(f"  Version-reuse images:     {len(version_reuse_md5s)}")
    print(f"  Prior-version documents:  {len(version_docs)}")
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
