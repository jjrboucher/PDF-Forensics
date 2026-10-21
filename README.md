# PDF Forensics

![Application: Apache 2.0](https://img.shields.io/badge/Application-Apache_2.0-blue.svg)
![Course & Guide: CC BY 4.0](https://img.shields.io/badge/Course_%26_Guide-CC_BY_4.0-lightgrey.svg)
![Application version](https://img.shields.io/badge/app-v1.0.0-informational)
![Course version](https://img.shields.io/badge/course-0.9_pre--release-orange)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)

A free, open toolkit and training package for the forensic examination of PDF
documents. This repository brings together three companion pieces:

| Component | What it is | Location | Status |
|---|---|---|---|
| **PDF Forensics Suite** | A desktop and command-line application that examines PDFs for signs of alteration and produces reports, graphs, spreadsheets and a case index | [`Application/`](Application) | v1.0.0 (build 2026-10-20) |
| **PDF Forensics Examiner Course** | A self-paced, browser-based course with lessons, hands-on labs, quizzes, a capstone exercise, a final assessment and a certificate | [`Course/`](Course) | 0.9 pre-release (beta review) |
| **Technical Reference Guide** | An in-depth guide to PDF structure, detection logic, risk scoring, false positives, counter-verification and chain of custody | [`PDF_Forensics_Technical_Guide.docx`](PDF_Forensics_Technical_Guide.docx) | v1.2 (applies to Suite v1.0.0) |

The application tells you **where to look**; the course teaches you **how to
look** with independent tools; the guide explains **why** each finding matters
and how to verify it.

> **Findings are leads, not determinations.** Nothing in this repository makes
> conclusions about a document's authenticity or anyone's intent. Every finding
> should be independently verified by a qualified examiner, using a second
> method, before it is relied upon.

## Contents

- [Repository layout](#repository-layout)
- [PDF Forensics Suite (application)](#pdf-forensics-suite-application)
- [PDF Forensics Examiner Course](#pdf-forensics-examiner-course)
- [Technical Reference Guide](#technical-reference-guide)
- [Producer corpus (under development)](#producer-corpus-under-development)
- [Verifying downloads](#verifying-downloads)
- [Licensing](#licensing)
- [Disclaimer](#disclaimer)
- [Author](#author)

## Repository layout

```
PDF-Forensics/
├── README.md                              This file
├── PDF_Forensics_Technical_Guide.docx     Technical Reference Guide (CC BY 4.0)
├── Corpus (under development).xlsx        Creator/Producer reference data (work in progress)
├── Application/                           PDF Forensics Suite (Apache 2.0)
│   ├── README.md                          Full application documentation
│   ├── RELEASE_NOTES.md · CHANGELOG.md
│   ├── LICENSE · NOTICE · SHA256SUMS.txt
│   ├── requirements.txt
│   ├── pdf_forensics.py                   Entry point (GUI or CLI)
│   ├── pdf_forensics/                     Application package
│   └── Documentation/                     User guides (.docx)
└── Course/                                PDF Forensics Examiner Course (CC BY 4.0)
    ├── README.md                          Course documentation
    ├── LICENSE                            CC BY 4.0 legal code (course and guide)
    ├── Beta_Feedback_Form.docx            Form for beta reviewers
    └── html/                              The course itself; open html/index.html
```

## PDF Forensics Suite (application)

The Suite analyses one or more PDFs and flags indicators of alteration and
concealment, including text overlays (annotation, white-box and text-over-text),
hidden, overlapping, off-page and reused images, metadata and timeline
inconsistencies, incremental updates (with prior versions extracted and
analysed), font and version anomalies, unapplied redactions and modification
after signing. Results are stored in a SQLite database and presented as 21
interactive HTML reports, a Visual Overlay Report, image-relationship graphs,
Excel triage and risk spreadsheets, and a case index with an MD5 manifest of
every output. Source files are only ever read, never modified.

### Quick start

Requires Python 3.9 or newer.

```bash
git clone https://github.com/jjrboucher/PDF-Forensics.git
cd PDF-Forensics/Application

# (Recommended) create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# Launch the graphical interface
python pdf_forensics.py

# ...or use the command line
python pdf_forensics.py --help
python pdf_forensics.py --case 2026-0001 analyze file1.pdf file2.pdf -o /path/to/case
```

See [`Application/README.md`](Application/README.md) for the full feature
list, every command and option, the list of reports, the case folder layout,
handling of encrypted PDFs and guidance for large batches. User guides
(getting started, risk scoring, HTML reports and graph reports, each in a
technical and a plain-language edition) are in
[`Application/Documentation/`](Application/Documentation).

## PDF Forensics Examiner Course

A hands-on course for digital forensic examiners that teaches PDF analysis
from first principles using free, independent tools (qpdf, mutool, peepdf-3,
ExifTool and a hex editor), so that examiners can verify by hand what an
automated tool reports. No prior PDF knowledge is required.

| Module | Topic |
|---|---|
| 00 | Setup & Orientation |
| 01 | PDF Internals |
| 02 | Document Metadata |
| 03 | Incremental Updates |
| 04 | Image Manipulation |
| 05 | Text Overlay Detection |
| 06 | EXIF, GPS & Comments |
| 07 | Capstone Exercise |
| 🏆 | Final Assessment and Certificate of Completion |

The course is a set of static HTML pages with no server or internet connection
required. To start, open [`Course/html/index.html`](Course/html/index.html) in
a browser. See [`Course/README.md`](Course/README.md) for module details, lab
files, completion rules and how to run it locally or host it.

The course is in **beta review** and has not yet been released as version 1.0.

## Technical Reference Guide

[`PDF_Forensics_Technical_Guide.docx`](PDF_Forensics_Technical_Guide.docx)
(version 1.2, applies to PDF Forensics Suite v1.0.0, build 2026-10-20) is the
in-depth companion to both the application and the course. It covers the
applicable standards, a PDF structure primer, every artifact the Suite
analyses and its detection logic, risk scoring, known false positives,
counter-verification procedures and chain-of-custody considerations.

## Producer corpus (under development)

[`Corpus (under development).xlsx`](<Corpus (under development).xlsx>) collects
Creator, Producer and Title values observed in real-world PDFs. It is the start
of a producer-fingerprint corpus planned for a later version of the Suite and
is not yet used by the application.

## Verifying downloads

[`Application/SHA256SUMS.txt`](Application/SHA256SUMS.txt) lists the SHA-256
hashes of the application release package and the Technical Reference Guide.

```bash
# macOS / Linux
sha256sum PDF_Forensics_Technical_Guide.docx

# Windows (PowerShell)
Get-FileHash PDF_Forensics_Technical_Guide.docx -Algorithm SHA256
```

The value must match the one in `SHA256SUMS.txt`. After installing the
application, `python pdf_forensics.py --version` should print
`pdf_forensics 1.0.0 (build 2026-10-20)`.

## Licensing

This repository uses two licenses:

- **Application** (everything in [`Application/`](Application)): the
  [Apache License, Version 2.0](Application/LICENSE). See also
  [`Application/NOTICE`](Application/NOTICE).
- **Course and Technical Reference Guide** (everything in
  [`Course/`](Course) and `PDF_Forensics_Technical_Guide.docx`): the
  [Creative Commons Attribution 4.0 International License (CC BY 4.0)](Course/LICENSE)
  ([summary](https://creativecommons.org/licenses/by/4.0/)).

Suggested attribution for the course or guide:

> "PDF Forensics Examiner Course" (or "PDF Forensics Technical Reference
> Guide") by Jacques Boucher, used under CC BY 4.0. Source:
> github.com/jjrboucher/PDF-Forensics

## Disclaimer

The application, course and guide are provided free of charge and "as is,"
without warranty of any kind, express or implied, including warranties of
accuracy, reliability, merchantability or fitness for a particular purpose.
They are intended to assist, not replace, a qualified examiner's judgment. The
examiner, not the author, is responsible for any conclusions drawn from their
use and for any report or testimony based on them. Because the materials are
distributed free of charge, the author accepts no liability for damages of any
kind arising from their use. This disclaimer supplements the warranty and
liability terms of the Apache 2.0 and CC BY 4.0 licenses. The full disclaimer
appears in the application's README, in the course's
[License & Disclaimer](Course/html/license/index.html) page and in the
Technical Reference Guide.

## Author

- **Author:** Jacques Boucher
- **Email:** jjrboucher@gmail.com
- **Repository:** <https://github.com/jjrboucher/PDF-Forensics>
