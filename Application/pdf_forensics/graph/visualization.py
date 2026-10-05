"""
Graph visualization and custom UI injection.

visualize_graph() creates a pyvis HTML file, then inject_custom_ui()
post-processes it to add the interactive features (right-click menus,
exclude/restore, report generation, etc.).
"""

import os
import json

try:
    from pyvis.network import Network
except ImportError:
    pass


def get_pdf_dirs_from_db(conn):
    """
    Return a list of unique directories where the analyzed PDFs
    were stored. Used to suggest a default output location.
    """
    try:
        rows = conn.execute(
            "SELECT DISTINCT pdf_path FROM analyses").fetchall()
    except Exception:
        return []
    dirs = []
    for (path,) in rows:
        if path:
            d = os.path.dirname(path)
            if d and d not in dirs and os.path.isdir(d):
                dirs.append(d)
    return dirs


def select_output_path(db_path, conn,
                       default_filename="image_relationship_graph.html"):
    """
    Choose where to write the output HTML file.

    Default-path resolution chain:
      1. The directory containing the database
      2. The directory containing the analyzed PDFs (from the DB)
      3. The current working directory

    The user gets a save-file dialog (or terminal prompt fallback)
    pre-populated with the chosen default. If they cancel, returns
    None.
    """
    # Choose default directory using the resolution chain
    default_dir = None
    if db_path and os.path.isdir(os.path.dirname(os.path.abspath(db_path))):
        default_dir = os.path.dirname(os.path.abspath(db_path))
    if not default_dir:
        pdf_dirs = get_pdf_dirs_from_db(conn)
        if pdf_dirs:
            default_dir = pdf_dirs[0]
    if not default_dir:
        default_dir = os.getcwd()

    suggested = os.path.join(default_dir, default_filename)

    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        path = filedialog.asksaveasfilename(
            title="Save graph HTML as",
            defaultextension=".html",
            initialdir=default_dir,
            initialfile=default_filename,
            filetypes=[
                ("HTML file", "*.html *.htm"),
                ("All files", "*.*"),
            ],
            confirmoverwrite=True,
        )
        root.destroy()
        if path:
            return path
        # User cancelled — fall back to suggested path with a prompt
        print(f"No output path selected. Using default: {suggested}")
        return suggested
    except Exception as e:
        print(f"GUI unavailable ({e}). Using prompt.")
        prompt = (f"Output HTML path "
                  f"[default: {suggested}]: ")
        path = input(prompt).strip().strip('"').strip("'")
        return path if path else suggested


# Scope names → (display label, plain-language definition). Embedded in
# each generated graph so the exhibit self-describes which filter
# produced it — two scopes can legitimately yield the same relationship
# set, and the file itself must say what it is.
SCOPE_INFO = {
    "all_placements": (
        "All Placements",
        "images whose content (MD5) appears in two or more placements "
        "anywhere, including repeats on the same page"),
    "cross_page": (
        "Cross-Page",
        "images whose content (MD5) appears on two or more distinct "
        "pages, in the same or different documents"),
    "cross_document": (
        "Cross-Document",
        "images whose content (MD5) appears in two or more distinct "
        "documents"),
}


def visualize_graph(G, image_meta, thumbnails, db_path,
                    doc_meta=None,
                    output_path="image_relationship_graph.html",
                    case_number=None,
                    scope=None, group_versions=True):
    # pyvis versions vary in what they accept for height/width.
    # Try CSS units first, then pixel strings, then bare integers.
    net = None
    for h, w in [("100vh", "100%"), ("900px", "1200px"), (900, 1200)]:
        try:
            net = Network(
                height=h, width=w,
                bgcolor="#1B1B1B",
                font_color="#F0F0F0",
                notebook=False,
                cdn_resources="remote",
            )
            break
        except (ValueError, TypeError):
            continue
    if net is None:
        raise RuntimeError(
            "Could not initialize pyvis Network. "
            "Try updating pyvis: pip install --upgrade pyvis")
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

    # Generation provenance is captured NOW — at write time — so the
    # exhibit carries the true generation timestamp. (Previously the
    # 'Generated' line was computed by JavaScript when the file was
    # VIEWED, which misrepresents an exhibit's creation time.)
    from datetime import datetime
    generated_at = datetime.now().astimezone().strftime(
        "%Y-%m-%d %H:%M:%S %Z")
    _version_reuse = sum(
        1 for d in (image_meta or {}).values()
        if d.get("is_version_reuse"))
    _cross_doc = sum(
        1 for d in (image_meta or {}).values()
        if d.get("is_cross_doc"))
    _version_docs = sum(
        1 for d in (doc_meta or {}).values()
        if d.get("is_version"))
    graph_stats = {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "unique_images": len(image_meta or {}),
        "documents": len(doc_meta or {}),
        "cross_doc_images": _cross_doc,
        "version_reuse_images": _version_reuse,
        "version_documents": _version_docs,
        "group_versions": bool(group_versions),
    }

    # Inject our custom JavaScript for right-click exclude and
    # the excluded images panel
    inject_custom_ui(output_path, image_meta, thumbnails, db_path,
                     doc_meta=doc_meta or {}, case_number=case_number,
                     scope=scope, generated_at=generated_at,
                     graph_stats=graph_stats)

    return os.path.abspath(output_path)


def inject_custom_ui(html_path, image_meta, thumbnails, db_path,
                     doc_meta=None, case_number=None,
                     scope=None, generated_at=None, graph_stats=None):
    """
    Inject CSS, HTML panel, and JavaScript into the pyvis-generated
    HTML for right-click exclude, freeze physics after stabilization,
    and excluded images review panel.
    """
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Load logo for toolbar
    logo_html = ""
    try:
        from pdf_forensics.assets import get_logo_base64
        logo_uri = get_logo_base64()
        if logo_uri:
            logo_html = (f'<img src="{logo_uri}" alt="" '
                         f'style="height:28px;margin-right:8px;">')
    except Exception:
        pass

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
            "risk_score":   m.get("risk_score", 0),
            "risk_tier":    m.get("risk_tier", "low"),
            "is_cross_doc": m.get("is_cross_doc", False),
            "findings":     m.get("findings", []),
        }
    meta_json = json.dumps(js_meta)
    db_name_json = json.dumps(os.path.basename(db_path))
    doc_meta_json = json.dumps(doc_meta or {})

    # Branding payload for the printable report cover + footer
    from pdf_forensics import branding as _branding
    from pdf_forensics.database import compute_file_md5
    from pdf_forensics import __version__ as _ver, __tool_name__ as _tn
    _bcfg = _branding.load_branding()
    _scope_label, _scope_def = SCOPE_INFO.get(
        scope or "", (scope or "", ""))
    _stats = graph_stats or {}
    branding_payload = {
        "agency_logo":   _branding.get_agency_logo_data_uri(_bcfg) or "",
        "info_pairs":    _branding.case_info_pairs(case_number, _bcfg),
        "classification": _branding.classification_text(_bcfg),
        "footer_text":   _branding.footer_text(case_number, _bcfg),
        "agency_name":   (_bcfg.get("agency_name") or "").strip(),
        "unit_name":     (_bcfg.get("unit_name") or "").strip(),
        "case_number":   case_number or "",
        "db_md5":        compute_file_md5(db_path) if db_path else "",
        "tool_label":    f"{_tn} v{_ver}",
        "generated_at":  generated_at or "",
        "scope":         scope or "",
        "scope_label":   _scope_label,
        "scope_definition": _scope_def,
        "graph_nodes":   _stats.get("nodes", ""),
        "graph_edges":   _stats.get("edges", ""),
        "unique_images": _stats.get("unique_images", ""),
        "documents":     _stats.get("documents", ""),
        "cross_doc_images":     _stats.get("cross_doc_images", ""),
        "version_reuse_images": _stats.get("version_reuse_images", ""),
        "version_documents":    _stats.get("version_documents", ""),
        "group_versions":       _stats.get("group_versions", True),
    }
    branding_json = json.dumps(branding_payload)

    css = """
    <style>
      #toolbar .scope-badge {
        display: inline-block; margin-left: 8px; padding: 1px 8px;
        border: 1px solid #E24B4A; border-radius: 3px;
        color: #F0F0F0; font-size: 11px; letter-spacing: 0.5px;
        vertical-align: middle; cursor: help;
      }
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
      #toolbar .legend {
        display: flex; gap: 14px; margin-left: 24px;
        align-items: center; font-size: 11px;
        color: #A8A8A8; letter-spacing: 0.3px;
      }
      #toolbar .legend-item {
        display: flex; align-items: center; gap: 5px;
        cursor: pointer; padding: 2px 6px; border-radius: 3px;
      }
      #toolbar .legend-item:hover { background: rgba(255,255,255,0.1); }
      #toolbar .legend .dot {
        display: inline-block; width: 10px; height: 10px;
        border-radius: 50%;
      }
      #toolbar .legend .dot.ring {
        background: #555; border: 2px solid #FA0F00;
      }
      #toolbar .legend .dot.version-ring {
        background: #555; border: 2px dashed #8E7CC3;
      }
      #toolbar .legend .dash {
        display: inline-block; width: 16px; height: 0;
        border-top: 2px dashed #6C8EBF; vertical-align: middle;
      }
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
      /* Nudge vis.js's built-in navigation buttons up from the
         very bottom so they aren't clipped by the viewport edge.
         Default position is bottom:10px which can clip on some
         displays. */
      .vis-navigation .vis-button {
        bottom: auto !important;
      }
      .vis-network div.vis-navigation {
        bottom: 30px !important;
      }

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
      .panel-tabs {
        display: flex; border-bottom: 1px solid #3D3D3D;
        background: #1F1F1F;
      }
      .panel-tabs .tab-btn {
        flex: 1; background: transparent; border: none;
        color: #A8A8A8; font-family: "Segoe UI", sans-serif;
        font-size: 12px; padding: 10px 8px; cursor: pointer;
        text-transform: uppercase; letter-spacing: 0.5px;
        border-bottom: 2px solid transparent;
      }
      .panel-tabs .tab-btn:hover { color: #F0F0F0; }
      .panel-tabs .tab-btn.active {
        color: #F0F0F0; border-bottom-color: #ED1C24;
      }
      .panel-tabs .tab-count {
        display: inline-block; background: #444;
        color: #fff; padding: 1px 6px; border-radius: 8px;
        font-size: 10px; margin-left: 4px;
      }
      .panel-tabs .tab-btn.active .tab-count {
        background: #ED1C24;
      }
      .tab-pane { display: none; }
      .tab-pane.active { display: block; }
      #excluded-list, #excluded-doc-list {
        flex: 1; overflow-y: auto; padding: 8px;
      }
      #excluded-doc-list .item {
        background: #363636; margin-bottom: 8px; padding: 12px;
        border-radius: 3px; border: 1px solid #3D3D3D;
      }
      #excluded-doc-list .item .doc-name {
        font-weight: bold; color: #F0F0F0;
        margin-bottom: 6px; word-break: break-all;
        font-size: 12px;
      }
      #excluded-doc-list .item .doc-meta {
        font-size: 11px; color: #A8A8A8; margin-bottom: 8px;
      }
      #excluded-doc-list .item button {
        background: #378ADD; color: #fff; border: none;
        padding: 6px 12px; cursor: pointer; width: 100%;
        font-size: 12px; border-radius: 2px;
      }
      #excluded-doc-list .item button:hover {
        background: #4A9EE8;
      }
      #excluded-doc-list .empty {
        text-align: center; color: #7A7A7A; padding: 40px 20px;
        font-size: 12px;
      }
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
      #excluded-list .item .risk-badge {
        font-size: 10px; font-weight: bold; text-align: center;
        padding: 4px; margin-bottom: 4px; border-radius: 2px;
        letter-spacing: 0.5px;
      }
      #excluded-list .item .cross-badge {
        background: transparent; color: #FA0F00;
        border: 2px solid #FA0F00;
        font-size: 10px;
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

      #legend-menu {
        position: fixed; background: #252525;
        border: 1px solid #3D3D3D; border-radius: 3px;
        z-index: 2000; display: none; min-width: 200px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.5);
      }
      #legend-menu .menu-item {
        padding: 10px 16px; color: #F0F0F0; cursor: pointer;
        font-family: "Segoe UI", sans-serif; font-size: 13px;
      }
      #legend-menu .menu-item:hover { background: #ED1C24; }

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

    def _attr_esc(s):
        return (str(s).replace("&", "&amp;").replace('"', "&quot;")
                .replace("<", "&lt;").replace(">", "&gt;"))

    _scope_suffix = ""
    if _scope_label:
        _scope_suffix = (
            ' <span class="scope-badge" title="Scope: '
            + _attr_esc(_scope_label) + " \u2014 " + _attr_esc(_scope_def)
            + ". Generated " + _attr_esc(generated_at or "unknown")
            + '.">' + _attr_esc(_scope_label) + "</span>")

    toolbar_html = f"""
    <div id="toolbar">
      <div class="title">{logo_html}<span class="accent">PDF</span> FORENSICS — Image Graph{_scope_suffix}</div>
      <div class="legend">
        <span class="legend-item" data-risk="low" title="Right-click for options"><span class="dot" style="background:#5DCAA5"></span>Low</span>
        <span class="legend-item" data-risk="mid" title="Right-click for options"><span class="dot" style="background:#EF9F27"></span>Mid</span>
        <span class="legend-item" data-risk="high" title="Right-click for options"><span class="dot" style="background:#E24B4A"></span>High</span>
        <span class="legend-item" data-risk="crossdoc" title="Genuine cross-document reuse (spans 2+ lineages). Right-click for options"><span class="dot ring"></span>Cross-doc</span>
        <span class="legend-item" title="Within-lineage reuse: an image shared only between a document and its own prior versions (expected, not cross-document)"><span class="dot version-ring"></span>Version reuse</span>
        <span class="legend-item" title="A placement that lives in a prior version of a document is drawn with a dashed edge"><span class="dash"></span>Prior version</span>
      </div>
      <div class="spacer"></div>
      <button id="exclude-all-btn">Exclude all images</button>
      <button id="include-all-btn">Include all images</button>
      <button id="fit-btn">Fit to screen</button>
      <button id="physics-btn">Restart layout</button>
      <button id="report-btn">
        Report <span class="count" id="report-count">0</span>
      </button>
      <button id="excluded-btn">
        Excluded <span class="count" id="excluded-total-count">0</span>
      </button>
    </div>
    <div id="excluded-panel">
      <div class="panel-header">
        <h3>Excluded Items</h3>
        <button class="close-btn" id="close-panel">×</button>
      </div>
      <div class="panel-tabs">
        <button class="tab-btn active" data-tab="images">
          Images <span class="tab-count" id="excluded-count">0</span>
        </button>
        <button class="tab-btn" data-tab="documents">
          Documents <span class="tab-count" id="excluded-doc-count">0</span>
        </button>
      </div>
      <div id="excluded-list" class="tab-pane active"></div>
      <div id="excluded-doc-list" class="tab-pane"></div>
    </div>
    <div id="context-menu">
      <div class="menu-item" id="menu-exclude">Exclude this image</div>
      <div class="menu-item" id="menu-toggle-report">Add to report</div>
      <div class="menu-item menu-doc-only" id="menu-exclude-doc">Exclude this document</div>
    </div>
    <div id="legend-menu">
      <div class="menu-item" id="legend-exclude-tier">Exclude all</div>
      <div class="menu-item" id="legend-include-tier">Include all</div>
    </div>
    """

    script = f"""
    <script>
    const IMAGE_META = {meta_json};
    const DOC_META = {doc_meta_json};
    const DB_NAME = {db_name_json};
    const BRANDING = {branding_json};
    const excludedImages = new Set();
    const excludedDocuments = new Set();
    const reportImages = new Set();
    let rightClickedNodeId = null;

    function nodeIsImage(nodeId) {{
      return typeof nodeId === "string" && nodeId.startsWith("img_");
    }}

    function nodeIsDocument(nodeId) {{
      return typeof nodeId === "string" && nodeId.startsWith("doc_");
    }}

    function md5FromNodeId(nodeId) {{
      return nodeId.replace(/^img_/, "");
    }}

    function analysisIdFromNodeId(nodeId) {{
      return nodeId.replace(/^doc_/, "");
    }}

    // Force-hide pyvis's loading bar overlay. Pyvis bakes its own
    // loading bar template into every generated HTML file using
    // id="loadingBar" — this is separate from vis.js's built-in
    // loading bar and isn't controlled by the stabilization
    // option. We must hide it explicitly.
    function hideLoadingBar() {{
      const bar = document.getElementById("loadingBar");
      if (bar) {{
        bar.style.display = "none";
        bar.style.visibility = "hidden";
        bar.style.opacity = "0";
        bar.style.pointerEvents = "none";
      }}
      // Also catch any vis.js built-in loading bar variants
      const candidates = document.querySelectorAll(
        ".vis-network-loadingBar, .vis-loading-bar, " +
        "div[class*='loadingBar'], div[class*='LoadingBar']");
      candidates.forEach(el => {{
        el.style.display = "none";
        el.style.pointerEvents = "none";
      }});
    }}

    // Inject CSS rule that hides the pyvis #loadingBar element
    // unconditionally. Combined with hideLoadingBar(), this
    // ensures the bar can never block interaction.
    function installLoadingBarSuppressor() {{
      const style = document.createElement("style");
      style.textContent = `
        #loadingBar {{
          display: none !important;
          visibility: hidden !important;
          opacity: 0 !important;
          pointer-events: none !important;
        }}
        .vis-network-loadingBar,
        .vis-loading-bar,
        div[class*='loadingBar'],
        div[class*='LoadingBar'] {{
          display: none !important;
          visibility: hidden !important;
          opacity: 0 !important;
          pointer-events: none !important;
        }}
      `;
      document.head.appendChild(style);
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

      // Risk badge (color-coded)
      const risk = meta.risk_score || 0;
      const tier = meta.risk_tier || "low";
      const tierColors = {{
        low:  "#5DCAA5",
        mid:  "#EF9F27",
        high: "#E24B4A",
      }};
      const riskBadge = document.createElement("div");
      riskBadge.style.background = tierColors[tier];
      riskBadge.style.color = "#000";
      riskBadge.style.fontWeight = "bold";
      riskBadge.style.padding = "4px 8px";
      riskBadge.style.marginBottom = "6px";
      riskBadge.style.borderRadius = "2px";
      riskBadge.style.textAlign = "center";
      riskBadge.style.letterSpacing = "0.5px";
      riskBadge.textContent = "RISK " + tier.toUpperCase()
        + " — " + risk + "/100";
      root.appendChild(riskBadge);

      if (isCrossDoc) {{
        const warn = document.createElement("div");
        warn.style.color = "#FA0F00";
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

      // Findings summary — count by type
      const findings = meta.findings || [];
      if (findings.length > 0) {{
        const findingCounts = {{}};
        findings.forEach(f => {{
          findingCounts[f.code] = (findingCounts[f.code] || 0) + 1;
        }});

        const sep = document.createElement("hr");
        sep.style.margin = "6px 0";
        sep.style.border = "none";
        sep.style.borderTop = "1px solid #444";
        root.appendChild(sep);

        const ftitle = document.createElement("div");
        ftitle.style.fontWeight = "bold";
        ftitle.style.marginBottom = "2px";
        ftitle.textContent = "Findings:";
        root.appendChild(ftitle);

        Object.keys(findingCounts).sort().forEach(code => {{
          const ln = document.createElement("div");
          ln.style.fontSize = "11px";
          ln.style.color = "#CCC";
          ln.textContent = "  " + code
            + " (" + findingCounts[code] + ")";
          root.appendChild(ln);
        }});
      }}

      const hint = document.createElement("div");
      hint.style.marginTop = "6px";
      hint.style.color = "#7A7A7A";
      hint.style.fontSize = "11px";
      hint.textContent = "Right-click for options";
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
      // Iterate IMAGE_META (the canonical list of all images) —
      // not the live nodes DataSet. Individually-excluded images
      // have already been removed from `nodes`, so iterating
      // `nodes` would miss them. Iterating IMAGE_META guarantees
      // every image ends up in the excluded list.
      Object.keys(IMAGE_META).forEach(md5 => {{
        excludedImages.add(md5);
      }});
      // Wipe the entire graph (no images = nothing to show)
      nodes.clear();
      edges.clear();
      updateExcludedPanel();
    }}

    function includeAllImages() {{
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

    // -----------------------------------------------------------------
    // Risk-based bulk exclude / include
    // -----------------------------------------------------------------
    function excludeByRisk(tier) {{
      // Exclude all images of a given risk tier
      const toExclude = [];
      Object.keys(IMAGE_META).forEach(md5 => {{
        const meta = IMAGE_META[md5];
        if (meta && (meta.risk_tier || "low") === tier
            && !excludedImages.has(md5)) {{
          toExclude.push(md5);
        }}
      }});
      // Remove from graph
      toExclude.forEach(md5 => {{
        const nodeId = "img_" + md5;
        if (nodes.get(nodeId)) {{
          excludeImage(nodeId);
        }} else {{
          excludedImages.add(md5);
        }}
      }});
      updateExcludedPanel();
    }}

    function includeByRisk(tier) {{
      // Include all excluded images of a given risk tier
      const toInclude = [];
      excludedImages.forEach(md5 => {{
        const meta = IMAGE_META[md5];
        if (meta && (meta.risk_tier || "low") === tier) {{
          toInclude.push(md5);
        }}
      }});
      toInclude.forEach(md5 => {{
        restoreImage(md5, {{ skipPanelUpdate: true, skipRelayout: true }});
      }});
      updateExcludedPanel();
      if (toInclude.length > 0) relayoutNewNodes();
    }}

    function includeAllCrossDoc() {{
      // Include all excluded images that are cross-document
      const toInclude = [];
      excludedImages.forEach(md5 => {{
        const meta = IMAGE_META[md5];
        if (meta && meta.is_cross_doc) {{
          toInclude.push(md5);
        }}
      }});
      toInclude.forEach(md5 => {{
        restoreImage(md5, {{ skipPanelUpdate: true, skipRelayout: true }});
      }});
      updateExcludedPanel();
      if (toInclude.length > 0) relayoutNewNodes();
    }}

    function excludeAllCrossDoc() {{
      // Exclude all cross-document images currently in graph
      const toExclude = [];
      Object.keys(IMAGE_META).forEach(md5 => {{
        const meta = IMAGE_META[md5];
        if (meta && meta.is_cross_doc && !excludedImages.has(md5)) {{
          toExclude.push(md5);
        }}
      }});
      toExclude.forEach(md5 => {{
        const nodeId = "img_" + md5;
        if (nodes.get(nodeId)) {{
          excludeImage(nodeId);
        }} else {{
          excludedImages.add(md5);
        }}
      }});
      updateExcludedPanel();
    }}

    // -----------------------------------------------------------------
    // Document exclusion
    // -----------------------------------------------------------------
    function excludeDocument(nodeId) {{
      if (!nodeIsDocument(nodeId)) return;
      const aid = analysisIdFromNodeId(nodeId);
      excludedDocuments.add(aid);

      // Find all pages connected to this doc
      const connectedPages = network.getConnectedNodes(nodeId)
        .filter(id => typeof id === "string" && id.startsWith("page_"));

      nodes.remove(nodeId);

      // For each page, remove it and check if any of its images
      // become orphaned (no other pages reference them)
      const imagesToCheck = new Set();
      connectedPages.forEach(pageId => {{
        const imgs = network.getConnectedNodes(pageId)
          .filter(id => typeof id === "string" && id.startsWith("img_"));
        imgs.forEach(i => imagesToCheck.add(i));
        nodes.remove(pageId);
      }});

      // Remove image nodes that no longer have any page connections
      imagesToCheck.forEach(imgId => {{
        const remaining = network.getConnectedNodes(imgId)
          .filter(id => typeof id === "string" && id.startsWith("page_"));
        if (remaining.length === 0) {{
          nodes.remove(imgId);
          // Note: we do NOT add to excludedImages — the image is
          // implicitly hidden by virtue of all its documents being
          // excluded. Restoring the document brings it back.
        }}
      }});

      updateExcludedPanel();
    }}

    function restoreDocument(analysisId, opts) {{
      opts = opts || {{}};
      excludedDocuments.delete(analysisId);
      const docNodeId = "doc_" + analysisId;
      const docMeta = DOC_META[analysisId];
      if (!docMeta) return;

      // Place new cluster to the right of existing nodes
      const existingPositions = network.getPositions();
      const existingIds = Object.keys(existingPositions);
      let centerX = 0, centerY = 0;
      if (existingIds.length > 0) {{
        let maxX = -Infinity;
        existingIds.forEach(id => {{
          if (existingPositions[id].x > maxX) {{
            maxX = existingPositions[id].x;
          }}
        }});
        centerX = maxX + 400;
      }}

      // Re-add the document node
      const dn = Object.assign({{}}, ORIGINAL_NODES[docNodeId]);
      if (dn.pdf_filename) {{
        dn.title = makeDocTooltip(dn.pdf_filename);
      }}
      dn.x = centerX;
      dn.y = centerY;
      nodes.add(dn);

      // Find all pages and images that belong to this document
      const pageIds = [];
      const imageIds = new Set();
      ORIGINAL_EDGES.forEach(e => {{
        if (e.from === docNodeId || e.to === docNodeId) {{
          const otherId = (e.from === docNodeId) ? e.to : e.from;
          if (otherId.startsWith("page_") && !pageIds.includes(otherId)) {{
            pageIds.push(otherId);
          }}
        }}
      }});
      pageIds.forEach(pageId => {{
        ORIGINAL_EDGES.forEach(e => {{
          if (e.from === pageId || e.to === pageId) {{
            const otherId = (e.from === pageId) ? e.to : e.from;
            if (otherId.startsWith("img_")) {{
              imageIds.add(otherId);
            }}
          }}
        }});
      }});

      // Re-add page nodes in a circle around the doc
      const pageRadius = 180;
      pageIds.forEach((pageId, idx) => {{
        if (nodes.get(pageId)) return;  // already present
        const pn = Object.assign({{}}, ORIGINAL_NODES[pageId]);
        if (pn.page_number && pn.pdf_filename) {{
          pn.title = makePageTooltip(pn.page_number, pn.pdf_filename);
        }}
        const angle = (idx / Math.max(pageIds.length, 1)) * Math.PI * 2;
        pn.x = centerX + pageRadius * Math.cos(angle);
        pn.y = centerY + pageRadius * Math.sin(angle);
        nodes.add(pn);
      }});

      // Re-add image nodes that aren't separately excluded
      const imgRadius = 380;
      const imgList = Array.from(imageIds);
      imgList.forEach((imgId, idx) => {{
        const md5 = md5FromNodeId(imgId);
        if (excludedImages.has(md5)) return;  // user-excluded image
        if (nodes.get(imgId)) return;
        const meta = IMAGE_META[md5];
        if (!meta) return;

        const tierColors = {{
          low:  "#5DCAA5",
          mid:  "#EF9F27",
          high: "#E24B4A",
        }};
        const tierName = meta.risk_tier || "low";
        const fillColor = tierColors[tierName];
        const isCrossDoc = meta.is_cross_doc;
        const placements = meta.usage.length;
        const size = Math.min(20 + placements * 3, 60);

        const colorObj = isCrossDoc
          ? {{ background: fillColor, border: "#FA0F00",
               highlight: {{ background: fillColor, border: "#FA0F00" }} }}
          : fillColor;

        const angle = (idx / Math.max(imgList.length, 1)) * Math.PI * 2;
        const newNode = {{
          id: imgId,
          label: md5.substring(0, 8),
          title: makeImageTooltip(md5),
          color: colorObj,
          shape: "dot",
          size: size,
          x: centerX + imgRadius * Math.cos(angle),
          y: centerY + imgRadius * Math.sin(angle),
        }};
        if (isCrossDoc) {{
          newNode.borderWidth = 4;
          newNode.borderWidthSelected = 6;
        }}
        nodes.add(newNode);
      }});

      // Re-add all edges where both endpoints exist
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
        relayoutNewNodes();
      }}
    }}

    function restoreImage(md5, opts) {{
      opts = opts || {{}};
      excludedImages.delete(md5);
      const nodeId = "img_" + md5;
      const meta = IMAGE_META[md5];
      if (!meta) return;

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
      const tierColors = {{
        low:  "#5DCAA5",
        mid:  "#EF9F27",
        high: "#E24B4A",
      }};
      const tierName = meta.risk_tier || "low";
      const fillColor = tierColors[tierName];
      const isCrossDoc = (meta.is_cross_doc !== undefined)
        ? meta.is_cross_doc
        : (new Set(meta.usage.map(u => u.pdf)).size > 1);

      const colorObj = isCrossDoc
        ? {{
            background: fillColor,
            border: "#FA0F00",
            highlight: {{ background: fillColor, border: "#FA0F00" }},
          }}
        : fillColor;

      const newNode = {{
        id: nodeId,
        label: md5.substring(0, 8),
        title: makeImageTooltip(md5),
        color: colorObj,
        shape: "dot",
        size: size,
        x: centerX,
        y: centerY,
      }};
      if (isCrossDoc) {{
        newNode.borderWidth = 4;
        newNode.borderWidthSelected = 6;
      }}
      nodes.add(newNode);

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
    let loadingBarPollTimer = null;
    function relayoutNewNodes() {{
      if (relayoutTimer) clearTimeout(relayoutTimer);
      if (loadingBarPollTimer) clearInterval(loadingBarPollTimer);

      network.setOptions({{ physics: {{ enabled: true }} }});
      network.stabilize(150);

      // Poll-and-hide the loading bar every 50ms while we're
      // settling, since the 'stabilized' event isn't reliable on
      // small/fast restabilizations
      loadingBarPollTimer = setInterval(hideLoadingBar, 50);

      relayoutTimer = setTimeout(function() {{
        network.setOptions({{ physics: {{ enabled: false }} }});
        clearInterval(loadingBarPollTimer);
        loadingBarPollTimer = null;
        hideLoadingBar();
      }}, 1500);
    }}

    // -----------------------------------------------------------------
    // Excluded panel
    // -----------------------------------------------------------------
    function updateExcludedPanel() {{
      // Update total counter
      const totalBadge = document.getElementById("excluded-total-count");
      if (totalBadge) {{
        totalBadge.textContent = excludedImages.size + excludedDocuments.size;
      }}

      // Update doc counter and list
      const docCountBadge = document.getElementById("excluded-doc-count");
      if (docCountBadge) {{
        docCountBadge.textContent = excludedDocuments.size;
      }}
      updateExcludedDocList();

      const list = document.getElementById("excluded-list");
      const countBadge = document.getElementById("excluded-count");
      countBadge.textContent = excludedImages.size;

      if (excludedImages.size === 0) {{
        list.innerHTML = '<div class="empty">No images excluded.<br><br>Right-click an image node to exclude it, or use "Exclude all images" to clear the graph.</div>';
        return;
      }}

      // Sort: highest risk first, then cross-doc, then placements
      const sorted = Array.from(excludedImages).sort((a, b) => {{
        const ma = IMAGE_META[a], mb = IMAGE_META[b];
        if (!ma || !mb) return 0;
        const riskA = ma.risk_score || 0;
        const riskB = mb.risk_score || 0;
        if (riskA !== riskB) return riskB - riskA;
        const crossA = ma.is_cross_doc ? 1 : 0;
        const crossB = mb.is_cross_doc ? 1 : 0;
        if (crossA !== crossB) return crossB - crossA;
        return mb.usage.length - ma.usage.length;
      }});

      const tierColors = {{
        low:  "#5DCAA5",
        mid:  "#EF9F27",
        high: "#E24B4A",
      }};

      let html = "";
      sorted.forEach(md5 => {{
        const meta = IMAGE_META[md5];
        if (!meta) return;
        const docCount = new Set(meta.usage.map(u => u.pdf)).size;
        const isCrossDoc = meta.is_cross_doc;
        const thumb = meta.thumbnail
          ? `<img src="${{meta.thumbnail}}" />`
          : "<div style='text-align:center;color:#7A7A7A;padding:20px'>(no thumbnail)</div>";

        const risk = meta.risk_score || 0;
        const tier = meta.risk_tier || "low";
        const tierColor = tierColors[tier];
        const riskBadge = `<div class="risk-badge" style="background:${{tierColor}};color:#000;">RISK ${{tier.toUpperCase()}} — ${{risk}}/100</div>`;

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
            ${{riskBadge}}
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

    function updateExcludedDocList() {{
      const list = document.getElementById("excluded-doc-list");
      if (!list) return;

      if (excludedDocuments.size === 0) {{
        list.innerHTML = '<div class="empty">No documents excluded.<br><br>Right-click a document node to exclude it from the graph.</div>';
        return;
      }}

      const sorted = Array.from(excludedDocuments).sort((a, b) => {{
        const ma = DOC_META[a], mb = DOC_META[b];
        if (!ma || !mb) return 0;
        return (ma.pdf_filename || "").localeCompare(mb.pdf_filename || "");
      }});

      let html = "";
      sorted.forEach(aid => {{
        const meta = DOC_META[aid];
        if (!meta) return;
        const pdfName = meta.pdf_filename || ("Document " + aid);
        const pages = meta.page_count || 0;
        const images = meta.image_count || 0;
        html += `
          <div class="item">
            <div class="doc-name">${{pdfName}}</div>
            <div class="doc-meta">
              ${{pages}} page(s) with duplicate images,
              ${{images}} unique image(s)
            </div>
            <button onclick="restoreDocument('${{aid}}')">Add to graph</button>
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

      const esc = escapeHtml;
      let classificationHtml = "";
      if (BRANDING.classification) {{
        classificationHtml =
          `<div id="classification">${{esc(BRANDING.classification)}}</div>`;
      }}
      let coverLogoHtml = BRANDING.agency_logo
        ? `<img class="cover-logo" src="${{BRANDING.agency_logo}}" alt="Agency logo">`
        : "";
      let agencyLine = BRANDING.agency_name
        ? `<div class="cover-agency">${{esc(BRANDING.agency_name)}}</div>` : "";
      let unitLine = BRANDING.unit_name
        ? `<div class="cover-unit">${{esc(BRANDING.unit_name)}}</div>` : "";
      let metaRows = (BRANDING.info_pairs || []).map(p =>
        `<tr><td class="k">${{esc(p[0])}}</td><td class="v">${{esc(p[1])}}</td></tr>`
      ).join("");
      let md5Line = BRANDING.db_md5
        ? ` &middot; DB MD5: <span class="mono">${{esc(BRANDING.db_md5)}}</span>` : "";
      let scopeLine = BRANDING.scope_label
        ? `<br>Scope: ${{esc(BRANDING.scope_label)}} \u2014 ${{esc(BRANDING.scope_definition)}}`
        : "";
      let versionLine = "";
      if (BRANDING.version_documents) {{
        const grp = BRANDING.group_versions
          ? "prior versions grouped by lineage (a document and its own "
            + "versions are treated as one; reuse within a lineage is shown "
            + "as version reuse, not cross-document)"
          : "each prior version treated as a separate document";
        versionLine = `<br>Prior versions: ${{esc(String(BRANDING.version_documents))}} `
          + `version document(s) in view; ${{esc(grp)}}. `
          + `Version-reuse images: ${{esc(String(BRANDING.version_reuse_images || 0))}}; `
          + `cross-document images: ${{esc(String(BRANDING.cross_doc_images || 0))}}.`;
      }}
      let coverHtml = `
  ${{classificationHtml}}
  <div class="cover-page">
    <div class="cover-top">
      <div>${{agencyLine}}${{unitLine}}</div>
      ${{coverLogoHtml}}
    </div>
    <div class="cover-rule"></div>
    <div class="cover-title">PDF Forensics Report</div>
    <div class="cover-subtitle">Image Duplication &amp; Reuse Analysis</div>
    <table class="cover-meta"><tbody>${{metaRows}}</tbody></table>
    <div class="cover-foot">
      Generated ${{esc(BRANDING.generated_at || timestamp)}} &middot; ${{esc(BRANDING.tool_label || "")}}${{md5Line}}<br>
      Database: ${{esc(DB_NAME)}} &middot; Images in report: ${{reportImages.size}}${{scopeLine}}${{versionLine}}
    </div>
  </div>`;
      let footerHtml = (BRANDING.footer_text || BRANDING.db_md5)
        ? `<div id="print-footer"><span class="ft-left">${{esc(BRANDING.footer_text)}}</span>` +
          (BRANDING.db_md5 ? `<span class="ft-md5">DB MD5: ${{esc(BRANDING.db_md5)}}</span>` : "") +
          `</div>`
        : "";

      let html = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>PDF Forensics Report${{BRANDING.scope_label ? " \u2014 " + BRANDING.scope_label : ""}}</title>
<style>
  @page {{
    size: letter; margin: 0.75in;
    @bottom-right {{
      content: "Page " counter(page) " of " counter(pages);
      font-size: 9px; color: #777;
    }}
  }}
  @media print {{
    body {{ background: #fff !important; color: #000 !important; }}
    .no-print {{ display: none !important; }}
    .report-item {{ page-break-inside: avoid; }}
    .cover-page {{ page-break-after: always; }}
    #classification {{
      -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    #print-footer {{
      display: flex !important; justify-content: space-between;
      align-items: center; position: fixed; bottom: 0; left: 0; right: 0;
      padding: 6px 4px; border-top: 1px solid #bbb;
      font-size: 9px; color: #555; background: #fff;
    }}
    #print-footer .ft-md5 {{
      font-family: "Consolas","Monaco",monospace; color: #777; }}
  }}
  #classification {{
    background: #ED1C24; color: #fff; text-align: center;
    font-size: 12px; font-weight: 700; letter-spacing: 1px;
    text-transform: uppercase; padding: 6px 10px;
    margin: -20px -20px 20px;
  }}
  #print-footer {{ display: none; }}
  .cover-page {{
    min-height: 80vh; display: flex; flex-direction: column;
    padding: 10px 4px;
  }}
  .cover-top {{
    display: flex; justify-content: space-between;
    align-items: flex-start; gap: 24px;
  }}
  .cover-agency {{ font-size: 18px; font-weight: 700; color: #222; }}
  .cover-unit {{ font-size: 13px; font-weight: 600; color: #ED1C24;
    margin-top: 2px; }}
  .cover-logo {{ max-height: 76px; max-width: 180px; object-fit: contain; }}
  .cover-rule {{ height: 3px; background: #ED1C24; margin: 22px 0 26px; }}
  .cover-title {{ font-size: 30px; font-weight: 700; color: #222; }}
  .cover-subtitle {{ font-size: 14px; color: #666; margin-top: 6px; }}
  .cover-meta {{ margin-top: 34px; border-collapse: collapse;
    font-size: 14px; color: #333; }}
  .cover-meta td {{ padding: 7px 22px 7px 0; vertical-align: top; }}
  .cover-meta td.k {{ color: #888; white-space: nowrap; }}
  .cover-meta td.v {{ font-weight: 600; }}
  .cover-foot {{ margin-top: auto; padding-top: 22px;
    border-top: 1px solid #ddd; font-size: 11px; color: #999; }}
  .cover-foot .mono {{ font-family: "Consolas","Monaco",monospace; }}
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
    border-left: 4px solid #FA0F00;
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
    display: inline-block; background: #fff;
    color: #FA0F00; border: 2px solid #FA0F00;
    font-size: 10px; font-weight: bold;
    padding: 3px 8px; border-radius: 2px;
    margin: 0 0 8px 6px; letter-spacing: 0.5px;
  }}
  .risk-badge {{
    display: inline-block; color: #000;
    font-size: 11px; font-weight: bold;
    padding: 4px 10px; border-radius: 2px;
    margin: 0 0 8px 0; letter-spacing: 0.5px;
  }}
  .section-heading {{
    margin: 18px 0 6px; font-size: 12px;
    color: #666; text-transform: uppercase;
    letter-spacing: 0.8px; font-weight: bold;
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
  .appearances-table, .findings-table {{
    width: 100%; border-collapse: collapse;
    margin-top: 6px; font-size: 12px;
  }}
  .appearances-table th, .findings-table th {{
    background: #252525; color: #fff;
    text-align: left; padding: 8px 10px;
    font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.5px;
  }}
  .appearances-table td, .findings-table td {{
    padding: 6px 10px; border-bottom: 1px solid #eee;
  }}
  .appearances-table tr:last-child td,
  .findings-table tr:last-child td {{
    border-bottom: none;
  }}
  .findings-table code {{
    font-family: "Consolas", monospace; font-size: 11px;
  }}
  .sev-pill {{
    display: inline-block; padding: 2px 8px;
    border-radius: 10px; font-size: 10px;
    font-weight: bold; letter-spacing: 0.5px;
  }}
  .sev-pill.sev-high {{
    background: #E24B4A; color: #fff;
  }}
  .sev-pill.sev-info {{
    background: #888; color: #fff;
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
  ${{coverHtml}}
  ${{footerHtml}}
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
        const isCrossDoc = meta.is_cross_doc;
        const crossClass = isCrossDoc ? " cross-doc" : "";
        const crossBadge = isCrossDoc
          ? '<div class="cross-badge">CROSS-DOCUMENT REUSE</div>'
          : '';
        const thumbHtml = meta.thumbnail
          ? `<img src="${{meta.thumbnail}}" alt="Image ${{idx+1}}">`
          : '<span style="color:#999;font-style:italic">No thumbnail</span>';

        // Risk badge
        const tierColors = {{
          low:  "#5DCAA5",
          mid:  "#EF9F27",
          high: "#E24B4A",
        }};
        const risk = meta.risk_score || 0;
        const tier = meta.risk_tier || "low";
        const riskBadge = `<div class="risk-badge" style="background:${{tierColors[tier]}};">RISK ${{tier.toUpperCase()}} — ${{risk}}/100</div>`;

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

        // Findings list
        let findingsHtml = "";
        const findings = meta.findings || [];
        if (findings.length > 0) {{
          // Group by code -> list of (pdf, page) tuples
          const byCode = {{}};
          findings.forEach(f => {{
            if (!byCode[f.code]) byCode[f.code] = [];
            byCode[f.code].push(f);
          }});

          let findingRowsHtml = "";
          Object.keys(byCode).sort().forEach(code => {{
            const items = byCode[code];
            const sevClass = items[0].severity === "HIGH"
              ? "sev-high" : "sev-info";
            const locations = items.map(f =>
              `${{escapeHtml(f.pdf)}} p.${{f.page}}`
            ).join("; ");
            findingRowsHtml += `
              <tr>
                <td><span class="sev-pill ${{sevClass}}">${{items[0].severity}}</span></td>
                <td><code>${{code}}</code></td>
                <td>${{items.length}}</td>
                <td>${{locations}}</td>
              </tr>`;
          }});
          findingsHtml = `
            <h3 class="section-heading">Findings</h3>
            <table class="findings-table">
              <thead>
                <tr><th>Severity</th><th>Type</th><th>Count</th><th>Locations</th></tr>
              </thead>
              <tbody>${{findingRowsHtml}}</tbody>
            </table>`;
        }}

        html += `
  <div class="report-item${{crossClass}}">
    <div class="item-header">
      <div class="item-thumb">${{thumbHtml}}</div>
      <div class="item-details">
        <h2>Image ${{idx + 1}}</h2>
        ${{riskBadge}}
        ${{crossBadge}}
        <div class="detail-row"><strong>MD5:</strong> <code>${{escapeHtml(md5)}}</code></div>
        <div class="detail-row"><strong>Format:</strong> ${{escapeHtml(meta.format || "unknown")}}</div>
        <div class="detail-row"><strong>Dimensions:</strong> ${{meta.width || "?"}} × ${{meta.height || "?"}} px</div>
        <div class="detail-row"><strong>Placements:</strong> ${{meta.usage.length}}</div>
        <div class="detail-row"><strong>Documents:</strong> ${{docCount}}</div>
      </div>
    </div>
    <h3 class="section-heading">Appearances</h3>
    <table class="appearances-table">
      <thead>
        <tr><th>Document</th><th>Page</th><th>Image label</th></tr>
      </thead>
      <tbody>${{rowsHtml}}</tbody>
    </table>
    ${{findingsHtml}}
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

      // Install a CSS rule that suppresses any subsequent loading
      // bar overlays. The first stabilization has already happened
      // by the time we get here.
      installLoadingBarSuppressor();

      // Capture original nodes/edges for restoration
      window.ORIGINAL_NODES = {{}};
      nodes.forEach(n => {{
        ORIGINAL_NODES[n.id] = Object.assign({{}}, n);
      }});
      window.ORIGINAL_EDGES = edges.get().map(e => Object.assign({{}}, e));

      // Freeze physics after initial stabilization. With pyvis's
      // loading bar hidden via CSS, the user never sees the
      // progress indicator — but vis.js still does the work.
      network.on("stabilizationIterationsDone", function() {{
        network.setOptions({{ physics: {{ enabled: false }} }});
        hideLoadingBar();
      }});

      // 'stabilized' fires on every stabilize() call (initial and
      // subsequent restabilizations from adding nodes). Use it as
      // a backup to ensure the bar stays hidden.
      network.on("stabilized", function() {{
        hideLoadingBar();
      }});

      // Apply DOM tooltips to all existing nodes
      applyTooltipsToAllNodes();

      // Right-click handler — supports both image and document nodes
      network.on("oncontext", function(params) {{
        params.event.preventDefault();
        const nodeId = network.getNodeAt(params.pointer.DOM);
        const isImage = nodeId && nodeIsImage(nodeId);
        const isDoc   = nodeId && nodeIsDocument(nodeId);

        if (!nodeId || (!isImage && !isDoc)) {{
          document.getElementById("context-menu").style.display = "none";
          return;
        }}
        rightClickedNodeId = nodeId;

        // Show/hide menu items based on node type
        document.getElementById("menu-exclude").style.display =
          isImage ? "block" : "none";
        document.getElementById("menu-toggle-report").style.display =
          isImage ? "block" : "none";
        document.getElementById("menu-exclude-doc").style.display =
          isDoc ? "block" : "none";

        if (isImage) {{
          const md5 = md5FromNodeId(nodeId);
          document.getElementById("menu-toggle-report").textContent =
            reportImages.has(md5)
              ? "Remove from report"
              : "Add to report";
        }}

        const menu = document.getElementById("context-menu");
        menu.style.left = params.event.pageX + "px";
        menu.style.top = params.event.pageY + "px";
        menu.style.display = "block";
      }});

      document.addEventListener("click", function() {{
        document.getElementById("context-menu").style.display = "none";
        document.getElementById("legend-menu").style.display = "none";
      }});

      document.getElementById("menu-exclude").addEventListener("click", function(ev) {{
        ev.stopPropagation();
        if (rightClickedNodeId) {{
          excludeImage(rightClickedNodeId);
          rightClickedNodeId = null;
        }}
        document.getElementById("context-menu").style.display = "none";
      }});

      document.getElementById("menu-exclude-doc").addEventListener("click", function(ev) {{
        ev.stopPropagation();
        if (rightClickedNodeId) {{
          excludeDocument(rightClickedNodeId);
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

      // Tab switching in the excluded panel
      document.querySelectorAll(".panel-tabs .tab-btn").forEach(btn => {{
        btn.addEventListener("click", function() {{
          const tab = btn.getAttribute("data-tab");
          // Toggle button active state
          document.querySelectorAll(".panel-tabs .tab-btn").forEach(b => {{
            b.classList.remove("active");
          }});
          btn.classList.add("active");
          // Toggle pane visibility
          document.querySelectorAll(".tab-pane").forEach(p => {{
            p.classList.remove("active");
          }});
          const paneId = (tab === "documents")
            ? "excluded-doc-list"
            : "excluded-list";
          document.getElementById(paneId).classList.add("active");
        }});
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

      // ----- Legend right-click for bulk risk actions -----
      let legendClickedRisk = null;

      document.querySelectorAll(".legend-item").forEach(item => {{
        item.addEventListener("contextmenu", function(ev) {{
          ev.preventDefault();
          ev.stopPropagation();
          legendClickedRisk = item.getAttribute("data-risk");
          const menu = document.getElementById("legend-menu");

          // Update menu labels based on which legend dot was clicked
          const excludeItem = document.getElementById("legend-exclude-tier");
          const includeItem = document.getElementById("legend-include-tier");

          if (legendClickedRisk === "crossdoc") {{
            excludeItem.textContent = "Exclude all cross-doc images";
            includeItem.textContent = "Include all cross-doc images";
          }} else {{
            const tierLabel = legendClickedRisk.toUpperCase();
            excludeItem.textContent = "Exclude all " + tierLabel + " risk";
            includeItem.textContent = "Include all " + tierLabel + " risk";
          }}

          menu.style.left = ev.pageX + "px";
          menu.style.top = ev.pageY + "px";
          menu.style.display = "block";
        }});
      }});

      document.getElementById("legend-exclude-tier").addEventListener("click", function(ev) {{
        ev.stopPropagation();
        if (legendClickedRisk === "crossdoc") {{
          excludeAllCrossDoc();
        }} else if (legendClickedRisk) {{
          excludeByRisk(legendClickedRisk);
        }}
        document.getElementById("legend-menu").style.display = "none";
        legendClickedRisk = null;
      }});

      document.getElementById("legend-include-tier").addEventListener("click", function(ev) {{
        ev.stopPropagation();
        if (legendClickedRisk === "crossdoc") {{
          includeAllCrossDoc();
        }} else if (legendClickedRisk) {{
          includeByRisk(legendClickedRisk);
        }}
        document.getElementById("legend-menu").style.display = "none";
        legendClickedRisk = null;
      }});

      updateExcludedPanel();
    }}

    // Install loading-bar suppressor immediately — before
    // setupCustomUI runs and before vis.js shows any progress UI.
    installLoadingBarSuppressor();

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
