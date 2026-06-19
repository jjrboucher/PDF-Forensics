"""
HTML report renderer.

Generates self-contained HTML files with sortable columns,
text/numeric filtering, and Adobe-themed dark styling.

Filter syntax:
  - Text columns:   substring match (case-insensitive)
  - Numeric columns: >5  >=10  <3  <=7  =42  5-10 (range)
  - Date columns:    substring match on the ISO string
  - Hash columns:    prefix match
"""

import os
import sqlite3
import html as html_mod
from datetime import datetime

from pdf_forensics import __version__, __tool_name__


def generate_report(db_path, report_def, output_path, session=None):
    """
    Run a report query and write the result as a self-contained
    HTML file.

    Supports two modes:
      - report_def has "query": run SQL directly
      - report_def has "query_fn": call fn(conn) -> (columns, data)

    Returns the number of rows in the report.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if "query_fn" in report_def:
        # Dynamic report — Python function builds columns + data
        columns, table_data = report_def["query_fn"](conn)
    else:
        cur = conn.cursor()
        params = report_def.get("params", {})
        cur.execute(report_def["query"], params)
        rows = cur.fetchall()

        columns = report_def["columns"]
        table_data = []
        for row in rows:
            record = {}
            for col in columns:
                val = (row[col["name"]]
                       if col["name"] in row.keys() else "")
                record[col["name"]] = val if val is not None else ""
            table_data.append(record)

    conn.close()

    sticky_cols = report_def.get("sticky_cols", 0)

    html = _render_html(
        title=report_def["name"],
        description=report_def["description"],
        columns=columns,
        data=table_data,
        db_path=db_path,
        row_count=len(table_data),
        sticky_cols=sticky_cols,
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    if session:
        session.log(f"Report generated: {report_def['name']} "
                    f"({len(table_data)} rows) -> {output_path}")
        session.register_output("report", output_path)

    return len(table_data)


def _render_html(title, description, columns, data, db_path,
                 row_count, sticky_cols=0):
    """Build the complete self-contained HTML string."""

    # Load logo for embedding
    logo_uri = ""
    try:
        from pdf_forensics.assets import get_logo_base64
        logo_uri = get_logo_base64() or ""
    except Exception:
        pass

    def esc(val):
        return html_mod.escape(str(val)) if val else ""

    # Build header row
    header_cells = []
    filter_cells = []
    for i, col in enumerate(columns):
        sort_icon = '<span class="sort-icon">&#x25B2;&#x25BC;</span>'
        sticky_cls = " sticky-col" if i < sticky_cols else ""
        sticky_style = ""
        if i < sticky_cols:
            # Stack sticky columns left-to-right
            sticky_style = f' style="left: {i * 160}px; z-index: 4;"'

        header_cells.append(
            f'<th data-col="{i}" data-type="{col["col_type"]}" '
            f'class="sortable{sticky_cls}"{sticky_style}>'
            f'{esc(col["label"])} {sort_icon}</th>')

        placeholder = "Filter..."
        if col["col_type"] == "numeric":
            placeholder = ">5, <10, 5-10"

        f_sticky = ""
        if i < sticky_cols:
            f_sticky = (f' class="sticky-col"'
                        f' style="left: {i * 160}px; z-index: 3;"')
        filter_cells.append(
            f'<th{f_sticky}><input type="text" class="col-filter" '
            f'data-col="{i}" placeholder="{placeholder}"></th>')

    # Build data rows
    data_rows = []
    for record in data:
        cells = []
        for i, col in enumerate(columns):
            val = record.get(col["name"], "")
            if val is None:
                val = ""
            display = esc(val)

            if col["col_type"] == "hash" and val:
                display = f'<span class="hash">{esc(val)}</span>'

            raw = str(val) if val is not None else ""

            sticky_cls = ""
            sticky_style = ""
            if i < sticky_cols:
                sticky_cls = ' class="sticky-col"'
                sticky_style = f' style="left: {i * 160}px;"'

            cells.append(
                f'<td{sticky_cls}{sticky_style} '
                f'data-raw="{esc(raw)}">{display}</td>')
        data_rows.append("<tr>" + "".join(cells) + "</tr>")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db_basename = os.path.basename(db_path) if db_path else "report"
    esc_js_db_name = '"' + db_basename.replace('\\', '\\\\').replace('"', '\\"') + '"'

    sticky_css = ""
    if sticky_cols > 0:
        sticky_css = """
      .sticky-col {
        position: sticky;
        background: #252525;
        z-index: 1;
      }
      tr:hover .sticky-col { background: #2D2D2D; }
      thead th.sticky-col { z-index: 4 !important; }
      tr.filter-row th.sticky-col { z-index: 3 !important; }
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{esc(title)} — PDF Forensics Suite</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #1B1B1B; color: #F0F0F0;
    font-family: "Segoe UI", "SF Pro Text", "DejaVu Sans", sans-serif;
    font-size: 13px; padding: 0;
  }}
  #header {{
    background: #252525; padding: 20px 30px;
    border-bottom: 2px solid #ED1C24;
    display: flex; align-items: center; gap: 20px;
  }}
  #header .logo {{ height: 48px; }}
  #header .header-text {{ flex: 1; }}
  #header h1 {{
    font-size: 20px; font-weight: 700; color: #F0F0F0;
    margin-bottom: 4px;
  }}
  #header .subtitle {{ color: #A8A8A8; font-size: 12px; }}
  #header .description {{
    color: #A8A8A8; font-size: 12px; margin-top: 8px;
    max-width: 900px;
  }}
  #toolbar {{
    background: #252525; padding: 10px 30px;
    border-bottom: 1px solid #3D3D3D;
    display: flex; align-items: center; gap: 16px;
    flex-wrap: wrap;
  }}
  #toolbar .stat {{ color: #A8A8A8; font-size: 12px; }}
  #toolbar .stat strong {{
    color: #ED1C24; font-size: 14px; font-weight: 700;
  }}
  #toolbar button {{
    background: #363636; color: #F0F0F0; border: 1px solid #3D3D3D;
    padding: 6px 14px; border-radius: 3px; cursor: pointer;
    font-size: 12px; font-family: inherit;
  }}
  #toolbar button:hover {{ background: #3A3A3A; border-color: #ED1C24; }}
  #table-container {{
    padding: 16px 30px 40px 30px; overflow-x: auto;
  }}
  table {{
    width: max-content; min-width: 100%;
    border-collapse: separate; border-spacing: 0;
    background: #252525; border: 1px solid #3D3D3D;
  }}
  th {{
    background: #2A2A2A; color: #A8A8A8; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.5px;
    padding: 10px 12px; text-align: left; white-space: nowrap;
    border-bottom: 1px solid #3D3D3D; user-select: none;
    position: sticky; top: 0; z-index: 2;
  }}
  th.sortable {{ cursor: pointer; }}
  th.sortable:hover {{ color: #F0F0F0; }}
  th.sort-asc .sort-icon,
  th.sort-desc .sort-icon {{ color: #ED1C24; }}
  .sort-icon {{
    font-size: 8px; margin-left: 4px; color: #555;
    display: inline-block; vertical-align: middle;
  }}
  tr.filter-row th {{
    background: #222; padding: 4px 6px;
    position: sticky; top: 37px; z-index: 2;
  }}
  tr.filter-row input {{
    width: 100%; background: #363636; color: #F0F0F0;
    border: 1px solid #3D3D3D; padding: 5px 8px; font-size: 12px;
    border-radius: 2px; font-family: inherit;
  }}
  tr.filter-row input:focus {{
    outline: none; border-color: #ED1C24;
  }}
  tr.filter-row input::placeholder {{
    color: #666; font-size: 11px;
  }}
  td {{
    padding: 8px 12px; border-bottom: 1px solid #2F2F2F;
    color: #E0E0E0; font-size: 13px;
    max-width: 400px; overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap;
  }}
  tr:hover td {{ background: #2D2D2D; }}
  tr.hidden {{ display: none; }}
  .hash {{
    font-family: "Consolas", "Monaco", monospace;
    font-size: 11px; color: #7A7A7A;
  }}

  .num {{ font-variant-numeric: tabular-nums; }}
{sticky_css}
  @media print {{
    body {{ background: #fff; color: #000; font-size: 10px; }}
    #header {{ background: #f5f5f5; border-bottom: 2px solid #333; }}
    #header h1 {{ color: #000; }}
    #header .subtitle, #header .description {{ color: #555; }}
    #toolbar {{ display: none; }}
    #table-container {{ padding: 8px; }}
    table {{ background: #fff; border: 1px solid #ccc; }}
    th {{ background: #eee; color: #333; border-bottom: 1px solid #ccc; }}
    td {{ color: #000; border-bottom: 1px solid #eee; }}
    tr:hover td {{ background: inherit; }}
    .hash {{ color: #555; }}
    tr.filter-row {{ display: none; }}
    .sticky-col {{ position: static !important; }}
  }}
</style>
</head>
<body>

<div id="header">
  {"<img class='logo' src='" + logo_uri + "' alt='PDF Forensic Suite'>" if logo_uri else ""}
  <div class="header-text">
    <h1>{esc(title)}</h1>
    <div class="subtitle">
      {__tool_name__} v{__version__} &mdash;
      Generated {now} &mdash;
      Database: {esc(os.path.basename(db_path))}
    </div>
    <div class="description">{esc(description)}</div>
  </div>
</div>

<div id="toolbar">
  <div class="stat">Rows: <strong id="visible-count">{row_count}</strong>
    / {row_count}</div>
  <button onclick="clearFilters()">Clear filters</button>
  <button onclick="exportCSV(false)">Export all to CSV</button>
  <button onclick="exportCSV(true)">Export filtered to CSV</button>
  <button onclick="window.print()">Print / PDF</button>
</div>

<div id="table-container">
<table id="report-table">
  <thead>
    <tr>{"".join(header_cells)}</tr>
    <tr class="filter-row">{"".join(filter_cells)}</tr>
  </thead>
  <tbody>
    {"".join(data_rows)}
  </tbody>
</table>
</div>

<script>
(function() {{
  const table = document.getElementById("report-table");
  const tbody = table.querySelector("tbody");
  const headers = table.querySelectorAll("th.sortable");
  const filters = table.querySelectorAll("input.col-filter");
  const visibleCount = document.getElementById("visible-count");

  let sortCol = -1;
  let sortDir = 0;

  headers.forEach(th => {{
    th.addEventListener("click", function() {{
      const col = parseInt(this.dataset.col);
      const colType = this.dataset.type;

      if (sortCol === col) {{
        sortDir = sortDir === 1 ? 2 : 1;
      }} else {{
        sortCol = col;
        sortDir = 1;
      }}

      headers.forEach(h => {{
        h.classList.remove("sort-asc", "sort-desc");
      }});
      this.classList.add(sortDir === 1 ? "sort-asc" : "sort-desc");

      const rows = Array.from(tbody.querySelectorAll("tr"));
      rows.sort((a, b) => {{
        const aVal = a.children[col].dataset.raw;
        const bVal = b.children[col].dataset.raw;
        let cmp;
        if (colType === "numeric") {{
          cmp = (parseFloat(aVal) || 0) - (parseFloat(bVal) || 0);
        }} else {{
          cmp = aVal.localeCompare(bVal, undefined,
                                   {{sensitivity: "base"}});
        }}
        return sortDir === 2 ? -cmp : cmp;
      }});
      rows.forEach(r => tbody.appendChild(r));
    }});
  }});

  function parseNumericFilter(expr) {{
    expr = expr.trim();
    if (!expr) return null;
    let m;
    m = expr.match(/^(\\d+\\.?\\d*)\\s*-\\s*(\\d+\\.?\\d*)$/);
    if (m) {{ const lo=parseFloat(m[1]),hi=parseFloat(m[2]);
              return v => v >= lo && v <= hi; }}
    m = expr.match(/^>=\\s*(\\d+\\.?\\d*)$/);
    if (m) return v => v >= parseFloat(m[1]);
    m = expr.match(/^>\\s*(\\d+\\.?\\d*)$/);
    if (m) return v => v > parseFloat(m[1]);
    m = expr.match(/^<=\\s*(\\d+\\.?\\d*)$/);
    if (m) return v => v <= parseFloat(m[1]);
    m = expr.match(/^<\\s*(\\d+\\.?\\d*)$/);
    if (m) return v => v < parseFloat(m[1]);
    m = expr.match(/^=\\s*(\\d+\\.?\\d*)$/);
    if (m) return v => v === parseFloat(m[1]);
    m = expr.match(/^(\\d+\\.?\\d*)$/);
    if (m) return v => v === parseFloat(m[1]);
    return null;
  }}

  function applyFilters() {{
    const fvs = [];
    filters.forEach(f => {{
      const col = parseInt(f.dataset.col);
      const th = table.querySelector(
        `th.sortable[data-col="${{col}}"]`);
      fvs.push({{
        col, value: f.value.trim(),
        type: th ? th.dataset.type : "text",
      }});
    }});
    let visible = 0;
    tbody.querySelectorAll("tr").forEach(row => {{
      let show = true;
      for (const fv of fvs) {{
        if (!fv.value) continue;
        const raw = row.children[fv.col].dataset.raw;
        if (fv.type === "numeric") {{
          const fn = parseNumericFilter(fv.value);
          if (fn) {{
            if (!fn(parseFloat(raw) || 0)) {{ show = false; break; }}
          }} else {{
            if (!raw.toLowerCase().includes(
                fv.value.toLowerCase())) {{ show = false; break; }}
          }}
        }} else if (fv.type === "hash") {{
          if (!raw.toLowerCase().startsWith(
              fv.value.toLowerCase())) {{ show = false; break; }}
        }} else {{
          if (!raw.toLowerCase().includes(
              fv.value.toLowerCase())) {{ show = false; break; }}
        }}
      }}
      row.classList.toggle("hidden", !show);
      if (show) visible++;
    }});
    visibleCount.textContent = visible;
  }}

  filters.forEach(f => f.addEventListener("input", applyFilters));

  window.clearFilters = function() {{
    filters.forEach(f => {{ f.value = ""; }});
    applyFilters();
  }};

  window.exportCSV = function(filteredOnly) {{
    // Build header row from sortable th elements
    const headerRow = [];
    headers.forEach(th => {{
      // Get text content without the sort icon
      let text = th.textContent.replace(/[\\u25B2\\u25BC]/g, "").trim();
      headerRow.push(text);
    }});

    // Build data rows
    const dataRows = [];
    tbody.querySelectorAll("tr").forEach(row => {{
      if (filteredOnly && row.classList.contains("hidden")) return;
      const cells = [];
      row.querySelectorAll("td").forEach(td => {{
        cells.push(td.dataset.raw || "");
      }});
      dataRows.push(cells);
    }});

    // CSV escape helper
    function csvEscape(val) {{
      const s = String(val);
      if (s.includes(",") || s.includes('"') ||
          s.includes("\\n") || s.includes("\\r")) {{
        return '"' + s.replace(/"/g, '""') + '"';
      }}
      return s;
    }}

    // Build CSV string
    let csv = headerRow.map(csvEscape).join(",") + "\\n";
    dataRows.forEach(row => {{
      csv += row.map(csvEscape).join(",") + "\\n";
    }});

    // Generate filename from page title and database name
    const dbName = {esc_js_db_name};
    // Extract case prefix from DB name (e.g., "CASE-001" from "CASE-001_forensics_...")
    const casePrefix = dbName.split("_forensics_")[0] || dbName.replace(/\\.db$/i, "");
    const title = document.title.split(" — ")[0]
      .replace(/[^a-zA-Z0-9]/g, "_").replace(/_+/g, "_");
    const suffix = filteredOnly ? "_filtered" : "";
    const filename = casePrefix + "_" + title + suffix + ".csv";

    // Trigger download
    const blob = new Blob([csv], {{ type: "text/csv;charset=utf-8;" }});
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(link.href);
  }};
}})();
</script>

</body>
</html>"""
