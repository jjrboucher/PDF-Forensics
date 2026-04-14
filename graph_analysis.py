"""
PDF Forensics — Image Relationship Graph

Reads a database produced by "PDF forensics.py" and renders an
interactive graph showing which images appear in multiple documents
or on multiple pages.

Features:
  - Actual image thumbnails embedded in the HTML and shown on hover
  - Right-click an image node to exclude it from the graph
  - Excluded images panel for review and restoration
  - Cross-document images highlighted in orange
  - Image nodes sized by number of placements
  - Stable layout (physics disabled after stabilization)

Usage: python graph_analysis.py [database.db]
"""

import sys
import os
import base64
import sqlite3
import json
from collections import defaultdict

import networkx as nx
from pyvis.network import Network


# ===================================================================
# Configuration
# ===================================================================

# Maximum thumbnail size (longest edge) embedded in the HTML.
# Larger = better quality in tooltip, but much larger HTML file.
THUMBNAIL_MAX_SIZE = 200

# Maximum bytes for an embedded image (before resizing).
# Images larger than this are always resized.
THUMBNAIL_MAX_BYTES = 500 * 1024  # 500 KB


# ===================================================================
# Database selection
# ===================================================================

def select_database(cli_path=None):
    """Return the path to the database to use."""
    if cli_path:
        if os.path.isfile(cli_path):
            return cli_path
        print(f"Warning: {cli_path} not found. Opening file picker...")

    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        path = filedialog.askopenfilename(
            title="Select PDF Forensics database",
            filetypes=[
                ("SQLite database", "*.db *.sqlite *.sqlite3"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()
        if path and os.path.isfile(path):
            return path
        if not path:
            print("No database selected.")
            return None
    except Exception as e:
        print(f"GUI unavailable ({e}). Falling back to prompt.")
        path = input("Database path: ").strip().strip('"').strip("'")
        if path and os.path.isfile(path):
            return path

    return None


def validate_database(conn):
    """Check that the expected tables exist."""
    required = {"analyses", "pages", "images", "image_data"}
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    missing = required - tables
    if missing:
        raise RuntimeError(
            f"Database is missing required tables: "
            f"{', '.join(sorted(missing))}. "
            f"Is this a PDF Forensics database?")


# ===================================================================
# Data loading
# ===================================================================

def load_data(conn, scope="cross_document"):
    """
    Load image placements that appear more than once.

    scope options:
      'all_placements'  : md5 appears in 2+ image placements
      'cross_page'      : md5 appears on 2+ distinct pages
      'cross_document'  : md5 appears in 2+ distinct documents
    """
    if scope == "cross_document":
        dup_filter = """
            SELECT idata.md5_hash
            FROM image_data idata
            JOIN images i ON i.image_data_id = idata.id
            JOIN pages p ON p.id = i.page_id
            GROUP BY idata.md5_hash
            HAVING COUNT(DISTINCT p.analysis_id) > 1
        """
    elif scope == "cross_page":
        dup_filter = """
            SELECT idata.md5_hash
            FROM image_data idata
            JOIN images i ON i.image_data_id = idata.id
            GROUP BY idata.md5_hash
            HAVING COUNT(DISTINCT i.page_id) > 1
        """
    else:
        dup_filter = """
            SELECT idata.md5_hash
            FROM image_data idata
            JOIN images i ON i.image_data_id = idata.id
            GROUP BY idata.md5_hash
            HAVING COUNT(i.id) > 1
        """

    query = f"""
        SELECT
            a.id AS analysis_id,
            a.pdf_filename,
            p.id AS page_id,
            p.page_number,
            i.id AS image_id,
            i.label AS image_label,
            idata.md5_hash,
            idata.format_ext,
            idata.width_px,
            idata.height_px
        FROM image_data idata
        JOIN images i   ON i.image_data_id = idata.id
        JOIN pages p    ON p.id = i.page_id
        JOIN analyses a ON a.id = p.analysis_id
        WHERE idata.md5_hash IN ({dup_filter})
        ORDER BY idata.md5_hash, a.id, p.page_number
    """
    return conn.execute(query).fetchall()


def load_image_bytes(conn, md5_set):
    """
    Load image bytes for the given md5 hashes.

    Returns a dict: {md5: (bytes, format_ext, width, height)}
    Only the first occurrence per md5 is loaded (since duplicates
    have identical bytes by definition).
    """
    if not md5_set:
        return {}

    placeholders = ",".join(["?"] * len(md5_set))
    query = f"""
        SELECT md5_hash, image_bytes, format_ext, width_px, height_px
        FROM image_data
        WHERE md5_hash IN ({placeholders})
          AND image_bytes IS NOT NULL
        GROUP BY md5_hash
    """
    result = {}
    for row in conn.execute(query, list(md5_set)):
        md5, blob, ext, w, h = row
        if blob:
            result[md5] = (bytes(blob), ext, w, h)
    return result


# ===================================================================
# Thumbnail generation
# ===================================================================

def make_thumbnail_data_uri(image_bytes, ext, width, height):
    """
    Convert image bytes to a base64 data URI, resizing if needed.

    Returns (data_uri, displayed_width, displayed_height) or None
    if the image can't be processed.
    """
    if not image_bytes:
        return None

    # If image is small enough and common format, embed as-is
    if (len(image_bytes) <= THUMBNAIL_MAX_BYTES
            and width and height
            and max(width, height) <= THUMBNAIL_MAX_SIZE):
        mime = f"image/{ext}" if ext in ("jpeg", "jpg", "png",
                                          "gif", "webp") else None
        if mime:
            b64 = base64.b64encode(image_bytes).decode("ascii")
            return (f"data:{mime};base64,{b64}", width, height)

    # Otherwise resize via Pillow
    try:
        from PIL import Image
        import io
    except ImportError:
        return None

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception:
        return None

    # Convert mode if needed for JPEG output
    if img.mode in ("RGBA", "LA", "P"):
        if img.mode == "P":
            img = img.convert("RGBA")
        # Preserve transparency by outputting PNG
        output_format = "PNG"
        mime = "image/png"
    else:
        output_format = "JPEG"
        mime = "image/jpeg"

    # Resize preserving aspect ratio
    orig_w, orig_h = img.size
    max_edge = max(orig_w, orig_h)
    if max_edge > THUMBNAIL_MAX_SIZE:
        scale = THUMBNAIL_MAX_SIZE / max_edge
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
    else:
        new_w, new_h = orig_w, orig_h

    buf = io.BytesIO()
    save_kwargs = {"optimize": True}
    if output_format == "JPEG":
        save_kwargs["quality"] = 80
    img.save(buf, format=output_format, **save_kwargs)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return (f"data:{mime};base64,{b64}", new_w, new_h)


# ===================================================================
# Graph construction
# ===================================================================

COLOR_DOC          = "#378ADD"  # blue
COLOR_PAGE         = "#1D9E75"  # teal-green
COLOR_IMAGE        = "#E24B4A"  # red
COLOR_IMAGE_CROSS  = "#EF9F27"  # orange — cross-document reuse


def build_graph(rows, thumbnails):
    """
    Build a NetworkX graph from duplicate image rows.

    thumbnails is a dict: {md5: (data_uri, width, height)}
    """
    G = nx.Graph()

    md5_doc_count = defaultdict(set)
    md5_placements = defaultdict(int)
    for row in rows:
        analysis_id, _, _, _, _, _, md5, _, _, _ = row
        md5_doc_count[md5].add(analysis_id)
        md5_placements[md5] += 1

    for row in rows:
        (analysis_id, pdf_filename, page_id, page_number,
         image_id, image_label, md5, ext, width, height) = row

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
                group="document",
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
                group="page",
                node_type="page",
                page_number=page_number,
                pdf_filename=pdf_filename,
            )

        if not G.has_node(image_node):
            doc_count = len(md5_doc_count[md5])
            placements = md5_placements[md5]
            is_cross_doc = doc_count > 1
            color = (COLOR_IMAGE_CROSS if is_cross_doc
                     else COLOR_IMAGE)
            size = min(20 + placements * 3, 60)

            # Note: image tooltips are built as real DOM elements on
            # the JS side (see inject_custom_ui) because vis.js will
            # HTML-escape string titles. We omit the title here and
            # have the JS setupCustomUI function populate it.

            G.add_node(
                image_node,
                label=md5[:8],
                color=color,
                shape="dot",
                size=size,
                group="image",
                node_type="image",
                md5=md5,
            )

        G.add_edge(doc_node, page_node)
        G.add_edge(
            page_node, image_node,
            title=f"{image_label} on page {page_number}",
        )

    return G


# ===================================================================
# Visualization
# ===================================================================

def build_image_metadata(rows):
    """
    Build a metadata dict keyed by md5 for the JavaScript side.
    Contains all info needed to show excluded images in the panel.
    """
    meta = {}
    usage = defaultdict(list)
    for row in rows:
        _, pdf_filename, _, page_number, _, image_label, md5, \
            ext, width, height = row
        usage[md5].append({
            "pdf": pdf_filename,
            "page": page_number,
            "label": image_label,
        })
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

    return meta


def visualize_graph(G, image_meta, thumbnails, db_path,
                    output_path="image_relationship_graph.html"):
    net = Network(
        height="100vh",
        width="100%",
        bgcolor="#1B1B1B",
        font_color="#F0F0F0",
        notebook=False,
        cdn_resources="remote",
    )
    net.from_nx(G)

    # Physics config that stabilizes then freezes.
    net.set_options("""
    {
      "nodes": {
        "borderWidth": 1,
        "borderWidthSelected": 3,
        "font": {"color": "#F0F0F0", "size": 12}
      },
      "edges": {
        "color": {"color": "#555555", "highlight": "#ED1C24"},
        "smooth": {"type": "continuous"},
        "width": 1
      },
      "physics": {
        "enabled": true,
        "barnesHut": {
          "gravitationalConstant": -8000,
          "centralGravity": 0.3,
          "springLength": 120,
          "springConstant": 0.04,
          "damping": 0.9,
          "avoidOverlap": 0.2
        },
        "minVelocity": 0.75,
        "solver": "barnesHut",
        "stabilization": {
          "enabled": true,
          "iterations": 300,
          "updateInterval": 25,
          "fit": true
        }
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 150,
        "navigationButtons": true,
        "keyboard": true
      }
    }
    """)

    try:
        net.write_html(output_path, notebook=False,
                       open_browser=False)
    except TypeError:
        net.write_html(output_path)

    # Inject our custom JavaScript for right-click exclude and
    # the excluded images panel
    inject_custom_ui(output_path, image_meta, thumbnails, db_path)

    return os.path.abspath(output_path)


# ===================================================================
# Custom UI injection
# ===================================================================

def inject_custom_ui(html_path, image_meta, thumbnails, db_path):
    """
    Inject CSS, HTML panel, and JavaScript into the pyvis-generated
    HTML for right-click exclude, freeze physics after stabilization,
    and excluded images review panel.
    """
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Build a compact JS-safe dict of image metadata + thumbnails
    js_meta = {}
    for md5, m in image_meta.items():
        thumb = thumbnails.get(md5)
        js_meta[md5] = {
            "md5": md5,
            "format": m.get("format"),
            "width": m.get("width"),
            "height": m.get("height"),
            "usage": m.get("usage", []),
            "thumbnail": thumb[0] if thumb else None,
        }
    meta_json = json.dumps(js_meta)
    db_name_json = json.dumps(os.path.basename(db_path))

    css = """
    <style>
      body { margin: 0; background: #1B1B1B; overflow: hidden; }
      #toolbar {
        position: fixed; top: 0; left: 0; right: 0; height: 48px;
        background: #252525; border-bottom: 2px solid #ED1C24;
        display: flex; align-items: center; padding: 0 16px;
        z-index: 1000; font-family: "Segoe UI", sans-serif;
        color: #F0F0F0;
      }
      #toolbar .title { font-weight: bold; font-size: 15px; }
      #toolbar .title .accent { color: #ED1C24; }
      #toolbar .spacer { flex: 1; }
      #toolbar button {
        background: #363636; color: #F0F0F0; border: 1px solid #3D3D3D;
        padding: 6px 14px; margin-left: 8px; cursor: pointer;
        font-size: 13px; border-radius: 2px;
      }
      #toolbar button:hover { background: #3A3A3A; border-color: #ED1C24; }
      #toolbar .count {
        background: #ED1C24; color: #fff; padding: 2px 8px;
        border-radius: 10px; margin-left: 6px; font-size: 11px;
      }
      #mynetwork { position: fixed !important; top: 48px; left: 0;
                   right: 0; bottom: 0; border: none !important; }

      #excluded-panel {
        position: fixed; top: 48px; right: 0; bottom: 0; width: 340px;
        background: #252525; border-left: 1px solid #3D3D3D;
        color: #F0F0F0; font-family: "Segoe UI", sans-serif;
        z-index: 999; display: none; flex-direction: column;
      }
      #excluded-panel.open { display: flex; }
      #excluded-panel .panel-header {
        padding: 14px 16px; border-bottom: 1px solid #3D3D3D;
        display: flex; align-items: center; justify-content: space-between;
      }
      #excluded-panel .panel-header h3 {
        margin: 0; font-size: 14px; color: #F0F0F0;
        text-transform: uppercase; letter-spacing: 0.5px;
      }
      #excluded-panel .close-btn {
        background: none; border: none; color: #A8A8A8;
        font-size: 20px; cursor: pointer; padding: 0;
      }
      #excluded-panel .close-btn:hover { color: #ED1C24; }
      #excluded-list {
        flex: 1; overflow-y: auto; padding: 8px;
      }
      #excluded-list .item {
        background: #363636; margin-bottom: 8px; padding: 10px;
        border-radius: 3px; border: 1px solid #3D3D3D;
      }
      #excluded-list .item img {
        max-width: 100%; max-height: 140px; display: block;
        margin: 0 auto 8px; background: #fff; padding: 2px;
        border: 1px solid #555;
      }
      #excluded-list .item .md5 {
        font-family: monospace; font-size: 10px; color: #A8A8A8;
        word-break: break-all; margin-bottom: 6px;
      }
      #excluded-list .item .meta {
        font-size: 11px; color: #A8A8A8; margin-bottom: 8px;
      }
      #excluded-list .item button {
        background: #ED1C24; color: #fff; border: none;
        padding: 6px 12px; cursor: pointer; width: 100%;
        font-size: 12px; border-radius: 2px;
      }
      #excluded-list .item button:hover { background: #FA0F00; }
      #excluded-list .item button + button {
        margin-top: 6px;
      }
      #excluded-list .item button.report-btn-out {
        background: #363636; border: 1px solid #3D3D3D;
      }
      #excluded-list .item button.report-btn-out:hover {
        background: #3A3A3A; border-color: #EF9F27;
      }
      #excluded-list .item button.report-btn-in {
        background: #EF9F27; color: #000;
      }
      #excluded-list .item button.report-btn-in:hover {
        background: #FAC775;
      }
      #excluded-list .item .cross-badge {
        background: #EF9F27; color: #000; font-size: 10px;
        font-weight: bold; text-align: center; padding: 3px;
        margin-bottom: 6px; border-radius: 2px;
        letter-spacing: 0.5px;
      }
      #excluded-list .empty {
        text-align: center; color: #7A7A7A; padding: 40px 20px;
        font-size: 12px;
      }

      #context-menu {
        position: fixed; background: #252525;
        border: 1px solid #3D3D3D; border-radius: 3px;
        z-index: 2000; display: none; min-width: 200px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.5);
      }
      #context-menu .menu-item {
        padding: 10px 16px; color: #F0F0F0; cursor: pointer;
        font-family: "Segoe UI", sans-serif; font-size: 13px;
      }
      #context-menu .menu-item:hover { background: #ED1C24; }

      .vis-tooltip {
        background-color: #252525 !important;
        border: 1px solid #3D3D3D !important;
        color: #F0F0F0 !important;
        font-family: "Segoe UI", sans-serif !important;
        font-size: 12px !important;
        padding: 10px !important;
        border-radius: 3px !important;
        max-width: 280px !important;
      }
    </style>
    """

    toolbar_html = """
    <div id="toolbar">
      <div class="title"><span class="accent">PDF</span> FORENSICS — Image Graph</div>
      <div class="spacer"></div>
      <button id="exclude-all-btn">Exclude all images</button>
      <button id="include-all-btn">Include all images</button>
      <button id="fit-btn">Fit to screen</button>
      <button id="physics-btn">Restart layout</button>
      <button id="report-btn">
        Report <span class="count" id="report-count">0</span>
      </button>
      <button id="excluded-btn">
        Excluded images <span class="count" id="excluded-count">0</span>
      </button>
    </div>
    <div id="excluded-panel">
      <div class="panel-header">
        <h3>Excluded Images</h3>
        <button class="close-btn" id="close-panel">×</button>
      </div>
      <div id="excluded-list"></div>
    </div>
    <div id="context-menu">
      <div class="menu-item" id="menu-exclude">Exclude this image</div>
      <div class="menu-item" id="menu-toggle-report">Add to report</div>
    </div>
    """

    script = f"""
    <script>
    const IMAGE_META = {meta_json};
    const DB_NAME = {db_name_json};
    const excludedImages = new Set();
    const reportImages = new Set();
    let rightClickedNodeId = null;

    function nodeIsImage(nodeId) {{
      return typeof nodeId === "string" && nodeId.startsWith("img_");
    }}

    function md5FromNodeId(nodeId) {{
      return nodeId.replace(/^img_/, "");
    }}

    // -----------------------------------------------------------------
    // Build tooltip as a real DOM element (vis.js renders these, not
    // HTML strings).
    // -----------------------------------------------------------------
    function makeImageTooltip(md5) {{
      const meta = IMAGE_META[md5];
      if (!meta) return null;

      const root = document.createElement("div");
      root.style.maxWidth = "280px";
      root.style.color = "#F0F0F0";
      root.style.fontFamily = "Segoe UI, sans-serif";
      root.style.fontSize = "12px";

      if (meta.thumbnail) {{
        const img = document.createElement("img");
        img.src = meta.thumbnail;
        img.style.maxWidth = "260px";
        img.style.maxHeight = "220px";
        img.style.display = "block";
        img.style.margin = "0 auto 8px";
        img.style.background = "#fff";
        img.style.padding = "2px";
        img.style.border = "1px solid #555";
        root.appendChild(img);
      }} else {{
        const no = document.createElement("div");
        no.style.color = "#7A7A7A";
        no.style.fontStyle = "italic";
        no.style.marginBottom = "6px";
        no.textContent = "(no thumbnail — image bytes not stored in database)";
        root.appendChild(no);
      }}

      const docCount = new Set(meta.usage.map(u => u.pdf)).size;
      const isCrossDoc = docCount > 1;

      if (isCrossDoc) {{
        const warn = document.createElement("div");
        warn.style.color = "#EF9F27";
        warn.style.fontWeight = "bold";
        warn.style.marginBottom = "4px";
        warn.textContent = "\\u26A0 CROSS-DOCUMENT REUSE";
        root.appendChild(warn);
      }}

      function addLine(label, value) {{
        const line = document.createElement("div");
        const b = document.createElement("b");
        b.textContent = label + " ";
        line.appendChild(b);
        line.appendChild(document.createTextNode(value));
        root.appendChild(line);
      }}

      addLine("MD5:", md5.substring(0, 16) + "...");
      addLine("Format:", meta.format || "?");
      addLine("Dimensions:",
              (meta.width || "?") + "\\u00D7" + (meta.height || "?"));
      addLine("Placements:", String(meta.usage.length));
      addLine("Documents:", String(docCount));

      const hint = document.createElement("div");
      hint.style.marginTop = "6px";
      hint.style.color = "#7A7A7A";
      hint.style.fontSize = "11px";
      hint.textContent = "Right-click to exclude";
      root.appendChild(hint);

      return root;
    }}

    function makeDocTooltip(pdfFilename) {{
      const root = document.createElement("div");
      root.style.color = "#F0F0F0";
      root.style.fontFamily = "Segoe UI, sans-serif";
      root.style.fontSize = "12px";
      const b = document.createElement("b");
      b.textContent = "Document";
      root.appendChild(b);
      root.appendChild(document.createElement("br"));
      root.appendChild(document.createTextNode(pdfFilename));
      return root;
    }}

    function makePageTooltip(pageNumber, pdfFilename) {{
      const root = document.createElement("div");
      root.style.color = "#F0F0F0";
      root.style.fontFamily = "Segoe UI, sans-serif";
      root.style.fontSize = "12px";
      const b = document.createElement("b");
      b.textContent = "Page " + pageNumber;
      root.appendChild(b);
      root.appendChild(document.createElement("br"));
      root.appendChild(document.createTextNode(pdfFilename));
      return root;
    }}

    // Apply DOM tooltips to all nodes currently in the dataset
    function applyTooltipsToAllNodes() {{
      nodes.forEach(function(node) {{
        if (node.id.startsWith("img_")) {{
          const md5 = md5FromNodeId(node.id);
          const tip = makeImageTooltip(md5);
          if (tip) nodes.update({{ id: node.id, title: tip }});
        }} else if (node.id.startsWith("doc_")) {{
          const orig = ORIGINAL_NODES[node.id] || node;
          if (orig.pdf_filename) {{
            nodes.update({{
              id: node.id,
              title: makeDocTooltip(orig.pdf_filename)
            }});
          }}
        }} else if (node.id.startsWith("page_")) {{
          const orig = ORIGINAL_NODES[node.id] || node;
          if (orig.page_number && orig.pdf_filename) {{
            nodes.update({{
              id: node.id,
              title: makePageTooltip(orig.page_number, orig.pdf_filename)
            }});
          }}
        }}
      }});
    }}

    // -----------------------------------------------------------------
    // Exclude / include logic
    // -----------------------------------------------------------------
    function excludeImage(nodeId) {{
      if (!nodeIsImage(nodeId)) return;
      const md5 = md5FromNodeId(nodeId);
      excludedImages.add(md5);

      const connectedPages = network.getConnectedNodes(nodeId)
        .filter(id => typeof id === "string" && id.startsWith("page_"));

      nodes.remove(nodeId);

      connectedPages.forEach(pageId => {{
        const remaining = network.getConnectedNodes(pageId)
          .filter(id => typeof id === "string" && id.startsWith("img_"));
        if (remaining.length === 0) {{
          const docNeighbors = network.getConnectedNodes(pageId)
            .filter(id => typeof id === "string" && id.startsWith("doc_"));
          nodes.remove(pageId);
          docNeighbors.forEach(docId => {{
            const pagesLeft = network.getConnectedNodes(docId)
              .filter(id => typeof id === "string" && id.startsWith("page_"));
            if (pagesLeft.length === 0) {{
              nodes.remove(docId);
            }}
          }});
        }}
      }});

      updateExcludedPanel();
    }}

    function excludeAllImages() {{
      // Collect all image node ids currently in the graph
      const imageIds = [];
      nodes.forEach(function(node) {{
        if (nodeIsImage(node.id)) imageIds.push(node.id);
      }});
      imageIds.forEach(id => {{
        excludedImages.add(md5FromNodeId(id));
      }});
      // Remove every non-image as well (since no image = no graph)
      nodes.clear();
      edges.clear();
      updateExcludedPanel();
    }}

    function includeAllImages() {{
      // Restore every image in IMAGE_META
      Object.keys(IMAGE_META).forEach(md5 => {{
        if (excludedImages.has(md5)) {{
          restoreImage(md5, {{
            skipPanelUpdate: true,
            skipRelayout: true,
          }});
        }}
      }});
      updateExcludedPanel();
      relayoutNewNodes();
    }}

    function restoreImage(md5, opts) {{
      opts = opts || {{}};
      excludedImages.delete(md5);
      const nodeId = "img_" + md5;
      const meta = IMAGE_META[md5];
      if (!meta) return;

      const docCount = new Set(meta.usage.map(u => u.pdf)).size;
      const isCrossDoc = docCount > 1;
      const placements = meta.usage.length;
      const size = Math.min(20 + placements * 3, 60);

      // Determine a center position for the new cluster. If other
      // nodes already exist, place this cluster in empty space;
      // otherwise center at origin.
      const existingPositions = network.getPositions();
      const existingIds = Object.keys(existingPositions);
      let centerX = 0, centerY = 0;
      if (existingIds.length > 0) {{
        // Place the new cluster to the right of the bounding box
        // of existing nodes, with some padding
        let maxX = -Infinity;
        existingIds.forEach(id => {{
          if (existingPositions[id].x > maxX) {{
            maxX = existingPositions[id].x;
          }}
        }});
        centerX = maxX + 400;
        centerY = 0;
      }}

      // Collect all page nodes that will be added for this image
      const pagesToAdd = [];
      const docsToAdd = new Set();
      ORIGINAL_EDGES.forEach(e => {{
        if (e.to === nodeId || e.from === nodeId) {{
          const pageId = (e.from === nodeId) ? e.to : e.from;
          if (!nodes.get(pageId) && ORIGINAL_NODES[pageId]) {{
            if (!pagesToAdd.includes(pageId)) {{
              pagesToAdd.push(pageId);
            }}
          }}
          // Find the document for this page
          ORIGINAL_EDGES.forEach(e2 => {{
            if (e2.from === pageId || e2.to === pageId) {{
              const otherId = (e2.from === pageId) ? e2.to : e2.from;
              if (otherId.startsWith("doc_") && !nodes.get(otherId)
                  && ORIGINAL_NODES[otherId]) {{
                docsToAdd.add(otherId);
              }}
            }}
          }});
        }}
      }});

      // Add image node at cluster center
      nodes.add({{
        id: nodeId,
        label: md5.substring(0, 8),
        title: makeImageTooltip(md5),
        color: isCrossDoc ? "#EF9F27" : "#E24B4A",
        shape: "dot",
        size: size,
        group: "image",
        x: centerX,
        y: centerY,
      }});

      // Add page nodes in a circle around the image
      const pageRadius = 180;
      const numPages = pagesToAdd.length;
      pagesToAdd.forEach((pageId, idx) => {{
        const pn = Object.assign({{}}, ORIGINAL_NODES[pageId]);
        if (pn.page_number && pn.pdf_filename) {{
          pn.title = makePageTooltip(pn.page_number, pn.pdf_filename);
        }}
        // Distribute pages on a circle around the image
        const angle = (idx / Math.max(numPages, 1)) * Math.PI * 2;
        pn.x = centerX + pageRadius * Math.cos(angle);
        pn.y = centerY + pageRadius * Math.sin(angle);
        nodes.add(pn);
      }});

      // Add document nodes on an outer ring
      const docRadius = 380;
      const docIds = Array.from(docsToAdd);
      docIds.forEach((docId, idx) => {{
        const dn = Object.assign({{}}, ORIGINAL_NODES[docId]);
        if (dn.pdf_filename) {{
          dn.title = makeDocTooltip(dn.pdf_filename);
        }}
        // Spread documents evenly around the outer ring
        const angle = (idx / Math.max(docIds.length, 1)) * Math.PI * 2;
        dn.x = centerX + docRadius * Math.cos(angle);
        dn.y = centerY + docRadius * Math.sin(angle);
        nodes.add(dn);
      }});

      // Add all edges touching the new nodes
      ORIGINAL_EDGES.forEach(e => {{
        if (nodes.get(e.from) && nodes.get(e.to)
            && !edges.get(e.id)) {{
          edges.add(e);
        }}
      }});

      if (!opts.skipPanelUpdate) {{
        updateExcludedPanel();
      }}

      if (!opts.skipRelayout) {{
        // Run brief physics to let the new nodes settle into
        // non-overlapping positions
        relayoutNewNodes();
      }}
    }}

    // Briefly re-enable physics so newly-added nodes can settle
    // without overlapping. Existing nodes barely move because they
    // are already in stable positions.
    let relayoutTimer = null;
    function relayoutNewNodes() {{
      if (relayoutTimer) clearTimeout(relayoutTimer);
      network.setOptions({{ physics: {{ enabled: true }} }});
      network.stabilize(150);
      relayoutTimer = setTimeout(function() {{
        network.setOptions({{ physics: {{ enabled: false }} }});
      }}, 1500);
    }}

    // -----------------------------------------------------------------
    // Excluded panel
    // -----------------------------------------------------------------
    function updateExcludedPanel() {{
      const list = document.getElementById("excluded-list");
      const countBadge = document.getElementById("excluded-count");
      countBadge.textContent = excludedImages.size;

      if (excludedImages.size === 0) {{
        list.innerHTML = '<div class="empty">No images excluded.<br><br>Right-click an image node to exclude it, or use "Exclude all images" to clear the graph.</div>';
        return;
      }}

      // Sort excluded images: cross-document first, then by placements
      const sorted = Array.from(excludedImages).sort((a, b) => {{
        const ma = IMAGE_META[a], mb = IMAGE_META[b];
        if (!ma || !mb) return 0;
        const crossA = new Set(ma.usage.map(u => u.pdf)).size > 1;
        const crossB = new Set(mb.usage.map(u => u.pdf)).size > 1;
        if (crossA !== crossB) return crossB - crossA;
        return mb.usage.length - ma.usage.length;
      }});

      let html = "";
      sorted.forEach(md5 => {{
        const meta = IMAGE_META[md5];
        if (!meta) return;
        const docCount = new Set(meta.usage.map(u => u.pdf)).size;
        const isCrossDoc = docCount > 1;
        const thumb = meta.thumbnail
          ? `<img src="${{meta.thumbnail}}" />`
          : "<div style='text-align:center;color:#7A7A7A;padding:20px'>(no thumbnail)</div>";
        const crossBadge = isCrossDoc
          ? '<div class="cross-badge">CROSS-DOC</div>'
          : '';
        const inReport = reportImages.has(md5);
        const reportBtnLabel = inReport
          ? "Remove from report"
          : "Add to report";
        const reportBtnClass = inReport
          ? "report-btn-in"
          : "report-btn-out";
        html += `
          <div class="item">
            ${{crossBadge}}
            ${{thumb}}
            <div class="md5">${{md5}}</div>
            <div class="meta">
              ${{meta.format || "?"}} &bull; ${{meta.width || "?"}}&times;${{meta.height || "?"}}<br>
              ${{meta.usage.length}} placement(s), ${{docCount}} document(s)
            </div>
            <button onclick="restoreImage('${{md5}}')">Add to graph</button>
            <button class="${{reportBtnClass}}" onclick="toggleReport('${{md5}}')">${{reportBtnLabel}}</button>
          </div>
        `;
      }});
      list.innerHTML = html;
    }}

    // -----------------------------------------------------------------
    // Report generation
    // -----------------------------------------------------------------
    function toggleReport(md5) {{
      if (reportImages.has(md5)) {{
        reportImages.delete(md5);
      }} else {{
        reportImages.add(md5);
      }}
      document.getElementById("report-count").textContent = reportImages.size;
      updateExcludedPanel();
    }}

    function escapeHtml(s) {{
      if (s == null) return "";
      return String(s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/\"/g, "&quot;");
    }}

    function generateReport() {{
      if (reportImages.size === 0) {{
        alert("No images selected for the report.\\n\\n" +
              "Right-click an image in the graph and choose " +
              "\\"Add to report\\", or click \\"Add to report\\" " +
              "in the excluded images panel.");
        return;
      }}

      // Sort by cross-doc first, then placements
      const sorted = Array.from(reportImages).sort((a, b) => {{
        const ma = IMAGE_META[a], mb = IMAGE_META[b];
        if (!ma || !mb) return 0;
        const crossA = new Set(ma.usage.map(u => u.pdf)).size > 1;
        const crossB = new Set(mb.usage.map(u => u.pdf)).size > 1;
        if (crossA !== crossB) return crossB - crossA;
        return mb.usage.length - ma.usage.length;
      }});

      const now = new Date();
      const timestamp = now.toLocaleString();

      let html = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>PDF Forensics Report</title>
<style>
  @page {{ size: letter; margin: 0.75in; }}
  @media print {{
    body {{ background: #fff !important; color: #000 !important; }}
    .no-print {{ display: none !important; }}
    .report-item {{ page-break-inside: avoid; }}
  }}
  body {{
    font-family: "Segoe UI", Arial, sans-serif;
    background: #f5f5f5; color: #222;
    max-width: 850px; margin: 0 auto;
    padding: 20px;
  }}
  header {{
    border-bottom: 3px solid #ED1C24;
    padding-bottom: 16px; margin-bottom: 24px;
  }}
  header h1 {{
    margin: 0; font-size: 26px;
    color: #222;
  }}
  header h1 .accent {{ color: #ED1C24; }}
  header .meta {{
    color: #666; font-size: 12px; margin-top: 8px;
  }}
  .toolbar {{
    position: sticky; top: 0; background: #252525;
    color: #fff; padding: 12px 16px;
    margin: -20px -20px 20px; z-index: 100;
    border-bottom: 2px solid #ED1C24;
    display: flex; justify-content: space-between;
    align-items: center;
  }}
  .toolbar button {{
    background: #ED1C24; color: #fff; border: none;
    padding: 10px 20px; font-size: 13px;
    cursor: pointer; border-radius: 2px;
    font-weight: bold;
  }}
  .toolbar button:hover {{ background: #FA0F00; }}
  .toolbar .instruction {{
    font-size: 12px; color: #ccc;
  }}
  .report-item {{
    background: #fff; border: 1px solid #ddd;
    padding: 20px; margin-bottom: 20px;
    border-radius: 3px;
  }}
  .report-item.cross-doc {{
    border-left: 4px solid #EF9F27;
  }}
  .item-header {{
    display: flex; gap: 20px; margin-bottom: 16px;
  }}
  .item-thumb {{
    flex-shrink: 0; width: 200px;
    background: #f9f9f9; border: 1px solid #ccc;
    padding: 8px; text-align: center;
  }}
  .item-thumb img {{
    max-width: 100%; max-height: 200px;
  }}
  .item-details {{ flex: 1; }}
  .item-details h2 {{
    margin: 0 0 8px; font-size: 16px;
    color: #222;
  }}
  .cross-badge {{
    display: inline-block; background: #EF9F27;
    color: #000; font-size: 10px; font-weight: bold;
    padding: 3px 8px; border-radius: 2px;
    margin-bottom: 8px; letter-spacing: 0.5px;
  }}
  .detail-row {{
    font-size: 12px; color: #444;
    margin: 4px 0;
  }}
  .detail-row strong {{
    display: inline-block; min-width: 100px;
    color: #666;
  }}
  .detail-row code {{
    font-family: "Consolas", monospace;
    font-size: 11px; background: #f5f5f5;
    padding: 1px 4px; word-break: break-all;
  }}
  .appearances-table {{
    width: 100%; border-collapse: collapse;
    margin-top: 12px; font-size: 12px;
  }}
  .appearances-table th {{
    background: #252525; color: #fff;
    text-align: left; padding: 8px 10px;
    font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.5px;
  }}
  .appearances-table td {{
    padding: 6px 10px; border-bottom: 1px solid #eee;
  }}
  .appearances-table tr:last-child td {{
    border-bottom: none;
  }}
  .summary-box {{
    background: #fff; border-left: 4px solid #ED1C24;
    padding: 14px 18px; margin-bottom: 24px;
  }}
  .summary-box h3 {{
    margin: 0 0 8px; font-size: 14px;
    text-transform: uppercase; letter-spacing: 0.5px;
    color: #666;
  }}
  .summary-box .stats {{
    display: flex; gap: 24px;
  }}
  .summary-box .stat {{
    font-size: 13px; color: #444;
  }}
  .summary-box .stat strong {{
    display: block; font-size: 22px;
    color: #ED1C24;
  }}
</style>
</head>
<body>
  <div class="toolbar no-print">
    <span class="instruction">Use your browser's print function (Ctrl+P / ⌘P) and select "Save as PDF"</span>
    <button onclick="window.print()">Print / Save as PDF</button>
  </div>
  <header>
    <h1><span class="accent">PDF</span> Forensics Report</h1>
    <div class="meta">
      Generated: ${{escapeHtml(timestamp)}}<br>
      Database: ${{escapeHtml(DB_NAME)}}<br>
      Images in report: ${{reportImages.size}}
    </div>
  </header>
`;

      // Summary box
      let totalPlacements = 0;
      const allDocs = new Set();
      let crossDocCount = 0;
      sorted.forEach(md5 => {{
        const meta = IMAGE_META[md5];
        if (!meta) return;
        totalPlacements += meta.usage.length;
        meta.usage.forEach(u => allDocs.add(u.pdf));
        if (new Set(meta.usage.map(u => u.pdf)).size > 1) {{
          crossDocCount++;
        }}
      }});

      html += `
  <div class="summary-box">
    <h3>Summary</h3>
    <div class="stats">
      <div class="stat"><strong>${{sorted.length}}</strong>Unique images</div>
      <div class="stat"><strong>${{totalPlacements}}</strong>Total placements</div>
      <div class="stat"><strong>${{allDocs.size}}</strong>Documents</div>
      <div class="stat"><strong>${{crossDocCount}}</strong>Cross-document</div>
    </div>
  </div>
`;

      // Per-image sections
      sorted.forEach((md5, idx) => {{
        const meta = IMAGE_META[md5];
        if (!meta) return;

        const docCount = new Set(meta.usage.map(u => u.pdf)).size;
        const isCrossDoc = docCount > 1;
        const crossClass = isCrossDoc ? " cross-doc" : "";
        const crossBadge = isCrossDoc
          ? '<div class="cross-badge">CROSS-DOCUMENT REUSE</div>'
          : '';
        const thumbHtml = meta.thumbnail
          ? `<img src="${{meta.thumbnail}}" alt="Image ${{idx+1}}">`
          : '<span style="color:#999;font-style:italic">No thumbnail</span>';

        // Group placements by document
        const byDoc = {{}};
        meta.usage.forEach(u => {{
          if (!byDoc[u.pdf]) byDoc[u.pdf] = [];
          byDoc[u.pdf].push(u);
        }});

        let rowsHtml = "";
        Object.keys(byDoc).sort().forEach(pdf => {{
          const placements = byDoc[pdf].sort(
            (a, b) => a.page - b.page);
          placements.forEach((p, pidx) => {{
            const pdfCell = pidx === 0
              ? `<td rowspan="${{placements.length}}">${{escapeHtml(pdf)}}</td>`
              : "";
            rowsHtml += `
              <tr>
                ${{pdfCell}}
                <td>${{p.page}}</td>
                <td><code>${{escapeHtml(p.label)}}</code></td>
              </tr>`;
          }});
        }});

        html += `
  <div class="report-item${{crossClass}}">
    <div class="item-header">
      <div class="item-thumb">${{thumbHtml}}</div>
      <div class="item-details">
        <h2>Image ${{idx + 1}}</h2>
        ${{crossBadge}}
        <div class="detail-row"><strong>MD5:</strong> <code>${{escapeHtml(md5)}}</code></div>
        <div class="detail-row"><strong>Format:</strong> ${{escapeHtml(meta.format || "unknown")}}</div>
        <div class="detail-row"><strong>Dimensions:</strong> ${{meta.width || "?"}} × ${{meta.height || "?"}} px</div>
        <div class="detail-row"><strong>Placements:</strong> ${{meta.usage.length}}</div>
        <div class="detail-row"><strong>Documents:</strong> ${{docCount}}</div>
      </div>
    </div>
    <table class="appearances-table">
      <thead>
        <tr><th>Document</th><th>Page</th><th>Image label</th></tr>
      </thead>
      <tbody>${{rowsHtml}}</tbody>
    </table>
  </div>
`;
      }});

      html += `</body></html>`;

      // Open in new tab via Blob URL
      const blob = new Blob([html], {{ type: "text/html" }});
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
    }}

    // -----------------------------------------------------------------
    // Setup
    // -----------------------------------------------------------------
    function setupCustomUI() {{
      if (typeof network === "undefined") {{
        setTimeout(setupCustomUI, 100);
        return;
      }}

      // Capture original nodes/edges for restoration
      window.ORIGINAL_NODES = {{}};
      nodes.forEach(n => {{
        ORIGINAL_NODES[n.id] = Object.assign({{}}, n);
      }});
      window.ORIGINAL_EDGES = edges.get().map(e => Object.assign({{}}, e));

      // Freeze physics after initial stabilization
      network.on("stabilizationIterationsDone", function() {{
        network.setOptions({{ physics: {{ enabled: false }} }});
      }});

      // Apply DOM tooltips to all existing nodes
      applyTooltipsToAllNodes();

      // Right-click handler
      network.on("oncontext", function(params) {{
        params.event.preventDefault();
        const nodeId = network.getNodeAt(params.pointer.DOM);
        if (!nodeId || !nodeIsImage(nodeId)) {{
          document.getElementById("context-menu").style.display = "none";
          return;
        }}
        rightClickedNodeId = nodeId;
        const md5 = md5FromNodeId(nodeId);
        // Update the report menu item label based on current state
        document.getElementById("menu-toggle-report").textContent =
          reportImages.has(md5)
            ? "Remove from report"
            : "Add to report";
        const menu = document.getElementById("context-menu");
        menu.style.left = params.event.pageX + "px";
        menu.style.top = params.event.pageY + "px";
        menu.style.display = "block";
      }});

      document.addEventListener("click", function() {{
        document.getElementById("context-menu").style.display = "none";
      }});

      document.getElementById("menu-exclude").addEventListener("click", function(ev) {{
        ev.stopPropagation();
        if (rightClickedNodeId) {{
          excludeImage(rightClickedNodeId);
          rightClickedNodeId = null;
        }}
        document.getElementById("context-menu").style.display = "none";
      }});

      document.getElementById("menu-toggle-report").addEventListener("click", function(ev) {{
        ev.stopPropagation();
        if (rightClickedNodeId) {{
          toggleReport(md5FromNodeId(rightClickedNodeId));
          rightClickedNodeId = null;
        }}
        document.getElementById("context-menu").style.display = "none";
      }});

      document.getElementById("report-btn").addEventListener("click", function() {{
        generateReport();
      }});

      document.getElementById("exclude-all-btn").addEventListener("click", function() {{
        if (nodes.length === 0) return;
        if (confirm("Exclude all images from the graph?")) {{
          excludeAllImages();
        }}
      }});

      document.getElementById("include-all-btn").addEventListener("click", function() {{
        includeAllImages();
      }});

      document.getElementById("excluded-btn").addEventListener("click", function() {{
        const panel = document.getElementById("excluded-panel");
        panel.classList.toggle("open");
      }});

      document.getElementById("close-panel").addEventListener("click", function() {{
        document.getElementById("excluded-panel").classList.remove("open");
      }});

      document.getElementById("fit-btn").addEventListener("click", function() {{
        network.fit({{ animation: {{ duration: 500 }} }});
      }});

      document.getElementById("physics-btn").addEventListener("click", function() {{
        network.setOptions({{ physics: {{ enabled: true }} }});
        network.stabilize(300);
        setTimeout(function() {{
          network.setOptions({{ physics: {{ enabled: false }} }});
        }}, 3000);
      }});

      updateExcludedPanel();
    }}

    setupCustomUI();
    </script>
    """

    # Inject CSS before </head>
    if "</head>" in html:
        html = html.replace("</head>", css + "</head>")
    else:
        html = css + html

    # Inject toolbar immediately after <body>
    if "<body>" in html:
        html = html.replace("<body>", "<body>" + toolbar_html)
    else:
        html = toolbar_html + html

    # Inject script before </body>
    if "</body>" in html:
        html = html.replace("</body>", script + "</body>")
    else:
        html = html + script

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)


# ===================================================================
# Summary
# ===================================================================

def print_summary(rows, G, thumbnail_count):
    md5_set = {row[6] for row in rows}
    doc_set = {row[0] for row in rows}
    page_set = {row[2] for row in rows}

    cross_doc_md5s = [
        node for node, data in G.nodes(data=True)
        if data.get("node_type") == "image"
        and data.get("color") == COLOR_IMAGE_CROSS
    ]

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Unique duplicate images:  {len(md5_set)}")
    print(f"  Documents involved:       {len(doc_set)}")
    print(f"  Pages involved:           {len(page_set)}")
    print(f"  Total placements:         {len(rows)}")
    print(f"  Cross-document images:    {len(cross_doc_md5s)}")
    print(f"  Thumbnails embedded:      "
          f"{thumbnail_count} / {len(md5_set)}")
    if thumbnail_count < len(md5_set):
        print("    (missing thumbnails = images not stored in DB)")


# ===================================================================
# Main
# ===================================================================

def prompt_scope():
    print()
    print("Select duplicate detection scope:")
    print("  1. All placements      (same image appearing 2+ times)")
    print("  2. Cross-page          (same image on 2+ distinct pages)")
    print("  3. Cross-document      (same image in 2+ documents) "
          "[most interesting]")
    choice = input("Choice [1/2/3] (default 3): ").strip()
    return {
        "1": "all_placements",
        "2": "cross_page",
        "3": "cross_document",
        "": "cross_document",
    }.get(choice, "cross_document")


def main():
    cli_path = sys.argv[1] if len(sys.argv) > 1 else None
    db_path = select_database(cli_path)
    if not db_path:
        print("No database selected. Exiting.")
        sys.exit(1)

    print(f"Database: {db_path}")

    try:
        conn = sqlite3.connect(db_path)
        validate_database(conn)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    scope = prompt_scope()
    print(f"Scope: {scope}")

    print("Loading data...")
    rows = load_data(conn, scope=scope)
    print(f"Loaded {len(rows)} placement row(s)")

    if not rows:
        print("No duplicate images found for the selected scope.")
        conn.close()
        return

    print("Loading image bytes...")
    md5_set = {row[6] for row in rows}
    image_bytes = load_image_bytes(conn, md5_set)
    print(f"Retrieved bytes for {len(image_bytes)} unique image(s)")

    print("Generating thumbnails...")
    thumbnails = {}
    for md5, (blob, ext, w, h) in image_bytes.items():
        thumb = make_thumbnail_data_uri(blob, ext, w, h)
        if thumb:
            thumbnails[md5] = thumb
    print(f"Generated {len(thumbnails)} thumbnail(s)")

    print("Building graph...")
    G = build_graph(rows, thumbnails)

    print("Building metadata dict...")
    image_meta = build_image_metadata(rows)

    print("Rendering...")
    output = visualize_graph(G, image_meta, thumbnails, db_path)

    print_summary(rows, G, len(thumbnails))

    print()
    print(f"Graph written to: {output}")
    print("Open it in your browser to interact with the graph.")
    print()
    print("Controls:")
    print("  - Hover over a node: see details (images show thumbnails)")
    print("  - Right-click an image node: exclude from graph")
    print("  - 'Excluded images' button: review/restore excluded items")
    print("  - 'Fit to screen': reset view")
    print("  - 'Restart layout': re-run physics if things look cramped")

    conn.close()


if __name__ == "__main__":
    main()
