#!/usr/bin/env python3
"""
PDF Forensics Suite — launcher script.

Delegates to the pdf_forensics package.

Usage:
  python pdf_forensics.py                          # Launch GUI
  python pdf_forensics.py analyze file.pdf [...]   # CLI analysis
  python pdf_forensics.py graph db.db              # CLI graph
  python pdf_forensics.py --version                # Print version
"""

from pdf_forensics.cli import main_cli

if __name__ == "__main__":
    main_cli()
