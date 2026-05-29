# PDF Forensics Suite — Changelog

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
