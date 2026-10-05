# PDF Forensics Suite — Changelog

## v1.0.0 — Update (2026-07-09b)

### Documentation correction
- Graph guides (technical and broader): the cross-document image
  border was described as "orange (#FFA500), width 3" but the tool
  actually renders it bright red (#FA0F00, width 4) — the colour
  the examiner sees in the legend and graph. Corrected all border
  references (body text, the vis.js code snippet, manual-validation
  step) and retitled two broader-guide headings ("The Orange Border"
  -> "The Cross-Document Border"; "Red-with-Orange-Border Nodes" ->
  "High-Risk Cross-Document Nodes"). The MID risk-tier colour, which
  is genuinely amber/orange (#EF9F27), is unchanged. The broader
  guide's table of contents should be refreshed in Word (the two
  retitled headings).

## v1.0.0 — Update (2026-07-09)

### Graph: prior-version lineage handling
- Image reuse in the relationship graph is now classified by
  LINEAGE rather than raw document count. A document and the prior
  versions extracted from it form one lineage; an image shared only
  within a lineage is treated as version reuse, not cross-document
  reuse, so an expected overlap between a document and its own
  versions no longer appears as a false cross-document flag.
- Schema revision 7 adds analyses.source_analysis_id and
  analyses.version_number, recording each extracted version's parent
  and version number at analysis time (additive, idempotent
  migration). Lineage is recorded explicitly rather than inferred
  from filenames. save_to_db now returns the analysis id;
  analyze_pdf accepts and records the lineage.
- Cross-document scope groups prior versions by lineage by default
  (COUNT(DISTINCT COALESCE(source_analysis_id, id)) > 1). A toggle
  reverts to the legacy per-document count: GUI "Group prior
  versions by lineage" (on by default); CLI --separate-versions.
- Within-lineage (version) reuse is shown, not hidden: a violet
  dashed border on the image node, dashed edges for any placement in
  a prior version, and a muted-blue "(prior vN)" label on
  prior-version document nodes. This preserves the forensically
  useful case of an image present in a prior version but removed
  from the current one (a shared node reaching only into the dashed
  version subtree).
- New legend entries (Version reuse, Prior version) and a cross-doc
  tooltip clarifying it means cross-lineage. The grouping state,
  prior-version document count, and version-reuse / cross-document
  image counts are embedded in each exhibit (toolbar + printable
  cover) per the exhibit-provenance discipline.
- Graph guides (technical and broader) document the lineage grouping,
  the version-reuse visual encoding, and the toggle.

## v1.0.0 — Update (2026-07-03b)

### Triage: prior-version metadata in the Excel output
- The triage spreadsheet now includes the metadata of prior
  (incremental-update) versions, matching the coverage the HTML
  metadata report already had. For each triaged PDF that contains
  two or more %%EOF markers, every prior version is reconstructed in
  memory (byte-identical to what the version-extraction feature
  writes to disk) and scanned by the same method as the current
  version, so its metadata appears as its own row.
- A new Source column on the pdf-triage, pdf-metadata, and comments
  worksheets labels each row "Current" or "Prior v1", "Prior v2",
  etc. Prior-version rows use the filename basename_versionN.pdf, the
  same convention as the extracted-version files.
- triage_pdf was refactored into a bytes-based core (triage_pdf_bytes)
  so prior versions are scanned from memory without writing temporary
  files. A reconstruct_prior_versions() helper mirrors the existing
  extract_prior_versions() truncation logic exactly.
- Enabled by default; the CLI gains --no-prior-versions to opt out.
  Reviewer comments are also extracted per prior version.
- Getting Started guide updated to describe the Source column and
  prior-version rows.

## v1.0.0 — Update (2026-07-03)

### Documentation refresh
- All seven in-app guides brought current with the 2026-07-02 code
  changes. Getting Started notes the visual-only report run. Risk
  Scoring guides: false-positive conditions for the document-level
  detections (technical); extended document-score description, an
  unapplied-redaction entry in 4.7, a new plain-language section 4.8
  on document-record checks, and updated weight rationale (broader).
  HTML Reports guides: Incremental Updates report sections document
  the Linearized column, updated SQL, and the linearization exclusion
  rule; Document Risk Summary sections state the full document-score
  formula (page maximum + document-level weights + comment flag) and
  correct the previous comment-flag-only difference explanation.
- The standalone Technical Reference Guide was updated separately to
  Version 1.1 (July 2026) with the same content changes.

## v1.0.0 — Update (2026-07-02d)

### Per-page processing speed
- Page text is now extracted once per page instead of three times.
  A single rawdict extraction (using the library's default flag set,
  with span-level text synthesized from the per-character data) is
  shared by the annotation-overlay, text-over-text, and font-
  collection detectors. Each detector keeps a self-extraction
  fallback, so standalone use and per-detector error behaviour are
  unchanged. Shared-vs-fallback outputs verified identical by test.
- The page content stream is now parsed once per page instead of
  three times. The engine parses once and shares the operator list
  with image-placement mapping, z-order/graphics-state analysis, and
  the white-box overlay detector (each with a self-parse fallback).
  Benchmark on a 48,000-operator page: the parse workload drops
  ~3x (measured 5-9x wall-clock on the parsing portion depending on
  cache warmth); savings scale with content-stream size.
- Behaviour note: the annotation-overlay detector previously
  extracted text with only the preserve-whitespace flag; it now
  shares the default-flag extraction, which additionally preserves
  ligatures and applies the library's default MediaBox clipping.
  Effect: ligature glyphs appear unexpanded in overlap details, and
  text lying entirely outside the MediaBox (which is never rendered,
  so cannot be visually concealed by an annotation) is no longer
  considered. Detection outcomes are otherwise identical.

## v1.0.0 — Update (2026-07-02c)

### New document-level detections (analysis/doc_checks.py)
- METADATA_DATE_ANOMALY (HIGH, +25): Info dictionary ModDate precedes
  CreationDate. Dates are parsed timezone-aware; unparseable values
  produce no comparison, and comparisons that relied on assuming UTC
  for a designator-less date say so in the finding.
- METADATA_MISMATCH (MEDIUM, +15 per field): Info dictionary and XMP
  stream disagree on Producer, CreationDate, or ModDate. Dates are
  compared as instants, so equivalent times in different timezones do
  not false-positive.
- VERSION_MISMATCH (INFO, +5): header %PDF-N.M differs from the
  Document Catalog /Version entry.
- XMP_ID_ANOMALY (INFO, +5): xmpMM:DocumentID equals xmpMM:InstanceID.
- MIXED_CAMERA (MEDIUM, +15): images carry EXIF Make/Model from two or
  more distinct capture devices (guide 8.3 previously required this
  comparison to be done manually). EXIF-less images are not counted
  either way and the finding states how many images were assessable.
- REDACT_UNAPPLIED (HIGH, +35, page-level): /Redact annotation present
  but not applied — the covered content remains recoverable in the
  file. One finding per annotation with rect and object locator.
- SIGNED_THEN_MODIFIED (HIGH, +35): file bytes extend beyond the last
  digital signature's /ByteRange coverage — content was appended
  after signing. Structural check only (no cryptographic validation,
  which remains out of scope); a signature whose ByteRange cannot be
  evaluated is reported as explicitly INDETERMINATE.
- STRUCTURAL_WARNING (INFO, +5): the qpdf structural check reported
  warnings (stream /Length discrepancies, damaged xref data, etc.);
  up to ten are listed in the finding, all in the session log.
- Document-level findings add their weights directly to the document
  risk score (doc_risk = MIN(MAX(page score) + SUM(document-level
  weights) + comment flag, 100)) and are stored attached to page 1,
  identified as document-level in their detail text and excluded from
  page 1's page-level score by construction. The Document Risk
  Summary report's Contributing Findings column includes the new
  codes. New finding types are seeded with INSERT OR IGNORE, so
  existing databases gain them on next open (no schema change).

### GUI fix
- The visual overlay report can now be run on its own from the HTML
  report menu. Previously at least one standard report had to be
  selected even when only the visual report was wanted; the validation
  now requires a standard report OR the visual report, and the status
  line correctly reports success for a visual-only run.

## v1.0.0 — Update (2026-07-02b)

### Graph exhibit provenance and scope transparency
- Graph HTML files now self-describe. Each generated graph embeds its
  scope name, the scope definition, the generation timestamp, and
  node/edge/image/document counts. The scope appears as a badge in the
  toolbar (hover for the definition and generation time) and on the
  printable report cover, whose title also names the scope.
- The "Generated" timestamp on the printable cover is now captured at
  file-generation time and embedded in the exhibit. Previously it was
  computed by JavaScript when the file was VIEWED, so every viewing of
  an exhibit displayed a fresh "generated" time — misleading for a
  file that may be presented in proceedings.
- The GUI now reports when two selected scopes select the identical
  dataset for a database (the scopes are nested filters, so this is
  legitimate — e.g. All Placements and Cross-Page coincide when no
  image repeats solely within a single page). The coincidence is
  stated in the generation log and session log instead of being left
  to be discovered by hashing the output files.
- Because the scope is embedded, identical datasets no longer produce
  byte-identical files across scopes; each file identifies itself.
- Graph guides (technical and broader) now explain the nested-scope
  relationship and the embedded provenance.

## v1.0.0 — Update (2026-07-02)

### Detection accuracy fixes
- Linearization-aware incremental update analysis. Linearized
  (web-optimized) PDFs legitimately carry two %%EOF markers; the file
  head is now checked for the /Linearized marker, the state is recorded
  in pdf_metadata (True/False/indeterminate), and the Incremental
  Updates report excludes linearized files with exactly two markers and
  shows a Linearized column. Previously every web-optimized PDF was a
  false positive in this report.
- Form XObject analysis rewritten with correct graphics-state tracking.
  The CTM is now composed through q/Q/cm (previously each cm operator
  was tested in isolation, mis-locating images under nested transforms
  and flagging matrices unrelated to any image), and clipping paths are
  carried as part of the saved/restored graphics state. BBOX_CROP is
  evaluated per image Do using the composed placement geometry.
- EXPLICIT_CLIP is now geometry-aware. A rectangular clip that fully
  contains the image is no longer reported (it conceals nothing); a
  cropping clip reports the hidden percentage; and non-rectangular clip
  paths — previously not reported at all due to a rect-only code path —
  are reported with an explicit note that the extent of concealment is
  undetermined and requires manual review.
- White-box overlay detection: fill colour is tracked correctly. CMYK
  white (0 0 0 0 k) and scn-set colours are now recognized; SC/SCN
  (stroking-colour operators) are no longer misread as fill; the fill
  colour is saved/restored with q/Q; and setting a colour space (cs)
  conservatively resets the colour to non-white.
- Overlap detection uses exact rotated footprints. When one or both
  images are rotated, the overlap is computed by convex-polygon
  intersection of the transformed placement rectangles, eliminating the
  documented false positives from axis-aligned bounding boxes on
  rotated content. Where a transform cannot be recovered, the finding
  explicitly states its figures are an upper bound requiring manual
  verification.
- Findings now state uncertainty explicitly wherever geometry cannot be
  fully determined (rotated placements assessed by bounding box,
  non-rectangular clips, unresolved XObject subtypes).
- Documentation aligned with implemented behaviour: the Technical
  Reference Guide and the Risk Scoring Technical guide now state the
  actual thresholds (HIDDEN_THRESHOLD_PTS = 0.5; text-over-text overlap
  ratio 0.55 with 1.5-point same-glyph exclusion), the sixteen-report
  count, schema revision 6, and the new clip/overlap semantics.

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
