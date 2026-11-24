"""
Entry point for python -m pdf_forensics.
"""

from pdf_forensics.cli import main_cli

if __name__ == "__main__":
    # Required for parallel analysis in a packaged executable (PyInstaller):
    # worker processes start from this file and must not open the app.
    import multiprocessing
    multiprocessing.freeze_support()
    main_cli()
