"""
Data loading from the forensics database for graph generation.
"""

import sqlite3
from collections import defaultdict


def load_data(conn, scope="cross_document", group_versions=True):
    """
    Load image placements that appear more than once.

    scope options:
      'all_placements'  : md5 appears in 2+ image placements
      'cross_page'      : md5 appears on 2+ distinct pages
      'cross_document'  : md5 appears in 2+ distinct documents

    group_versions (cross_document only): when True (default), a
    document and the prior versions extracted from it are treated as a
    single lineage, so an image shared only among versions of the SAME
    document is NOT counted as cross-document reuse. When False, every
    version counts as its own document (legacy behaviour). Reuse that
    spans two distinct lineages is always cross-document either way.

    Each returned row carries, after risk_score:
      source_analysis_id (11), version_number (12), lineage_root (13)
    so the graph builder can distinguish genuine cross-lineage reuse
    from within-lineage (version) reuse.
    """
    # The risk_score column was added in a later schema version.
    cur = conn.execute("PRAGMA table_info(images)")
    has_risk = any(row[1] == "risk_score" for row in cur.fetchall())
    risk_select = "i.risk_score AS risk_score" if has_risk \
        else "0 AS risk_score"

    # Lineage columns arrived in schema revision 7. Degrade gracefully
    # on older databases: every document is then its own lineage.
    cur = conn.execute("PRAGMA table_info(analyses)")
    acols = {row[1] for row in cur.fetchall()}
    has_lineage = ("source_analysis_id" in acols
                   and "version_number" in acols)
    if has_lineage:
        lineage_root_expr = "COALESCE(a.source_analysis_id, a.id)"
        source_select = "a.source_analysis_id AS source_analysis_id"
        version_select = "a.version_number AS version_number"
    else:
        lineage_root_expr = "a.id"
        source_select = "NULL AS source_analysis_id"
        version_select = "NULL AS version_number"

    # Grouping affects only the cross-document distinctness test.
    if group_versions and has_lineage:
        cross_doc_key = lineage_root_expr
    else:
        cross_doc_key = "p.analysis_id"

    if scope == "cross_document":
        dup_filter = f"""
            SELECT idata.md5_hash
            FROM image_data idata
            JOIN images i ON i.image_data_id = idata.id
            JOIN pages p ON p.id = i.page_id
            JOIN analyses a ON a.id = p.analysis_id
            GROUP BY idata.md5_hash
            HAVING COUNT(DISTINCT {cross_doc_key}) > 1
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
            idata.height_px,
            {risk_select},
            {source_select},
            {version_select},
            {lineage_root_expr} AS lineage_root
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


def load_findings_for_md5s(conn, md5_set):
    """
    Return a dict: {md5: [(finding_type_code, severity, role,
                           pdf_filename, page_number, detail), ...]}

    Aggregates every finding linked to any placement of each
    image (by md5 hash). Used for tooltips and risk explanations.
    """
    findings = {md5: [] for md5 in md5_set}
    if not md5_set:
        return findings

    placeholders = ",".join(["?"] * len(md5_set))
    try:
        rows = conn.execute(f"""
            SELECT
                idata.md5_hash,
                ft.code,
                ft.severity,
                fi.role,
                a.pdf_filename,
                p.page_number,
                f.detail
            FROM image_data idata
            JOIN images i          ON i.image_data_id = idata.id
            JOIN finding_images fi ON fi.image_id = i.id
            JOIN findings f        ON f.id = fi.finding_id
            JOIN finding_types ft  ON ft.id = f.finding_type_id
            JOIN pages p           ON p.id = i.page_id
            JOIN analyses a        ON a.id = p.analysis_id
            WHERE idata.md5_hash IN ({placeholders})
            ORDER BY ft.severity DESC, ft.code
        """, list(md5_set)).fetchall()
    except Exception:
        return findings

    for row in rows:
        md5 = row[0]
        findings[md5].append({
            "code":     row[1],
            "severity": row[2],
            "role":     row[3],
            "pdf":      row[4],
            "page":     row[5],
            "detail":   row[6],
        })
    return findings
