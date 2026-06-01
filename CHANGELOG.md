# PDF Forensics Suite — Changelog

## v1.0.0 — Update (2026-06-01)

### Visual Overlay Report — Before/After Reveal
- The visual overlay report can now show, for recoverable overlays, what
  is hidden beneath them. Where the underlying content still exists in the
  file (white-box masks, text-over-text, and opaque annotations), the page
  is re-rendered with the overlay suppressed and offered alongside the
  normal view via a toggle.
- Two independent reveal modes are provided:
  - A page-level toggle on each full page image ("As displayed" vs
    "Overlays removed") that suppresses every overlay on that page at once.
  - A per-finding toggle on each detail card ("As displayed" vs
    "Hidden beneath") that suppresses only that one flagged overlay.
- Suppression is performed at the content-stream level by the new
  `reports/reveal.py` module, which re-parses the page content stream and
  removes the operators that paint the overlay (the white rectangle and the
  text drawn on top, the overlying glyphs, or the annotation), exposing the
  original content that remained underneath. The original underlying
  content is never modified.
- Text-over-text reveals are labelled as best-effort reconstructions.
- When printed, both states are shown stacked with captions so a filed PDF
  preserves the comparison.

## v1.0.0 — Update (2026-05-31)

### Report Branding & Agency Information
- New "Branding / agency info" dialog on the main menu to configure
  the agency logo, investigator name / email / phone, agency name,
  unit name, agency address, and an optional classification caveat
- Settings persist to `branding.json` in the application folder
  (falls back to the home directory if that folder is not writable)
  and are applied automatically by both the GUI and the CLI
- HTML reports now carry a three-column banner: report title (left),
  case/agency information (centre), and the agency logo (right)
- The visual overlay report uses the same banner
- Graph reports now open with a professional cover page (agency name
  and unit, logo, case/investigator details, and a generated-on /
  database-integrity strip), printed as its own page
- Optional configurable classification strip (e.g. "Law Enforcement
  Sensitive") across the top of every report and the graph cover
- Per-page print footer (case number, investigator, database MD5) on
  HTML reports, the visual report, and graph reports; repeats on each
  page in Chromium-based browsers
- Page numbers ("Page X of Y") via the CSS `@page` margin box
  (rendered by Firefox and PDF print engines)
- Database MD5 shown on the graph cover and in report footers for
  chain-of-custody
- New cached `compute_file_md5()` helper so the evidence database is
  hashed once per session rather than once per report

### Output Folder Change
- Extracted prior PDF versions are now written to a `pdf_versions/`
  sub-folder (each file's versions under `{name}_versions/`) instead
  of inside `extracted_images/`, for a clearer folder layout

## v1.0.0 — Update (2026-05-29)

### Text Overlay Detection
- Added three independent text-overlay detectors, each catching a
  different document-alteration technique:
  - `check_text_overlays` — annotation-based overlays (FreeText,
    Widget, Square, Redact annotations with opaque backgrounds over
    existing page text)
  - `check_content_stream_text_overlay` — white (or near-white)
    rectangles painted over content in the page content stream,
    followed by replacement text
  - `check_text_over_text` — new text painted directly over existing
    text with no masking rectangle (detected via per-character bounding
    box overlap from PyMuPDF rawdict; excludes faux-bold and drop-shadow
    rendering effects)
- New `TEXT_OVERLAY` finding type (HIGH severity, risk weight 35)
- New report 13: "Text Overlay Detection"
- Findings now record a bounding box (`bbox_x0/y0/x1/y1`) and
  `overlay_kind` to support visual reporting (schema revision 4,
  auto-migrated)

### Visual Overlay Report (new)
- New self-contained HTML report that visually shows detected overlays
  to a non-technical reader:
  - Full annotated page images with each detected overlay highlighted
    in a colour-coded box and numbered marker (red = text-over-text,
    orange = white-box masking, blue = annotation)
  - Per-finding detail cards with a high-resolution zoomed crop of the
    affected region and a plain-language description
  - Legend, intro caveats, and print-optimised CSS for browser
    "Print to PDF"
- Available via the GUI Reports panel ("Generate visual overlay
  report" checkbox, on by default) and the CLI (`report --visual`)
- Gracefully degrades to a text-only section when a source PDF cannot
  be located

### Fixes
- Triage Excel output now saved to the `reports/` subfolder instead of
  `extracted_images/`
- Fixed crash ("'NoneType' object has no attribute 'split'") when
  scoring or saving findings that are not image-specific (e.g.
  TEXT_OVERLAY); `f.get("image")` now coerces `None` to an empty string
  in both `analysis/risk.py` and `database.py`

## v1.0.0 (2026-04-19)

### Initial Release — Unified Package

Merged standalone PDF forensics analysis and graph analysis scripts
into a single unified toolkit, refactored into a Python package.

#### Package Structure
- 22 modules across 5 subpackages (`analysis/`, `graph/`, `reports/`,
  `gui/`, plus core)
- Thin `pdf_forensics.py` launcher script for backwards compatibility
- `python -m pdf_forensics` entry point
- Each module is 50–450 lines (largest is `graph/visualization.py`
  at ~1,670 lines for the JavaScript injection)

#### Case & Session Management
- Case number prompted at launch; displayed in GUI header
- Per-case output folder structure relative to database location:
  `logs/`, `graph_reports/`, `reports/`, `extracted_images/`
- Filename convention: `{case}_{kind}_{timestamp}.{ext}`
- Single timestamp per session shared across all outputs
- Session switching with confirmation dialog; clears state cleanly
- Last-used case persisted in `~/.pdf_forensics_config.json`

#### Forensic Logging
- Per-session timestamped log file in `logs/` subfolder
- Environment capture: tool version, Python, OS, library versions
- Per-PDF detail: file path, MD5, size, results, error tracebacks
- Session summary: counts, duration, output file list, database MD5

#### Duplicate PDF Detection
- PDFs already in the database (by MD5 match) are flagged
- GUI: dialog asking whether to re-process
- CLI: skipped by default; `--force` flag to override

#### PDF Analysis Engine
- Image manipulation detection: BBOX_CROP, EXPLICIT_CLIP, OVERLAP,
  OFFPAGE, SOFT_MASK, IMAGE_SMASK, COMPLEX_TRANSFORM, PARSE_ERROR
- PDF metadata extraction (Info Dict, XMP, Catalog)
- Prior version detection via %%EOF markers
- Image metadata extraction (EXIF, GPS via Pillow)
- MD5 hashing of PDFs and each unique image
- Per-image risk scoring (0–100) based on finding types/severity
- Per-PDF error handling: one bad file doesn't crash the batch

#### Graph Analysis Engine
- Interactive HTML visualizations via vis.js / pyvis
- Three duplicate-detection scopes: all placements, cross-page,
  cross-document
- Embedded image thumbnails in node tooltips
- Risk-based node coloring: green (low), amber (mid), red (high)
- Orange border for cross-document image reuse
- Right-click context menu: exclude images/documents, add to report
- Excluded items panel with tabbed Images/Documents views
- Printable HTML report generation from selected images
- Document exclusion with orphan cleanup
- GUI: checkboxes to generate multiple scopes in one run

#### Unified GUI
- Adobe Acrobat-inspired dark theme (centralized in `gui/theme.py`)
- Main menu with three module cards: Analysis, Graph, Reports
- Path pre-population: case entry → directory picker → DB, output,
  graph paths all auto-filled
- PDF list import from text files (`--pdf-list` CLI, GUI button)
- Reports sub-menu placeholder for future release

#### CLI
- Subcommands: `analyze`, `graph`
- `--pdf-list` / `-l` for bulk file ingestion from text files
- `--case` for case number assignment
- `--force` to override duplicate detection
- `--version` flag
- GUI launches by default; `--gui` for explicit mode

#### Database Schema (Revision 2)
- `schema_version` table for version tracking with revision history
- `risk_score` column on `images` table
- `OFFPAGE` finding type
- Automatic schema migration for older databases
- `check_pdf_already_analyzed()` for duplicate detection
