# PDF Forensics Examiner Course — Changelog

Version numbers and dates here must always match `assets/js/course-version.js`.
The date recorded for each version is the date the course owner accepted that
version as complete and froze it for distribution — not the date individual
edits were made during development.

## Versioning policy

- The course remains pre-release (no version number below 1.0 is distributed)
  until the owner explicitly signs off on a complete, deployment-ready version.
- 1.0 is the first signed-off, distributable version.
- After 1.0, a version bump happens only on explicit sign-off, not on every edit.
- Minor vs. major is the owner's call, based on the scope of what changed:
  small fixes/clarifications typically warrant a minor bump (1.1, 1.2, ...);
  substantial new content, structural changes, or theme/feature changes
  typically warrant a major bump (2.0, 3.0, ...).
- Every version bump gets an entry below summarizing what changed since
  the prior version.

---

## Unreleased (pre-1.0)

Course is in development. No version has been signed off for distribution yet.
Entries below will be consolidated into the 1.0 entry once the owner accepts
a complete version.

### Unified case scenario + lab rework (pending sign-off)

- Replaced all seven lab PDFs with a new, self-consistent exhibit set built
  around a single investigation: *Callahan Property Group v. Meridian
  Consulting LLC* (a consulting-fee dispute, original fee $8,500 inflated to
  $48,500). Each lab file still stands alone for single-module use.
  - lab01 engagement letter (clean baseline; object 2 = Info dict; DCTDecode
    image + Form XObject).
  - lab02 cover memo (metadata anomalies: Chrome/Skia Info vs Word XMP;
    impossible ModDate; Info/XMP divergence).
  - lab03 invoice with 3 revisions via incremental updates (recover $8,500
    original by truncation; FreeText annotations changing total and due date).
  - lab04 site-report figures (BBOX_CROP, OVERLAP, OFFPAGE, DPI_ANOMALY).
  - lab05 revised statement (annotation, white-box, text-over-text overlays;
    white-box total $8,500 -> $48,500, matching the case anchor).
  - lab06 site photos (EXIF: Canon scanner / Samsung+GPS Las Vegas / Fujifilm;
    reviewer annotations).
  - lab07 capstone settlement package (5 findings across all categories).
- Rewired every lab page, quiz, and answer key (JSON + HTML) to the new
  exhibits: file-panel MD5s, embedded-image MD5s, byte offsets, object numbers,
  dates, GPS coordinates, dollar figures, tool/producer strings, and scenario
  narrative all updated to match the delivered files.
- Fixed a pre-existing Module 03 answer-key contradiction (the "1 %%EOF / 0
  incremental updates" answer and a mismatched extracted-version MD5).
- Module 00 lab: the "Download Lab File" button now opens in a new browser
  window; the former "Copy MD5" button is now "Display MD5" and opens
  `sample_pdfs/md5sums.txt` (all lab files and their MD5s) in a new window.
- Added `sample_pdfs/md5sums.txt`.

Note: version left at 0.9 (pre-release) pending owner sign-off, per the
versioning policy above.

### Module 01 peepdf command fix (pending sign-off)

- Corrected the Module 01 peepdf walkthrough. The `pdf> objects` command lists
  object NUMBERS only (output: "Version 0: Objects (N): [1, 2, 3, ...]"), but the
  lab, lesson, and reference incorrectly said it also shows each object's TYPE.
  Object types come from `pdf> tree`. Reworded so `objects` is described as a
  number listing and `tree` as the command that shows types, in the lab sequence
  (info / objects / tree / metadata), the lesson, and the reference card.

### Legibility rebuild + module fixes (pending sign-off)

- **Rebuilt all seven lab PDFs for legibility.** The previous rebuild embedded
  subset fonts with a non-standard encoding that rendered as garbage in viewers.
  All seven are now generated with standard Helvetica (WinAnsiEncoding) and
  literal-string text, matching the original course's approach, so they display
  cleanly everywhere. Every planted artifact is preserved (incremental updates,
  BBOX_CROP/overlap/off-page/DPI images, text overlays, EXIF/GPS, metadata
  anomalies), and all new MD5s, byte offsets, and image hashes were re-propagated
  to md5sums.txt, lab panels, quizzes, and answer keys.
- **Module 00:** MuPDF instructions now specify MuPDF (not PyMuPDF), the latest
  .tar.gz source, and extraction; step 3 clarifies the relative path from the
  extract location; step 5 reminds the user to prepend their base path. ExifTool
  instructions now cover the Windows 64-bit download, unzip, and the
  exiftool(-k).exe -> exiftool.exe rename. Per-module lab download buttons now
  force a download instead of opening inline.
- **Module 01:** fixed the byte-offset structure diagram (now preserves line
  breaks); added the expected SHA-256 to Exercise 1; converted the peepdf/qpdf
  object-number placeholders to a readable "{...} from previous command" form
  with worked examples. Knowledge Check JS fixed: the Next button no longer
  sticks on "View Results" after a retry, and quiz scores now keep the best
  attempt (which resolves both the lost-retake-score and the cross-module
  "not completed" warning).
- **Module 06:** fixed a GPS hemisphere discrepancy (Exercise 2 table said
  115.1398 E; corrected to W to match Q2 and the actual Las Vegas location).
- **Module 07:** corrected the Financial Impact Summary (CAP-04 now reads
  inflated $8,500 -> $48,500 / $40,000 overstatement; CAP-03 references the
  hidden $8,500 fee) and fixed stale Dubai GPS values in the answer key and quiz.

