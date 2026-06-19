"""
pdf_forensics/disclaimers.py
Approved, final disclaimer and authorship text for the PDF Forensics Suite.

The wording in this module is final and approved and is shared verbatim with
the companion course and Technical Reference Guide so all three deliverables
stay consistent. Do not reword these strings; they are used in the GUI
first-run acknowledgment, the GUI About dialog, the CLI startup banner, and
(as reference) the repository LICENSE/NOTICE/README files.
"""

# ---------------------------------------------------------------------------
# SHORT disclaimer — first-run acknowledgment / CLI banner
# ---------------------------------------------------------------------------
SHORT_DISCLAIMER = (
    "USE AT YOUR OWN RISK. This software is provided free of charge, "
    "\"as is,\" with no warranty of any kind. Every reasonable effort has "
    "been made to ensure its reliability and accuracy, but none is "
    "guaranteed. You are solely responsible for independently verifying any "
    "finding before relying on it, and for any loss of data, time, or other "
    "consequence arising from your use of this software. Because this "
    "software is distributed at no cost, no monetary remedy is available in "
    "connection with its use."
)

# One-line permanent reminder for the status bar (after first acknowledgment).
FOOTER_REMINDER = "Use at your own risk \u2014 see About for full disclaimer"

# ---------------------------------------------------------------------------
# MEDIUM disclaimer — README.md
# ---------------------------------------------------------------------------
MEDIUM_DISCLAIMER = (
    "This software is provided free of charge and \"as is,\" without "
    "warranty of any kind, express or implied, including but not limited to "
    "warranties of accuracy, reliability, merchantability, or fitness for a "
    "particular purpose. Every reasonable effort has been made to ensure the "
    "software performs reliably and produces accurate results, but no "
    "assurance or guarantee is given that it is free of errors or that its "
    "output is complete or correct.\n\n"
    "You assume all risk arising from your use of this software, including "
    "but not limited to any loss of data, corruption of source files, or "
    "reliance on an incorrect or incomplete finding. As with any forensic "
    "tool, every finding produced by this software should be independently "
    "verified using a second method before being relied upon in a report, "
    "examination, or proceeding.\n\n"
    "Because this software is distributed free of charge, the author accepts "
    "no liability for damages of any kind arising from its use, and no "
    "monetary remedy is available. This disclaimer is in addition to, and "
    "does not limit, the warranty disclaimer and limitation of liability set "
    "out in the Apache License 2.0 under which this software is distributed."
)

# ---------------------------------------------------------------------------
# FULL disclaimer — GUI About dialog
# ---------------------------------------------------------------------------
FULL_DISCLAIMER_TITLE = "DISCLAIMER AND LIMITATION OF LIABILITY"

FULL_DISCLAIMER = (
    "The PDF Forensic Suite (the \"Software\") and its accompanying course "
    "and Technical Reference Guide (the \"Materials\") are made available "
    "free of charge to the digital forensics community. They are provided "
    "\"as is,\" without warranty of any kind, whether express or implied, "
    "including without limitation any warranty of accuracy, completeness, "
    "reliability, merchantability, or fitness for a particular purpose.\n\n"
    "Every reasonable effort has been made in the design and testing of the "
    "Software to ensure that its detection logic, risk scoring, and "
    "reporting are accurate and reliable. No assurance is given, however, "
    "that the Software is free of defects, that its findings are complete, "
    "or that its output will be accurate in every case or file. PDF is a "
    "large and varied specification, real-world documents are frequently "
    "non-conformant with it, and any automated tool \u2014 this one included "
    "\u2014 can produce incomplete, mistaken, or misleading results on a "
    "given file.\n\n"
    "For this reason, the Software is intended to assist, not replace, a "
    "qualified examiner's own judgment. Findings produced by the Software "
    "should be treated as leads for further investigation, not as "
    "conclusions, and should be independently verified by the examiner using "
    "a second method before being relied upon in any report, examination, or "
    "legal proceeding.\n\n"
    "The examiner using the Software, not its author, bears sole "
    "responsibility for the conclusions drawn from its output and for the "
    "accuracy of any report or testimony based upon it.\n\n"
    "By using the Software or Materials, you accept all risk associated with "
    "that use, including but not limited to: loss, corruption, or unintended "
    "modification of source files; reliance on an incomplete or inaccurate "
    "finding; and any consequence, financial, evidentiary, or otherwise, "
    "arising from the Software's use or inability to use. Because the "
    "Software and Materials are distributed free of charge, no payment has "
    "been made by any user in connection with their use, and accordingly no "
    "monetary remedy or damages of any kind are available against the author "
    "in connection with their use.\n\n"
    "This disclaimer supplements, and does not limit or replace, the "
    "warranty disclaimer and limitation of liability provisions of the "
    "Apache License 2.0 (governing the Software) and the Creative Commons "
    "Attribution 4.0 International License (governing the accompanying course "
    "and Technical Reference Guide), under which these materials are "
    "respectively distributed."
)

# ---------------------------------------------------------------------------
# Authorship / contact block — About dialog and README
# ---------------------------------------------------------------------------
AUTHOR_NAME = "Jacques Boucher"
AUTHOR_EMAIL = "jjrboucher@gmail.com"
REPO_URL = "https://github.com/jjrboucher/PDF-Forensics/"
LICENSE_NAME = "Apache License, Version 2.0"

AUTHORSHIP_BLOCK = (
    f"Author: {AUTHOR_NAME}\n"
    f"Email: {AUTHOR_EMAIL}\n"
    f"Repository: {REPO_URL}\n"
    f"License: {LICENSE_NAME} \u2014 see LICENSE file"
)
