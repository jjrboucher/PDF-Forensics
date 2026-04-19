"""
Adobe Acrobat-inspired theme constants for the GUI.
"""

import sys


# Color palette
BG_DARK     = "#1B1B1B"
BG_PANEL    = "#252525"
BG_INPUT    = "#363636"
BG_HOVER    = "#3A3A3A"
BORDER      = "#3D3D3D"
TEXT_PRIM   = "#F0F0F0"
TEXT_SEC    = "#A8A8A8"
TEXT_DIM    = "#7A7A7A"
ACCENT      = "#ED1C24"
ACCENT_HVR  = "#FA0F00"
ACCENT_PRSS = "#B30B00"
SUCCESS     = "#4CAF50"

# Font family
if sys.platform == "win32":
    FONT_FAMILY = "Segoe UI"
elif sys.platform == "darwin":
    FONT_FAMILY = "SF Pro Text"
else:
    FONT_FAMILY = "DejaVu Sans"

FONT_BASE     = (FONT_FAMILY, 10)
FONT_BOLD     = (FONT_FAMILY, 10, "bold")
FONT_SUBTITLE = (FONT_FAMILY, 9)
FONT_SECTION  = (FONT_FAMILY, 11, "bold")


def apply_theme(style):
    """Apply the Adobe-inspired theme to a ttk.Style instance."""
    style.theme_use("clam")
    style.configure(".", background=BG_DARK, foreground=TEXT_PRIM,
                    fieldbackground=BG_INPUT, font=FONT_BASE,
                    borderwidth=0, focuscolor=ACCENT)
    style.configure("TFrame", background=BG_DARK)
    style.configure("Panel.TFrame", background=BG_PANEL)
    style.configure("TLabel", background=BG_DARK,
                    foreground=TEXT_PRIM, font=FONT_BASE)
    style.configure("Panel.TLabel", background=BG_PANEL,
                    foreground=TEXT_PRIM, font=FONT_BASE)
    style.configure("Section.TLabel", background=BG_PANEL,
                    foreground=TEXT_SEC, font=FONT_SECTION)
    style.configure("Hint.TLabel", background=BG_PANEL,
                    foreground=TEXT_DIM, font=FONT_SUBTITLE)
    style.configure("Status.TLabel", background=BG_DARK,
                    foreground=TEXT_SEC, font=FONT_SUBTITLE)
    style.configure("TEntry", fieldbackground=BG_INPUT,
                    foreground=TEXT_PRIM, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER,
                    insertcolor=TEXT_PRIM, padding=6)
    style.map("TEntry",
              bordercolor=[("focus", ACCENT)],
              lightcolor=[("focus", ACCENT)],
              darkcolor=[("focus", ACCENT)])
    style.configure("TButton", background=BG_INPUT, foreground=TEXT_PRIM,
                    bordercolor=BORDER, lightcolor=BG_INPUT,
                    darkcolor=BG_INPUT, focusthickness=0,
                    padding=(14, 8), font=FONT_BASE, relief="flat")
    style.map("TButton",
              background=[("active", BG_HOVER), ("pressed", BG_DARK)],
              bordercolor=[("active", ACCENT)],
              foreground=[("disabled", TEXT_DIM)])
    style.configure("Accent.TButton", background=ACCENT,
                    foreground="#FFFFFF", bordercolor=ACCENT,
                    lightcolor=ACCENT, darkcolor=ACCENT,
                    padding=(20, 10), font=FONT_BOLD, relief="flat")
    style.map("Accent.TButton",
              background=[("active", ACCENT_HVR),
                          ("pressed", ACCENT_PRSS),
                          ("disabled", "#5A2020")],
              foreground=[("disabled", "#A89090")])
    style.configure("Danger.TButton", background=BG_INPUT,
                    foreground="#E68080", bordercolor=BORDER,
                    lightcolor=BG_INPUT, darkcolor=BG_INPUT,
                    padding=(14, 8), font=FONT_BASE, relief="flat")
    style.map("Danger.TButton",
              background=[("active", "#3A2222"), ("pressed", BG_DARK)],
              bordercolor=[("active", ACCENT)])
    style.configure("Menu.TButton", background=BG_PANEL,
                    foreground=TEXT_PRIM, bordercolor=BORDER,
                    lightcolor=BG_PANEL, darkcolor=BG_PANEL,
                    padding=(20, 18), font=(FONT_FAMILY, 12, "bold"),
                    relief="flat")
    style.map("Menu.TButton",
              background=[("active", BG_HOVER), ("pressed", BG_DARK)],
              bordercolor=[("active", ACCENT)])
    style.configure("TCheckbutton", background=BG_PANEL,
                    foreground=TEXT_PRIM, indicatorcolor=BG_INPUT,
                    focuscolor=ACCENT, font=FONT_BASE, padding=4)
    style.map("TCheckbutton",
              indicatorcolor=[("selected", ACCENT),
                              ("active", BG_HOVER)],
              background=[("active", BG_PANEL)])
