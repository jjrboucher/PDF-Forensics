"""
Shared GUI widget helpers.
"""

import os
import sys
import tkinter as tk
from tkinter import ttk

from pdf_forensics.gui.theme import *


def make_panel(parent, label_text):
    """Create a styled panel with a section heading."""
    outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
    outer.pack(fill="x", pady=(0, 12))
    inner = tk.Frame(outer, bg=BG_PANEL)
    inner.pack(fill="x")
    ttk.Label(inner, text=label_text.upper(),
              style="Section.TLabel").pack(anchor="w", padx=14,
                                           pady=(10, 4))
    body = tk.Frame(inner, bg=BG_PANEL)
    body.pack(fill="x", padx=14, pady=(0, 12))
    return body


def stat_box(parent, label, value):
    """Create a stat display box for summary dialogs."""
    box = tk.Frame(parent, bg=BG_PANEL, padx=16, pady=12)
    box.pack(side="left", fill="x", expand=True, padx=4)
    tk.Label(box, text=str(value), bg=BG_PANEL, fg=ACCENT,
             font=(FONT_FAMILY, 18, "bold")).pack(anchor="w")
    tk.Label(box, text=label, bg=BG_PANEL, fg=TEXT_SEC,
             font=FONT_SUBTITLE).pack(anchor="w")


def open_in_file_manager(path):
    """Open a file or folder in the host file manager."""
    import subprocess
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        print(f"Could not open {path}: {e}")
