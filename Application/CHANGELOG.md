# PDF Forensics Suite — Changelog

**Current: version 1.1.2 — 2026-10-22 (build 2026-10-22e)** · schema revision 10. Version 1.0.0 (build 2026-10-20) is frozen. Later changes are released as incremental updates (1.0.1, 1.0.2, …); for each, update `__version__` and `BUILD_DATE` in `pdf_forensics/__init__.py` and add a dated entry below. Dated entries record when each change was made and are kept as historical record.

## Version 1.1.2 — Release (2026-10-22, build 2026-10-22e)

No database schema change. Two new finding types are added to existing
databases automatically. Re-analyse documents to apply the new checks.
Prompted by a file edited with
`exiftool -PDFVersion="1.05" -Creator=... -Author=... -Producer=...`,
of which 1.1.1 reported only VERSION_CONFLICT.

### Version format: "1.05" is invalid, and no longer masks an anachronism
- Declared versions were read leniently, so ExifTool's XMP pdf:PDFVersion
  "1.05" counted as 1.5. That raised the highest declared version to 1.5
  and hid a genuine 1.5 anachronism (cross-reference streams under a 1.4
  header) that the same file's prior version still showed. A version must
  now be written as one digit, a dot and one digit (1.0 to 1.7, 2.0);
  anything else is VERSION_INVALID and excluded from the comparison.
  (`analysis/doc_checks.py`)

### Info vs XMP: six text fields compared
- METADATA_MISMATCH compared only Producer and the two dates. It now also
  compares Creator with xmp:CreatorTool, Author with dc:creator, Title with
  dc:title, Subject with dc:description and Keywords with pdf:Keywords,
  ignoring case, spacing and list separators; one finding per field.
  ExifTool's -Creator writes the Info Creator and XMP dc:creator (the
  author) and leaves xmp:CreatorTool unchanged; both disagreements are now
  reported.

### New: metadata changed by a later revision (METADATA_REVISED)
- Each revision's text metadata (Info dictionary and XMP) is compared with
  the revision before; every field added, changed or removed is listed
  with both values (MEDIUM, risk +15). A revision that changes metadata
  but keeps every modification date is called out as a silent edit.
- Timeline: the silent edit is also flagged there, on the unchanged
  modification dates of that revision. (`analysis/timeline.py`)

### New: ExifTool updates identified (EXIFTOOL_EDIT)
- ExifTool ends each update with `%EndExifToolUpdate` and the original
  file length. The marker is now reported (MEDIUM, risk +15), naming the
  prior version that is the original file, and the Incremental Updates
  report has an Editing Tool Identified column. (`reports/queries.py`)

### XMP arrays stored correctly
- XMP properties that are unordered lists (rdf:Bag, such as dc:creator in
  some files) were stored as Python set text, e.g. {'Steve Miller Band'}.
  They are now stored as plain text in analysis and triage.
  (`analysis/metadata.py`, `analysis/triage.py`)

### Documentation
- Technical Reference Guide: new section 4.6 (metadata changes across
  revisions, silent edits, ExifTool markers) with a table-of-contents
  entry; 4.4 (version format), 4.5 (silent edits); finding-type and
  risk-weight tables. Risk Scoring technical guide and HTML Reports
  technical guide updated. All guides state version 1.1.2, build
  2026-10-22e.

## Version 1.1.1 — Release (2026-10-22, build 2026-10-22d)

No database schema change (still revision 10). Re-analyse documents to
record their timelines revision by revision.

### Timeline Analysis: every revision listed in full
- 1.1.0 listed each distinct timestamp once, with the span of revisions
  in which it appeared ("revision 2 to current"). The checks did cover
  every revision, but the report did not show it: a prior version's
  timestamps had no rows of their own unless they changed, and the
  prior-version sections said only "included in parent". The timeline
  now lists every timestamp of every revision, including values
  unchanged from the revision before. (`analysis/timeline.py`)
- Each prior version's section lists the timestamps of its revision, with
  its own verdict (CONSISTENT or INCONSISTENT, as checked within its
  parent's timeline), so filtering on a prior version shows its place in
  the timeline directly.
- The parent's summary states the revisions examined, naming each by its
  extracted file ("revision 2 (..._version2.pdf)"), and explains any
  %%EOF marker that is not a revision (for example the first marker of a
  linearized file). The Revision column now follows the UTC column.
- A comment edited in a later revision is now checked against that
  revision's save as well as the revision where it first appeared.
- A problem that persists across revisions is reported once in the
  TIMELINE_INCONSISTENT finding, while every revision's row is flagged.
- Databases from 1.1.0 still display; their rows keep the old spans.
  (`reports/queries.py`)

### New: Timeline Analysis spreadsheet
- An Excel workbook with the same content, generated with the reports
  (GUI and command line) and listed under Spreadsheets in the case index:
  a timeline sheet (flagged rows and verdicts highlighted, filters,
  frozen header) and a summary sheet (one row per document: verdict,
  timestamps, flagged, timestamps assumed UTC). A note above each sheet
  states that all times are normalised to UTC. Rebuilt with the reports
  after a password retry. (`reports/timeline_xlsx.py`, `gui/app.py`,
  `cli.py`, `reports/case_index.py`)

### Documentation
- Technical Reference Guide 4.5, Risk Scoring technical guide 5.5, HTML
  Reports guides (Timeline Analysis report and the new spreadsheet);
  all guides' covers state version 1.1.1, build 2026-10-22d.

## Version 1.1.0 — Release (2026-10-22, build 2026-10-22c)

First feature release after 1.0. Database schema revision 10: a new
`timeline_events` table, added to existing databases automatically when
they are opened. Re-analyse documents to build their timelines.

### New report: Timeline Analysis
- Every timestamp in each submitted document, across all its revisions
  (each prior version recovered from an incremental update, and the
  current file), in chronological order. Sources: Info dictionary
  CreationDate and ModDate; XMP CreateDate, ModifyDate and MetadataDate;
  the XMP edit history (xmpMM:History); annotation /CreationDate and /M;
  digital signature signing times; embedded file dates; and photo EXIF
  DateTimeOriginal and DateTimeDigitized. Each distinct value is listed
  once with the span of revisions in which it appears.
- All timestamps are normalised to UTC, and the report says so. A value
  with no timezone is assumed to be UTC, compared and flagged like any
  other, and marked "none (assumed UTC)".
- Checks: created not after modified (Info, XMP, annotations, embedded
  files; photos digitised not before taken); creation date unchanged
  across revisions; modification dates never going backwards from one
  revision to the next; XMP history in order and not after the
  revision's last save; comments and signatures not dated before the
  document was created; a comment not dated after the save of the
  revision that added it; no revision saved after a signature but dated
  before it; no photo taken after the document's last modification; no
  date in the future or before 1993. Different sources allow 60 seconds.
- Each document opens with a SUMMARY row: CONSISTENT, INCONSISTENT,
  INCLUDED IN PARENT (prior versions) or NOT AVAILABLE (analysed before
  1.1.0). (`analysis/timeline.py`, `reports/queries.py`)
- New finding **TIMELINE_INCONSISTENT** (HIGH, risk +20), one per
  document, listed in the Document Risk Summary and counted in the
  Document Risk Dossier. An Info ModDate before the Info CreationDate in
  the current revision on its own is not counted twice (it is already
  METADATA_DATE_ANOMALY). (`analysis/engine.py`, `analysis/risk.py`,
  `database.py`)
- The Reports screen lists 22 reports; its checkbox rows are tighter so
  the list still fits a 1080p screen. (`gui/app.py`)

### Info vs XMP date columns
- The triage spreadsheet's pdf-metadata sheet and the PDF Metadata report
  have two new columns, CreationDate: Info = XMP and ModDate: Info = XMP:
  TRUE when both values denote the same moment within 60 seconds after
  conversion to UTC, FALSE (bold red in the spreadsheet) when they do
  not, blank when either is missing. (`analysis/triage.py`,
  `reports/queries.py`)

### EXIF capture dates
- EXIF extraction read only the main image directory, so DateTimeOriginal,
  DateTimeDigitized, their offsets and the other Exif sub-IFD tags
  (exposure, lens) never reached the EXIF & GPS report. They are now
  extracted. (`analysis/metadata.py`)

### Documentation
- Technical Reference Guide: section 4.3 explains the three places a
  version can be declared and how a metadata tool's edit lands in a later
  revision; new section 4.5 Timeline Analysis; a note in 4.2 on the Info =
  XMP columns; new Annex A, PDF Versions (each version's specification,
  publication date and main features, from the bibliographies of ISO
  32000-1 and 32000-2); table of contents entries for 4.4, 4.5 and Annex
  A (4.4 had none); finding-type and risk-weight tables.
- Risk Scoring technical guide: TIMELINE_INCONSISTENT weight; section 5.5
  Timeline Events (schema revision 10).
- HTML Reports guides: new Timeline Analysis section; PDF Metadata
  columns; Document Risk Summary list; report count 22. The plain-language
  guide's report table also gained its missing Encrypted Files row.
- All guides' cover lines, headers and footers state version 1.1.0, build
  2026-10-22c.

## Version 1.0.3 — Release (2026-10-22, build 2026-10-22b)

Third incremental update. No database schema change (still revision 9).
Two new finding types are added to existing databases automatically when
they are opened. The build marker carries a letter because 1.0.2 was
built the same day.

### Version checks: invalid and conflicting PDF versions
- A declared PDF version that does not exist was not reported. The
  Version Anachronism check only compared the declared version with the
  features present, and a file whose header and XMP were edited to 0.3
  passed if it used none of the features on its list. New finding
  **VERSION_INVALID** (HIGH, risk +25): any declared version (header,
  Catalog /Version or XMP pdf:PDFVersion) outside the published versions
  1.0 to 1.7 and 2.0.
- Invalid values no longer take part in the anachronism comparison. That
  comparison uses the highest declared version, so a fictitious high
  value (e.g. a header edited to 9.9) would have hidden any genuine gap.
- Versions are parsed whole: 1.10 was read as 1.1.
- New finding **VERSION_CONFLICT** (MEDIUM, risk +15): the XMP
  pdf:PDFVersion disagrees with the version in effect (the later of the
  header and the Catalog /Version), or a later incremental update added,
  changed or removed the XMP pdf:PDFVersion, or lowered, removed or
  invalidated the Catalog /Version. Metadata tools such as ExifTool append
  an update rather than editing the original bytes and cannot change the
  header, so an attempted version change left the header as it was and
  went unreported. The Detail lists each revision's declarations. Not
  reported: a Catalog /Version raised by an update (the standard upgrade,
  still reported as VERSION_MISMATCH) and an XMP version written by an
  update that equals the version in effect without lowering an earlier
  value. An invalid XMP value is reported once, as VERSION_INVALID. The
  revision comparison runs on submitted files, not on prior versions
  analysed in their own right. (`analysis/doc_checks.py`,
  `analysis/engine.py`, `analysis/risk.py`, `database.py`)
- The Version Anachronism report now lists all three finding types, with
  a new Type column, so every version problem is in one report. The
  Document Risk Dossier counts and lists the new types.
  (`reports/queries.py`)

### Case index: same-day build markers
- The case index read build markers as a strict date, so a build such as
  2026-10-22b would have been read as 2026-10-22 and its warning about
  outputs from more than one build would have missed it. It now reads the
  optional letter. (`reports/case_index.py`)

### Documentation
- Technical Reference Guide section 4.4 (comparison, invalid versions,
  conflicting declarations), finding-type and risk-weight tables; Risk
  Scoring technical guide (weights table); HTML Reports guides (Version
  Anachronism report, Dossier). All guides' cover lines, headers and
  footers state version 1.0.3, build 2026-10-22b.

## Version 1.0.2 — Release (2026-10-22, build 2026-10-22)

Second incremental update. No database schema change (still revision 9);
databases from 1.0.0 and 1.0.1 open unchanged.

### Command line: wildcards now work on Windows
- `analyze` and `triage` accept patterns such as `*.pdf`, but did not
  expand them: macOS and Linux shells expand a pattern before the program
  sees it, while Windows (cmd and PowerShell) passes it through unchanged,
  so `triage *.pdf` reported "*.pdf" as not found.
- Patterns containing `*` or `?` are now expanded by the application
  itself, the same way on every platform. Square brackets are matched
  literally first, so exhibit prefixes work (`"[010]*.pdf"`); only if that
  finds nothing are they treated as a character class. An argument that
  names an existing file is always used as is. A pattern that matches
  nothing is still reported as not found. Matches are sorted, a file
  already listed is not added twice, and each pattern's match count is
  printed and written to the session log. (`cli.py`)

### GUI: the Locked counter
- After a password retry opened a locked file, the Locked counter still
  counted it, and Processed and Images did not include it. Each file the
  retry opens now moves from Locked to Processed, with its images added,
  so the counters match the run summary.
- The Locked counter was not reset at the start of a run, so a run could
  start showing the previous run's locked files. It is now reset with the
  other counters.
- Triage never set the Locked counter; it now shows the files triage could
  not open, and is updated after the triage retry.
- The triage retry reused the main run's progress handler, which set
  Processed to the retry's own count (1, 2, …). It now logs its progress
  only, and afterwards Processed shows the rows in the merged spreadsheet.
  (`gui/app.py`)

### Documentation
- All seven in-app guides and the Technical Reference Guide: cover line,
  running header and footer now state version 1.0.2, build 2026-10-22.
- README files and release notes updated for 1.0.2; the application
  README's command-line section notes that wildcards work on every
  platform.

## Version 1.0.1 — Release (2026-10-21, build 2026-10-21)

First incremental update to 1.0.0. No database schema change (still
revision 9); databases from 1.0.0 open unchanged.

### Triage: PyMuPDF messages now written to the session log
- Build 2026-10-14 stopped PyMuPDF's parser messages (e.g. "corrupt object
  stream") printing to the terminal and wrote them to the session log
  instead, but only analysis wrote them to the log. During triage they
  were suppressed from the console and then either never logged or logged
  later against the next file analysed in the session.
- Triage now writes them to the session log after each file and after
  each prior version it triages, labelled with the file they came from
  (e.g. `[triage: [001.1] Example Bank Letter_version1.pdf]`). Messages
  left over from earlier processing in the session are logged first,
  labelled "before triage", so they are not attributed to the first file
  triaged.
- Logging only; analysis is unchanged. (`analysis/triage.py`)

### Triage: prior versions of encrypted files now use the password list
- Triage reconstructs each prior version in memory and triages it, but did
  not pass on the run's password list or the password that opened the
  current version. A prior version of a file that needs a password
  (an incremental update to an encrypted file is encrypted in the same
  way) therefore could not be opened: its metadata was missing from the
  spreadsheet, and its Encryption Status read "Not opened — no password
  list supplied" even when a list had been supplied and had opened the
  current version.
- A prior version is now tried first with the password that opened the
  current version, as analysis already does, then in the usual order
  (empty password, passwords already found this run, the supplied list).
  The Encryption Status shows "Opened with the parent document's password"
  when that password opened it, and the Password column shows the password.
- A prior version that still cannot be opened is now also noted in the
  session log as an encrypted, unopened prior version. The end-of-run
  retry prompt offers the files whose current version could not be
  opened; a prior version that stays locked although its file opened is
  reported but not offered for retry.
- Changes triage results: prior versions of encrypted files that were
  previously reported as not opened can now be opened and their metadata
  read. Re-run triage on affected cases. Analysis was not affected; it
  already tries the parent's password on prior versions.
  (`analysis/triage.py`)

### Triage: the end-of-run retry is merged into the spreadsheet
- When triage met encrypted files it could not open, the end-of-run prompt
  (GUI) offered to re-triage them with a password list. That re-triage
  saved to the same file as the main run, so it replaced the whole triage
  spreadsheet with one holding only the re-triaged files, without their
  prior versions; the other files' rows and the comments sheet were lost.
  The log then advised re-running triage on the full set to "refresh" the
  spreadsheet that had already been overwritten.
- The re-triage is now merged into the main spreadsheet. The rows for each
  re-triaged file (current version, prior versions and comments) are
  replaced in place, in their original position, and every other row is
  kept unchanged. A file whose re-triage produces no row keeps its earlier
  rows, and if no file can be re-triaged the spreadsheet is left
  untouched. The re-triage includes prior versions whenever the main run
  did. The session log records the merge (files re-triaged, rows replaced,
  rows now in the spreadsheet), and the spreadsheet is listed once in the
  session's outputs. (`analysis/triage.py` `run_triage(run_state=...)`,
  `gui/app.py`)

### Triage: comments from opened encrypted files
- Triage extracted reviewer comments by opening each file without a
  password, so no comments were ever read from an encrypted file that
  needs one, even after triage had opened it. Comments are now extracted
  with the password that opened the file (or prior version). Files that
  could not be opened are skipped quietly, as they are already reported
  as not opened. (`analysis/triage.py`)

### Triage: no crash when nothing could be triaged
- When no file produced a row, `run_triage()` returned three values where
  every caller expects four, which would have raised an error in the GUI
  and on the command line. It now returns four values, writes no
  spreadsheet, and leaves an existing one unchanged. (`analysis/triage.py`)

### Documentation
- All seven in-app guides and the Technical Reference Guide: cover line,
  running header and footer now state version 1.0.1, build 2026-10-21.
  The Risk Scoring technical guide's introduction names v1.0.1.
- Six in-app guides (01a, 01b, 02a, 02b, 03a, 03b) stated "Released under
  the MIT License" on the cover. The application is licensed under the
  Apache License, Version 2.0 (see `LICENSE`); the covers now say so, as
  00 Getting Started already did. No licensing terms changed.
- Technical Reference Guide: the authorship section said the repository
  was private during the beta review period; it is now public, and the
  Guide says so.
- README files and release notes updated for 1.0.1. The application
  README's Encrypted PDFs section now states how prior versions of
  encrypted files are opened, that the triage retry updates the same
  spreadsheet, and that comments are read from opened encrypted files. The version comments
  in `pdf_forensics/__init__.py` now describe the release policy instead of
  the pre-release one.

## Version 1.0.0 — Release (2026-10-21, build 2026-10-20)

First frozen release. The application code is build 2026-10-20 unchanged;
this release adds the README and release notes. Highlights of what 1.0
contains:

- Forensic analysis of PDFs: text overlays (annotations, stacked
  box-and-replace annotations, white boxes with painted text, text over
  text), image overlap/off-page/soft-mask concealment, DPI anomalies, font
  consistency, version anachronism, unapplied redactions, signature
  coverage and structural integrity.
- Metadata, creator/producer, XMP and timeline analysis; incremental-update
  analysis with validated prior-version extraction and analysis.
- 21 HTML reports, the Visual Overlay Report (verified, toggleable layers),
  relationship graphs, triage and Document Risk Overview spreadsheets, and
  the case index with an output manifest.
- Every submitted file accounted for (analysed, identical copy, encrypted
  and not opened, failed, not found), with duplicates noted on all reports.
- Encrypted PDFs opened with an examiner-supplied password list, recorded
  in the Encrypted Files report.
- Recorded disclaimer acknowledgement; version and build on every output;
  complete session logging.
- Seven in-app guides and the standalone Technical Reference Guide (v1.2),
  all stating build 2026-10-20.

Verified by the author on real case material before release, including
password-list decryption, prior-version validation, long and bracketed
file names, and duplicate handling.

### Documentation errata corrected at re-issue
- The database is at schema revision 9. Revision 9 was introduced with
  build 2026-10-14 and added the `encryption` table: one row per encrypted
  file handled in a run, recording whether it was opened, the password
  that worked and its source, the encryption scheme, the number of
  passwords tried, and the linked analysis. It feeds the Encrypted Files
  report. The bump was not recorded in this CHANGELOG at the time, so the
  header line above, the release notes and the Technical Reference Guide's
  architecture table stated revision 8. All three now state revision 9.
- Risk Scoring technical guide (01a): added section 5.4, Encryption Record
  (schema revision 9), with the table's columns.
- Documentation only; no code change. Databases created by build
  2026-10-14 or later already have the table, and older databases gain it
  automatically when opened.

## v1.0.0 — Update (2026-10-20)

### Prior versions: false positives and invalid fragments no longer extracted
- Every %%EOF marker before the last was treated as the end of a prior
  version. In a linearized ("fast web view") PDF the first %%EOF ends the
  first-page section near the start of the file (often with startxref 0),
  so these files produced a "prior version" of a few hundred bytes that is
  not a PDF. For an encrypted file the fragment also carried the /Encrypt
  entry and was reported as a password-protected version that could not be
  opened. In one test batch every reported prior version was such a
  fragment.
- New classify_prior_versions (metadata.py) validates each candidate: its
  startxref must point to a cross-reference section inside the bytes, and
  the bytes must open without recovery and contain at least one page.
  Outcomes: valid; password-protected (structurally valid, needs a
  password; the parent document’s password is tried first); not a prior
  version (linearized first-page section); not a usable prior version
  (with the reason). Only valid and password-protected versions are
  extracted, triaged or analysed; the others are logged with the reason.
- Triage: a new Prior-Version Check column on each file’s row explains
  how each %%EOF marker was treated. Triage also now checks encryption on
  the bytes being triaged; a prior version previously inherited its parent
  file’s encryption status.
- Analysis passes the parent document’s password into version
  extraction.

### Case index: encrypted outcomes counted and labelled correctly
- A prior version that could not be opened was recorded as a submitted
  file rather than as a prior version, inflating the submitted count. The
  encryption step now records whether the file is a prior version.
- "encrypted_unopened" is shown as "Encrypted — not opened (password
  required)" and counted in the summary line, which previously did not add
  up when such files were present.
- When the end-of-run retry opens a locked file, its existing record is
  updated to "analysed" instead of a second record being added.

### Documentation
- Technical Reference Guide 5.2 (validation of prior versions) and Getting
  Started (Prior-Version Check column). All documents state build
  2026-10-20.

## v1.0.0 — Update (2026-10-15b)

### Case index: prior versions with bracketed names now listed
- Extracted Material showed "0 prior version(s)" for every document even
  when versions were on disk. The index listed each version folder’s
  files with glob, but an exhibit number like [010] in the folder name is
  a glob character class, so the pattern matched nothing. Directory paths
  are now escaped (glob.escape) in every index scan, so names containing
  square brackets are listed correctly. The same escaping was applied to
  the report-rebuild scan in the GUI.

### Duplicate (identical-copy) documents flagged on all reports
- A document not analysed because it is a byte-identical copy of another
  (e.g. [025] identical to [010]) appeared only in the case index
  overview and the Duplicate Submissions report. On other reports it was
  simply absent, which could read as the document having been missed.
- Every per-document report now carries a note when the database contains
  such copies: how many there are, an example (which file is identical to
  which), that they were recorded as duplicates rather than re-analysed
  and were not missed, and a pointer to the Duplicate Submissions report.
  The note is omitted from the Duplicate Submissions report itself and
  when there are no duplicates (and on databases predating the
  submissions record).

## v1.0.0 — Update (2026-10-15)

### Prior-version extraction: Windows long-path failure fixed
- Extracted prior versions were not written for documents with long
  names in a deeply nested case folder. The document name appears twice
  in the path (the "<name>_versions" folder and each
  "<name>_versionN.pdf" file), which on top of a deep path (e.g. a
  OneDrive case folder) exceeded the Windows 260-character limit. Python
  reported the write as succeeding, but pikepdf/PyMuPDF could not reopen
  the over-limit path, so analysis of the version failed with "No such
  file or directory", the version folder appeared empty, and the index
  showed the version as a failed submission. Short-named documents were
  unaffected; triage still listed the versions because it reconstructs
  them in memory rather than on disk.
- extract_prior_versions now keeps the path within the limit: when the
  full name would not fit, it shortens the base used for the folder and
  files and appends a short hash of the original name for uniqueness,
  preserving the "_versionN.pdf" suffix used to identify the version.
  Short names are unchanged. Writes are now wrapped so a version that
  still cannot be written is logged and skipped rather than queued as a
  non-existent file (which had produced a spurious "failed" row).
- Re-run analysis on affected cases to extract the versions that were
  missed; the spurious failed-submission rows will not recur.

## v1.0.0 — Update (2026-10-14)

### Encrypted-PDF fixes from field testing
- Triage now detects encrypted PDFs. Detection used PyMuPDF opening the
  file from a byte stream, which fails on imperfect-but-readable files, so
  locked documents were missed and no password prompt appeared. Triage now
  uses the same pikepdf-based detection as analysis (which also identifies
  permissions-only encryption), accepts a password list (GUI "Password
  list…" button, CLI -p/--password-list), opens files the list can open
  and reads their metadata with the password, and offers the same
  end-of-run prompt. Two columns were added to the triage spreadsheet:
  Encryption Status and Password.
- Encrypted Files report no longer goes stale after the end-of-run
  retry. When the prompt opens locked files after the main run, the
  reports already generated for that database are now rebuilt (previously
  only the case index was refreshed), so the report reflects the files the
  supplied password opened instead of still showing "no password list
  supplied".
- PyMuPDF messages (e.g. "corrupt object stream") no longer print to the
  terminal. They are suppressed from the console and written to the
  session log instead, so the record is kept without alarming output.
- The analysis window is taller so the Run button is not clipped after the
  password-list row was added.

## v1.0.0 — Update (2026-10-13c)

### Technical Reference Guide: Encrypted PDFs is now its own section
- The Encrypted PDFs material was numbered 9a (a sub-number) and so did
  not appear in the table of contents. It is now section 10 in its own
  right, with sub-sections 10.1-10.4, listed in the table of contents.
- Former sections 10-16 are renumbered 11-17 (Risk Scoring Model is now
  11; SQLite Query Reference is now 17), with their sub-sections,
  heading bookmarks and table-of-contents entries updated to match.
- Internal cross-references updated accordingly: former Chapter 12
  (Counter-Verification) is referenced as Chapter 13, and former
  Sections 12.3/12.4/12.5 and 15.5 as 13.3/13.4/13.5 and 16.5.
  References to ISO 32000-2:2020 clauses (e.g. §14.3.3) are unchanged.

## v1.0.0 — Update (2026-10-13b)

### Encrypted PDFs: open with a supplied password list
- When a submitted PDF is password-encrypted, the application now tries
  to open it using a text file of candidate passwords the examiner
  supplies. Not a password cracker: one attempt per supplied password, in
  order, stopping at the first that works; no guessing or brute force; the
  file is only opened for reading and never modified.
- Order per file: the empty password (opens permissions-only files),
  then passwords already found this run (most-recent first), then the
  supplied list in order. A password that works is promoted to the front
  of the known-good list for the files that follow. Soft limit of 1,000
  with a warning. Passwords read verbatim (leading/trailing spaces and a
  leading # are part of the password; no comment lines); UTF-8/UTF-16/
  Windows encodings detected.
- Permissions-only encryption is now detected (via the /Encrypt
  dictionary) even though such files open with the empty password;
  previously they were treated as unencrypted and not recorded.
- Five recorded outcomes per file: not encrypted; opened with no
  password; opened with a supplied password; not opened (no supplied
  password worked); not opened (no password list supplied) — the last
  two kept distinct so a reviewer can tell a file was never attempted
  against a list.
- New Encrypted Files report (Document Overview & Provenance; 21 reports
  now): every encrypted PDF, its status, the password that opened it
  (shown verbatim, as evidence and a repeatable step), the source, the
  scheme and the attempt count. The report header carries a visible
  caution that it contains passwords. A database analysed before this
  build shows an explanatory row.
- GUI: a "Password list…" button and a Locked counter; locked files are
  set aside and, at the end of the run, the application offers to try a
  password list on just those files and analyse any it opens (so a batch
  never stops to wait mid-run). CLI: -p / --password-list on analyze and
  triage; with no list, locked files are recorded as "no list supplied".
- The successful password, the list file path and the list MD5 are
  written to the session log; the password list itself is not stored and
  is not kept between cases.
- Documentation: Technical Reference Guide chapter 9a (Encrypted PDFs),
  architecture table (passwords.py) and section 13.1; HTML Reports
  technical 2.5.1 and plain-language 2.21; Getting Started.

## v1.0.0 — Update (2026-10-13)

### Text-over-text detector: OCR spacing no longer reported
- On OCR-converted documents (a scanned page converted into real text over
  a background image), the OCR application squeezes each recognised word
  into the width it had on the scan, so neighbouring letters overlap. The
  text-over-text check compared every character with every nearby
  character and reported these neighbours as text drawn over text: in one
  case every finding on two documents was a letter overlapping the next
  letter of the same word or label (e.g. "UN" under "NI" in "UNI...").
- Fix: each extracted line is divided into runs wherever the drawing
  position steps backwards; within a run, a character drawn later and
  further along the line is the next character of the same text, however
  tightly spaced, and the pair is skipped. Text drawn over existing text
  is still compared: it appears as a separate line, or steps back within
  the line and starts a new run (including overprinting offset from the
  original). The faux-bold / drop-shadow exclusion is unchanged.
- Tested against squeezed words, compressed placeholders, unmappable OCR
  glyphs, words or letters drawn as separate pieces and vertical text
  (all reported by build 2026-10-09, none now), and against text drawn
  separately over old text, text redrawn over itself within one line, and
  the same offset by a third of a letter (all still reported).
- Re-analyse documents processed with earlier builds to clear these
  findings and their effect on the document risk score.
- Documentation: Technical Reference Guide 7.3.1 (new exclusion) and
  section 11 (OCR-converted documents, including what to check instead);
  HTML Reports technical 2.16. All documents now state build 2026-10-13.

## v1.0.0 — Update (2026-10-09b)

### Fictitious example names
- Example file names, paths and reference numbers in the guides, code
  comments, report descriptions and this CHANGELOG were taken from a real
  case. All are replaced with fictitious ones, e.g.
  D:\Cases\2026-EXAMPLE\Source\[001.1] Example Bank Letter.pdf and
  [001.2] / [002.1] Invoice 0000123.pdf. Affected: Getting Started (section
  4), HTML Reports technical (2.20) and plain-language (2.20), the
  Duplicate Submissions report description (shown in the report and the
  case index), database.py comments and earlier CHANGELOG entries.

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
  match once a leading reference such as "[001.2]" is ignored but whose
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
  text where the font encoding allows (e.g. "PAYEE : EXAMPLE TRADING
  LTD"); otherwise it is labelled "Painted text" with a note.
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
