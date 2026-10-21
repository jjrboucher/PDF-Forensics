# PDF Forensics Suite — Release Notes

## Version 1.0.0

**Released:** 2026-10-21 · **Build:** 2026-10-20 · **Database schema:** revision 8

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
