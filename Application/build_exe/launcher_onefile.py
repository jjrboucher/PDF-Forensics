"""Entry point for the single-file executable.

In a single-file build the package is unpacked to a temporary folder that is
deleted on exit, so branding saved there would be lost. This launcher points the
branding file at the folder containing the .exe instead (falling back to the
user's home folder, as the application already does, if that is not writable).
"""
import os
import sys

if getattr(sys, "frozen", False):
    from pdf_forensics import branding
    _exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    branding._PRIMARY_PATH = os.path.join(_exe_dir, "branding.json")
    # Seed the external file from the bundled default only if it does not exist
    # and the folder is writable; otherwise the home-directory fallback applies.

from pdf_forensics.cli import main_cli

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()   # parallel analysis workers
    main_cli()
