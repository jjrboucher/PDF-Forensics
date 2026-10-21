# PDF Forensics Examiner Course

![License: CC BY 4.0](https://img.shields.io/badge/License-CC_BY_4.0-lightgrey.svg)
![Version](https://img.shields.io/badge/version-0.9_pre--release-orange)
![Format](https://img.shields.io/badge/format-static_HTML-informational)

A self-paced, hands-on course that trains digital forensic examiners to detect,
analyse and document forensic artifacts in PDF documents, and to present those
findings in a court-ready way.

Every technique is taught with free, independent tools (qpdf, mutool, peepdf-3,
ExifTool and a hex editor) rather than with the PDF Forensics Suite itself. The
aim is that an examiner can confirm by hand anything an automated tool
reports, which is exactly the second-method verification a forensic finding
needs.

> **Status: beta review.** The course is at version 0.9 (pre-release) and has
> not yet been signed off as version 1.0. Content may change before release.

## Contents

- [Getting started](#getting-started)
- [Prerequisites](#prerequisites)
- [Required tools](#required-tools)
- [Modules](#modules)
- [Lab files](#lab-files)
- [Quizzes, final assessment and certificate](#quizzes-final-assessment-and-certificate)
- [Answer keys and reference](#answer-keys-and-reference)
- [Folder layout](#folder-layout)
- [For beta reviewers](#for-beta-reviewers)
- [Versioning](#versioning)
- [License and attribution](#license-and-attribution)
- [Disclaimer](#disclaimer)
- [Author](#author)

## Getting started

The course is a set of static HTML pages. There is nothing to install, no
server-side component and no internet connection required.

**Option 1: open it directly.** Open [`html/index.html`](html/index.html) in a
modern browser and choose **Start Course**.

**Option 2: serve it locally (recommended).** Some browsers isolate local
files from one another, which can stop your progress carrying from page to
page. Serving the folder avoids this:

```bash
cd Course/html
python -m http.server 8000
# then browse to http://localhost:8000/
```

**Option 3: host it.** Because the pages are static, the `html/` folder can be
published as-is on any web server or static host (for example GitHub Pages).

Your progress, quiz scores and preferences are saved in your browser's local
storage on your own computer. Nothing is sent anywhere. Clearing your browser
data, switching browsers or using a private window starts the course afresh;
the **Reset** link in the sidebar clears progress deliberately.

## Prerequisites

The course assumes a working knowledge of cryptographic hashing (MD5 and
SHA-256), byte offsets and hexadecimal notation, command-line use, and basic
file-format concepts. **No prior PDF knowledge is required**; Module 01 covers
everything you need.

## Required tools

Module 00 walks through installing and verifying each tool on Windows and on
Linux/macOS, including adding each one to the Windows PATH and building mutool
from source on Windows.

| Tool | Purpose | Install |
|---|---|---|
| Python 3.10+ | Runtime for peepdf-3 and short scripts | [python.org](https://www.python.org/downloads/) or `apt install python3` |
| peepdf-3 | Interactive PDF object inspector | `pip install peepdf-3` |
| qpdf | Stream decoding, object inspection, JSON dump | [qpdf.sourceforge.io](https://qpdf.sourceforge.io) or `apt install qpdf` |
| mutool (MuPDF) | Image extraction, object display | [mupdf.com](https://mupdf.com/releases) (build on Windows) or `apt install mupdf-tools` |
| ExifTool | EXIF and GPS metadata extraction | [exiftool.org](https://exiftool.org) or `apt install libimage-exiftool-perl` |
| Hex editor | Raw byte inspection | HxD (Windows) or `xxd` (Linux/macOS) |

On Windows, Windows Subsystem for Linux (WSL) is an alternative that installs
every tool with a single `apt install` command.

## Modules

Eight modules, followed by a final assessment. Total time is roughly eight
hours.

| # | Module | Covers | Time | Lab file |
|---|---|---|---|---|
| 00 | [Setup & Orientation](html/module_00/index.html) | Tool installation, environment verification, hashing your first PDF, forensic workflow principles | 20 min | n/a |
| 01 | [PDF Internals](html/module_01/index.html) | File structure, object model, content streams, cross-reference tables, Image vs Form XObjects | 60 min | `lab01_structure.pdf` |
| 02 | [Document Metadata](html/module_02/index.html) | Info dictionary, XMP, Creator/Producer analysis, impossible dates, Info/XMP divergence | 50 min | `lab02_metadata.pdf` |
| 03 | [Incremental Updates](html/module_03/index.html) | `%%EOF` markers, prior-version extraction, comparing versions, edit-timeline reconstruction and its limits | 50 min | `lab03_incremental.pdf` |
| 04 | [Image Manipulation](html/module_04/index.html) | BBOX_CROP, OVERLAP, OFFPAGE and DPI_ANOMALY findings; recovering hidden image content | 75 min | `lab04_images.pdf` |
| 05 | [Text Overlay Detection](html/module_05/index.html) | Annotation overlays, white-box masking, text-over-text substitution | 70 min | `lab05_textoverlay.pdf` |
| 06 | [EXIF, GPS & Comments](html/module_06/index.html) | Embedded image metadata, GPS coordinates, mixed-camera anomalies, reviewer annotations | 55 min | `lab06_exif_comments.pdf` |
| 07 | [Capstone Exercise](html/module_07/index.html) | Unassisted analysis of a multi-artifact contract, findings table, financial impact and a court-ready statement | 90 min | `lab07_capstone.pdf` |
| 🏆 | [Final Assessment](html/final/assessment.html) | 18 scenario questions that combine findings across modules | n/a | n/a |

Modules 01 to 06 each contain an overview, a lesson, a lab and a knowledge
check. Module 07 has no lesson and no hints: it is a capstone that tests
independent examination.

## Lab files

The lab PDFs are in [`html/sample_pdfs/`](html/sample_pdfs). Hash each file
before you begin, record the value in your notes, and confirm it matches the
table below, just as you would for an exhibit. Work on copies.

| File | MD5 |
|---|---|
| `lab01_structure.pdf` | `5440841e16b52738b7bdc352fda1bb1e` |
| `lab02_metadata.pdf` | `d2199d83e50edbdde67b4d5940b665b7` |
| `lab03_incremental.pdf` | `57fe4a57a80043fa8654cf7be9ea8603` |
| `lab04_images.pdf` | `350f99d17a897348ff0080d2755b10c2` |
| `lab05_textoverlay.pdf` | `d28ca040172c8abb1499a59bb265d229` |
| `lab06_exif_comments.pdf` | `4430ead9f72e5d2fbfe1d80b6b3b1aa9` |
| `lab07_capstone.pdf` | `f6a8282914f633ee465866c47e1229ad` |

```bash
md5sum html/sample_pdfs/*.pdf                                   # Linux / macOS (macOS: md5)
Get-FileHash -Algorithm MD5 html\sample_pdfs\*.pdf              # Windows PowerShell
```

## Quizzes, final assessment and certificate

- **Knowledge checks.** Modules 01 to 07 each end with a quiz (5 to 10
  questions). A score of **70% or higher** passes the module. Quizzes can be
  retaken.
- **Progression.** Modules are meant to be taken in order. A module after one
  you have not yet passed shows a warning, but remains open.
- **Final assessment.** 18 questions, each requiring you to combine findings
  from two or more modules. It becomes available once every module is passed,
  requires **70% or higher**, has no time limit and can be retaken.
- **Certificate.** After passing every module quiz and the final assessment,
  the [certificate page](html/final/certificate.html) lets you enter your name
  and print or save a Certificate of Completion as a PDF. The certificate
  documents course completion and assessed knowledge; it is **not** accredited
  Continuing Education (CE) credit.

## Answer keys and reference

The [Course Reference](html/reference/index.html) page contains:

- **Answer keys** for every lab, as a readable walkthrough (HTML) and as raw
  JSON. Complete each lab, and especially the capstone, before opening its key.
- A **quick command reference** for hashing, counting `%%EOF` markers,
  extracting images, decoding streams and using peepdf interactively.
- Project, source and package links for every tool used in the course.

The [Technical Reference Guide](../PDF_Forensics_Technical_Guide.docx) in the
repository root is the course's companion document, covering detection logic,
risk scoring, chain of custody and the standards landscape in more depth.
Several course pages point to sections of it for further reading.

## Folder layout

```
Course/
├── README.md                  This file
├── Beta_Feedback_Form.docx    Reviewer feedback form (beta only)
└── html/
    ├── index.html             Course home: start here
    ├── CHANGELOG.md           Course version history
    ├── assets/                Stylesheet, scripts, logos and images
    │   └── js/course-version.js   Course version number and date
    ├── module_00/ … module_07/    Overview, lesson, lab and quiz pages per module
    ├── final/                 Final assessment and certificate
    ├── reference/             Answer keys (HTML and JSON) and quick reference
    ├── sample_pdfs/           The seven lab PDFs
    └── license/               License, authorship and disclaimer
```

## For beta reviewers

Thank you for reviewing the course. Please record your feedback on
[`Beta_Feedback_Form.docx`](Beta_Feedback_Form.docx), one copy per reviewer.
The form highlights the areas most in need of an experienced examiner's view
(the Module 04 image-finding categories, the Module 02 metadata anomaly
reasoning, Module 03's incremental-update coverage and the quality of the
final assessment questions), followed by a per-module rating and comments.
Specific references (module, page, exercise or question number) are the most
useful.

## Versioning

The course version and date are defined in one place,
[`html/assets/js/course-version.js`](html/assets/js/course-version.js), and
every change of version is recorded in
[`html/CHANGELOG.md`](html/CHANGELOG.md).

- The course stays pre-release (below 1.0) until the owner signs off on a
  complete, deployment-ready version; 1.0 is the first distributable version.
- After 1.0, the version changes only on explicit sign-off of a frozen
  version: a minor bump (1.1, 1.2, …) for fixes and clarifications, a major
  bump (2.0, 3.0, …) for substantial new content or structural changes.
- The date recorded is the date a version was accepted and frozen, not the
  date individual edits were made.

## License and attribution

This course (all modules, labs, the final assessment and the certificate) is
licensed under the
[Creative Commons Attribution 4.0 International License (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).
You may share and adapt it for any purpose, including commercially, provided
you give appropriate credit, link to the license and indicate any changes.
You may not suggest the author endorses you or your use.

Suggested attribution:

> "PDF Forensics Examiner Course" by Jacques Boucher, used under CC BY 4.0.
> Source: github.com/jjrboucher/PDF-Forensics

The PDF Forensics Suite application in [`../Application`](../Application) is
licensed separately under the Apache License, Version 2.0.

## Disclaimer

The course is provided free of charge and "as is," without warranty of any
kind. It is intended to support, not replace, a qualified examiner's own
judgment. Techniques taught here produce leads that must be independently
verified before being relied upon in any report, examination or proceeding,
and the examiner bears sole responsibility for conclusions drawn. The full
disclaimer is on the course's
[License & Disclaimer](html/license/index.html) page.

## Author

- **Author:** Jacques Boucher
- **Email:** jjrboucher@gmail.com
- **Repository:** <https://github.com/jjrboucher/PDF-Forensics>
