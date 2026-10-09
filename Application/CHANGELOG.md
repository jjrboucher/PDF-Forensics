# PDF Forensics Suite — Changelog

**Current build: 2026-10-09** · app version 1.0.0 (pre-launch, not bumped until public release) · schema revision 8. Update this line and `BUILD_DATE` in `pdf_forensics/__init__.py` when cutting a new internal build. Dated entries below record when each change was made and are left as historical record.

## v1.0.0 — Update (2026-10-09)

### PDF selection lists (From list, -l / --pdf-list)
- One shared reader (pdf_forensics/pathlist.py) for the GUI From list
  button and the command-line --pdf-list option of analyze and triage.
- Quoted paths now load. File Explorer's "Copy as path" wraps each path
  in quotation marks; these (and typographic quotes) are removed.
  Previously every quoted line was counted as not found.
- Text encoding is detected from the file: UTF-8 with or without a
  byte-order mark, UTF-16 (e.g. Excel "Unicode Text"), or the Windows
  legacy encoding. Previously the list was always read in the Windows
  legacy encoding, so paths with accented characters in a UTF-8 list (the
  current Notepad default) were not found, and UTF-16 lists failed.
- A line copied from several spreadsheet cells (tab-separated) is
  accepted: the first cell that is an existing file is used.
- Duplicates are detected regardless of slashes or letter case.
- Paths not found are listed by name (GUI message and console), not just
  counted, and every one is written to the session log.
- The session log records each list loaded: its path and MD5, the
  encoding detected, and the counts added, ignored and not found.

### Disclaimer acknowledgement record
- The acknowledgement now records when it was given (with time zone),
  the Windows user, the computer, the disclaimer version (first 12 hex
  characters of the SHA-256 of the disclaimer text shown) and the
  application version and build. Previously only a true/false flag was
  stored.
- Every session log header states the acknowledgement on record, or
  that none is on record (command-line runs display the disclaimer but
  do not ask for acknowledgement).
- Users are asked again if the disclaimer wording changes. Users who
  acknowledged under the old true/false flag are asked once more so that
  a record is created; the dialog explains why.

### Documentation
- Getting Started section 3 (acknowledgement record) and section 4 (From
  list: quotes, encodings and spreadsheet cells accepted; missing paths
  shown and logged; the "without quotation marks" caveat removed).
  Technical Reference Guide section 13.1: the acknowledgement and
  selection-list records. All documents now state build 2026-10-09.

## v1.0.0 — Update (2026-10-08i)

### Getting Started guide
- Section 3: the disclaimer acknowledgement is stored in the user’s
  .pdf_forensics_config.json, so it is shown once per Windows user
  account, not once per computer.
- Section 4: documents the existing "From list" button (one full path per
  line; blank and # lines ignored; duplicates added once; missing paths
  counted) and the triage-first workflow: triage everything, copy the
  triage spreadsheet’s Path column for the files that warrant full
  analysis into a text file, load it with From list.
- Section 6: the command-line -l / --pdf-list option for analyze and
  triage.

## v1.0.0 — Update (2026-10-08h)

### Documentation brought in sync with build 2026-10-08
- Every guide now states on its cover the application version and build
  it applies to ("Applies to PDF Forensics Suite v1.0.0, build
  2026-10-08"), dated October 8, 2026. The standalone Technical Reference
  Guide is revised to Version 1.2 and its running footer, which still read
  "v1.0 — June 2026", now carries the version and build.
- HTML Reports (technical): report count corrected to twenty; new
  sections 2.16-2.20 for Text Overlay Detection, Font Consistency
  Analysis, Document Comments, Concealment Overview and Duplicate
  Submissions, with SQL and columns taken from the report definitions; new
  chapter 3 (Visual Overlay Report, Document Risk Overview spreadsheet,
  case index, submitted-files record). Later chapters renumbered.
- HTML Reports (plain language): counts corrected (the guide said both
  sixteen and eighteen); overview table extended from 12 to 20 reports;
  plain-language sections for the five reports above and a new chapter on
  the visual report, risk spreadsheet, case index and file accounting.
- Getting Started: identical-copy handling, the run summary and Copies
  counter, the case index as the starting point, and Copy path.
- Risk Scoring (technical): how overlays are counted (a white box with
  painted text scores once; stacked annotations score separately); schema
  sections for revision 7 (lineage columns) and revision 8 (submissions).
  Risk Scoring (plain language): "one change is counted once".
- Graph Reports (both): graphs appear in the case index, which refreshes
  after each graph run; each graph records its build.
- Technical Reference Guide: architecture table (schema revision 8, twenty
  reports, reveal.py role, new rows for visual.py, case_index.py and
  risk_overview.py); 7.1.1 stacking rule and /Stamp; 7.2.1 white-box
  consolidation; 7.3.2 worked example corrected (threshold 0.55, one
  finding per cluster; it said 0.8 and one per pair); 7.4 rewritten (it
  described colour-coded boxes, zoomed crops and a before/after toggle);
  10.2.2 counting note; 13.1-13.3 build date, submitted-files record and
  output manifest; 15.6-15.9 quick-start steps updated.

### Application text
- The Text Overlay Detection report described itself as covering only
  annotations with an opaque background. Its description (shown in the
  report header and on the case index) now covers all three kinds,
  including stacked annotations and white boxes reported once per box.

### Remaining step
- Tables of contents must be refreshed in Word (right-click the table of
  contents, Update Field, Update entire table) for the new and renumbered
  sections to appear in them.

## v1.0.0 — Update (2026-10-08g)

### Every submitted file is now accounted for (schema revision 8)
- Problem: with "Skip PDFs already in the database" on (the default), a
  file byte-identical to one already analysed was skipped with only an
  on-screen note. It was not written to the session log, not counted in
  the run summary and not recorded in the database, so the submitted
  filename appeared nowhere in the case record. In one case, 12 files
  were submitted, 6 were identical copies, and the case index reported
  "Documents analysed: 10" (6 documents plus 4 prior versions) with no
  trace of the copies.
- New submissions table records every file submitted for analysis with
  its outcome: analysed; identical copy of a file already analysed (with
  the file it matches); failed (with the error); or not found. Recorded
  in the GUI and command line, for original files and prior versions.
- Session log: each skipped copy is logged with the file it matches, and
  each run ends with a summary line, e.g. "12 submitted: 6 analysed, 6
  skipped as identical copies of files already analysed, 0 failed; plus
  4 prior version(s) extracted and analysed". The GUI run summary uses
  the same wording and gains a "Copies" counter.
- Case index Overview: "Documents analysed" is replaced by "Submitted
  files" (the reconciliation above, with an expandable list of every
  submitted file, its outcome and MD5) and "Analyses in database" (e.g.
  "10 (6 submitted documents + 4 prior versions)"). Databases analysed
  before this build show the analyses breakdown and state that submitted
  files were not recorded.
- New report: Duplicate Submissions (Cross-Document & Review). Same
  content, different name: byte-identical files submitted under
  different filenames. Same name, different content: files whose names
  match once a leading reference such as "[008.1]" is ignored but whose
  content differs. Prior versions are excluded. On a database analysed
  before this build it shows an explanatory row rather than an empty
  table, so it cannot be read as "no duplicates".
- Existing databases gain the (empty) submissions table on next open;
  re-run the analysis to record submissions for an earlier batch.

## v1.0.0 — Update (2026-10-08f)

### Case index: Copy path instructions
- The Copy path note and tooltip no longer suggest pasting into Excel’s
  File > Open dialog. In testing, a pasted full file path failed there
  ("You can’t open this location using this program"), while Win+R and
  the File Explorer address bar both opened the original file. The note
  now names only those two.

## v1.0.0 — Update (2026-10-08e)

### Case index: spreadsheets and databases
- Clicking a spreadsheet in the case index prompted to save it instead of
  opening Excel. Browsers will not launch desktop applications from a web
  page; they can only download file types they cannot display. Setting the
  browser to "always open" .xlsx files is not a fix for case work: Chrome
  and Edge open a copy saved to the Downloads folder, not the original.
- Spreadsheets (.xlsx/.xls/.csv) and databases (.db) now show a "Copy path"
  button instead of a link, with a note explaining why. The copied full
  path can be pasted into Excel (File > Open), the File Explorer address
  bar or Win+R to open the original file in place. The path is worked out
  when clicked, from the index’s own location, so it stays correct if the
  case folder is moved or copied; Windows drive, network share (UNC) and
  macOS/Linux paths are handled. Logs keep their Open link and also get
  Copy path. HTML reports, PDFs and image folders open in the browser as
  before.

## v1.0.0 — Update (2026-10-08d)

### Case index at the root of the case folder
- The report index is replaced by a case index, {case}_index.html, at the
  root of the case folder (next to the databases). It links to every
  output for the case: forensic reports, the visual overlay report,
  relationship graphs, the triage and risk-overview spreadsheets,
  extracted images, prior versions, session logs and databases.
  Previously the index lived in reports/ and covered only the catalogue
  reports, graphs and the risk overview; the visual overlay report and
  triage spreadsheet were missing from it.
- Layout: one self-contained HTML file with a sidebar menu (Overview,
  Forensic Reports, Visual & Graphs, Spreadsheets, Extracted Material,
  Logs & Provenance). No frames, server or external libraries; works from
  local disk or a zipped folder. Each section has its own address
  (#reports etc.). Reports open in a new tab as standalone exhibits.
- Outputs are grouped by the analysis database they came from, read from
  the file itself (so a report generated in a later session is filed
  under the database it was built from). The latest database is shown by
  default with a selector for earlier ones. Each output shows the build
  that produced it, and the overview warns when one database’s outputs
  come from more than one build. Outputs whose database is not in the
  folder are listed separately.
- Output manifest: size and MD5 of each database, report, graph,
  spreadsheet, log and prior version at the time the index was built.
  Extracted images are counted per folder, not hashed individually.
  Hashes are cached (.pdf_forensics_index_cache.json) by size and
  modification time so unchanged files are not re-hashed.
- The index is rebuilt automatically after every operation that writes to
  the case folder: analysis, triage, HTML reports and graphs, in both the
  GUI and the command line, through one function (refresh_case_index)
  that never interrupts the operation if it fails.
- Ordering and "Generated" times use the session timestamp in each
  filename, which survives copying the case folder (file modification
  times do not).
- Session logs now record the build ("Build: YYYY-MM-DD") in their header,
  and the visual overlay report now states its build like every other
  report. The visual report filename is now "visual-overlays" from both
  the GUI and the command line (the command line used "visual_overlays").
- reports/index_page.py removed; any {case}_index.html left in reports/ by
  an earlier build is removed when the case index is written.

## v1.0.0 — Update (2026-10-08c)

### Report index: always current, one file
- Removed the "Rebuild index" button from the HTML Reports tab. It was
  redundant (the index is rebuilt automatically at the end of every report
  run) and it pushed the visual-report option out of view in the window.
- The index is now also refreshed automatically after graph generation
  (GUI and CLI), since it lists graphs under "Other Artifacts". This was
  the one case the button covered.
- The index is written to a single stable file, {case}_index.html, and
  overwritten on each refresh. Previously each rebuild wrote a new
  timestamped file, so the reports folder accumulated several indexes.
- When not told which Document Risk Overview spreadsheet to link, the
  index links the newest one in the reports folder.

## v1.0.0 — Update (2026-10-08b)

### Visual overlay report: white-box alterations shown step by step
- A white-box alteration is still counted as ONE finding (database, risk
  score and tabular reports are unchanged), but the visual report now
  shows its component edits as separate, toggleable steps: the white box
  itself, then each line of text painted on it, labelled 1a, 1b, 1c...
  under an "Alteration 1" heading. Each painted line is labelled with its
  text where the font encoding allows (e.g. "BANK : HUNTINGTON NATIONAL
  BANK"); otherwise it is labelled "Painted text" with a note.
  Previously the box and its text were a single layer, so the report
  could only show the final page or the original, not the painted text.
- This lets the examiner see every state: the original; the blank box
  hiding it; the painted text alone over the original (box unticked);
  any single line on the box; and the final page.
- How the layers are built: the box layer is the box rendered on its own
  compared with the original; each text layer is the box plus that line
  compared with the box alone. Measuring text against the box captures
  painted glyphs completely, including where they sit directly on top of
  original text of the same colour. The existing self-check (all layers
  must reproduce the page as received) still applies.
- reveal.py: new white_box_components() identifies the fill operations
  and the painted-text operations of an inline white box, grouping the
  text into lines; build_revealed_pdf_bytes() gains keep_ops to leave
  chosen operations in place. Operations are identified by stream
  position in walk order, which is stable across separate opens. White
  boxes wrapped in a container Form XObject together with their text are
  still shown as a single layer.

### Documentation (queued, not yet updated)
- Section 7.4 of the Technical Reference Guide must also describe the
  step-by-step display of white-box alterations.

## v1.0.0 — Update (2026-10-08)

### Visual overlay report: correct rendering of white-box alterations

A white box drawn over original text with new text painted on it was
rendered incorrectly: the "all overlays shown" view did not match the
page as opened in a PDF viewer, and the "all removed" view deleted
genuine original text. Three causes, three fixes.

- One alteration was reported as many. Text extraction still returns the
  original glyphs hidden under a white box, so the text-over-text detector
  also fired on the new text, and its 25-pt clustering split one replaced
  block into many findings (one real case: 1 white box + 11
  text-over-text). New merge_text_over_white_box() folds any
  text-over-text cluster with >= 80% of its area inside a white box into
  that single white-box finding, preserving the original-vs-painted glyph
  samples in its detail. Applied in the analysis engine (so the database,
  Text Overlay report, Dossier, Concealment Overview and risk score count
  one edit) and again in the visual report (so databases analysed before
  this build also render correctly).
  NOTE: document risk scores change for affected files on re-analysis
  (e.g. a page previously capped at 100 by many duplicate TEXT_OVERLAY
  findings now scores 35 for one white-box alteration). This is a
  correction. Re-analyse to update counts and scores.
- The text-over-text removal deleted genuine text. reveal._decide_text_inline
  kept only the earliest-drawn text in a region and dropped everything
  later, regardless of source, so multi-line regions lost original lines.
  It now treats the stream (page content or Form XObject) that drew the
  earliest text as the underlying layer, keeps all of its text, and drops
  only text from a different stream drawn after it. When all text in a
  region comes from one stream it skips the region and reports it as
  skipped rather than guessing.
- Unverified reconstructions were shown as fact. The reveal step reports a
  destructive removal as a success, so a per-overlay "isolated" flag could
  not catch this. Replaced with a self-check: the base plus all overlay
  layers must reproduce the page as received (within the overlay areas).
  If it does not, the page is shown exactly as received, the overlay
  toggles are disabled, and the reason is stated on the page. When it does,
  the page renders as layers as before, and with every overlay ticked the
  as-received render itself is displayed, so the opening view always
  matches what a PDF viewer shows.
- Layer isolation now measures pixel change by per-channel maximum rather
  than luminance; luminance under-weighted blue, so e.g. dark-blue text
  painted over black text could be dropped from its layer.

### Visual overlay report: markers
- New "Show numbers & lines" checkbox per page hides every badge, anchor
  dot and leader line, to view (or print) the page unobstructed.
- Unticking an overlay now also hides its leader line (previously only the
  badge was hidden, leaving a stray line on the page).
- Printing now shows the page exactly as toggled on screen (a print rule
  that forced every overlay layer visible was removed).

### Documentation (not yet updated; queued)
- Technical Reference Guide section 7.4 still describes colour-coded boxes
  drawn on the page, zoomed crops and a before/after toggle; the report now
  uses verified per-overlay layers, toggles and draggable badges.
- The in-app HTML Reports guides do not describe the visual overlay report.

## v1.0.0 — Update (2026-10-06d)

### Report index page, Concealment Overview, and risk overview sheet
- New Report Index page: a single catalogue-complete landing page a
  reviewer opens to navigate a case. It lists EVERY report grouped by
  category, marks each as generated (with a link that opens in a new
  tab and a timestamp) or not-yet-generated, and carries the same
  case/agency banner as the individual reports. Aggregate reports show
  "Combines: …" and detail reports show "Also summarized in: …", a
  many-to-many relationship expressed in words rather than a numbering
  scheme. Written/refreshed automatically at the end of every report
  run and via a new "Rebuild index" button (GUI); the index is a
  navigation aid, not evidence.
- New Concealment Overview report (aggregate, summarize-and-link): one
  row per document combining the two concealment mechanisms —
  image-over-image overlaps (incl. full-concealment count) and
  annotation/box-over-content overlays, plus unapplied redactions —
  so a reviewer has one place to see all concealment rather than
  cross-referencing Overlap & Concealment and Text Overlay separately.
  It leads the Manipulation & Alteration group.
- Report relationship metadata (REPORT_COMPOSED_OF, with report_part_of
  derived) added as the single source of truth for which detail reports
  make up each aggregate, keyed by stable report id (no renumbering).
- New Document Risk Overview spreadsheet (Option B): a NEW Excel file
  written at report time with one row per analyzed document — filename,
  risk score, and per-category signal counts (the Document Risk Dossier
  data) — with auto-filter and a frozen header for sorting/filtering by
  risk. Deliberately a separate artifact rather than editing the triage
  sheet after the fact, to avoid an after-the-stated-time modification.
- CLI report runs also emit the risk overview and index.
- Render-testing caveat unchanged: the index/overview generation,
  discovery logic, and Concealment Overview query were unit-tested; the
  banner visuals reuse the existing report branding block.

## v1.0.0 — Update (2026-10-06c)

### Visual overlay report: legibility + draggable badges
- Overlay summary is now black text on a white card, on screen and in
  print, so it stays legible when the report is printed or saved to PDF
  (previously light grey on the dark theme, readable only on hover).
- Number badges are now draggable, graph-style: each badge can be moved
  anywhere on the page and a leader line traces back to the overlay’s
  true location (marked with an anchor dot), so an examiner can move a
  badge off important content and still see what it refers to. Dragged
  positions are kept for printing.
- Badges now start close to their overlay instead of being fanned far
  away (which had pushed later badges in a stack, e.g. #7, well away
  from their target); coincident badges still get a small offset so
  each is individually grabbable, and dragging handles the rest.
- Hover-linking retained (hovering a badge/row highlights the matching
  items and leader line), but no longer required for legibility.

## v1.0.0 — Update (2026-10-06b)

### Visual overlay report: interactive per-overlay layers
- The visual overlay report is now an interactive layered view. The
  page renders as a true-original base (all overlays removed) with one
  transparent, independently toggleable layer per detected overlay,
  stacked in z-order. A left-hand checkbox panel (one box per overlay,
  plus All/None) shows or hides each overlay live; the page defaults to
  all overlays shown (the document as received) and peels to the
  recovered original as boxes are unticked. This replaces the fixed
  "remove one" / "remove all" modes and the per-overlay reveal crops.
- Overlay numbers are now DOM badges rather than pixels baked into the
  image, so stacked overlays no longer hide each other’s numbers.
  Colliding badges are fanned apart with leader-dot anchors, and
  hovering a badge, checkbox, or summary row highlights all three.
  Overlays are numbered in stacking order (1 = bottom).
- Per-overlay layers are isolated precisely: "only overlay k present"
  is produced by removing every other overlay BY OBJECT REFERENCE,
  which separates stacked annotations that share the same /Rect (the
  box-and-replace case) — rectangle matching alone could not. The
  layer is then the pixel difference from the base, so compositing the
  chosen layers over the base reproduces any subset of overlays.
- The per-overlay summary (type, geometry, object locator, and the
  annotation’s text — the fabricated value) is kept beneath the page;
  only the reveal crops were removed. Overlays that cannot be cleanly
  isolated (e.g. some content-stream overlays) are listed and labelled
  rather than given a misleading independent toggle.
- reveal.build_revealed_pdf_bytes / _suppress_annotations now accept
  object-reference targets (obj_num/obj_gen from the finding) with
  rectangle matching retained as a fallback.
- Not render-tested in the build environment (no PyMuPDF/pyvis there);
  the object-reference removal, layer compositing, and HTML/JS were
  unit-tested, and the rendering reuses the existing proven page-render
  path. Validate on a real document before evidentiary use.

## v1.0.0 — Update (2026-10-06)

### Stacked annotation overlay detection (box-and-replace tampering)
- check_text_overlays now detects STACKED overlay annotations, the
  signature of box-and-replace tampering: an opaque box hides the
  original value and a (usually transparent) text annotation supplies
  a replacement on top. Previously only the opaque box was flagged
  (FreeText/Widget required an opaque background), so the
  replacement-value layer was missed and the visual reveal removed
  the box but left the false text — never showing the true original.
- New rule: an overlay-subtype annotation (/FreeText, /Widget,
  /Square, /Redact, and now /Stamp) is flagged when it overlaps
  another overlay annotation in the same region with at least one of
  the pair opaque — regardless of its own background opacity. The
  existing rule (opaque background + overlaps page text) is unchanged,
  so prior findings keep their exact wording, with a stacking note
  appended where a box is now known to be paired with a replacement
  layer.
- The replacement annotation’s text (/Contents) — the fabricated
  value — is captured in the finding detail, so the report shows the
  false value alongside the original page text it covers.
- Consequence without any further change: the Text Overlay report now
  lists both layers, and the visual overlay report’s "remove all
  overlays" reveal now strips the box and the replacement text
  together, showing the true underlying original. /Stamp added to the
  reveal’s removable subtypes.
- Precision preserved: a lone transparent text annotation that is not
  stacked on a box is still not flagged (avoids false positives on
  legitimate callouts/comments).
- Next iteration (not in this build): interactive per-overlay toggle
  and z-order step-through in the visual report, to view intermediate
  states and peel stacked layers one at a time.

## v1.0.0 — Update (2026-07-10b)

### Version anachronism: accuracy refinements
- AES-256 (/AESV3) temporal year corrected. It was mapped to PDF
  1.7's publication year (2006), but AES-256 shipped in Adobe
  Extension Level 3 in 2008, so 2006 was too early and could miss a
  temporal contradiction. Added a per-feature year override (AES-256
  -> 2008, its true earliest) used by both the temporal check and the
  displayed year; all other features continue to use their base
  version's publication year. A file claiming a pre-2008 creation
  date while using AES-256 now correctly flags the temporal
  contradiction. (2008 is also safer than the 2009 the guide
  previously cited, which could have falsely flagged a legitimately-
  2008 file.)
- JBIG2 / JPEG2000 detection limitation documented. Unlike the
  storage/cross-reference/encryption markers (always plaintext), an
  image filter name can sit inside a compressed object stream, so a
  raw-byte scan may under-report those two (never over-report). The
  detector comment and the Technical Reference Guide now state this
  conservative, safe-direction limitation explicitly.
- Tests extended to 26 checks (added AES-256 2007->temporal,
  2009->no-temporal, and non-override year guards). Technical Guide
  §4.4 updated (AES year 2008, reliability/limitation wording).

## v1.0.0 — Update (2026-07-10)

### Version anachronism detection + aggregate risk dossier
- New VERSION_ANACHRONISM detector (analysis/doc_checks.py): flags
  files whose structural features require a newer PDF version than they
  declare. The declared version (header, Catalog /Version, XMP) is
  trivially editable; the features present cannot be lowered without
  re-authoring the file, so they set a hard minimum version and, via
  each feature’s publication year, an earliest-possible date.
- Detected features (reliable storage/encoding/encryption markers read
  from the raw bytes, plus Catalog checks): object streams and xref
  streams (1.5), JBIG2 (1.4), JPXDecode (1.5), AES-128 /AESV2 (1.6),
  AES-256 /AESV3 (1.7+/2.0), optional content (1.5), portfolios (1.7),
  XFA (1.5). Compared conservatively against max(header, Catalog, XMP).
- Temporal contradiction: when the claimed creation date predates the
  required feature’s year, the finding says so explicitly — the
  strongest form. Bare gaps carry the hard-coded-header caveat and read
  as requires-review. Feeds document risk at +15 (MEDIUM); distinct
  from VERSION_MISMATCH (header vs Catalog).
- New reports: Version Anachronism (detail, Provenance group) and
  Document Risk Dossier (aggregate) — one row per document composing
  every document-level signal behind its score into a single view so
  the number is legible as the sum of named, individually-caveated
  contributions. 18 reports total.
- Empirical note recorded in the Technical Reference Guide (new section
  4.4): the Info dictionary has no version field; a conformant producer
  raises the header when it writes a newer feature, so a legitimate
  1.4->1.7 edit updates the header — an anachronism therefore means a
  non-conformant producer or a deliberately lowered version string.
- Guides updated: Technical Reference Guide (section 4.4, category and
  weight tables, caveats); Risk Scoring technical/broader (weight,
  finding list, FP note); HTML Reports technical/broader (two report
  sections, count 16->18).

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
