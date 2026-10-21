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

- Module 00 lab: the "Download Lab File" button now downloads
  `sample_pdfs/lab_files.zip` (all seven lab PDFs) instead of linking to the
  `sample_pdfs/` folder, and the panel shows the ZIP's MD5.
- Added `reference/manifest.json` listing the size, page count, MD5 and
  SHA-256 of every lab PDF and of the ZIP package. Module 00 now links to it
  and Step 2 asks learners to verify each hash against it.
- Added `Course/LICENSE` containing the full CC BY 4.0 legal code.
