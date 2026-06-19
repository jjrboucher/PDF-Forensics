# PDF Forensics Suite

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

A forensic analysis toolkit for PDF documents. The PDF Forensics Suite
examines one or more PDFs for signs of manipulation — overlaid or hidden
content, reused images, inconsistent metadata, incremental-update history,
and more — scores each finding by risk, and produces human-readable HTML
reports, relationship graphs, and Excel triage spreadsheets to support a
digital forensic examination.

It can be run as a desktop application with a graphical interface, or
headlessly from the command line for scripted and batch workflows.

## Features

- **Forensic analysis** of PDFs: text/image overlay detection (annotation,
  white-box masking, and text-over-text alterations), overlapping and
  off-page images, soft-mask concealment, DPI/resolution anomalies, and
  metadata, creator/producer, and incremental-update (`%%EOF`) analysis.
- **Before/after overlay reveal** that reconstructs what an overlay hides,
  where the underlying content is recoverable.
- **Reviewer comment extraction** from markup annotations (sticky notes,
  text boxes, highlights, etc.).
- **Risk scoring** of findings to help prioritize review.
- **HTML reports** (including a Text Overlay report and a Manipulation
  Detail report with object/stream locators for independent validation),
  **relationship graphs** of reused images across documents, and an
  **Excel triage** workbook.
- Results are stored in a SQLite database for repeatable, auditable review.

## Requirements

- Python 3.9 or newer
- The Python packages listed in [`requirements.txt`](requirements.txt):
  PyMuPDF, pikepdf, Pillow, networkx, pyvis, and openpyxl.

## Installation

```bash
# Clone the repository
git clone https://github.com/jjrboucher/PDF-Forensics.git
cd PDF-Forensics

# (Recommended) create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Graphical interface

Launch the desktop application:

```bash
python pdf_forensics.py
```

On first launch you will be asked to read and acknowledge a short
disclaimer, then to enter a case number. All output files are organized
under that case. From the main menu you can run analysis, build graphs, and
generate reports.

### Command line

```bash
# Analyze one or more PDFs into a case database
python pdf_forensics.py analyze file1.pdf file2.pdf -o /path/to/case_output

# Quick triage of PDFs into an Excel workbook
python pdf_forensics.py triage *.pdf -o triage.xlsx

# Generate HTML reports from a database (use --list to see report IDs)
python pdf_forensics.py report case.db --list
python pdf_forensics.py report case.db -r all -o /path/to/reports

# Build a relationship graph of reused images
python pdf_forensics.py graph case.db -o graph.html

# Print the version
python pdf_forensics.py --version
```

Run any subcommand with `-h`/`--help` for its full set of options.

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

Licensed under the Apache License, Version 2.0. You may obtain a copy of the
License in the [`LICENSE`](LICENSE) file or at
<http://www.apache.org/licenses/LICENSE-2.0>. See the [`NOTICE`](NOTICE) file
for attribution.

The accompanying course and Technical Reference Guide are distributed
separately under the Creative Commons Attribution 4.0 International License
(CC BY 4.0).

## Author

- **Author:** Jacques Boucher
- **Email:** jjrboucher@gmail.com
- **Repository:** <https://github.com/jjrboucher/PDF-Forensics/>
- **License:** Apache License, Version 2.0 — see [`LICENSE`](LICENSE)
