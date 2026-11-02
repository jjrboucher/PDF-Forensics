"""
Database initialization, schema management, and data persistence.
"""

import os
import sqlite3
import hashlib
from datetime import datetime, timezone

from pdf_forensics import __version__, __tool_name__, SCHEMA_REVISION


_md5_cache = {}


def compute_file_md5(path, short=False):
    """
    Compute the MD5 of a file, cached by (path, mtime, size) so the
    same database isn't re-hashed once per report in a batch.

    Returns the hex digest, or "unavailable" on error. When short is
    True, returns an abbreviated form for compact display.
    """
    try:
        st = os.stat(path)
        key = (os.path.abspath(path), st.st_mtime, st.st_size)
        digest = _md5_cache.get(key)
        if digest is None:
            h = hashlib.md5()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            digest = h.hexdigest()
            _md5_cache[key] = digest
    except Exception:
        return "unavailable"
    if short and len(digest) == 32:
        return f"{digest[:8]}\u2026{digest[-4:]}"
    return digest


# ===================================================================
# Constants
# ===================================================================

FINDING_TYPE_DEFS = {
    "BBOX_CROP":            ("Image cropped by BBox boundary",          "HIGH"),
    "EXPLICIT_CLIP":        ("Explicit clipping path applied",          "HIGH"),
    "OVERLAP":              ("Overlapping images",                      "HIGH"),
    "OFFPAGE":              ("Image extends beyond page boundary",      "HIGH"),
    "DPI_ANOMALY":          ("Inconsistent image resolution",           "HIGH"),
    "TEXT_OVERLAY":         ("Annotation overlaid on page text",        "HIGH"),
    "FONT_ANOMALY":         ("Font inconsistent with document body",    "MEDIUM"),
    "SOFT_MASK":            ("Soft mask on Form XObject",               "INFO"),
    "IMAGE_SMASK":          ("Soft mask on Image XObject",              "INFO"),
    "COMPLEX_TRANSFORM":    ("Complex transform (manual review needed)","INFO"),
    "PARSE_ERROR":          ("Stream parse error",                      "INFO"),
    # Document-level finding types (analysis/doc_checks.py). Seeded via
    # INSERT OR IGNORE, so existing databases gain them on next open.
    "METADATA_DATE_ANOMALY": ("ModDate precedes CreationDate",          "HIGH"),
    "METADATA_MISMATCH":    ("Info dictionary / XMP disagreement",      "MEDIUM"),
    "VERSION_MISMATCH":     ("Header / Catalog PDF version differ",     "INFO"),
    "XMP_ID_ANOMALY":       ("XMP DocumentID equals InstanceID",        "INFO"),
    "MIXED_CAMERA":         ("Images from multiple capture devices",    "MEDIUM"),
    "REDACT_UNAPPLIED":     ("Unapplied redaction (content recoverable)","HIGH"),
    "SIGNED_THEN_MODIFIED": ("File modified after digital signature",   "HIGH"),
    "STRUCTURAL_WARNING":   ("Structural integrity warnings (qpdf)",    "INFO"),
    "VERSION_ANACHRONISM":  ("Features exceed declared PDF version",     "MEDIUM"),
    "VERSION_INVALID":      ("Declared PDF version does not exist",      "HIGH"),
    "VERSION_CONFLICT":     ("PDF version declarations disagree or changed", "MEDIUM"),
    "TIMELINE_INCONSISTENT": ("Timestamps out of chronological order",   "HIGH"),
    "METADATA_REVISED":     ("Metadata changed by a later revision",     "MEDIUM"),
    "EXIFTOOL_EDIT":        ("Edited with ExifTool (update marker)",     "MEDIUM"),
}


# ---------------------------------------------------------------------
# Text that SQLite cannot store
#
# Malformed PDFs can yield text with unpaired UTF-16 surrogates (half of a
# character), e.g. in metadata, comments or font names. Python holds such
# text, but SQLite must store valid UTF-8 and raises UnicodeEncodeError
# ("surrogates not allowed"), which used to fail the whole analysis at the
# database save. Every write now goes through a connection that stores
# each unpaired surrogate as a visible escape (e.g. \udc8f), so the save
# succeeds and the examiner can still see exactly what the PDF contained.
# ---------------------------------------------------------------------
import re as _re

_SURROGATE = _re.compile("[\ud800-\udfff]")


def _escape_surrogates(value, counter):
    if isinstance(value, str) and _SURROGATE.search(value):
        counter[0] += 1
        return _SURROGATE.sub(lambda m: "\\u%04x" % ord(m.group()), value)
    return value


def _clean_params(params, counter):
    if params is None:
        return params
    if isinstance(params, dict):
        return {k: _escape_surrogates(v, counter) for k, v in params.items()}
    if isinstance(params, (list, tuple)):
        return type(params)(_escape_surrogates(v, counter) for v in params)
    return params


class _SafeCursor(sqlite3.Cursor):
    def execute(self, sql, params=()):
        return super().execute(sql, _clean_params(params,
                                                  self.connection.escaped))

    def executemany(self, sql, seq):
        esc = self.connection.escaped
        return super().executemany(sql, (_clean_params(p, esc) for p in seq))


class SafeConnection(sqlite3.Connection):
    """sqlite3 connection whose writes escape unpaired surrogates.
    escaped[0] counts the values escaped since the connection opened."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.escaped = [0]

    def cursor(self, factory=_SafeCursor):
        return super().cursor(factory)

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def executemany(self, sql, seq):
        return self.cursor().executemany(sql, seq)


# Indexes on the columns the reports join and filter on. Without them the
# reports that correlate findings, pages and analyses scanned whole tables
# for every row (Concealment Overview took over two minutes on a 700-file
# case). Created when any database is opened, so existing databases gain
# them too; they do not change any data.
_INDEXES = (
    ("idx_pages_analysis", "pages(analysis_id)"),
    ("idx_images_page", "images(page_id)"),
    ("idx_images_image_data", "images(image_data_id)"),
    ("idx_findings_page", "findings(page_id)"),
    ("idx_findings_type", "findings(finding_type_id)"),
    ("idx_finding_images_finding", "finding_images(finding_id)"),
    ("idx_finding_images_image", "finding_images(image_id)"),
    ("idx_overlap_front", "overlap_details(front_image_id)"),
    ("idx_overlap_back", "overlap_details(back_image_id)"),
    ("idx_image_data_md5", "image_data(md5_hash)"),
    ("idx_image_metadata_image", "image_metadata(image_data_id)"),
    ("idx_pdf_metadata_analysis", "pdf_metadata(analysis_id)"),
    ("idx_pdf_versions_analysis", "pdf_versions(analysis_id)"),
    ("idx_comments_analysis", "comments(analysis_id)"),
    ("idx_analyses_md5", "analyses(pdf_md5)"),
    ("idx_analyses_source", "analyses(source_analysis_id)"),
    ("idx_submissions_analysis", "submissions(analysis_id)"),
    ("idx_submissions_path", "submissions(pdf_path)"),
    ("idx_encryption_path", "encryption(pdf_path)"),
)


def refresh_statistics(conn_or_path, only_if_missing=False):
    """Gather the query planner's statistics (ANALYZE). With the indexes
    above, the slowest reports run in a fraction of a second instead of
    minutes, but only once SQLite has statistics; without them it can
    choose a slower plan than with no indexes at all. ANALYZE writes a
    small sqlite_stat1 table, so it runs at the end of an analysis run
    (when the database is being written anyway), and before report
    generation only for a database that has no statistics yet
    (only_if_missing=True), so generating reports does not otherwise
    change the database."""
    own = isinstance(conn_or_path, str)
    conn = sqlite3.connect(conn_or_path) if own else conn_or_path
    try:
        if only_if_missing:
            has = conn.execute("SELECT 1 FROM sqlite_master WHERE "
                               "name='sqlite_stat1'").fetchone()
            if has:
                return False
        conn.execute("ANALYZE")
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        if own:
            conn.close()


def init_db(db_path, session=None):
    """Create database and tables if they don't exist."""
    conn = sqlite3.connect(db_path, factory=SafeConnection)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            version         TEXT    NOT NULL,
            schema_revision INTEGER NOT NULL,
            created_at      TEXT    NOT NULL,
            tool_name       TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS analyses (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            pdf_filename  TEXT    NOT NULL,
            pdf_path      TEXT    NOT NULL,
            pdf_size_bytes INTEGER NOT NULL,
            pdf_md5       TEXT    NOT NULL,
            total_pages   INTEGER NOT NULL,
            analyzed_at   TEXT    NOT NULL,
            doc_risk_score INTEGER DEFAULT 0,
            source_analysis_id INTEGER
                         REFERENCES analyses(id) ON DELETE SET NULL,
            version_number INTEGER
        );

        CREATE TABLE IF NOT EXISTS pages (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id   INTEGER NOT NULL
                          REFERENCES analyses(id) ON DELETE CASCADE,
            page_number   INTEGER NOT NULL,
            risk_score    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS image_data (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id   INTEGER NOT NULL
                          REFERENCES analyses(id) ON DELETE CASCADE,
            xref          INTEGER NOT NULL,
            format_ext    TEXT,
            width_px      INTEGER,
            height_px     INTEGER,
            image_bytes   BLOB,
            byte_size     INTEGER NOT NULL,
            md5_hash      TEXT    NOT NULL,
            UNIQUE(analysis_id, xref)
        );

        CREATE TABLE IF NOT EXISTS images (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id               INTEGER NOT NULL
                                  REFERENCES pages(id) ON DELETE CASCADE,
            image_data_id         INTEGER
                                  REFERENCES image_data(id) ON DELETE SET NULL,
            label                 TEXT    NOT NULL,
            z_order               INTEGER,
            opacity               REAL    DEFAULT 1.0,
            blend_mode            TEXT    DEFAULT '/Normal',
            has_smask             INTEGER DEFAULT 0,
            in_transparency_group INTEGER DEFAULT 0,
            form_xobject_xref    INTEGER DEFAULT 0,
            risk_score            INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS finding_types (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            code     TEXT    NOT NULL UNIQUE,
            label    TEXT    NOT NULL,
            severity TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS findings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id         INTEGER NOT NULL
                            REFERENCES pages(id) ON DELETE CASCADE,
            finding_type_id INTEGER NOT NULL
                            REFERENCES finding_types(id),
            detail          TEXT    NOT NULL,
            bbox_x0         REAL,
            bbox_y0         REAL,
            bbox_x1         REAL,
            bbox_y1         REAL,
            overlay_kind    TEXT,
            obj_num         INTEGER,
            obj_gen         INTEGER,
            obj_locator     TEXT
        );

        CREATE TABLE IF NOT EXISTS finding_images (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            finding_id INTEGER NOT NULL
                       REFERENCES findings(id) ON DELETE CASCADE,
            image_id   INTEGER NOT NULL
                       REFERENCES images(id) ON DELETE CASCADE,
            role       TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS overlap_details (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            finding_id             INTEGER NOT NULL UNIQUE
                                   REFERENCES findings(id) ON DELETE CASCADE,
            front_image_id         INTEGER NOT NULL
                                   REFERENCES images(id) ON DELETE CASCADE,
            back_image_id          INTEGER NOT NULL
                                   REFERENCES images(id) ON DELETE CASCADE,
            overlap_area_sqpts     REAL,
            overlap_pct            REAL,
            front_opacity          REAL,
            front_blend_mode       TEXT,
            front_has_smask        INTEGER,
            concealment_assessment TEXT
        );

        CREATE TABLE IF NOT EXISTS pdf_metadata (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id  INTEGER NOT NULL
                         REFERENCES analyses(id) ON DELETE CASCADE,
            source       TEXT    NOT NULL,
            key          TEXT    NOT NULL,
            value        TEXT
        );

        CREATE TABLE IF NOT EXISTS pdf_versions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id     INTEGER NOT NULL
                            REFERENCES analyses(id) ON DELETE CASCADE,
            version_number  INTEGER NOT NULL,
            eof_offset      INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS image_metadata (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            image_data_id  INTEGER NOT NULL
                           REFERENCES image_data(id) ON DELETE CASCADE,
            source         TEXT    NOT NULL,
            key            TEXT    NOT NULL,
            value          TEXT
        );

        CREATE TABLE IF NOT EXISTS comments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id   INTEGER NOT NULL
                          REFERENCES analyses(id) ON DELETE CASCADE,
            page_number   INTEGER,
            annot_subtype TEXT,
            author        TEXT,
            contents      TEXT,
            created_date  TEXT,
            modified_date TEXT,
            obj_num       INTEGER,
            obj_gen       INTEGER
        );

        -- Every file submitted for analysis and what happened to it
        -- (schema rev 8). Analyses only exist for files that completed,
        -- so without this a skipped identical copy or a failed file left
        -- no trace in the case record.
        CREATE TABLE IF NOT EXISTS submissions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_ts      TEXT,
            submitted_at    TEXT NOT NULL,
            pdf_path        TEXT NOT NULL,
            pdf_filename    TEXT NOT NULL,
            name_key        TEXT,
            pdf_md5         TEXT,
            pdf_size        INTEGER,
            is_version      INTEGER NOT NULL DEFAULT 0,
            outcome         TEXT NOT NULL,
            analysis_id     INTEGER REFERENCES analyses(id) ON DELETE SET NULL,
            duplicate_of    TEXT,
            reason          TEXT
        );

        -- Every timestamp in a submitted document, across all its
        -- revisions, normalised to UTC (schema rev 10). One row per
        -- distinct value; feeds the Timeline Analysis report.
        CREATE TABLE IF NOT EXISTS timeline_events (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id   INTEGER NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
            seq           INTEGER NOT NULL,  -- chronological order (unparseable last)
            revisions     TEXT,              -- e.g. "revision 2 to current"
            category      TEXT,              -- document, history, annotation, signature, embedded file, photo EXIF
            source        TEXT,
            field         TEXT,
            obj_ref       TEXT,
            raw_value     TEXT,
            timezone      TEXT,              -- explicit / none (assumed UTC) / unparseable
            utc           TEXT,              -- YYYY-MM-DD HH:MM:SS, UTC
            status        TEXT,              -- OK / FLAGGED / UNPARSEABLE
            issue         TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_timeline_analysis ON timeline_events(analysis_id);

        -- Encryption outcome per submitted file (schema rev 9). Separate
        -- from submissions so it is additive; one row per file handled in
        -- a run. Lets the Encrypted Files report be rebuilt from the
        -- database on a later run.
        CREATE TABLE IF NOT EXISTS encryption (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            session_ts    TEXT,
            recorded_at   TEXT NOT NULL,
            pdf_path      TEXT NOT NULL,
            pdf_filename  TEXT NOT NULL,
            pdf_md5       TEXT,
            is_encrypted  INTEGER NOT NULL,
            opened        INTEGER NOT NULL,
            password      TEXT,          -- the password that worked ("" = empty); NULL if none did or n/a
            password_source TEXT,        -- e.g. "list line 14", "empty", "known-good"
            scheme        TEXT,          -- e.g. "AES-256 (V5 R6)"
            attempts      INTEGER,       -- passwords tried on this file
            analysis_id   INTEGER REFERENCES analyses(id) ON DELETE SET NULL
        );
    """)

    for name, target in _INDEXES:
        try:
            cur.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")
        except sqlite3.Error:
            pass

    for code, (label, severity) in FINDING_TYPE_DEFS.items():
        cur.execute("""
            INSERT OR IGNORE INTO finding_types (code, label, severity)
            VALUES (?, ?, ?)
        """, (code, label, severity))

    # Migration: ensure risk_score column exists on images
    cur.execute("PRAGMA table_info(images)")
    image_cols = {row[1] for row in cur.fetchall()}
    if "risk_score" not in image_cols:
        cur.execute(
            "ALTER TABLE images ADD COLUMN risk_score INTEGER DEFAULT 0")

    # Migration: ensure DPI columns exist on images
    if "dpi_x" not in image_cols:
        cur.execute(
            "ALTER TABLE images ADD COLUMN dpi_x REAL")
    if "dpi_y" not in image_cols:
        cur.execute(
            "ALTER TABLE images ADD COLUMN dpi_y REAL")
    if "display_w_pts" not in image_cols:
        cur.execute(
            "ALTER TABLE images ADD COLUMN display_w_pts REAL")
    if "display_h_pts" not in image_cols:
        cur.execute(
            "ALTER TABLE images ADD COLUMN display_h_pts REAL")

    # Migration: ensure bbox/overlay_kind columns exist on findings
    cur.execute("PRAGMA table_info(findings)")
    finding_cols = {row[1] for row in cur.fetchall()}
    for col in ("bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1"):
        if col not in finding_cols:
            cur.execute(
                f"ALTER TABLE findings ADD COLUMN {col} REAL")
    if "overlay_kind" not in finding_cols:
        cur.execute(
            "ALTER TABLE findings ADD COLUMN overlay_kind TEXT")
    # Migration: object/stream locator columns on findings (rev 5)
    if "obj_num" not in finding_cols:
        cur.execute(
            "ALTER TABLE findings ADD COLUMN obj_num INTEGER")
    if "obj_gen" not in finding_cols:
        cur.execute(
            "ALTER TABLE findings ADD COLUMN obj_gen INTEGER")
    if "obj_locator" not in finding_cols:
        cur.execute(
            "ALTER TABLE findings ADD COLUMN obj_locator TEXT")

    # Migration: document/page risk score columns (rev 6).
    # Additive and idempotent — harmless if run against an older dev DB.
    cur.execute("PRAGMA table_info(analyses)")
    analyses_cols = {row[1] for row in cur.fetchall()}
    if "doc_risk_score" not in analyses_cols:
        cur.execute(
            "ALTER TABLE analyses ADD COLUMN doc_risk_score INTEGER DEFAULT 0")
    # Lineage columns (rev 7): link an extracted prior version to
    # the analysis of its parent document. Additive and idempotent.
    if "source_analysis_id" not in analyses_cols:
        cur.execute(
            "ALTER TABLE analyses ADD COLUMN source_analysis_id INTEGER")
    if "version_number" not in analyses_cols:
        cur.execute(
            "ALTER TABLE analyses ADD COLUMN version_number INTEGER")
    cur.execute("PRAGMA table_info(pages)")
    pages_cols = {row[1] for row in cur.fetchall()}
    if "risk_score" not in pages_cols:
        cur.execute(
            "ALTER TABLE pages ADD COLUMN risk_score INTEGER DEFAULT 0")

    # Migration: comments table (rev 5)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id   INTEGER NOT NULL
                          REFERENCES analyses(id) ON DELETE CASCADE,
            page_number   INTEGER,
            annot_subtype TEXT,
            author        TEXT,
            contents      TEXT,
            created_date  TEXT,
            modified_date TEXT,
            obj_num       INTEGER,
            obj_gen       INTEGER
        )
    """)

    # Record schema version if this is a new database or a new revision
    cur.execute("""
        SELECT MAX(schema_revision) FROM schema_version
    """)
    row = cur.fetchone()
    current_rev = row[0] if row and row[0] else 0
    if current_rev < SCHEMA_REVISION:
        cur.execute("""
            INSERT INTO schema_version
                (version, schema_revision, created_at, tool_name)
            VALUES (?, ?, ?, ?)
        """, (__version__, SCHEMA_REVISION,
              datetime.now(timezone.utc).isoformat(),
              __tool_name__))
        if session:
            session.log(f"Database schema updated to revision "
                        f"{SCHEMA_REVISION} (v{__version__})")

    conn.commit()
    return conn


def get_finding_type_id(cur, code):
    cur.execute("SELECT id FROM finding_types WHERE code = ?", (code,))
    row = cur.fetchone()
    return row[0] if row else None


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



_REF_PREFIX_RE = None


def submission_name_key(filename):
    """
    Name used to spot "same name, different content". A leading bracketed
    or parenthesised reference such as "[001.2] " or "(12) " is removed
    (exhibit/reference numbering added by the examiner), then case and
    whitespace are normalised. "[001.2] Invoice 0000123.pdf" and
    "[002.1] Invoice 0000123.pdf" therefore share a key.
    """
    global _REF_PREFIX_RE
    import re
    if _REF_PREFIX_RE is None:
        _REF_PREFIX_RE = re.compile(r"^\s*[\[\(][^\]\)]*[\]\)]\s*[-_.]*\s*")
    name = _REF_PREFIX_RE.sub("", filename or "", count=1)
    return " ".join(name.lower().split())


def _md5_and_size(path):
    try:
        h = hashlib.md5()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest(), os.path.getsize(path)
    except Exception:
        return None, None


def record_submission(conn, pdf_path, outcome, session=None,
                      analysis_id=None, duplicate_of=None, reason=None,
                      is_version=False, md5=None, size=None):
    """
    Record one submitted file and its outcome:
      'analysed'   analysis completed (analysis_id = its analysis)
      'duplicate'  byte-identical to a file already in the database, so not
                   re-analysed (analysis_id = the matching analysis,
                   duplicate_of = that file's name)
      'failed'     analysis raised an error (reason = the error)
      'not_found'  the file did not exist when its turn came
    Never raises: a recording failure must not interrupt the analysis.
    """
    try:
        if md5 is None and outcome != "not_found":
            md5, size = _md5_and_size(pdf_path)
        name = os.path.basename(pdf_path)
        conn.execute(
            """INSERT INTO submissions (session_ts, submitted_at, pdf_path,
                   pdf_filename, name_key, pdf_md5, pdf_size, is_version,
                   outcome, analysis_id, duplicate_of, reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (getattr(session, "timestamp", None),
             datetime.now(timezone.utc).isoformat(),
             os.path.abspath(pdf_path), name, submission_name_key(name),
             md5, size, 1 if is_version else 0, outcome, analysis_id,
             duplicate_of, (str(reason)[:500] if reason else None)))
        conn.commit()
    except Exception:
        pass


def record_encryption(conn, pdf_path, result, session=None,
                      analysis_id=None, md5=None, scheme=None, source=None):
    """
    Record one file's encryption outcome for the Encrypted Files report.
    `result` is the dict from pdf_forensics.passwords.try_open. The
    successful password is stored verbatim: in a forensic report the
    password is part of the evidence and the repeatable procedure.
    Never raises.
    """
    try:
        name = os.path.basename(pdf_path)
        conn.execute(
            """INSERT INTO encryption (session_ts, recorded_at, pdf_path,
                   pdf_filename, pdf_md5, is_encrypted, opened, password,
                   password_source, scheme, attempts, analysis_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (getattr(session, "timestamp", None),
             datetime.now(timezone.utc).isoformat(),
             os.path.abspath(pdf_path), name, md5,
             1 if result.get("encrypted") else 0,
             1 if result.get("opened") else 0,
             result.get("password"), (source or result.get("label")),
             scheme, result.get("attempts"), analysis_id))
        conn.commit()
    except Exception:
        pass


def check_pdf_already_analyzed(conn, pdf_path):
    """
    Check if a PDF with the same MD5 hash has already been analyzed.

    Returns (True, existing_row) if found, (False, None) otherwise.
    existing_row is a dict with keys: pdf_filename, analyzed_at, id.
    """
    pdf_md5 = hashlib.md5()
    try:
        with open(pdf_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                pdf_md5.update(chunk)
    except Exception:
        return False, None

    cur = conn.execute(
        "SELECT id, pdf_filename, analyzed_at FROM analyses "
        "WHERE pdf_md5 = ?", (pdf_md5.hexdigest(),))
    row = cur.fetchone()
    if row:
        return True, {
            "id": row[0],
            "pdf_filename": row[1],
            "analyzed_at": row[2],
            "pdf_md5": pdf_md5.hexdigest(),
        }
    return False, None



def save_timeline(conn, analysis_id, rows):
    """Store a document's timeline (see analysis/timeline.py). rows are
    (seq, revisions, category, source, field, obj_ref, raw_value,
    timezone, utc, status, issue). Replaces any earlier rows for the
    analysis."""
    if not analysis_id:
        return
    conn.execute("DELETE FROM timeline_events WHERE analysis_id = ?",
                 (analysis_id,))
    conn.executemany("""
        INSERT INTO timeline_events (analysis_id, seq, revisions, category,
            source, field, obj_ref, raw_value, timezone, utc, status, issue)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [(analysis_id,) + tuple(r) for r in rows])
    conn.commit()


# EXIF / format metadata by image MD5, shared across documents in a run, so
# a prior version does not re-parse its parent's images. Small entries;
# bounded by count.
_IMG_META_CACHE = {}
_IMG_META_CACHE_MAX = 50000


def _image_metadata_cached(md5, image_bytes, ext):
    from pdf_forensics.analysis.metadata import extract_image_metadata
    key = (md5, ext)
    if key in _IMG_META_CACHE:
        return _IMG_META_CACHE[key]
    meta = extract_image_metadata(image_bytes, ext)
    if len(_IMG_META_CACHE) >= _IMG_META_CACHE_MAX:
        _IMG_META_CACHE.clear()
    _IMG_META_CACHE[key] = meta
    return meta


def save_to_db(conn, pdf_path, total_pages, page_data,
               pdf_metadata=None, pdf_versions=None,
               store_images=True, comments=None, doc_risk=0,
               source_analysis_id=None, version_number=None):
    """Write all analysis results to the SQLite database.

    doc_risk : the document-level risk score (0..100). Per-page risk
               scores are read from each page_data entry's "page_risk"
               key (defaulting to 0 when absent).
    source_analysis_id : when this PDF is an extracted prior version,
               the analyses.id of the parent document (establishes the
               version lineage). None for originals.
    version_number : the prior-version number when this is an extracted
               version, else None.

    Returns the analyses.id of the newly inserted row.
    """
    from pdf_forensics.analysis.metadata import extract_image_metadata
    cur = conn.cursor()

    # Compute MD5 of the PDF file
    pdf_md5 = hashlib.md5()
    with open(pdf_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            pdf_md5.update(chunk)
    pdf_md5_hex = pdf_md5.hexdigest()

    cur.execute("""
        INSERT INTO analyses (pdf_filename, pdf_path, pdf_size_bytes,
                              pdf_md5, total_pages, analyzed_at,
                              doc_risk_score, source_analysis_id,
                              version_number)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        os.path.basename(pdf_path),
        os.path.abspath(pdf_path),
        os.path.getsize(pdf_path),
        pdf_md5_hex,
        total_pages,
        datetime.now(timezone.utc).isoformat(),
        int(doc_risk or 0),
        source_analysis_id,
        version_number,
    ))
    analysis_id = cur.lastrowid

    # Insert PDF metadata
    if pdf_metadata:
        for source, key, value in pdf_metadata:
            cur.execute("""
                INSERT INTO pdf_metadata (analysis_id, source, key, value)
                VALUES (?, ?, ?, ?)
            """, (analysis_id, source, key, value))

    # Insert PDF versions (%%EOF markers)
    if pdf_versions:
        for version_num, offset in pdf_versions:
            cur.execute("""
                INSERT INTO pdf_versions
                    (analysis_id, version_number, eof_offset)
                VALUES (?, ?, ?)
            """, (analysis_id, version_num, offset))

    # Insert PDF comments / annotation notes
    if comments:
        for c in comments:
            cur.execute("""
                INSERT INTO comments
                    (analysis_id, page_number, annot_subtype, author,
                     contents, created_date, modified_date,
                     obj_num, obj_gen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                analysis_id,
                c.get("page_number"),
                c.get("annot_subtype"),
                c.get("author"),
                c.get("contents"),
                c.get("created_date"),
                c.get("modified_date"),
                c.get("obj_num"),
                c.get("obj_gen"),
            ))

    ft_ids = {}
    for code in FINDING_TYPE_DEFS:
        ft_ids[code] = get_finding_type_id(cur, code)

    # One map per document (not per page): an image placed on many pages
    # is hashed, looked up and EXIF-parsed once, and its image_metadata
    # rows are written once rather than once per page.
    xref_to_image_data_id = {}
    for page_num in sorted(page_data.keys()):
        pd = page_data[page_num]

        cur.execute("""
            INSERT INTO pages (analysis_id, page_number, risk_score)
            VALUES (?, ?, ?)
        """, (analysis_id, page_num, int(pd.get("page_risk", 0) or 0)))
        page_id = cur.lastrowid

        label_to_info = pd["label_to_info"]
        transparency = pd["transparency"]

        # Insert unique image blobs into image_data (one per xref)
        for label in sorted(label_to_info.keys()):
            info = label_to_info[label]
            xref = info["xref"]

            if xref in xref_to_image_data_id:
                continue  # already stored this xref

            image_bytes = info.get("image_bytes")
            if image_bytes:
                img_md5 = hashlib.md5(image_bytes).hexdigest()
                # Store blob only if requested; always store the
                # metadata row so findings can reference the image.
                blob_to_store = (sqlite3.Binary(image_bytes)
                                 if store_images else None)
                cur.execute("""
                    INSERT OR IGNORE INTO image_data
                        (analysis_id, xref, format_ext, width_px,
                         height_px, image_bytes, byte_size, md5_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    analysis_id,
                    xref,
                    info["ext"],
                    info["width"],
                    info["height"],
                    blob_to_store,
                    len(image_bytes),
                    img_md5,
                ))
                # Retrieve the id (INSERT OR IGNORE may not set lastrowid)
                cur.execute("""
                    SELECT id FROM image_data
                    WHERE analysis_id = ? AND xref = ?
                """, (analysis_id, xref))
                row = cur.fetchone()
                image_data_id = row[0] if row else None
                xref_to_image_data_id[xref] = image_data_id

                # Extract and store image metadata (EXIF, format info)
                if image_data_id is not None:
                    img_meta = _image_metadata_cached(
                        img_md5, image_bytes, info["ext"])
                    for source, mkey, mvalue in img_meta:
                        cur.execute("""
                            INSERT INTO image_metadata
                                (image_data_id, source, key, value)
                            VALUES (?, ?, ?, ?)
                        """, (image_data_id, source, mkey, mvalue))
            else:
                xref_to_image_data_id[xref] = None

        # Insert images
        label_to_image_id = {}
        risk_scores = pd.get("risk_scores", {})
        for label in sorted(label_to_info.keys()):
            info = label_to_info[label]
            t = transparency.get(label, {})
            image_data_id = xref_to_image_data_id.get(info["xref"])
            risk = risk_scores.get(label, 0)

            cur.execute("""
                INSERT INTO images
                    (page_id, image_data_id, label,
                     z_order, opacity, blend_mode,
                     has_smask, in_transparency_group,
                     form_xobject_xref, risk_score,
                     dpi_x, dpi_y, display_w_pts, display_h_pts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                page_id,
                image_data_id,
                label,
                t.get("z_order", info.get("z_order", 0)),
                t.get("opacity", 1.0),
                t.get("blend_mode", "/Normal"),
                1 if t.get("has_smask") else 0,
                1 if t.get("in_transparency_group") else 0,
                info.get("form_xref", 0),
                risk,
                info.get("dpi_x"),
                info.get("dpi_y"),
                info.get("display_w_pts"),
                info.get("display_h_pts"),
            ))
            label_to_image_id[label] = cur.lastrowid

        # Insert findings
        for f in pd["findings"]:
            ft_id = ft_ids.get(f["type"])
            if ft_id is None:
                continue

            bbox = f.get("bbox")
            bx0, by0, bx1, by1 = (bbox if bbox and len(bbox) == 4
                                  else (None, None, None, None))
            cur.execute("""
                INSERT INTO findings
                    (page_id, finding_type_id, detail,
                     bbox_x0, bbox_y0, bbox_x1, bbox_y1, overlay_kind,
                     obj_num, obj_gen, obj_locator)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (page_id, ft_id, f["detail"],
                  bx0, by0, bx1, by1, f.get("overlay_kind"),
                  f.get("obj_num"), f.get("obj_gen"),
                  f.get("obj_locator")))
            finding_id = cur.lastrowid

            image_str = f.get("image") or ""
            labels_in_finding = [
                lbl.strip() for lbl in image_str.split("/")
            ]

            if f["type"] == "OVERLAP" and "_overlap" in f:
                ol = f["_overlap"]
                front_id = label_to_image_id.get(ol["front_label"])
                back_id = label_to_image_id.get(ol["back_label"])

                if front_id:
                    cur.execute("""
                        INSERT INTO finding_images
                            (finding_id, image_id, role)
                        VALUES (?, ?, 'front')
                    """, (finding_id, front_id))
                if back_id:
                    cur.execute("""
                        INSERT INTO finding_images
                            (finding_id, image_id, role)
                        VALUES (?, ?, 'back')
                    """, (finding_id, back_id))

                if front_id and back_id:
                    cur.execute("""
                        INSERT INTO overlap_details
                            (finding_id, front_image_id, back_image_id,
                             overlap_area_sqpts, overlap_pct,
                             front_opacity, front_blend_mode,
                             front_has_smask, concealment_assessment)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        finding_id,
                        front_id,
                        back_id,
                        ol["overlap_area"],
                        ol["overlap_pct"],
                        ol["front_opacity"],
                        ol["front_blend_mode"],
                        1 if ol["front_has_smask"] else 0,
                        ol["concealment"],
                    ))
            else:
                for lbl in labels_in_finding:
                    for sub_lbl in lbl.split(","):
                        sub_lbl = sub_lbl.strip()
                        img_id = label_to_image_id.get(sub_lbl)
                        if img_id:
                            cur.execute("""
                                INSERT INTO finding_images
                                    (finding_id, image_id, role)
                                VALUES (?, ?, 'subject')
                            """, (finding_id, img_id))

    conn.commit()
    return analysis_id
