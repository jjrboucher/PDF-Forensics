# PDF Forensics Suite — Release Notes

## Version 1.1.1

**Released:** 2026-10-22 · **Build:** 2026-10-22d · **Database schema:** revision 10 (unchanged)

### What changed

- **Timeline Analysis lists every revision in full.** Each prior version's
  timestamps are listed, even when unchanged from the next revision, and
  each prior version has its own section and verdict. The summary names
  the revisions examined and explains any %%EOF marker that is not a
  revision. (The checks already covered every revision in 1.1.0; the
  report now shows it.)
- **New Timeline Analysis spreadsheet,** listed under Spreadsheets in the
  case index: the full timeline plus a one-row-per-document summary.

### Upgrading

Replace the application folder with the 1.1.1 package. No database
migration is needed. Re-analyse documents to record their timelines
revision by revision; documents analysed with 1.1.0 still display.

### Verifying this release

```bash
# Windows (PowerShell)
Get-FileHash PDF_Forensics_Suite_v1.1.1.zip -Algorithm SHA256

# macOS / Linux
sha256sum PDF_Forensics_Suite_v1.1.1.zip
```

The value must match the one in `SHA256SUMS.txt`. Running
`python pdf_forensics.py --version` should print `pdf_forensics 1.1.1 (build 2026-10-22d)`.

---

## Version 1.1.0

**Released:** 2026-10-22 · **Build:** 2026-10-22c · **Database schema:** revision 10

The first feature release after 1.0. The full change history is in
[`CHANGELOG.md`](CHANGELOG.md).

### What's new

- **Timeline Analysis report.** Every timestamp in a document and its
  earlier versions (document dates, edit history, comments, signatures,
  embedded files and photo capture dates), normalised to UTC and checked
  for chronological sense. Each document is marked CONSISTENT or
  INCONSISTENT; out-of-order timestamps are flagged with the reason, and
  an inconsistent timeline adds to the document risk score.
- **Info = XMP date columns** in the triage spreadsheet's metadata sheet
  and the PDF Metadata report: TRUE when the two creation (or
  modification) dates agree, FALSE when they do not.
- **Photo capture dates** (EXIF DateTimeOriginal) now appear in the EXIF &
  GPS report.
- **Technical Reference Guide:** Timeline Analysis (section 4.5), where
  a PDF version can be declared (4.3), and a new annex of PDF versions.

### Upgrading

Replace the application folder with the 1.1.0 package and keep your case
folders. The database is upgraded automatically (schema revision 10) when
opened. **Re-analyse** documents to build their timelines; documents
analysed with an earlier version show "NOT AVAILABLE" in the Timeline
Analysis report.

### Verifying this release

```bash
# Windows (PowerShell)
Get-FileHash PDF_Forensics_Suite_v1.1.0.zip -Algorithm SHA256

# macOS / Linux
sha256sum PDF_Forensics_Suite_v1.1.0.zip
```

The value must match the one in `SHA256SUMS.txt`. Running
`python pdf_forensics.py --version` should print `pdf_forensics 1.1.0 (build 2026-10-22c)`.

---

## Version 1.0.3

**Released:** 2026-10-22 · **Build:** 2026-10-22b · **Database schema:** revision 9 (unchanged)

The third incremental update to 1.0.0. The full change history is in
[`CHANGELOG.md`](CHANGELOG.md).

### What changed

- **Invalid PDF versions are now reported.** A declared version that does
  not exist (only 1.0 to 1.7 and 2.0 do), in the header, the Catalog or the
  XMP metadata, is reported as VERSION_INVALID, and can no longer mask a
  genuine version gap.
- **Changed or conflicting version declarations are now reported.** When
  the XMP version disagrees with the version in effect, or a later update
  altered a version declaration (as metadata tools such as ExifTool do,
  since they cannot change the header), the file is reported as
  VERSION_CONFLICT, with each revision's declarations.
- **One report for all version problems.** The Version Anachronism report
  lists all three version findings, with a new Type column.

### Upgrading

Replace the application folder with the 1.0.3 package and keep your case
folders. No database migration is needed; the new finding types are added
to existing databases when they are opened. **Re-analyse** documents to
apply the new checks.

### Verifying this release

```bash
# Windows (PowerShell)
Get-FileHash PDF_Forensics_Suite_v1.0.3.zip -Algorithm SHA256

# macOS / Linux
sha256sum PDF_Forensics_Suite_v1.0.3.zip
```

The value must match the one in `SHA256SUMS.txt`. Running
`python pdf_forensics.py --version` should print `pdf_forensics 1.0.3 (build 2026-10-22b)`.

---

## Version 1.0.2

**Released:** 2026-10-22 · **Build:** 2026-10-22 · **Database schema:** revision 9 (unchanged)

The second incremental update to 1.0.0. The full change history is in
[`CHANGELOG.md`](CHANGELOG.md).

### What changed

- **Command line: wildcards on Windows.** `analyze` and `triage` now
  expand patterns such as `*.pdf` themselves, so they work in Windows cmd
  and PowerShell as they already did on macOS and Linux. Exhibit prefixes
  in square brackets work in patterns (`"[010]*.pdf"`).
- **GUI: Locked counter.** After a password retry opens a file, it moves
  from Locked to Processed (with its images). The counter is reset at the
  start of each run, and triage now sets it too.

### Upgrading

Replace the application folder with the 1.0.2 package and keep your case
folders. No database migration is needed.

### Verifying this release

```bash
# Windows (PowerShell)
Get-FileHash PDF_Forensics_Suite_v1.0.2.zip -Algorithm SHA256

# macOS / Linux
sha256sum PDF_Forensics_Suite_v1.0.2.zip
```

The value must match the one in `SHA256SUMS.txt`. Running
`python pdf_forensics.py --version` should print `pdf_forensics 1.0.2 (build 2026-10-22)`.

---

## Version 1.0.1

**Released:** 2026-10-21 · **Build:** 2026-10-21 · **Database schema:** revision 9 (unchanged)

The first incremental update to 1.0.0. The full change history is in
[`CHANGELOG.md`](CHANGELOG.md).

### What changed

- **Triage logging.** PyMuPDF's parser messages (for example "corrupt
  object stream") raised during triage are now written to the session log,
  labelled with the file or prior version that produced them, as analysis
  already did. Previously triage kept them off the terminal but did not
  log them.
- **Triage: prior versions of encrypted files.** Triage did not pass the
  password list, or the password that opened a file, to that file's prior
  versions, so a prior version of a password-protected file could not be
  opened: its metadata was missing and its status wrongly read "no
  password list supplied". A prior version is now tried first with the
  password that opened the current version, as analysis already does,
  then with the usual order and the supplied list. **Re-run triage** on
  cases with encrypted files that have prior versions. Analysis was not
  affected.
- **Triage: retry no longer replaces the spreadsheet.** When the
  end-of-run prompt re-triaged encrypted files with a password list, it
  overwrote the triage spreadsheet with only those files, losing every
  other row and the comments sheet. The retry is now merged in: the rows
  for those files (with their prior versions and comments) are updated in
  place and all other rows are kept. **If you used this prompt in 1.0.0,
  re-run triage on the full set**; the earlier spreadsheet was replaced.
- **Triage: comments from encrypted files.** Reviewer comments are now read
  from encrypted files that triage opened; previously none were.
- **Triage: no crash when nothing could be triaged.** A run (or retry) in
  which no file could be triaged no longer stops with an error, and leaves
  any existing spreadsheet unchanged.
- **Guides.** Every guide now states version 1.0.1, build 2026-10-21. Six
  in-app guides wrongly said "Released under the MIT License" on the
  cover; they now state the Apache License, Version 2.0, which is the
  application's license. No licensing terms changed.

### Upgrading

Replace the application folder with the 1.0.1 package and keep your case
folders. No database migration is needed: 1.0.0 databases open in 1.0.1
unchanged, and reports regenerated from them record build 2026-10-21.

### Verifying this release

```bash
# Windows (PowerShell)
Get-FileHash PDF_Forensics_Suite_v1.0.1.zip -Algorithm SHA256

# macOS / Linux
sha256sum PDF_Forensics_Suite_v1.0.1.zip
```

The value must match the one in `SHA256SUMS.txt`. Running
`python pdf_forensics.py --version` should print `pdf_forensics 1.0.1 (build 2026-10-21)`.

The known limitations and planned work listed for 1.0.0 below still apply.

---

## Version 1.0.0

**Released:** 2026-10-21 · **Build:** 2026-10-20 · **Database schema:** revision 9

First frozen release of the PDF Forensics Suite. Changes after this release
are issued as incremental updates (1.0.1, 1.0.2, …), each with its own build
date. The full change history is in [`CHANGELOG.md`](CHANGELOG.md).

### What 1.0 does

- **Detects alteration and concealment:** text overlays (annotations, stacked
  box-and-replace annotations, white boxes with painted text, text over text),
  image overlap, off-page and soft-mask concealment, DPI anomalies, font
  inconsistencies, version anachronism, unapplied redactions, modification
  after signing, and structural problems.
- **Analyses document history:** metadata, creator/producer, XMP and
  timeline checks; incremental updates, with genuine prior versions validated,
  extracted and analysed.
- **Accounts for every file:** each submitted file is recorded as analysed,
  identical copy of another file, encrypted and not opened, failed, or not
  found. Duplicates are noted on every report.
- **Opens encrypted PDFs** with a password list the examiner supplies, and
  records the outcome and the password that opened each file.
- **Reports:** 21 HTML reports, the Visual Overlay Report, relationship
  graphs, triage and Document Risk Overview spreadsheets, and a case index
  with a manifest of every output and its MD5.

### Requirements

Python 3.9 or newer, and the packages in `requirements.txt` (PyMuPDF, pikepdf,
Pillow, networkx, pyvis, openpyxl). See [`README.md`](README.md) for
installation and usage.

### Verifying this release

The release package is accompanied by a `SHA256SUMS.txt` file. To confirm
you have the unaltered release:

```bash
# Windows (PowerShell)
Get-FileHash PDF_Forensics_Suite_v1.0.0.zip -Algorithm SHA256

# macOS / Linux
sha256sum PDF_Forensics_Suite_v1.0.0.zip
```

The value must match the one in `SHA256SUMS.txt`. Running
`python pdf_forensics.py --version` should print `pdf_forensics 1.0.0 (build 2026-10-20)`.

### Known limitations

- Findings are leads to verify, not determinations; confirm each one
  independently before relying on it.
- On OCR-converted documents, tightly spaced OCR text can still produce some
  text-over-text findings. The detector was deliberately not tuned further, to
  avoid missing genuine overwrites.
- Large documents with many overlays take time in the Visual Overlay Report;
  a speed-up is planned for a later version.
- Tables of contents in the Word guides are refreshed in Word (right-click,
  Update Field, Update entire table).

### Planned for later versions

Parallel processing of batches; a faster Visual Overlay Report; an Examiner
Summary report; reassessment of OCR false positives; a producer-fingerprint
corpus; post-OCR edit detection; and optional AI-assisted analysis.
