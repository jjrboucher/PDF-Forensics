"""
Pre-built forensic SQL queries for report generation.

Each report is a dict with:
  - id:          unique identifier
  - name:        display name
  - description: what the report shows
  - query:       SQL query (for simple tabular reports)
  - query_fn:    callable(conn) -> (columns, data) for pivoted reports
  - columns:     list of column defs (for SQL-based reports)
  - sticky_cols: number of leftmost columns to freeze on scroll

col_type is one of:
  - "text"    : string, filtered by substring match
  - "numeric" : number, filtered by expressions (>5, >=10, <3, 5-10)
  - "date"    : ISO date string, filtered as text
  - "hash"    : hash string, displayed monospace, prefix-match filter
"""

from collections import OrderedDict


# ===================================================================
# Pivot functions for metadata reports
# ===================================================================

# Common metadata keys in preferred display order
_META_KEY_ORDER = [
    "Title", "Author", "Subject", "Creator", "Producer",
    "CreationDate", "ModDate", "Keywords",
    "pdf_version_header", "encrypted", "needs_password",
    "PageMode", "PageLayout", "Lang", "Version",
]


def _query_metadata_pivoted(conn):
    """
    Pivot pdf_metadata into one row per PDF, one column per
    metadata key. Missing fields show 'nil'.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT
            a.id, a.pdf_filename, a.pdf_md5, a.total_pages,
            a.pdf_size_bytes, a.analyzed_at,
            m.source, m.key, m.value
        FROM analyses a
        LEFT JOIN pdf_metadata m ON m.analysis_id = a.id
        ORDER BY a.pdf_filename, a.id
    """)
    rows = cur.fetchall()

    # Collect all unique keys and build per-PDF data
    all_keys = OrderedDict()  # (source, key) -> display_label
    pdf_data = OrderedDict()  # analysis_id -> {display_label: value}
    pdf_info = {}             # analysis_id -> (filename, md5, ...)

    for row in rows:
        aid = row[0]
        if aid not in pdf_info:
            pdf_info[aid] = {
                "Filename": row[1],
                "PDF MD5": row[2],
                "Pages": row[3],
                "Size (bytes)": row[4],
                "Analyzed": row[5],
            }
            pdf_data[aid] = {}

        source = row[6]
        key = row[7]
        value = row[8]

        if source and key:
            # Use source prefix only for non-info_dict to keep
            # common keys clean: "Creator" not "info_dict: Creator"
            if source == "info_dict":
                display = key
            else:
                display = f"{source}: {key}"

            all_keys[(source, key)] = display
            pdf_data[aid][display] = value or ""

    # Sort keys: preferred order first, then alphabetical
    def key_sort(item):
        sk, dk = item
        source, key = sk
        try:
            idx = _META_KEY_ORDER.index(key)
        except ValueError:
            idx = 999
        return (idx, source, key)

    sorted_keys = sorted(all_keys.items(), key=key_sort)

    # Build columns
    columns = [
        {"name": "Filename",     "label": "Filename",     "col_type": "text"},
        {"name": "Pages",        "label": "Pages",        "col_type": "numeric"},
        {"name": "Size (bytes)", "label": "Size (bytes)", "col_type": "numeric"},
        {"name": "PDF MD5",      "label": "PDF MD5",      "col_type": "hash"},
        {"name": "Analyzed",     "label": "Analyzed",     "col_type": "date"},
    ]
    meta_col_names = []
    for (source, key), display in sorted_keys:
        columns.append({
            "name": display, "label": display, "col_type": "text"
        })
        meta_col_names.append(display)

    # Build data rows
    data = []
    for aid in pdf_data:
        record = dict(pdf_info[aid])
        for col_name in meta_col_names:
            record[col_name] = pdf_data[aid].get(col_name, "")
        data.append(record)

    return columns, data


def _query_exif_pivoted(conn):
    """
    Pivot image_metadata into one row per unique image, one column
    per metadata key. Missing fields show 'nil'.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT
            id_tbl.md5_hash,
            id_tbl.format_ext,
            id_tbl.width_px,
            id_tbl.height_px,
            GROUP_CONCAT(DISTINCT a.pdf_filename) AS filenames,
            im.source,
            im.key,
            im.value
        FROM image_metadata im
        JOIN image_data id_tbl ON id_tbl.id = im.image_data_id
        JOIN analyses a        ON a.id = id_tbl.analysis_id
        GROUP BY id_tbl.md5_hash, im.source, im.key
        ORDER BY id_tbl.md5_hash, im.source, im.key
    """)
    rows = cur.fetchall()

    if not rows:
        columns = [
            {"name": "Image MD5", "label": "Image MD5", "col_type": "hash"},
            {"name": "Format",    "label": "Format",    "col_type": "text"},
            {"name": "Found In",  "label": "Found In",  "col_type": "text"},
        ]
        return columns, []

    # Collect unique keys and per-image data
    all_keys = OrderedDict()
    img_data = OrderedDict()
    img_info = {}

    for row in rows:
        md5 = row[0]
        if md5 not in img_info:
            img_info[md5] = {
                "Image MD5": md5,
                "Format": row[1] or "",
                "Width": row[2] or "",
                "Height": row[3] or "",
                "Found In": row[4] or "",
            }
            img_data[md5] = {}

        source = row[5]
        key = row[6]
        value = row[7]

        if source and key:
            if source == "exif":
                display = key
            else:
                display = f"{source}: {key}"
            all_keys[(source, key)] = display
            img_data[md5][display] = value or ""

    sorted_keys = sorted(all_keys.items(),
                         key=lambda x: (x[0][0], x[0][1]))

    columns = [
        {"name": "Image MD5", "label": "Image MD5", "col_type": "hash"},
        {"name": "Format",    "label": "Format",    "col_type": "text"},
        {"name": "Width",     "label": "Width",     "col_type": "numeric"},
        {"name": "Height",    "label": "Height",    "col_type": "numeric"},
        {"name": "Found In",  "label": "Found In",  "col_type": "text"},
    ]
    meta_col_names = []
    for (source, key), display in sorted_keys:
        columns.append({
            "name": display, "label": display, "col_type": "text"
        })
        meta_col_names.append(display)

    data = []
    for md5 in img_data:
        record = dict(img_info[md5])
        for col_name in meta_col_names:
            record[col_name] = img_data[md5].get(col_name, "")
        data.append(record)

    return columns, data


# ===================================================================
# Report definitions
# ===================================================================

REPORTS = [

    # -----------------------------------------------------------------
    # 1. Metadata Report (pivoted — one row per PDF)
    # -----------------------------------------------------------------
    {
        "id": "metadata",
        "name": "PDF Metadata",
        "description":
            "One row per analyzed PDF with all metadata fields as "
            "columns. Missing fields show 'nil'. Scroll right to "
            "see all columns; the Filename column stays visible.",
        "query_fn": _query_metadata_pivoted,
        "sticky_cols": 1,
    },

    # -----------------------------------------------------------------
    # 2. Cross-Document Image Reuse
    # -----------------------------------------------------------------
    {
        "id": "cross_document",
        "name": "Cross-Document Image Reuse",
        "description":
            "Images that appear in more than one analyzed document. "
            "Each row is a unique image with the list of documents "
            "and pages where it was found.",
        "query": """
            SELECT
                id_tbl.md5_hash           AS "Image MD5",
                id_tbl.format_ext         AS "Format",
                id_tbl.width_px           AS "Width",
                id_tbl.height_px          AS "Height",
                COUNT(DISTINCT a.id)      AS "Documents",
                COUNT(DISTINCT p.id)      AS "Pages",
                COUNT(*)                  AS "Placements",
                GROUP_CONCAT(DISTINCT a.pdf_filename)
                                          AS "Found In",
                MAX(i.risk_score)         AS "Max Risk"
            FROM images i
            JOIN pages p        ON p.id = i.page_id
            JOIN analyses a     ON a.id = p.analysis_id
            JOIN image_data id_tbl ON id_tbl.id = i.image_data_id
            GROUP BY id_tbl.md5_hash
            HAVING COUNT(DISTINCT a.id) > 1
            ORDER BY COUNT(DISTINCT a.id) DESC, MAX(i.risk_score) DESC
        """,
        "columns": [
            {"name": "Image MD5",  "label": "Image MD5",  "col_type": "hash"},
            {"name": "Format",     "label": "Format",     "col_type": "text"},
            {"name": "Width",      "label": "Width (px)", "col_type": "numeric"},
            {"name": "Height",     "label": "Height (px)","col_type": "numeric"},
            {"name": "Documents",  "label": "Documents",  "col_type": "numeric"},
            {"name": "Pages",      "label": "Pages",      "col_type": "numeric"},
            {"name": "Placements", "label": "Placements", "col_type": "numeric"},
            {"name": "Found In",   "label": "Found In",   "col_type": "text"},
            {"name": "Max Risk",   "label": "Max Risk",   "col_type": "numeric"},
        ],
    },

    # -----------------------------------------------------------------
    # 3. High-Risk Images
    # -----------------------------------------------------------------
    {
        "id": "high_risk",
        "name": "High-Risk Images",
        "description":
            "All image placements with a non-zero risk score, "
            "sorted by score descending. Shows which specific "
            "findings contributed to each image's risk rating.",
        "query": """
            SELECT
                a.pdf_filename       AS "Filename",
                p.page_number        AS "Page",
                i.label              AS "Label",
                i.risk_score         AS "Risk Score",
                id_tbl.md5_hash      AS "Image MD5",
                id_tbl.format_ext    AS "Format",
                id_tbl.width_px      AS "Width",
                id_tbl.height_px     AS "Height",
                COALESCE(
                    GROUP_CONCAT(DISTINCT ft.code), ''
                )                    AS "Finding Types"
            FROM images i
            JOIN pages p        ON p.id = i.page_id
            JOIN analyses a     ON a.id = p.analysis_id
            LEFT JOIN image_data id_tbl ON id_tbl.id = i.image_data_id
            LEFT JOIN finding_images fi ON fi.image_id = i.id
            LEFT JOIN findings f        ON f.id = fi.finding_id
            LEFT JOIN finding_types ft  ON ft.id = f.finding_type_id
            WHERE i.risk_score > 0
            GROUP BY i.id
            ORDER BY i.risk_score DESC, a.pdf_filename, p.page_number
        """,
        "columns": [
            {"name": "Filename",      "label": "Filename",      "col_type": "text"},
            {"name": "Page",          "label": "Page",          "col_type": "numeric"},
            {"name": "Label",         "label": "Label",         "col_type": "text"},
            {"name": "Risk Score",    "label": "Risk Score",    "col_type": "numeric"},
            {"name": "Image MD5",     "label": "Image MD5",     "col_type": "hash"},
            {"name": "Format",        "label": "Format",        "col_type": "text"},
            {"name": "Width",         "label": "Width (px)",    "col_type": "numeric"},
            {"name": "Height",        "label": "Height (px)",   "col_type": "numeric"},
            {"name": "Finding Types", "label": "Finding Types", "col_type": "text"},
        ],
        "sticky_cols": 1,
    },

    # -----------------------------------------------------------------
    # 4. Manipulation Detail
    # -----------------------------------------------------------------
    {
        "id": "manipulation_detail",
        "name": "Manipulation Detail",
        "description":
            "Every finding detected across all analyzed documents, "
            "with full detail text. Group or filter by finding type "
            "to focus on specific manipulation indicators.",
        "query": """
            SELECT
                a.pdf_filename       AS "Filename",
                p.page_number        AS "Page",
                ft.code              AS "Type",
                ft.severity          AS "Severity",
                f.detail             AS "Detail",
                COALESCE(
                    GROUP_CONCAT(DISTINCT i.label), ''
                )                    AS "Images",
                COALESCE(f.obj_locator, '') AS "Object / Stream",
                a.pdf_md5            AS "PDF MD5"
            FROM findings f
            JOIN finding_types ft  ON ft.id = f.finding_type_id
            JOIN pages p           ON p.id = f.page_id
            JOIN analyses a        ON a.id = p.analysis_id
            LEFT JOIN finding_images fi ON fi.finding_id = f.id
            LEFT JOIN images i          ON i.id = fi.image_id
            GROUP BY f.id
            ORDER BY a.pdf_filename, p.page_number, ft.severity DESC
        """,
        "columns": [
            {"name": "Filename",  "label": "Filename",  "col_type": "text"},
            {"name": "Page",      "label": "Page",      "col_type": "numeric"},
            {"name": "Type",      "label": "Type",      "col_type": "text"},
            {"name": "Severity",  "label": "Severity",  "col_type": "text"},
            {"name": "Detail",    "label": "Detail",    "col_type": "text"},
            {"name": "Images",    "label": "Images",    "col_type": "text"},
            {"name": "Object / Stream", "label": "Object / Stream (for validation)", "col_type": "text"},
            {"name": "PDF MD5",   "label": "PDF MD5",   "col_type": "hash"},
        ],
        "sticky_cols": 1,
    },

    # -----------------------------------------------------------------
    # 5. Incremental Updates
    # -----------------------------------------------------------------
    {
        "id": "incremental_updates",
        "name": "Incremental Updates (%%EOF Analysis)",
        "description":
            "Documents with multiple %%EOF markers, indicating "
            "post-creation modifications via incremental save.",
        "query": """
            SELECT
                a.pdf_filename       AS "Filename",
                a.pdf_size_bytes     AS "File Size",
                COUNT(v.id)          AS "Versions",
                MIN(v.eof_offset)    AS "First EOF Offset",
                MAX(v.eof_offset)    AS "Last EOF Offset",
                a.pdf_md5            AS "PDF MD5",
                a.analyzed_at        AS "Analyzed"
            FROM pdf_versions v
            JOIN analyses a ON a.id = v.analysis_id
            GROUP BY a.id
            HAVING COUNT(v.id) > 1
            ORDER BY COUNT(v.id) DESC
        """,
        "columns": [
            {"name": "Filename",         "label": "Filename",         "col_type": "text"},
            {"name": "File Size",        "label": "File Size (bytes)","col_type": "numeric"},
            {"name": "Versions",         "label": "Versions",         "col_type": "numeric"},
            {"name": "First EOF Offset", "label": "First EOF",        "col_type": "numeric"},
            {"name": "Last EOF Offset",  "label": "Last EOF",         "col_type": "numeric"},
            {"name": "PDF MD5",          "label": "PDF MD5",          "col_type": "hash"},
            {"name": "Analyzed",         "label": "Analyzed",         "col_type": "date"},
        ],
    },

    # -----------------------------------------------------------------
    # 6. EXIF & GPS (pivoted — one row per image)
    # -----------------------------------------------------------------
    {
        "id": "exif_gps",
        "name": "EXIF & GPS Data",
        "description":
            "One row per unique image with all EXIF/GPS metadata "
            "as columns. Missing fields show 'nil'. GPS data in a "
            "supposedly scanned document or mismatched camera models "
            "are forensic indicators. Scroll right for all fields.",
        "query_fn": _query_exif_pivoted,
        "sticky_cols": 1,
    },

    # -----------------------------------------------------------------
    # 7. Creator / Producer Analysis
    # -----------------------------------------------------------------
    {
        "id": "creator_producer",
        "name": "Creator / Producer Analysis",
        "description":
            "One row per document showing Creator, Producer, and "
            "dates. Mismatches within related documents suggest "
            "different software was used.",
        "query": """
            SELECT
                a.pdf_filename   AS "Filename",
                MAX(CASE WHEN m.key = 'Creator'  THEN m.value END)
                                 AS "Creator",
                MAX(CASE WHEN m.key = 'Producer' THEN m.value END)
                                 AS "Producer",
                MAX(CASE WHEN m.key = 'CreationDate' THEN m.value END)
                                 AS "Created",
                MAX(CASE WHEN m.key = 'ModDate' THEN m.value END)
                                 AS "Modified",
                a.total_pages    AS "Pages",
                a.pdf_md5        AS "PDF MD5"
            FROM analyses a
            LEFT JOIN pdf_metadata m
                ON m.analysis_id = a.id AND m.source = 'info_dict'
            GROUP BY a.id
            ORDER BY
                MAX(CASE WHEN m.key = 'Creator' THEN m.value END),
                MAX(CASE WHEN m.key = 'Producer' THEN m.value END)
        """,
        "columns": [
            {"name": "Filename",  "label": "Filename",  "col_type": "text"},
            {"name": "Creator",   "label": "Creator",   "col_type": "text"},
            {"name": "Producer",  "label": "Producer",  "col_type": "text"},
            {"name": "Created",   "label": "Created",   "col_type": "text"},
            {"name": "Modified",  "label": "Modified",  "col_type": "text"},
            {"name": "Pages",     "label": "Pages",     "col_type": "numeric"},
            {"name": "PDF MD5",   "label": "PDF MD5",   "col_type": "hash"},
        ],
        "sticky_cols": 1,
    },

    # -----------------------------------------------------------------
    # 8. Document Comparison Matrix
    # -----------------------------------------------------------------
    {
        "id": "doc_comparison",
        "name": "Document Comparison Matrix",
        "description":
            "Pairs of documents that share one or more images.",
        "query": """
            SELECT
                a1.pdf_filename      AS "Document A",
                a2.pdf_filename      AS "Document B",
                COUNT(DISTINCT id1.md5_hash) AS "Shared Images"
            FROM images i1
            JOIN pages p1          ON p1.id = i1.page_id
            JOIN analyses a1       ON a1.id = p1.analysis_id
            JOIN image_data id1    ON id1.id = i1.image_data_id
            JOIN image_data id2    ON id2.md5_hash = id1.md5_hash
                                  AND id2.id != id1.id
            JOIN images i2         ON i2.image_data_id = id2.id
            JOIN pages p2          ON p2.id = i2.page_id
            JOIN analyses a2       ON a2.id = p2.analysis_id
                                  AND a2.id > a1.id
            GROUP BY a1.id, a2.id
            ORDER BY COUNT(DISTINCT id1.md5_hash) DESC
        """,
        "columns": [
            {"name": "Document A",    "label": "Document A",    "col_type": "text"},
            {"name": "Document B",    "label": "Document B",    "col_type": "text"},
            {"name": "Shared Images", "label": "Shared Images", "col_type": "numeric"},
        ],
    },

    # -----------------------------------------------------------------
    # 9. Off-Page Images
    # -----------------------------------------------------------------
    {
        "id": "offpage",
        "name": "Off-Page Images",
        "description":
            "Images that extend beyond the visible page boundary.",
        "query": """
            SELECT
                a.pdf_filename       AS "Filename",
                p.page_number        AS "Page",
                i.label              AS "Label",
                i.risk_score         AS "Risk Score",
                f.detail             AS "Detail",
                id_tbl.md5_hash      AS "Image MD5",
                id_tbl.format_ext    AS "Format",
                id_tbl.width_px      AS "Width",
                id_tbl.height_px     AS "Height"
            FROM findings f
            JOIN finding_types ft  ON ft.id = f.finding_type_id
            JOIN pages p           ON p.id = f.page_id
            JOIN analyses a        ON a.id = p.analysis_id
            JOIN finding_images fi ON fi.finding_id = f.id
            JOIN images i          ON i.id = fi.image_id
            LEFT JOIN image_data id_tbl ON id_tbl.id = i.image_data_id
            WHERE ft.code = 'OFFPAGE'
            ORDER BY a.pdf_filename, p.page_number
        """,
        "columns": [
            {"name": "Filename",   "label": "Filename",    "col_type": "text"},
            {"name": "Page",       "label": "Page",        "col_type": "numeric"},
            {"name": "Label",      "label": "Label",       "col_type": "text"},
            {"name": "Risk Score", "label": "Risk Score",  "col_type": "numeric"},
            {"name": "Detail",     "label": "Detail",      "col_type": "text"},
            {"name": "Image MD5",  "label": "Image MD5",   "col_type": "hash"},
            {"name": "Format",     "label": "Format",      "col_type": "text"},
            {"name": "Width",      "label": "Width (px)",  "col_type": "numeric"},
            {"name": "Height",     "label": "Height (px)", "col_type": "numeric"},
        ],
        "sticky_cols": 1,
    },

    # -----------------------------------------------------------------
    # 10. Overlap / Concealment Detail
    # -----------------------------------------------------------------
    {
        "id": "overlap_concealment",
        "name": "Overlap & Concealment Detail",
        "description":
            "Detailed overlap findings with concealment assessment.",
        "query": """
            SELECT
                a.pdf_filename       AS "Filename",
                p.page_number        AS "Page",
                i_front.label        AS "Front Image",
                i_back.label         AS "Back Image",
                od.overlap_area_sqpts  AS "Overlap Area",
                ROUND(od.overlap_pct, 1) AS "Overlap %",
                od.front_opacity     AS "Front Opacity",
                od.front_blend_mode  AS "Blend Mode",
                od.concealment_assessment AS "Concealment",
                i_back.risk_score    AS "Back Risk"
            FROM overlap_details od
            JOIN findings f        ON f.id = od.finding_id
            JOIN pages p           ON p.id = f.page_id
            JOIN analyses a        ON a.id = p.analysis_id
            JOIN images i_front    ON i_front.id = od.front_image_id
            JOIN images i_back     ON i_back.id = od.back_image_id
            ORDER BY
                od.concealment_assessment DESC,
                od.overlap_pct DESC
        """,
        "columns": [
            {"name": "Filename",      "label": "Filename",      "col_type": "text"},
            {"name": "Page",          "label": "Page",          "col_type": "numeric"},
            {"name": "Front Image",   "label": "Front Image",   "col_type": "text"},
            {"name": "Back Image",    "label": "Back Image",    "col_type": "text"},
            {"name": "Overlap Area",  "label": "Overlap Area",  "col_type": "numeric"},
            {"name": "Overlap %",     "label": "Overlap %",     "col_type": "numeric"},
            {"name": "Front Opacity", "label": "Opacity",       "col_type": "numeric"},
            {"name": "Blend Mode",    "label": "Blend Mode",    "col_type": "text"},
            {"name": "Concealment",   "label": "Concealment",   "col_type": "text"},
            {"name": "Back Risk",     "label": "Back Risk",     "col_type": "numeric"},
        ],
        "sticky_cols": 1,
    },

    # -----------------------------------------------------------------
    # 11. Stamp / Signature Reuse Candidates
    # -----------------------------------------------------------------
    {
        "id": "stamp_reuse",
        "name": "Stamp / Signature Reuse Candidates",
        "description":
            "Small images that appear on multiple pages — likely "
            "stamps, signatures, or initials.",
        "query": """
            SELECT
                id_tbl.md5_hash          AS "Image MD5",
                id_tbl.format_ext        AS "Format",
                id_tbl.width_px          AS "Width",
                id_tbl.height_px         AS "Height",
                COUNT(DISTINCT p.id)     AS "Pages",
                COUNT(DISTINCT a.id)     AS "Documents",
                GROUP_CONCAT(DISTINCT a.pdf_filename)
                                         AS "Found In",
                MAX(i.risk_score)        AS "Max Risk"
            FROM images i
            JOIN pages p         ON p.id = i.page_id
            JOIN analyses a      ON a.id = p.analysis_id
            JOIN image_data id_tbl ON id_tbl.id = i.image_data_id
            WHERE id_tbl.width_px < 500
              AND id_tbl.height_px < 500
            GROUP BY id_tbl.md5_hash
            HAVING COUNT(DISTINCT p.id) > 1
            ORDER BY COUNT(DISTINCT p.id) DESC
        """,
        "columns": [
            {"name": "Image MD5",  "label": "Image MD5",  "col_type": "hash"},
            {"name": "Format",     "label": "Format",     "col_type": "text"},
            {"name": "Width",      "label": "Width (px)", "col_type": "numeric"},
            {"name": "Height",     "label": "Height (px)","col_type": "numeric"},
            {"name": "Pages",      "label": "Pages",      "col_type": "numeric"},
            {"name": "Documents",  "label": "Documents",  "col_type": "numeric"},
            {"name": "Found In",   "label": "Found In",   "col_type": "text"},
            {"name": "Max Risk",   "label": "Max Risk",   "col_type": "numeric"},
        ],
    },

    # -----------------------------------------------------------------
    # 12. DPI / Resolution Analysis
    # -----------------------------------------------------------------
    {
        "id": "dpi_analysis",
        "name": "DPI / Resolution Analysis",
        "description":
            "Effective DPI of every image placement, computed from "
            "pixel dimensions and the PDF transformation matrix. "
            "Mixed DPIs within a document suggest images from "
            "different sources (scanner, camera, screenshot). "
            "Stretched images (X ≠ Y DPI) indicate manual resizing.",
        "query": """
            SELECT
                a.pdf_filename       AS "Filename",
                p.page_number        AS "Page",
                i.label              AS "Label",
                id_tbl.md5_hash      AS "Image MD5",
                id_tbl.width_px      AS "Pixel W",
                id_tbl.height_px     AS "Pixel H",
                ROUND(i.display_w_pts, 1) AS "Display W (pts)",
                ROUND(i.display_h_pts, 1) AS "Display H (pts)",
                ROUND(i.display_w_pts / 72.0, 2) AS "Display W (in)",
                ROUND(i.display_h_pts / 72.0, 2) AS "Display H (in)",
                ROUND(i.dpi_x, 1)   AS "DPI X",
                ROUND(i.dpi_y, 1)   AS "DPI Y",
                CASE
                    WHEN i.dpi_x IS NULL THEN ''
                    WHEN ABS(i.dpi_x - i.dpi_y) >
                         (i.dpi_x + i.dpi_y) * 0.05
                    THEN 'STRETCHED'
                    ELSE ''
                END                  AS "Stretched",
                CASE
                    WHEN i.dpi_x IS NULL THEN ''
                    WHEN (i.dpi_x + i.dpi_y) / 2.0 < 100
                    THEN 'Screenshot / Web'
                    WHEN (i.dpi_x + i.dpi_y) / 2.0 < 200
                    THEN 'Low-res / Resized'
                    WHEN (i.dpi_x + i.dpi_y) / 2.0 < 350
                    THEN 'Standard scan'
                    ELSE 'High-res photo/scan'
                END                  AS "Likely Source",
                i.risk_score         AS "Risk Score",
                id_tbl.format_ext    AS "Format"
            FROM images i
            JOIN pages p        ON p.id = i.page_id
            JOIN analyses a     ON a.id = p.analysis_id
            LEFT JOIN image_data id_tbl ON id_tbl.id = i.image_data_id
            WHERE i.dpi_x IS NOT NULL
            ORDER BY a.pdf_filename, p.page_number, i.label
        """,
        "columns": [
            {"name": "Filename",         "label": "Filename",         "col_type": "text"},
            {"name": "Page",             "label": "Page",             "col_type": "numeric"},
            {"name": "Label",            "label": "Label",            "col_type": "text"},
            {"name": "Image MD5",        "label": "Image MD5",        "col_type": "hash"},
            {"name": "Pixel W",          "label": "Pixel W",          "col_type": "numeric"},
            {"name": "Pixel H",          "label": "Pixel H",          "col_type": "numeric"},
            {"name": "Display W (pts)",  "label": "Display W (pts)",  "col_type": "numeric"},
            {"name": "Display H (pts)",  "label": "Display H (pts)",  "col_type": "numeric"},
            {"name": "Display W (in)",   "label": "Display W (in)",   "col_type": "numeric"},
            {"name": "Display H (in)",   "label": "Display H (in)",   "col_type": "numeric"},
            {"name": "DPI X",            "label": "DPI X",            "col_type": "numeric"},
            {"name": "DPI Y",            "label": "DPI Y",            "col_type": "numeric"},
            {"name": "Stretched",        "label": "Stretched",        "col_type": "text"},
            {"name": "Likely Source",    "label": "Likely Source",    "col_type": "text"},
            {"name": "Risk Score",       "label": "Risk Score",       "col_type": "numeric"},
            {"name": "Format",           "label": "Format",           "col_type": "text"},
        ],
        "sticky_cols": 1,
    },

    # -----------------------------------------------------------------
    # 13. Text Overlay Detection
    # -----------------------------------------------------------------
    {
        "id": "text_overlay",
        "name": "Text Overlay Detection",
        "description":
            "Annotations (text boxes, form fields, rectangles) placed "
            "over existing page text with an opaque background — the "
            "most common method for altering visible dates, amounts, "
            "and names in a PDF without modifying the underlying "
            "content stream.",
        "query": """
            SELECT
                a.pdf_filename       AS "Filename",
                p.page_number        AS "Page",
                ft.code              AS "Type",
                f.detail             AS "Detail",
                COALESCE(f.obj_locator, '') AS "Object / Stream",
                a.pdf_md5            AS "PDF MD5"
            FROM findings f
            JOIN finding_types ft  ON ft.id = f.finding_type_id
            JOIN pages p           ON p.id = f.page_id
            JOIN analyses a        ON a.id = p.analysis_id
            WHERE ft.code = 'TEXT_OVERLAY'
            ORDER BY a.pdf_filename, p.page_number
        """,
        "columns": [
            {"name": "Filename", "label": "Filename", "col_type": "text"},
            {"name": "Page",     "label": "Page",     "col_type": "numeric"},
            {"name": "Type",     "label": "Type",     "col_type": "text"},
            {"name": "Detail",   "label": "Detail",   "col_type": "text"},
            {"name": "Object / Stream", "label": "Object / Stream (for validation)", "col_type": "text"},
            {"name": "PDF MD5",  "label": "PDF MD5",  "col_type": "hash"},
        ],
        "sticky_cols": 1,
    },

    # -----------------------------------------------------------------
    # 14. Document Comments
    # -----------------------------------------------------------------
    {
        "id": "document_comments",
        "name": "Document Comments",
        "description":
            "Reviewer comments and markup annotations (sticky notes, "
            "text boxes, highlights, etc.) embedded in the analyzed "
            "documents, with author, timestamps, and the PDF object "
            "number for validation.",
        "query": """
            SELECT
                a.pdf_filename       AS "Filename",
                a.pdf_path           AS "Path",
                c.page_number        AS "Page",
                c.annot_subtype      AS "Type",
                c.author             AS "Author",
                c.contents           AS "Comment",
                COALESCE(c.modified_date, c.created_date) AS "Date/Time",
                c.created_date       AS "Created",
                c.modified_date      AS "Modified",
                CASE
                    WHEN c.obj_num IS NOT NULL
                    THEN c.obj_num || ' ' || COALESCE(c.obj_gen, 0) || ' R'
                    ELSE ''
                END                  AS "Object",
                a.pdf_md5            AS "PDF MD5"
            FROM comments c
            JOIN analyses a ON a.id = c.analysis_id
            ORDER BY a.pdf_filename, c.page_number, c.id
        """,
        "columns": [
            {"name": "Filename",  "label": "Filename",  "col_type": "text"},
            {"name": "Path",      "label": "Path",      "col_type": "text"},
            {"name": "Page",      "label": "Page",      "col_type": "numeric"},
            {"name": "Type",      "label": "Type",      "col_type": "text"},
            {"name": "Author",    "label": "Author",    "col_type": "text"},
            {"name": "Comment",   "label": "Comment",   "col_type": "text"},
            {"name": "Date/Time", "label": "Date/Time", "col_type": "date"},
            {"name": "Created",   "label": "Created",   "col_type": "date"},
            {"name": "Modified",  "label": "Modified",  "col_type": "date"},
            {"name": "Object",    "label": "Object (for validation)", "col_type": "text"},
            {"name": "PDF MD5",   "label": "PDF MD5",   "col_type": "hash"},
        ],
        "sticky_cols": 1,
    },

    # -----------------------------------------------------------------
    # Font Consistency Analysis (ANAL-03)
    # -----------------------------------------------------------------
    {
        "id": "font_anomaly",
        "name": "Font Consistency Analysis",
        "description":
            "Text spans whose font is inconsistent with the document's "
            "dominant body font. Text inserted by a different application "
            "during an alteration commonly uses a different font, subset, "
            "or encoding than the surrounding text, so an out-of-place "
            "font is an independent indicator of an in-place edit.",
        "query": """
            SELECT
                a.pdf_filename       AS "Filename",
                p.page_number        AS "Page",
                f.detail             AS "Detail",
                a.pdf_md5            AS "PDF MD5"
            FROM findings f
            JOIN finding_types ft  ON ft.id = f.finding_type_id
            JOIN pages p           ON p.id = f.page_id
            JOIN analyses a        ON a.id = p.analysis_id
            WHERE ft.code = 'FONT_ANOMALY'
            ORDER BY a.pdf_filename, p.page_number
        """,
        "columns": [
            {"name": "Filename", "label": "Filename", "col_type": "text"},
            {"name": "Page",     "label": "Page",     "col_type": "numeric"},
            {"name": "Detail",   "label": "Detail",   "col_type": "text"},
            {"name": "PDF MD5",  "label": "PDF MD5",  "col_type": "hash"},
        ],
        "sticky_cols": 1,
    },

]


def get_report_by_id(report_id):
    """Look up a report definition by its id."""
    for r in REPORTS:
        if r["id"] == report_id:
            return r
    return None


# Canonical grouping / ordering of reports, arranged to follow an
# examiner's workflow: document provenance first, then signs of
# alteration, then image-specific findings, then cross-document / review.
# Each entry is (group_label, [report_id, ...]).
REPORT_GROUPS = [
    ("Document Overview & Provenance", [
        "metadata",
        "creator_producer",
        "exif_gps",
        "incremental_updates",
    ]),
    ("Manipulation & Alteration", [
        "manipulation_detail",
        "text_overlay",
        "font_anomaly",
        "overlap_concealment",
        "dpi_analysis",
    ]),
    ("Image Analysis", [
        "high_risk",
        "offpage",
        "stamp_reuse",
    ]),
    ("Cross-Document & Review", [
        "cross_document",
        "doc_comparison",
        "document_comments",
    ]),
]


def _ordered_report_ids():
    """Report ids in canonical (grouped) order, with any report not listed
    in REPORT_GROUPS appended at the end so nothing is ever dropped."""
    ordered = [rid for _label, ids in REPORT_GROUPS for rid in ids]
    known = set(ordered)
    for r in REPORTS:
        if r["id"] not in known:
            ordered.append(r["id"])
    return ordered


def list_reports():
    """Return a list of (id, name, description) tuples in canonical order."""
    by_id = {r["id"]: r for r in REPORTS}
    out = []
    for rid in _ordered_report_ids():
        r = by_id.get(rid)
        if r:
            out.append((r["id"], r["name"], r["description"]))
    return out


def list_report_groups():
    """Return [(group_label, [(id, name, description), ...]), ...] in
    canonical order, for grouped display in the UI."""
    by_id = {r["id"]: r for r in REPORTS}
    groups = []
    placed = set()
    for label, ids in REPORT_GROUPS:
        items = []
        for rid in ids:
            r = by_id.get(rid)
            if r:
                items.append((r["id"], r["name"], r["description"]))
                placed.add(rid)
        if items:
            groups.append((label, items))
    # Any reports not assigned to a group go in a trailing "Other" group.
    leftovers = [(r["id"], r["name"], r["description"])
                 for r in REPORTS if r["id"] not in placed]
    if leftovers:
        groups.append(("Other", leftovers))
    return groups
