# PDF Forensics Suite — Changelog

## v1.0.0 — Update (2026-06-23)

### Document-level risk scoring and Document Risk Summary report
- New document-level risk dimension. Findings that describe a page or the
  document as a whole rather than a single image — text overlays
  (TEXT_OVERLAY) and font anomalies (FONT_ANOMALY) — are now scored
  separately from per-image risk, alongside a small informational flag for
  the presence of reviewer comments. Each finding type contributes to
  exactly one dimension, so nothing is double-counted and nothing is
  detected-but-unscored.
- Scoring (analysis/risk.py): added compute_document_risk(), producing a
  per-page score (sum of document-level finding weights, capped at 100) and
  a document score (the maximum page score plus the comment flag, capped at
  100). TEXT_OVERLAY (+35) and FONT_ANOMALY (+15) moved out of the per-image
  weight table into DOC_RISK_WEIGHTS; COMMENT_RISK_WEIGHT is +5. Per-image
  scores are unchanged.
- Schema revision 6: added analyses.doc_risk_score and pages.risk_score
  (both INTEGER DEFAULT 0). The migration is additive and idempotent;
  opening an older database upgrades it in place with no data loss.
- New "Document Risk Summary" report (report id document_risk): one row per
  analyzed PDF, ranked by document risk, showing the highest page risk, the
  contributing document-level finding types, and the comment count. It leads
  the Document Overview & Provenance report group.
- Documentation: the Risk Scoring guides (technical and broader) gain a
  section on the document-level dimension and its weights; the HTML Reports
  guides (technical and broader) document the new report.

## v1.0.0 — Update (2026-06-22b)

### Font consistency report, report reorganization, tooltips, progress bar
- New "Font Consistency Analysis" report (ANAL-03): a document-level
  detector flags text spans whose font is inconsistent with the
  document's dominant body font, an independent indicator of in-place
  edits. Added a FONT_ANOMALY finding type (Medium severity); the report
  is selected by default in the Reports menu.
- The Reports list is reorganized into a logical, workflow-based order
  grouped under headings: Document Overview & Provenance, Manipulation &
  Alteration, Image Analysis, and Cross-Document & Review. The Visual
  Report panel moves down to accommodate the grouped list.
- Hover tooltips with brief descriptions were added to every report in the
  Reports menu, to the graph scope options, and to the analysis options in
  the PDF analysis menu.
- GUI-03: batch analysis and triage now show a determinate progress bar
  with a per-file status label (file N of M, and current page), replacing
  the text-only progress indication.
- Fixed the Reports window being too short for the grouped report list:
  the window is taller, the Visual Report panel's description moved to a
  hover tooltip to reclaim space, and window sizes are now clamped to the
  display so a tall window never extends off smaller laptop screens.

## v1.0.0 — Update (2026-06-22)

### Add a folder of PDFs
- The PDF files panel gains an "Add folder" button. After choosing a
  folder, a Yes / No / Cancel prompt asks whether to search subfolders
  recursively (Yes = this folder and all subfolders, No = this folder
  only, Cancel = add nothing). Discovered PDFs are added to the list,
  de-duplicated against entries already present, with a short summary of
  how many were added or skipped.
- The PDF files button row now uses an equal-weight grid so all five
  buttons share the panel width evenly and cannot be clipped, and the
  analysis window / left panel were widened to fit the row comfortably.

## v1.0.0 — Update (2026-06-19)

### Licensing, authorship, and disclaimers (release prep)
- Added the Apache License 2.0 full text as `LICENSE` at the repository
  root, and a standard `NOTICE` file identifying the application, copyright
  holder, and year.
- Added `README.md` at the repository root with project description,
  install/usage instructions, an Apache 2.0 license badge/section, a link
  to `LICENSE`/`NOTICE`, the medium-form disclaimer, and the author/contact
  block.
- New `pdf_forensics/disclaimers.py` holds the approved, verbatim
  disclaimer and authorship text shared across the suite.
- GUI: on first launch the short disclaimer is shown as a blocking
  acknowledgment the user must accept to proceed; the acknowledgment is
  remembered, and on every launch thereafter a permanent reminder line
  ("Use at your own risk — see About for full disclaimer") appears in the
  status bar and opens the full disclaimer when clicked.
- GUI: the Help → About dialog now shows the full disclaimer and the
  author / contact / repository / license information, with the environment
  diagnostics retained below it (now a scrollable dialog).
- CLI: a short disclaimer banner is printed to stderr at the start of a
  command run (suppressed for `--version`, `--help`, `--quiet`, and the
  report `--list` listing) so headless users see it too.

## v1.0.0 — Update (2026-06-04)

### Comments, identity logging, validation locators (schema rev 5)
- Log files now record the agency name, unit name, and investigator
  (name and email) from the branding config alongside the case number,
  in both the session header and the closing summary.
- Excel triage workbook: the "pdf-metadata" sheet is now frozen at B2 so
  it matches the "pdf-triage" sheet (header row + filename column).
- Excel triage workbook: a new "comments" worksheet lists reviewer
  comments / markup annotations extracted from the examined PDFs, with
  columns Filename, Path, Page, Type, Author, Date/Time, Created,
  Modified, Comment, and Object (the PDF object number, for validation).
  Frozen at B2. The sheet is omitted entirely if no comments are found in
  any examined PDF.
- New "Document Comments" HTML report listing the same extracted comments.
- The Text Overlay Detection and Manipulation Detail reports now include an
  "Object / Stream (for validation)" column identifying where the flagged
  overlay lives: the annotation object number for annotation overlays, or
  the page content-stream object number (with a note that the overlying
  glyphs may be nested in a Form XObject) for content-stream overlays. An
  examiner can use this to validate findings in peepdf / qpdf / mutool.

### Database schema — revision 5
- Added a `comments` table (page, subtype, author, contents, creation and
  modification dates, object/generation number), linked to `analyses`.
- Added `obj_num`, `obj_gen`, and `obj_locator` columns to `findings` to
  record where each overlay finding can be validated in the source file.
- Existing rev-4 databases are migrated automatically (new columns and the
  comments table are added in place).

## v1.0.0 — Update (2026-06-01b)

### Menu / GUI refinements
- Changing the case number now always prompts for an output folder (the
  user may pick an existing folder or create a new one), instead of
  silently reusing the previous case's folder and database. The processing
  log window is also cleared, since a new case begins a fresh session.
- The header on every menu now shows the agency name, unit name, and
  investigator name alongside the case number, so the operator can confirm
  at a glance that the stored identity details are theirs before running
  anything. Missing fields are shown in amber as a prompt to set them, and
  the header updates immediately after branding is edited.
- The "Select reports" list is now laid out in two columns so the full
  list (and the controls beneath it) stays visible on smaller laptop
  screens.

## v1.0.0 — Update (2026-06-01)

### Visual Overlay Report — Before/After Reveal
- The visual overlay report can now show, for recoverable overlays, what is
  hidden beneath them. The page (or an individual region) is re-rendered
  with the overlay suppressed and offered alongside the normal view via a
  toggle.
- Two independent reveal modes are provided:
  - A page-level toggle on each full page image ("As displayed" vs
    "Overlays removed") that suppresses every recoverable overlay on the
    page at once.
  - A per-finding toggle on each detail card ("As displayed" vs
    "Hidden beneath") that suppresses only that one flagged overlay.
- Suppression is performed by the new `reports/reveal.py` module. It handles
  the common real-world case (e.g. PDFium-edited files) where an alteration
  is composited on top of the original through deeply nested Form XObjects
  as a TWO-part construct: a patch (a white rectangle, or one or more
  vector/image patch forms) that hides the original glyphs, plus forged text
  drawn over the patch. The module walks the entire content tree (page
  stream and every nested form) in draw order, then for each flagged region
  suppresses the whole edit group — patch and forged text together — at the
  container level, exposing the untouched original beneath. Simpler inline
  overlays (a masking rectangle drawn directly in a stream, or text painted
  over text without nesting) are handled as a fallback. The original
  underlying content is never modified.
- Evidentiary safety: if the underlying content for a region cannot be
  cleanly isolated from legitimate co-located content, the reveal is SKIPPED
  for that finding rather than shown partially. No toggle is offered for
  such findings and the detail card is labelled accordingly; the detection
  itself still stands. Hairline fills that the detector flags as "white box"
  but that mask no text (e.g. separator rules) are likewise skipped.
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
