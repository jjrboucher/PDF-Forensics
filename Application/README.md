# PDF Forensics Suite

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
![Version](https://img.shields.io/badge/version-1.0.3-informational)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)

A forensic analysis toolkit for PDF documents. The PDF Forensics Suite examines
one or more PDFs for signs of alteration: overlaid or hidden content, reused
images, inconsistent metadata, incremental-update history and more. It scores
what it finds, and produces self-contained HTML reports, relationship graphs,
Excel spreadsheets and a case index to support a digital forensic examination.

It runs as a desktop application with a graphical interface, or headlessly from
the command line for scripted and batch work.

> **The tool points the examiner to where to look; it does not make
> determinations.** Its findings and risk scores are leads to verify, not
> conclusions about authenticity or intent. Every finding should be confirmed
> independently before it is relied upon.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start (graphical interface)](#quick-start-graphical-interface)
- [Command line](#command-line)
- [Reports](#reports)
- [Case folder layout](#case-folder-layout)
- [Working with large batches](#working-with-large-batches)
- [Encrypted PDFs](#encrypted-pdfs)
- [Documentation](#documentation)
- [Forensic handling](#forensic-handling)
- [Versioning](#versioning)
- [Disclaimer](#disclaimer)
- [License](#license)
- [Author](#author)

## Features

**Alteration and concealment**
- Text overlay detection: annotations placed over page text (including a
  covering box stacked with a replacement-text annotation), white boxes drawn
  over content with new text painted on them, and text drawn over other text.
- Visual Overlay Report: each affected page shown as layers you can switch on
  and off, from the page as received to the original content underneath, with
  white-box alterations shown step by step. A self-check verifies that the
  layers reproduce the page as received; if they do not, the page is shown as
  received rather than as a possibly misleading reconstruction.
- Image analysis: overlapping and off-page images, soft-mask concealment,
  DPI/resolution anomalies, and cross-document image reuse.
- Font consistency analysis, unapplied redactions, and PDF version checks:
  versions that do not exist, version declarations that disagree or were
  changed by a later update, and features newer than the version a file
  declares.

**Document history and provenance**
- Metadata, creator/producer and XMP analysis, with timeline anomaly checks.
- Incremental-update (`%%EOF`) analysis, with **prior versions** extracted and
  analysed in their own right. Each candidate is validated first: a linearized
  file's first-page section and fragments that are not usable PDFs are reported
  as such rather than treated as earlier versions.
- Signature coverage (modified after signing) and structural integrity checks.

**Accounting for every file**
- Every submitted file is recorded with its outcome: analysed, identical copy
  of a file already analysed, encrypted and not opened, failed, or not found.
- Byte-identical copies submitted under different names are detected and listed
  (Duplicate Submissions report); every other report notes them so they are not
  mistaken for missed files.
- Password-protected PDFs can be opened with a list of candidate passwords you
  supply (see [Encrypted PDFs](#encrypted-pdfs)).

**Outputs**
- 21 interactive HTML reports (sortable, filterable, exportable to CSV).
- Relationship graphs of reused images across pages and documents.
- Excel triage spreadsheet and a Document Risk Overview spreadsheet.
- A **case index**: one landing page linking to every output for the case, with
  a manifest of output files and their MD5 hashes.
- All results stored in a SQLite database for repeatable, auditable review.

## Requirements

- Python 3.9 or newer
- The packages in [`requirements.txt`](requirements.txt): PyMuPDF, pikepdf,
  Pillow, networkx, pyvis and openpyxl.

## Installation

```bash
git clone https://github.com/jjrboucher/PDF-Forensics.git
cd PDF-Forensics/Application

# (Recommended) create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

## Quick start (graphical interface)

```bash
python pdf_forensics.py
```

1. On first launch you are asked to read and acknowledge a short disclaimer.
   The acknowledgement is recorded (date, user, computer and disclaimer
   version) and written to every session log.
2. Enter a case number. All output for the session is organised under it.
3. **Analyse PDFs:** add files with *Add files*, *Add folder* or *From list*,
   optionally choose a *Password list…*, and run the analysis (or run a quick
   triage instead).
4. **Generate reports and graphs** from the resulting database.
5. Open the **case index** (`{case}_index.html` in the results folder) as the
   starting point for review.

## Command line

Run `python pdf_forensics.py <command> --help` for the full options of any
command. `python pdf_forensics.py --version` prints the version and build.

| Command | Purpose |
|---|---|
| `analyze` | Full forensic analysis of PDFs into a case database |
| `triage` | Fast scan of PDFs into an Excel spreadsheet |
| `report` | Generate HTML reports from a case database |
| `graph` | Generate an image-relationship graph from a case database |

```bash
# Full analysis into a case folder (with a case number for the session)
python pdf_forensics.py --case 2026-0001 analyze file1.pdf file2.pdf -o /path/to/case

# Analyse the files named in a text file, trying a list of candidate passwords
python pdf_forensics.py --case 2026-0001 analyze -l selected.txt -p passwords.txt -o /path/to/case

# Fast triage to Excel
python pdf_forensics.py --case 2026-0001 triage *.pdf -o triage.xlsx

# List report IDs, then generate all reports (or selected ones) plus the visual report
python pdf_forensics.py report case.db --list
python pdf_forensics.py --case 2026-0001 report case.db --visual -o /path/to/reports
python pdf_forensics.py --case 2026-0001 report case.db -r metadata text_overlay

# Relationship graph (scope: all_placements, cross_page or cross_document)
python pdf_forensics.py --case 2026-0001 graph case.db -s cross_document -o graph.html
```

Wildcards such as `*.pdf` work on every platform: on Windows (cmd and
PowerShell), where the shell does not expand them, the application expands
them itself. Quote a pattern that contains spaces, for example
`"Exhibits\[010]*.pdf"`; square brackets in file names are matched
literally.

Key options:

| Option | Commands | Meaning |
|---|---|---|
| `-l`, `--pdf-list` | analyze, triage | Text file of PDF paths, one per line |
| `-p`, `--password-list` | analyze, triage | Text file of candidate passwords, one per line |
| `-o` | all | Output folder (analyze, report) or file (triage, graph) |
| `-d`, `--database` | analyze | Database path |
| `--force` | analyze | Re-analyse files already in the database |
| `--no-store-images` | analyze | Do not store image data in the database |
| `--no-prior-versions` | triage | Do not add rows for prior versions |
| `-r`, `--reports` | report | Report IDs to generate (default: all) |
| `--visual` | report | Also generate the Visual Overlay Report |
| `-s`, `--scope` | graph | `all_placements`, `cross_page` or `cross_document` |
| `--separate-versions` | graph | Treat prior versions as separate documents |

## Reports

| Group | Reports |
|---|---|
| Document Overview & Provenance | Encrypted Files · Document Risk Summary · Document Risk Dossier · PDF Metadata · Creator / Producer Analysis · EXIF & GPS Data · Incremental Updates (%%EOF Analysis) · Version Anachronism |
| Manipulation & Alteration | Concealment Overview · Manipulation Detail · Text Overlay Detection · Font Consistency Analysis · Overlap & Concealment Detail · DPI / Resolution Analysis |
| Image Analysis | High-Risk Images · Off-Page Images · Stamp / Signature Reuse Candidates |
| Cross-Document & Review | Duplicate Submissions · Cross-Document Image Reuse · Document Comparison Matrix · Document Comments |

Also produced: the **Visual Overlay Report**, the **Document Risk Overview**
spreadsheet, the **triage** spreadsheet, relationship **graphs**, and the
**case index**. Each report states the version and build that produced it and
the database it was built from.

## Case folder layout

```
<case folder>/
├── {case}_index.html                 Case index: start here
├── {case}_forensics_{timestamp}.db   Analysis database (one per analysis run)
├── reports/                          HTML reports and spreadsheets
├── graph_reports/                    Relationship graphs
├── extracted_images/                 Images extracted from each document
├── pdf_versions/                     Prior versions recovered from incremental updates
└── logs/                             Session logs (build, acknowledgement, every step)
```

The case index groups outputs by the analysis database they were produced from,
warns when one database's outputs come from more than one build, and offers
*Copy path* for files a browser cannot open (spreadsheets, databases).

## Working with large batches

- **Triage first.** Triage is fast. Review the triage spreadsheet, copy the
  *Path* column for the documents that warrant full analysis into a text file,
  and load it with *From list* (or `-l`). Exhibit-number prefixes such as
  `[010]` in file names are supported throughout.
- **Work on a local copy** of the case folder where possible. Cloud-synced
  folders (e.g. OneDrive) compete with the application for disk access.
- Untick *Store extracted images in database* (or use `--no-store-images`)
  when you do not need image data kept in the database.

## Encrypted PDFs

Encrypted PDFs are opened with passwords **you supply**; the tool does not
guess, generate or brute-force passwords, and files are only ever read.

- For each file it tries the empty password first (which opens
  *permissions-only* files), then passwords already found to work in the run,
  then your list in order.
- A prior version recovered from an encrypted file is tried first with the
  password that opened that file, since an earlier version normally shares
  its encryption, and then in the same order as above. This applies in both
  analysis and triage.
- The list is a plain text file, one password per line, read exactly as written
  (leading/trailing spaces and a leading `#` are part of the password). It is
  chosen for each run and is not kept by the application.
- If no list was supplied, or the list did not open a file, the file is set
  aside and the run continues. At the end, the application offers to try a
  password list on just those files. After a triage run, the rows for those
  files (with their prior versions and comments) are updated in the same
  triage spreadsheet, and every other row is kept.
- In triage, the reviewer comments of an encrypted file that was opened are
  extracted with the password that opened it.
- The **Encrypted Files** report lists every encrypted PDF and the password that
  opened it, or that none did. It contains passwords and should be handled with
  the same care as the password list.

## Documentation

Guides are in [`Documentation/`](Documentation):

| Guide | Audience |
|---|---|
| `00_Getting_Started.docx` | Running an analysis, step by step |
| `01a_Risk_Scoring_Technical.docx` / `01b_Risk_Scoring_Broader.docx` | How risk is scored (technical / plain language) |
| `02a_HTML_Reports_Technical.docx` / `02b_HTML_Reports_Broader.docx` | Every report explained (technical / plain language) |
| `03a_Graph_Reports_Technical.docx` / `03b_Graph_Reports_Broader.docx` | Relationship graphs (technical / plain language) |

A separate **Technical Reference Guide** covers detection logic, false
positives, counter-verification procedures and chain of custody in depth.

## Forensic handling

- **Source files are never modified.** PDFs are opened for reading only;
  prior versions are written as separate files in the case folder.
- **Everything is logged.** Each session log records the version and build,
  the disclaimer acknowledgement, the files processed, password lists used
  (path and MD5, not contents), each file's outcome, and any parser
  warnings PyMuPDF raised while analysing or triaging a file (kept off the
  terminal and labelled with the file they came from).
- **Findings are leads, not conclusions.** Soft indicators are labelled as
  such, and each report section points back to its source data so findings can
  be verified independently.
- **Reproducibility.** Every output records the build that produced it, and the
  case index records each output's MD5.

## Versioning

This is **version 1.0.3** (build 2026-10-22b), the third incremental
update to version 1.0.0, the first frozen release. Changes after 1.0 are released
as incremental updates (1.0.1, 1.0.2, …), each with its own build date.
`python pdf_forensics.py --version` prints the version and build you are
running. See [`RELEASE_NOTES.md`](RELEASE_NOTES.md) for what changed in
this release and [`CHANGELOG.md`](CHANGELOG.md) for the full history.

## Disclaimer

This software is provided free of charge and "as is," without warranty of
any kind, express or implied, including but not limited to warranties of
accuracy, reliability, merchantability, or fitness for a particular purpose.
Every reasonable effort has been made to ensure the software performs
reliably and produces accurate results, but no assurance or guarantee is
given that it is free of errors or that its output is complete or correct.

You assume all risk arising from your use of this software, including but
not limited to any loss of data, corruption of source files, or reliance on
an incorrect or incomplete finding. As with any forensic tool, every finding
produced by this software should be independently verified using a second
method before being relied upon in a report, examination, or proceeding.

Because this software is distributed free of charge, the author accepts no
liability for damages of any kind arising from its use, and no monetary
remedy is available. This disclaimer is in addition to, and does not limit,
the warranty disclaimer and limitation of liability set out in the Apache
License 2.0 under which this software is distributed.

## License

Licensed under the Apache License, Version 2.0. See the [`LICENSE`](LICENSE)
file or <http://www.apache.org/licenses/LICENSE-2.0>, and the
[`NOTICE`](NOTICE) file for attribution.

The accompanying course and Technical Reference Guide are distributed
separately under the Creative Commons Attribution 4.0 International License
(CC BY 4.0).

## Author

- **Author:** Jacques Boucher
- **Email:** jjrboucher@gmail.com
- **Repository:** <https://github.com/jjrboucher/PDF-Forensics/>
