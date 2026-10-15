"""
Main application GUI — unified launcher with main menu and sub-menus.
"""

import os
import re
import sys
import sqlite3
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import datetime

from pdf_forensics import (__version__, __tool_name__, SCHEMA_REVISION,
                           BUILD_DATE)
from pdf_forensics.session import Session, load_config, save_config
from pdf_forensics.database import (
    validate_database, init_db, check_pdf_already_analyzed,
    record_submission,
)
from pdf_forensics.analysis.engine import (
    process_pdfs, analyze_pdf, extract_prior_versions,
)
from pdf_forensics.analysis.triage import run_triage
from pdf_forensics.gui.theme import *
from pdf_forensics.gui.theme import apply_theme
from pdf_forensics.gui.widgets import make_panel, stat_box

try:
    from pdf_forensics.graph.data import (
        load_data, load_image_bytes, load_findings_for_md5s,
    )
    from pdf_forensics.graph.builder import (
        build_graph, build_image_metadata, build_document_metadata,
    )
    from pdf_forensics.graph.thumbnails import make_thumbnail_data_uri
    from pdf_forensics.graph.visualization import visualize_graph
    HAS_GRAPH = True
except ImportError:
    HAS_GRAPH = False


def launch_app(initial_case=None, initial_pdfs=None, initial_db=None,
               initial_output=None, initial_store_images=True):
    """Launch the unified PDF Forensics Suite GUI."""
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog

    root = tk.Tk()
    root.title(f"{__tool_name__} v{__version__}")
    root.minsize(720, 480)
    root.configure(bg=BG_DARK)
    # Position will be set by show_frame("main") on first display

    style = ttk.Style(root)
    apply_theme(style)

    # ---------------------------------------------------------------
    # Application state
    # ---------------------------------------------------------------
    app = {
        "session": None,
        "case_var": tk.StringVar(value=initial_case or ""),
        "current_frame": None,
        "password_manager": None,     # set when a password list is loaded
        "password_list_info": None,
    }
    pdf_files = list(initial_pdfs) if initial_pdfs else []
    db_path_var = tk.StringVar(value=initial_db or "pdf_forensics.db")
    output_dir_var = tk.StringVar(value=initial_output or "")
    store_images_var = tk.BooleanVar(value=initial_store_images)

    # ---------------------------------------------------------------
    # Persistent header bar
    # ---------------------------------------------------------------
    header = tk.Frame(root, bg=BG_DARK, height=128)
    header.pack(fill="x", side="top")
    header.pack_propagate(False)

    header_inner = tk.Frame(header, bg=BG_DARK)
    header_inner.pack(side="left", padx=24, pady=10)

    # Load logo and window icon from assets
    try:
        from pdf_forensics.assets import get_logo_path, get_icon_path

        # Window icon (red PDF square)
        icon_path = get_icon_path()
        if os.path.isfile(icon_path):
            icon_img = tk.PhotoImage(file=icon_path)
            root.iconphoto(True, icon_img)
            app["_icon_img"] = icon_img  # prevent GC

        # Header logo
        logo_path = get_logo_path()
        if os.path.isfile(logo_path):
            _pil_img = __import__("PIL.Image",
                                  fromlist=["Image"]).open(logo_path)
            # Scale to fit header height (~60px)
            logo_h = 72
            scale = logo_h / _pil_img.height
            logo_w = int(_pil_img.width * scale)
            _pil_img = _pil_img.resize((logo_w, logo_h),
                __import__("PIL.Image", fromlist=["Image"]).LANCZOS)
            _pil_tk = __import__("PIL.ImageTk",
                                 fromlist=["ImageTk"])
            logo_photo = _pil_tk.PhotoImage(_pil_img)
            logo_label = tk.Label(header_inner, image=logo_photo,
                                  bg=BG_DARK)
            logo_label.pack(side="left")
            app["_logo_photo"] = logo_photo  # prevent GC
        else:
            raise FileNotFoundError
    except Exception:
        # Fallback: red PDF badge if assets/PIL unavailable
        badge = tk.Frame(header_inner, bg=ACCENT, width=52, height=52)
        badge.pack(side="left")
        badge.pack_propagate(False)
        tk.Label(badge, text="PDF", bg=ACCENT, fg="#FFFFFF",
                 font=(FONT_FAMILY, 14, "bold")).place(
            relx=0.5, rely=0.5, anchor="center")

    title_block = tk.Frame(header_inner, bg=BG_DARK)
    title_block.pack(side="left", padx=(14, 0))
    tk.Label(title_block, text="PDF FORENSICS SUITE", bg=BG_DARK,
             fg=TEXT_PRIM, font=(FONT_FAMILY, 18, "bold")).pack(anchor="w")
    tk.Label(title_block, text=f"v{__version__} · build {BUILD_DATE}",
             bg=BG_DARK, fg=TEXT_DIM,
             font=FONT_SUBTITLE).pack(anchor="w")

    # Case + agency/investigator identity block (right side of header).
    # Showing these on every menu lets the operator visually confirm that
    # the stored agency, unit, and investigator details are theirs before
    # running anything, so reports and logs are not attributed to the wrong
    # person.
    case_frame = tk.Frame(header, bg=BG_DARK)
    case_frame.pack(side="right", padx=24, pady=10)

    case_row = tk.Frame(case_frame, bg=BG_DARK)
    case_row.pack(anchor="e")
    tk.Label(case_row, text="CASE:", bg=BG_DARK, fg=TEXT_SEC,
             font=(FONT_FAMILY, 9, "bold")).pack(side="left")
    case_label = tk.Label(case_row, textvariable=app["case_var"],
                          bg=BG_DARK, fg=ACCENT,
                          font=(FONT_FAMILY, 12, "bold"))
    case_label.pack(side="left", padx=(6, 0))

    # Agency / unit / investigator identity lines.
    app["agency_var"] = tk.StringVar(value="")
    app["unit_var"] = tk.StringVar(value="")
    app["investigator_var"] = tk.StringVar(value="")

    ident_block = tk.Frame(case_frame, bg=BG_DARK)
    ident_block.pack(anchor="e", pady=(3, 0))
    agency_label = tk.Label(ident_block, textvariable=app["agency_var"],
                            bg=BG_DARK, fg=TEXT_SEC,
                            font=(FONT_FAMILY, 9), justify="right")
    agency_label.pack(anchor="e")
    unit_label = tk.Label(ident_block, textvariable=app["unit_var"],
                          bg=BG_DARK, fg=TEXT_SEC,
                          font=(FONT_FAMILY, 9), justify="right")
    unit_label.pack(anchor="e")
    investigator_label = tk.Label(
        ident_block, textvariable=app["investigator_var"],
        bg=BG_DARK, fg=TEXT_DIM,
        font=(FONT_FAMILY, 9), justify="right")
    investigator_label.pack(anchor="e")

    def refresh_identity_header():
        """Populate the header identity lines from branding config."""
        try:
            from pdf_forensics import branding as _bmod
            cfg = _bmod.load_branding()
        except Exception:
            cfg = {}
        agency = (cfg.get("agency_name") or "").strip()
        unit = (cfg.get("unit_name") or "").strip()
        inv = (cfg.get("investigator_name") or "").strip()
        app["agency_var"].set(agency if agency else "Agency: not set")
        app["unit_var"].set(unit if unit else "Unit: not set")
        app["investigator_var"].set(
            inv if inv else "Investigator: not set")
        # Use a muted/alert colour when key fields are missing so the gap
        # is noticeable rather than blending in.
        agency_label.config(fg=TEXT_SEC if agency else "#EF9F27")
        unit_label.config(fg=TEXT_SEC if unit else "#EF9F27")
        investigator_label.config(fg=TEXT_DIM if inv else "#EF9F27")

    app["refresh_identity_header"] = refresh_identity_header
    refresh_identity_header()

    # Help button (right side, before case badge)
    def show_about():
        import platform as pf
        from pdf_forensics import disclaimers as _disc

        dlg = tk.Toplevel(root)
        dlg.title(f"About \u2014 {__tool_name__}")
        dlg.configure(bg=BG_DARK)
        dlg.transient(root)
        dlg.geometry("680x620")
        dlg.minsize(560, 460)

        # Title
        tk.Label(dlg, text=f"{__tool_name__} v{__version__}",
                 bg=BG_DARK, fg=TEXT_PRIM,
                 font=(FONT_FAMILY, 15, "bold")).pack(
                     anchor="w", padx=20, pady=(18, 2))
        tk.Label(dlg,
                 text=f"Build {BUILD_DATE} · schema rev {SCHEMA_REVISION}",
                 bg=BG_DARK, fg=TEXT_DIM,
                 font=FONT_SUBTITLE).pack(
                     anchor="w", padx=20, pady=(0, 6))

        # Scrollable body
        body = tk.Frame(dlg, bg=BG_DARK)
        body.pack(fill="both", expand=True, padx=20, pady=(6, 6))
        canvas = tk.Canvas(body, bg=BG_DARK, highlightthickness=0)
        scroll = ttk.Scrollbar(body, orient="vertical",
                               command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG_DARK)
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        def _wrap_label(parent, text, **kw):
            lbl = tk.Label(parent, text=text, bg=BG_DARK, justify="left",
                           anchor="w", wraplength=600, **kw)
            lbl.pack(anchor="w", fill="x", pady=2)
            return lbl

        # Authorship / contact
        _wrap_label(inner, "Author / Contact",
                    fg=ACCENT, font=(FONT_FAMILY, 11, "bold"))
        _wrap_label(inner, _disc.AUTHORSHIP_BLOCK,
                    fg=TEXT_SEC, font=FONT_SUBTITLE)

        tk.Frame(inner, bg=BORDER, height=1).pack(
            fill="x", pady=(12, 10))

        # Full disclaimer
        _wrap_label(inner, _disc.FULL_DISCLAIMER_TITLE,
                    fg=ACCENT, font=(FONT_FAMILY, 11, "bold"))
        _wrap_label(inner, _disc.FULL_DISCLAIMER,
                    fg=TEXT_PRIM, font=FONT_SUBTITLE)

        tk.Frame(inner, bg=BORDER, height=1).pack(
            fill="x", pady=(12, 10))

        # Environment / diagnostics (kept from the original About)
        _wrap_label(inner, "Environment",
                    fg=ACCENT, font=(FONT_FAMILY, 11, "bold"))
        env_lines = [
            f"Python: {sys.version.split()[0]}",
            f"OS: {pf.platform()}",
        ]
        for mod_name, attr in (("pymupdf", "version"),
                               ("pikepdf", "__version__"),
                               ("PIL", "__version__"),
                               ("networkx", "__version__"),
                               ("pyvis", "__version__")):
            try:
                m = __import__(mod_name)
                ver = getattr(m, attr, "installed")
                env_lines.append(f"{mod_name}: {ver}")
            except Exception:
                env_lines.append(f"{mod_name}: not installed")
        env_lines.append(f"Schema revision: {SCHEMA_REVISION}")
        if app["session"]:
            env_lines.append(f"Case: {app['case_var'].get()}")
            s = app["session"]
            if s.db_dir:
                env_lines.append(f"Output: {s.db_dir}")
            if s.log_path:
                env_lines.append(f"Log: {s.log_path}")
        _wrap_label(inner, "\n".join(env_lines),
                    fg=TEXT_SEC, font=FONT_SUBTITLE)

        # Close button
        btn_row = tk.Frame(dlg, bg=BG_DARK)
        btn_row.pack(fill="x", padx=20, pady=(4, 16))
        ttk.Button(btn_row, text="Close",
                   command=dlg.destroy).pack(side="right")

        dlg.update_idletasks()
        try:
            x = root.winfo_x() + (root.winfo_width() - dlg.winfo_width()) // 2
            y = root.winfo_y() + 60
            dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

    help_frame = tk.Frame(header, bg=BG_DARK)
    help_frame.pack(side="right", padx=(0, 12), pady=14)
    help_btn = tk.Label(
        help_frame, text="?", bg=BG_INPUT, fg=TEXT_PRIM,
        font=(FONT_FAMILY, 12, "bold"),
        width=3, height=1, relief="flat", cursor="hand2")
    help_btn.pack()
    help_btn.bind("<Button-1>", lambda e: show_about())
    help_btn.bind("<Enter>",
                  lambda e: help_btn.config(bg=BG_HOVER))
    help_btn.bind("<Leave>",
                  lambda e: help_btn.config(bg=BG_INPUT))

    tk.Frame(root, bg=ACCENT, height=2).pack(fill="x")

    # ---------------------------------------------------------------
    # Content area (frames are swapped here)
    # ---------------------------------------------------------------
    content_area = tk.Frame(root, bg=BG_DARK)
    content_area.pack(fill="both", expand=True)

    # Status bar
    status_var = tk.StringVar(value="Ready")
    status_frame = tk.Frame(root, bg=BG_PANEL, height=32)
    status_frame.pack(fill="x", side="bottom")
    status_frame.pack_propagate(False)
    tk.Frame(status_frame, bg=BORDER, height=1).pack(fill="x", side="top")
    status_label = tk.Label(status_frame, textvariable=status_var,
                            bg=BG_PANEL, fg=TEXT_SEC,
                            font=FONT_SUBTITLE, anchor="w")
    status_label.pack(side="left", padx=14, fill="y")

    # Permanent disclaimer reminder (right side of the status bar). The full
    # text is shown once as a blocking acknowledgment on first launch; this
    # line is the lightweight, always-present reminder thereafter.
    from pdf_forensics import disclaimers as _disc_mod
    disclaimer_status = tk.Label(
        status_frame, text=_disc_mod.FOOTER_REMINDER,
        bg=BG_PANEL, fg=TEXT_DIM, font=FONT_SUBTITLE, anchor="e",
        cursor="hand2")
    disclaimer_status.pack(side="right", padx=14, fill="y")
    # Clicking the reminder opens the full disclaimer in About.
    disclaimer_status.bind("<Button-1>", lambda e: show_about())

    # ---------------------------------------------------------------
    # Frame switching
    # ---------------------------------------------------------------
    frames = {}

    # Per-frame window sizes: (width, height)
    frame_sizes = {
        "main":     (780, 540),
        "analysis": (1200, 936),
        "graph":    (1060, 540),
        "reports":  (1180, 1000),
    }

    def center_window(w, h):
        """Position window centered horizontally, biased toward top.
        Clamp the requested size to the available screen so a tall window
        (e.g. the reports menu) never extends past the display on smaller
        laptop screens."""
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        # Leave a margin for the OS taskbar / window chrome.
        w = min(w, screen_w - 40)
        h = min(h, screen_h - 80)
        x = max(0, (screen_w - w) // 2)
        y = max(0, (screen_h - h) // 4)  # 1/4 from top, not 1/2
        root.geometry(f"{w}x{h}+{x}+{y}")

    def show_frame(name):
        if app["current_frame"]:
            app["current_frame"].pack_forget()
        frame = frames[name]
        frame.pack(in_=content_area, fill="both", expand=True)
        app["current_frame"] = frame
        w, h = frame_sizes.get(name, (780, 620))
        center_window(w, h)

    # ---------------------------------------------------------------
    # Helper: make a styled panel
    # ---------------------------------------------------------------
    def make_panel(parent, label_text):
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

    def attach_tooltip(widget, text, wraplength=320):
        """Attach a hover tooltip to a widget. The tip appears after a
        short delay near the cursor and disappears on leave. Reusable
        across the reports, graph, and analysis menus."""
        if not text:
            return
        state = {"tip": None, "after": None}

        def show():
            if state["tip"] is not None:
                return
            try:
                x = widget.winfo_pointerx() + 14
                y = widget.winfo_pointery() + 18
            except Exception:
                return
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            tip.configure(bg=BORDER)
            lbl = tk.Label(
                tip, text=text, justify="left", bg="#2B2B2B",
                fg=TEXT_PRIM, font=FONT_SUBTITLE, wraplength=wraplength,
                padx=8, pady=6, bd=0)
            lbl.pack(padx=1, pady=1)
            state["tip"] = tip

        def schedule(_e=None):
            cancel_after()
            state["after"] = widget.after(450, show)

        def hide(_e=None):
            cancel_after()
            if state["tip"] is not None:
                try:
                    state["tip"].destroy()
                except Exception:
                    pass
                state["tip"] = None

        def cancel_after():
            if state["after"] is not None:
                try:
                    widget.after_cancel(state["after"])
                except Exception:
                    pass
                state["after"] = None

        widget.bind("<Enter>", schedule, add="+")
        widget.bind("<Leave>", hide, add="+")
        widget.bind("<ButtonPress>", hide, add="+")

    # ===================================================================
    # MAIN MENU FRAME
    # ===================================================================
    main_frame = tk.Frame(content_area, bg=BG_DARK)
    frames["main"] = main_frame

    menu_inner = tk.Frame(main_frame, bg=BG_DARK)
    menu_inner.pack(expand=True)

    tk.Label(menu_inner, text="Select a module",
             bg=BG_DARK, fg=TEXT_SEC,
             font=(FONT_FAMILY, 14)).pack(pady=(20, 16))

    def menu_card(parent, title, subtitle, command):
        card = tk.Frame(parent, bg=BG_PANEL, padx=1, pady=1)
        card.pack(fill="x", padx=40, pady=4)
        inner = tk.Frame(card, bg=BG_PANEL)
        inner.pack(fill="x", padx=16, pady=12)
        tk.Label(inner, text=title, bg=BG_PANEL, fg=TEXT_PRIM,
                 font=(FONT_FAMILY, 13, "bold")).pack(anchor="w")
        tk.Label(inner, text=subtitle, bg=BG_PANEL, fg=TEXT_SEC,
                 font=FONT_SUBTITLE).pack(anchor="w", pady=(4, 0))
        inner.bind("<Button-1>", lambda e: command())
        for child in inner.winfo_children():
            child.bind("<Button-1>", lambda e: command())
        # Hover effect
        def on_enter(e):
            inner.config(bg=BG_HOVER)
            for c in inner.winfo_children():
                c.config(bg=BG_HOVER)
        def on_leave(e):
            inner.config(bg=BG_PANEL)
            for c in inner.winfo_children():
                c.config(bg=BG_PANEL)
        inner.bind("<Enter>", on_enter)
        inner.bind("<Leave>", on_leave)

    menu_card(menu_inner, "PDF Forensics Analysis",
              "Analyze PDFs for image manipulation, metadata, and risk scoring",
              lambda: show_frame("analysis"))

    menu_card(menu_inner, "Graph Analysis",
              "Generate interactive visualizations of image reuse across documents",
              lambda: show_frame("graph"))

    menu_card(menu_inner, "Forensic Reports",
              "Generate HTML reports from pre-built forensic queries",
              lambda: show_frame("reports"))

    # Bottom buttons on main menu
    main_btns = tk.Frame(menu_inner, bg=BG_DARK)
    main_btns.pack(fill="x", padx=40, pady=(20, 12))

    def edit_branding():
        from pdf_forensics import branding as bmod
        cfg = bmod.load_branding()

        dlg = tk.Toplevel(root)
        dlg.title("Agency / Investigator Branding")
        dlg.configure(bg=BG_DARK)
        dlg.transient(root)
        dlg.grab_set()
        dlg.resizable(False, False)

        wrap = tk.Frame(dlg, bg=BG_DARK, padx=24, pady=20)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text="Report Branding", bg=BG_DARK, fg=TEXT_PRIM,
                 font=(FONT_FAMILY, 14, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        tk.Label(wrap,
                 text="Shown on report banners, the graph cover page, "
                      "and page footers.\nSaved to the application folder.",
                 bg=BG_DARK, fg=TEXT_SEC, justify="left",
                 font=FONT_SUBTITLE).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 14))

        entries = {}
        r = 2
        for key, label in bmod.FIELDS:
            tk.Label(wrap, text=label, bg=BG_DARK, fg=TEXT_SEC,
                     font=FONT_BASE).grid(
                row=r, column=0, sticky="w", pady=4, padx=(0, 12))
            var = tk.StringVar(value=cfg.get(key, ""))
            ttk.Entry(wrap, textvariable=var, width=44).grid(
                row=r, column=1, sticky="we", pady=4)
            entries[key] = var
            if key == "agency_logo_path":
                def browse_logo(v=var):
                    p = filedialog.askopenfilename(
                        parent=dlg, title="Select agency logo",
                        filetypes=[
                            ("Images",
                             "*.png *.jpg *.jpeg *.gif *.webp *.bmp"),
                            ("All files", "*.*")])
                    if p:
                        v.set(p)
                ttk.Button(wrap, text="Browse\u2026",
                           command=browse_logo).grid(
                    row=r, column=2, padx=(8, 0), pady=4)
            r += 1

        wrap.columnconfigure(1, weight=1)

        btns = tk.Frame(wrap, bg=BG_DARK)
        btns.grid(row=r, column=0, columnspan=3, sticky="we", pady=(18, 0))

        def do_save():
            newcfg = {k: v.get() for k, v in entries.items()}
            path = bmod.save_branding(newcfg)
            if path:
                # Reflect any changed agency/unit/investigator details in
                # the header immediately.
                try:
                    app["refresh_identity_header"]()
                except Exception:
                    pass
                messagebox.showinfo(
                    "Branding saved",
                    f"Branding saved to:\n{path}", parent=dlg)
                dlg.destroy()
            else:
                messagebox.showerror(
                    "Save failed",
                    "Could not write the branding file.", parent=dlg)

        ttk.Button(btns, text="Save", style="Accent.TButton",
                   command=do_save).pack(side="right")
        ttk.Button(btns, text="Cancel",
                   command=dlg.destroy).pack(side="right", padx=(0, 8))

        dlg.update_idletasks()
        try:
            rx, ry = root.winfo_rootx(), root.winfo_rooty()
            rw, rh = root.winfo_width(), root.winfo_height()
            dw, dh = dlg.winfo_width(), dlg.winfo_height()
            dlg.geometry(
                f"+{rx + (rw - dw) // 2}+{ry + (rh - dh) // 3}")
        except Exception:
            pass

    def change_case():
        new_case = simpledialog.askstring(
            "Change Case",
            "Enter new case number:",
            parent=root,
            initialvalue=app["case_var"].get())
        if new_case and new_case.strip():
            new_case = new_case.strip()
            if app["session"]:
                if not messagebox.askyesno(
                    "Switch Case",
                    f"Switching to case '{new_case}' will start "
                    f"a new session.\n\nYou will be asked to choose an "
                    f"output folder for the new case (you may pick an "
                    f"existing folder or create a new one). Any case-wide "
                    f"counters will reset, and a new log file will be "
                    f"created.\n\nContinue?"):
                    return
                app["session"].write_summary(
                    db_path=db_path_var.get())
            pdf_files.clear()
            try:
                pdf_listbox.delete(0, "end")
            except Exception:
                pass
            # A new case must not silently inherit the previous case's
            # folder or database: reset the DB path so a fresh one is
            # derived from the newly chosen output folder.
            db_path_var.set("pdf_forensics.db")
            # Clear the processing log window — this is a new case.
            try:
                clear_log()
            except Exception:
                pass
            setup_session(new_case, always_prompt_dir=True)

    ttk.Button(main_btns, text="Change case number",
               command=change_case).pack(side="left")
    ttk.Button(main_btns, text="Branding / agency info",
               command=edit_branding).pack(side="left", padx=(8, 0))
    ttk.Button(main_btns, text="Exit", style="Danger.TButton",
               command=root.destroy).pack(side="right", padx=(12, 0))

    # ===================================================================
    # ANALYSIS SUB-MENU FRAME (left-right split)
    # ===================================================================
    analysis_frame = tk.Frame(content_area, bg=BG_DARK)
    frames["analysis"] = analysis_frame

    # Back button row (full width, above the split)
    back_row_a = tk.Frame(analysis_frame, bg=BG_DARK)
    back_row_a.pack(fill="x", padx=20, pady=(10, 6))
    ttk.Button(back_row_a, text="< Back to Main Menu",
               command=lambda: show_frame("main")).pack(side="left")

    # Horizontal split: left = form, right = status log
    split = tk.Frame(analysis_frame, bg=BG_DARK)
    split.pack(fill="both", expand=True, padx=20, pady=(0, 8))

    left_panel = tk.Frame(split, bg=BG_DARK, width=580)
    left_panel.pack(side="left", fill="y", padx=(0, 10))
    left_panel.pack_propagate(False)

    right_panel = tk.Frame(split, bg=BG_DARK)
    right_panel.pack(side="left", fill="both", expand=True)

    # --- LEFT SIDE: form inputs ---

    # PDF files panel
    pdf_body = make_panel(left_panel, "PDF files")
    list_container = tk.Frame(pdf_body, bg=BORDER, padx=1, pady=1)
    list_container.pack(fill="x", pady=(0, 8))
    pdf_listbox = tk.Listbox(
        list_container, height=5,
        bg=BG_INPUT, fg=TEXT_PRIM,
        selectbackground=ACCENT, selectforeground="#FFFFFF",
        highlightthickness=0, borderwidth=0,
        font=FONT_BASE, activestyle="none")
    pdf_listbox.pack(fill="x", expand=True)
    for p in pdf_files:
        pdf_listbox.insert("end", p)

    def add_pdfs():
        paths = filedialog.askopenfilenames(
            title="Select PDF file(s)",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        for p in paths:
            if p not in pdf_files:
                pdf_files.append(p)
                pdf_listbox.insert("end", p)

    def set_password_list():
        path = filedialog.askopenfilename(
            title="Select password list (one password per line)",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        from pdf_forensics import passwords as _pw
        try:
            passwords, info = _pw.read_password_list(path)
        except OSError as e:
            messagebox.showerror("Cannot read password list", str(e))
            return
        if len(passwords) > _pw.SOFT_LIMIT:
            if not messagebox.askyesno(
                    "Large password list",
                    f"{len(passwords)} passwords were supplied "
                    f"(more than {_pw.SOFT_LIMIT}).\n\nTrying many passwords "
                    f"against AES-256 files can be slow. Continue with this "
                    f"list?"):
                return
        app["password_manager"] = _pw.PasswordManager(passwords, info)
        app["password_list_info"] = info
        pw_list_var.set(f"Password list: {len(passwords)} "
                        f"\u2014 {os.path.basename(path)}")
        session = app.get("session")
        if session:
            session.log(f"Password list loaded: {info['path']} "
                        f"(MD5 {info['md5']}, {info['encoding']}): "
                        f"{len(passwords)} password(s)")
        messagebox.showinfo(
            "Password list loaded",
            f"{len(passwords)} password(s) will be tried (after the empty "
            f"password and any already found) to open encrypted PDFs.")

    def clear_password_list():
        app["password_manager"] = None
        app["password_list_info"] = None
        pw_list_var.set("No password list (encrypted PDFs needing a "
                        "password will be set aside)")

    def add_pdfs_from_list():
        path = filedialog.askopenfilename(
            title="Select text file with PDF paths",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        from pdf_forensics.pathlist import read_path_list, log_list, path_key
        try:
            res = read_path_list(path)
        except OSError as e:
            messagebox.showerror("Cannot read list", str(e))
            return
        have = {path_key(p) for p in pdf_files}
        added = 0
        for p in res["paths"]:
            if path_key(p) in have:
                res["duplicates"] += 1
                continue
            have.add(path_key(p))
            pdf_files.append(p)
            pdf_listbox.insert("end", p)
            added += 1
        session = app.get("session")
        log_list(session, res, added=added)
        msg = f"Added {added} PDF(s) from {os.path.basename(path)}."
        if res["duplicates"]:
            msg += (f"\n{res['duplicates']} entr"
                    f"{'y was' if res['duplicates'] == 1 else 'ies were'} "
                    f"already selected or listed twice, and ignored.")
        if res["missing"]:
            shown = res["missing"][:12]
            msg += (f"\n\n{len(res['missing'])} path(s) not found:\n"
                    + "\n".join(f"  \u2022 {m}" for m in shown))
            if len(res["missing"]) > len(shown):
                msg += f"\n  \u2026 and {len(res['missing']) - len(shown)} more"
            msg += ("\n\nAll paths not found are listed in the session log."
                    if session else "\n\n(No case session is open, so "
                    "this was not logged.)")
        (messagebox.showwarning if res["missing"] else
         messagebox.showinfo)("Import complete", msg)

    def add_pdfs_from_folder():
        folder = filedialog.askdirectory(
            title="Select a folder containing PDF files")
        if not folder:
            return

        # Ask whether to descend into subfolders. Yes = recursive,
        # No = this folder only, Cancel = abort the whole operation.
        recursive = messagebox.askyesnocancel(
            "Include subfolders?",
            "Search subfolders recursively for PDF files?\n\n"
            "Yes  \u2013 include this folder and all subfolders\n"
            "No   \u2013 only this folder\n"
            "Cancel \u2013 don't add anything")
        if recursive is None:   # Cancel
            return

        found = []
        if recursive:
            for root_dir, _dirs, files in os.walk(folder):
                for name in files:
                    if name.lower().endswith(".pdf"):
                        found.append(os.path.join(root_dir, name))
        else:
            try:
                for name in os.listdir(folder):
                    full = os.path.join(folder, name)
                    if (name.lower().endswith(".pdf")
                            and os.path.isfile(full)):
                        found.append(full)
            except OSError as e:
                messagebox.showerror(
                    "Folder error",
                    f"Could not read the folder:\n{e}")
                return

        found.sort()
        added = 0
        for p in found:
            if p not in pdf_files:
                pdf_files.append(p)
                pdf_listbox.insert("end", p)
                added += 1

        scope = "recursively" if recursive else "in the selected folder"
        if added:
            skipped = len(found) - added
            msg = f"Added {added} PDF(s) found {scope}."
            if skipped:
                msg += f"\n{skipped} already in the list (skipped)."
            messagebox.showinfo("Folder Import Complete", msg)
        else:
            if found:
                messagebox.showinfo(
                    "Folder Import Complete",
                    f"All {len(found)} PDF(s) found {scope} are already "
                    f"in the list.")
            else:
                messagebox.showinfo(
                    "No PDFs Found",
                    f"No PDF files were found {scope}.")

    def remove_pdfs():
        selected = list(pdf_listbox.curselection())
        for idx in reversed(selected):
            del pdf_files[idx]
            pdf_listbox.delete(idx)

    def remove_all_pdfs():
        pdf_files.clear()
        pdf_listbox.delete(0, "end")

    # Lay the buttons out in an equal-weight grid that fills the panel
    # width, so they always fit regardless of platform font metrics
    # (a fixed left-packed row can clip the last button on wider fonts).
    pdf_btns = tk.Frame(pdf_body, bg=BG_PANEL)
    pdf_btns.pack(fill="x")
    _pdf_buttons = [
        ("Add files", add_pdfs),
        ("Add folder", add_pdfs_from_folder),
        ("From list", add_pdfs_from_list),
        ("Remove", remove_pdfs),
        ("Clear all", remove_all_pdfs),
    ]
    pw_list_var = tk.StringVar(
        value="No password list (encrypted PDFs needing a password will be "
              "set aside)")
    for _col, (_label, _cmd) in enumerate(_pdf_buttons):
        pdf_btns.grid_columnconfigure(_col, weight=1, uniform="pdfbtn")
        ttk.Button(pdf_btns, text=_label, command=_cmd).grid(
            row=0, column=_col, sticky="ew",
            padx=(0 if _col == 0 else 4, 0))
    pw_row = tk.Frame(pdf_body, bg=BG_PANEL)
    pw_row.pack(fill="x", pady=(4, 0))
    ttk.Button(pw_row, text="Password list\u2026",
               command=set_password_list).pack(side="left")
    ttk.Button(pw_row, text="Clear",
               command=clear_password_list).pack(side="left", padx=(4, 8))
    tk.Label(pw_row, textvariable=pw_list_var, bg=BG_PANEL, fg=TEXT_DIM,
             font=FONT_SUBTITLE, anchor="w").pack(
                 side="left", fill="x", expand=True)

    # Database panel
    db_body = make_panel(left_panel, "Database")
    db_row = tk.Frame(db_body, bg=BG_PANEL)
    db_row.pack(fill="x")
    db_entry = ttk.Entry(db_row, textvariable=db_path_var)
    db_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

    def choose_db():
        path = filedialog.asksaveasfilename(
            title="Select or create database file",
            defaultextension=".db",
            filetypes=[("SQLite database", "*.db *.sqlite *.sqlite3"),
                       ("All files", "*.*")],
            confirmoverwrite=False)
        if path:
            db_path_var.set(path)
            # Also update graph DB to match
            graph_db_var.set(path)

    ttk.Button(db_row, text="Browse",
               command=choose_db).pack(side="left")
    ttk.Label(db_body, text="Existing databases will be appended to.",
              style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

    # Output folder panel
    out_body = make_panel(left_panel, "Output folder")
    out_row = tk.Frame(out_body, bg=BG_PANEL)
    out_row.pack(fill="x")
    out_entry = ttk.Entry(out_row, textvariable=output_dir_var)
    out_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

    def choose_output():
        path = filedialog.askdirectory(
            title="Select output folder")
        if path:
            output_dir_var.set(path)

    ttk.Button(out_row, text="Browse",
               command=choose_output).pack(side="left")

    # Options panel
    opt_body = make_panel(left_panel, "Options")

    triage_var = tk.BooleanVar(value=True)
    triage_cb = ttk.Checkbutton(
        opt_body,
        text="Triage mode (quick scan to Excel)",
        variable=triage_var)
    triage_cb.pack(anchor="w", pady=(0, 6))

    store_cb = ttk.Checkbutton(
        opt_body,
        text="Store extracted images in database",
        variable=store_images_var)
    store_cb.pack(anchor="w")
    extract_versions_var = tk.BooleanVar(value=True)
    versions_cb = ttk.Checkbutton(
        opt_body,
        text="Extract and process prior PDF versions",
        variable=extract_versions_var)
    versions_cb.pack(anchor="w")
    skip_duplicates_var = tk.BooleanVar(value=True)
    skip_cb = ttk.Checkbutton(
        opt_body,
        text="Skip PDFs already in the database",
        variable=skip_duplicates_var)
    skip_cb.pack(anchor="w")

    # Controls that get disabled in triage mode
    advanced_widgets = [store_cb, versions_cb, skip_cb,
                        db_entry]

    attach_tooltip(triage_cb,
                   "Quick scan that writes a triage spreadsheet (Excel) "
                   "instead of running the full forensic analysis \u2014 a "
                   "fast overview of many files, with per-file metadata and "
                   "any reviewer comments.")
    attach_tooltip(store_cb,
                   "Save each extracted image into the database so reports "
                   "and the relationship graph can show image thumbnails. "
                   "Increases database size.")
    attach_tooltip(versions_cb,
                   "When a PDF contains incremental updates (multiple "
                   "%%EOF markers), extract and analyze the earlier saved "
                   "versions as well, not just the current one.")
    attach_tooltip(skip_cb,
                   "Skip any PDF whose hash already exists in the selected "
                   "database, avoiding duplicate analysis on re-runs.")

    # Remember pre-triage checkbox states
    _pre_triage_state = {
        "store": True,
        "versions": True,
        "skip": True,
    }

    def on_triage_toggle(*_):
        is_triage = triage_var.get()
        state = "disabled" if is_triage else "normal"
        for w in advanced_widgets:
            w.config(state=state)
        if is_triage:
            # Save current states and uncheck
            _pre_triage_state["store"] = store_images_var.get()
            _pre_triage_state["versions"] = extract_versions_var.get()
            _pre_triage_state["skip"] = skip_duplicates_var.get()
            store_images_var.set(False)
            extract_versions_var.set(False)
            skip_duplicates_var.set(False)
            run_btn_a.config(text="Run triage")
        else:
            # Restore previous states
            store_images_var.set(_pre_triage_state["store"])
            extract_versions_var.set(_pre_triage_state["versions"])
            skip_duplicates_var.set(_pre_triage_state["skip"])
            run_btn_a.config(text="Run analysis")

    triage_var.trace_add("write", on_triage_toggle)

    # Run button at bottom of left panel
    action_row_a = tk.Frame(left_panel, bg=BG_DARK)
    action_row_a.pack(fill="x", side="bottom", pady=(8, 4))

    # --- RIGHT SIDE: status log ---

    # Counter row
    counter_outer = tk.Frame(right_panel, bg=BORDER, padx=1, pady=1)
    counter_outer.pack(fill="x", pady=(0, 8))
    counter_inner = tk.Frame(counter_outer, bg=BG_PANEL)
    counter_inner.pack(fill="x")
    counter_row = tk.Frame(counter_inner, bg=BG_PANEL)
    counter_row.pack(fill="x", padx=10, pady=8)

    count_selected = tk.StringVar(value="0")
    count_processed = tk.StringVar(value="0")
    count_failed = tk.StringVar(value="0")
    count_skipped = tk.StringVar(value="0")
    count_encrypted = tk.StringVar(value="0")
    count_images = tk.StringVar(value="0")

    def counter_label(parent, label_text, var, color=TEXT_SEC):
        f = tk.Frame(parent, bg=BG_PANEL)
        f.pack(side="left", padx=(0, 24))
        tk.Label(f, textvariable=var, bg=BG_PANEL, fg=color,
                 font=(FONT_FAMILY, 14, "bold"),
                 width=5, anchor="e").pack(side="left")
        tk.Label(f, text=f"  {label_text}", bg=BG_PANEL, fg=TEXT_DIM,
                 font=(FONT_FAMILY, 9)).pack(side="left")

    counter_label(counter_row, "Selected", count_selected)
    counter_label(counter_row, "Processed", count_processed, SUCCESS)
    counter_label(counter_row, "Failed", count_failed, ACCENT)
    counter_label(counter_row, "Copies", count_skipped)
    counter_label(counter_row, "Locked", count_encrypted, ACCENT)
    counter_label(counter_row, "Images", count_images)

    # Progress bar + per-PDF status label (GUI-03). Shown during batch
    # analysis/triage so the operator sees overall progress and which file
    # is being processed, instead of relying on the scrolling log alone.
    progress_outer = tk.Frame(right_panel, bg=BORDER, padx=1, pady=1)
    progress_outer.pack(fill="x", pady=(0, 8))
    progress_inner = tk.Frame(progress_outer, bg=BG_PANEL)
    progress_inner.pack(fill="x")
    progress_status_var = tk.StringVar(value="Idle")
    tk.Label(progress_inner, textvariable=progress_status_var,
             bg=BG_PANEL, fg=TEXT_SEC, font=(FONT_FAMILY, 9),
             anchor="w").pack(fill="x", padx=10, pady=(8, 2))
    analysis_progress = ttk.Progressbar(
        progress_inner, mode="determinate", maximum=100, value=0)
    analysis_progress.pack(fill="x", padx=10, pady=(0, 10))

    def progress_reset(total_files):
        analysis_progress.config(mode="determinate",
                                 maximum=max(1, total_files), value=0)
        progress_status_var.set(
            f"Starting \u2014 0 of {total_files} file(s)")
        root.update_idletasks()

    def progress_set_file(done, total, name, page=None, pages=None):
        analysis_progress.config(maximum=max(1, total), value=done)
        msg = f"File {min(done + 1, total)} of {total}: {name}"
        if page and pages:
            msg += f"  \u2014  page {page}/{pages}"
        progress_status_var.set(msg)
        root.update_idletasks()

    def progress_done(processed, failed):
        analysis_progress.config(value=analysis_progress["maximum"])
        progress_status_var.set(
            f"Complete \u2014 {processed} processed, {failed} failed")
        root.update_idletasks()

    # Scrollable log
    log_outer = tk.Frame(right_panel, bg=BORDER, padx=1, pady=1)
    log_outer.pack(fill="both", expand=True)
    log_inner = tk.Frame(log_outer, bg=BG_PANEL)
    log_inner.pack(fill="both", expand=True)
    ttk.Label(log_inner, text="PROCESSING LOG",
              style="Section.TLabel").pack(
        anchor="w", padx=10, pady=(8, 4))

    log_frame = tk.Frame(log_inner, bg=BG_PANEL)
    log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))
    log_scroll = tk.Scrollbar(log_frame)
    log_scroll.pack(side="right", fill="y")
    log_text = tk.Text(
        log_frame, wrap="word", bg=BG_INPUT, fg=TEXT_PRIM,
        insertbackground=TEXT_PRIM, highlightthickness=0,
        borderwidth=0, font=(FONT_FAMILY, 9), padx=8, pady=6,
        relief="flat", yscrollcommand=log_scroll.set)
    log_text.pack(fill="both", expand=True)
    log_scroll.config(command=log_text.yview)
    log_text.tag_configure("success", foreground=SUCCESS)
    log_text.tag_configure("error", foreground=ACCENT)
    log_text.tag_configure("skip", foreground="#EF9F27")
    log_text.tag_configure("dim", foreground=TEXT_DIM)
    log_text.tag_configure("bold",
                           font=(FONT_FAMILY, 9, "bold"))
    log_text.config(state="disabled")

    def log_to_gui(msg, tag=None):
        log_text.config(state="normal")
        if tag:
            log_text.insert("end", msg + "\n", tag)
        else:
            log_text.insert("end", msg + "\n")
        log_text.see("end")
        log_text.config(state="disabled")
        root.update_idletasks()

    def clear_log():
        """Empty the processing log window (e.g. when starting a new case)."""
        log_text.config(state="normal")
        log_text.delete("1.0", "end")
        log_text.config(state="disabled")

    def update_counters():
        count_selected.set(str(len(pdf_files)))

    # --- Run analysis ---

    def run_analysis():
        if not pdf_files:
            messagebox.showerror("No PDFs", "Please add PDF file(s).")
            return
        if not app["session"]:
            messagebox.showerror("No case",
                                 "Please set a case number first.")
            return

        # Route to triage if triage mode is on
        if triage_var.get():
            _run_triage_mode()
            return

        if not db_path_var.get():
            messagebox.showerror("No database",
                                 "Please choose a database.")
            return

        run_btn_a.config(state="disabled")
        status_var.set("Processing...")
        status_label.config(fg=ACCENT)

        log_text.config(state="normal")
        log_text.delete("1.0", "end")
        log_text.config(state="disabled")

        session = app["session"]
        db_val = db_path_var.get()
        out_dir = output_dir_var.get()

        if not out_dir:
            out_dir = session.extracted_images_dir or "extracted_images"
            os.makedirs(out_dir, exist_ok=True)
            output_dir_var.set(out_dir)

        session.log(f"Starting PDF analysis: {len(pdf_files)} file(s)")
        session.log(f"  Database: {db_val}")
        session.log(f"  Output: {out_dir}")
        session.register_output("database", db_val)

        conn = init_db(db_val, session=session)
        processed = 0
        skipped_copies = 0
        versions_done = 0
        not_found = 0
        failed = 0
        total_imgs = 0
        total_findings = 0

        count_processed.set("0")
        count_failed.set("0")
        count_skipped.set("0")
        count_images.set("0")
        update_counters()

        log_to_gui(f"Processing {len(pdf_files)} PDF(s)...", "bold")
        log_to_gui(f"Database: {os.path.basename(db_val)}", "dim")
        log_to_gui("")

        # Build a processing queue so extracted versions can be added.
        # Track which entries are extracted versions so we don't
        # cascade (extract versions from versions).
        process_queue = list(pdf_files)
        encrypted_unopened = []       # locked files no password opened
        is_extracted_version = set()  # indices of extracted versions
        # queue index -> (parent_analysis_id, version_number) for
        # extracted prior versions, so lineage is recorded in the DB.
        version_lineage = {}
        queue_idx = 0
        progress_reset(len(process_queue))

        while queue_idx < len(process_queue):
            pdf_path = process_queue[queue_idx]
            this_is_version = queue_idx in is_extracted_version
            this_lineage = version_lineage.get(queue_idx)
            queue_idx += 1
            basename = os.path.basename(pdf_path)

            if not os.path.isfile(pdf_path):
                log_to_gui(f"  \u2717 {basename} — not found", "error")
                failed += 1
                not_found += 1
                count_failed.set(str(failed))
                record_submission(conn, pdf_path, "not_found",
                                  session=session,
                                  is_version=this_is_version)
                if session:
                    session.log(f"Not found: {pdf_path}", "warning")
                continue

            base = os.path.splitext(basename)[0]
            pdf_extract_dir = os.path.join(out_dir, base) \
                if out_dir else None

            # Progress line: updated in-place per page
            log_text.config(state="normal")
            log_text.insert("end", f"  \u25cb {basename} — ", "dim")
            progress_idx = log_text.index("end - 1 line linestart")
            log_text.insert("end", "starting...\n", "dim")
            log_text.see("end")
            log_text.config(state="disabled")
            # Update the progress bar / status label for this file.
            progress_set_file(queue_idx - 1, len(process_queue), basename)
            root.update_idletasks()

            def on_page_progress(page_num, total_pages,
                                 _idx=progress_idx, _name=basename,
                                 _done=queue_idx - 1,
                                 _total=len(process_queue)):
                log_text.config(state="normal")
                log_text.delete(_idx, f"{_idx} lineend + 1 char")
                log_text.insert(_idx,
                    f"  \u25cb {_name} — "
                    f"page {page_num}/{total_pages}\n", "dim")
                log_text.see("end")
                log_text.config(state="disabled")
                progress_set_file(_done, _total, _name,
                                  page=page_num, pages=total_pages)
                root.update_idletasks()

            try:
                # Duplicate check (checkbox-based, no dialog)
                if skip_duplicates_var.get():
                    already, dup_info = check_pdf_already_analyzed(
                        conn, pdf_path)
                    if already:
                        log_text.config(state="normal")
                        log_text.delete(progress_idx,
                                        f"{progress_idx} lineend + 1 char")
                        log_text.insert(progress_idx,
                            f"  \u2298 {basename} — identical copy of "
                            f"{dup_info['pdf_filename']} (not re-analysed)\n",
                            "skip")
                        log_text.see("end")
                        log_text.config(state="disabled")
                        skipped_copies += 1
                        count_skipped.set(str(skipped_copies))
                        record_submission(
                            conn, pdf_path, "duplicate", session=session,
                            analysis_id=dup_info.get("id"),
                            duplicate_of=dup_info.get("pdf_filename"),
                            is_version=this_is_version)
                        if session:
                            session.log(
                                f"Skipped: {basename} is byte-identical to "
                                f"{dup_info['pdf_filename']} (already "
                                f"analysed {dup_info['analyzed_at']}); not "
                                f"re-analysed")
                        root.update_idletasks()
                        continue

                # Encryption: open permissions-only files with the empty
                # password, locked files with a supplied password; a
                # locked file no password opens is recorded and skipped,
                # and remembered so the user can supply a list afterwards.
                from pdf_forensics import passwords as _pw
                enc = _pw.resolve_file_password(
                    conn, pdf_path, app.get("password_manager"),
                    session=session, quiet=True)
                if enc["skip"]:
                    log_text.config(state="normal")
                    log_text.delete(progress_idx,
                                    f"{progress_idx} lineend + 1 char")
                    log_text.insert(progress_idx,
                        f"  \U0001f512 {basename} — encrypted, not opened "
                        f"({enc['scheme'] or 'scheme unknown'})\n", "skip")
                    log_text.see("end"); log_text.config(state="disabled")
                    encrypted_unopened.append(pdf_path)
                    count_encrypted.set(str(len(encrypted_unopened)))
                    root.update_idletasks()
                    continue

                summary = analyze_pdf(
                    pdf_path, db_val,
                    extract_dir=pdf_extract_dir,
                    store_images=store_images_var.get(),
                    conn=conn, session=session,
                    quiet=True,
                    progress_callback=on_page_progress,
                    skip_duplicates=False,
                    force=True,
                    password=enc["password"],
                    source_analysis_id=(this_lineage[0]
                                        if this_lineage else None),
                    version_number=(this_lineage[1]
                                    if this_lineage else None))

                # Replace progress line with final result
                log_text.config(state="normal")
                log_text.delete(progress_idx,
                                f"{progress_idx} lineend + 1 char")

                if summary:
                    imgs = summary["total_extracted"]
                    finds = summary["total_findings"]
                    total_imgs += imgs
                    total_findings += finds
                    processed += 1
                    if this_is_version:
                        versions_done += 1
                    log_text.insert(progress_idx,
                        f"  \u2713 {basename} — "
                        f"{imgs} img, {finds} findings\n",
                        "success")

                    # Extract prior versions only from original
                    # PDFs, not from already-extracted versions
                    # (which are subsets of the parent file)
                    if (extract_versions_var.get()
                            and not this_is_version):
                        versions_out = (session.pdf_versions_dir
                                        or os.path.join(
                                            out_dir, "pdf_versions"))
                        os.makedirs(versions_out, exist_ok=True)
                        version_paths = extract_prior_versions(
                            pdf_path, versions_out, session=session)
                        if version_paths:
                            log_to_gui(
                                f"    \u21b3 {len(version_paths)} prior "
                                f"version(s) extracted, queued",
                                "dim")
                            parent_aid = summary.get("analysis_id")
                            start_idx = len(process_queue)
                            process_queue.extend(version_paths)
                            for off, vpath in enumerate(version_paths):
                                vi = start_idx + off
                                is_extracted_version.add(vi)
                                m = re.search(r"_version(\d+)\.pdf$",
                                              os.path.basename(vpath))
                                vnum = int(m.group(1)) if m else None
                                version_lineage[vi] = (parent_aid, vnum)
                else:
                    failed += 1
                    log_text.insert(progress_idx,
                        f"  \u2717 {basename} — no result\n",
                        "error")
                    record_submission(conn, pdf_path, "failed",
                                      session=session,
                                      reason="analysis returned no result",
                                      is_version=this_is_version)

                log_text.see("end")
                log_text.config(state="disabled")

            except Exception as e:
                failed += 1
                log_text.config(state="normal")
                log_text.delete(progress_idx,
                                f"{progress_idx} lineend + 1 char")
                log_text.insert(progress_idx,
                    f"  \u2717 {basename} — {e}\n", "error")
                log_text.see("end")
                log_text.config(state="disabled")
                if session:
                    session.log_pdf_error(pdf_path, e)
                record_submission(conn, pdf_path, "failed", session=session,
                                  reason=e, is_version=this_is_version)

            root.update_idletasks()
            count_processed.set(str(processed))
            count_failed.set(str(failed))
            count_images.set(str(total_imgs))

        conn.close()

        progress_done(processed, failed)

        log_to_gui("")
        submitted = len(pdf_files)
        originals_done = processed - versions_done
        summary_line = (
            f"{submitted} submitted: {originals_done} analysed, "
            f"{skipped_copies} skipped as identical copies of files "
            f"already analysed, {failed} failed"
            + (f" ({not_found} not found)" if not_found else "")
            + (f", {len(encrypted_unopened)} encrypted (not opened)"
               if encrypted_unopened else "")
            + (f"; plus {versions_done} prior version(s) extracted and "
               f"analysed" if versions_done else ""))
        log_to_gui(f"Done: {summary_line}", "bold")
        log_to_gui(f"      {total_imgs} images, {total_findings} findings",
                   "bold")
        if session:
            session.log(f"Run summary: {summary_line}; {total_imgs} "
                        f"images, {total_findings} findings")

        status_var.set(
            f"Done. {originals_done} analysed, {skipped_copies} identical "
            f"cop{'y' if skipped_copies == 1 else 'ies'}, {failed} failed, "
            f"{total_findings} finding(s).")
        status_label.config(fg=SUCCESS)
        run_btn_a.config(state="normal")
        from pdf_forensics.reports.case_index import refresh_case_index
        if refresh_case_index(session):
            log_to_gui("\u2713 Case index updated", "dim")

        if encrypted_unopened:
            _prompt_locked(encrypted_unopened, conn, db_val, out_dir,
                           session)

    def _prompt_locked(locked, conn, db_val, out_dir, session):
        """After a run, offer to try a password list on the files that were
        encrypted and could not be opened, and reprocess just those."""
        from pdf_forensics import passwords as _pw
        have_list = app.get("password_manager") is not None
        n = len(locked)
        if have_list:
            msg = (f"{n} PDF(s) were password-protected and the supplied "
                   f"password list did not open them. They are recorded in "
                   f"the Encrypted Files report.\n\nTry a different password "
                   f"list on those {n} file(s) now?")
            btn = "Select another list\u2026"
        else:
            msg = (f"{n} PDF(s) are password-protected and no password list "
                   f"was supplied, so they were set aside (and recorded as "
                   f"such).\n\nSelect a password list and try to open those "
                   f"{n} file(s) now?")
            btn = "Select a list\u2026"
        if not messagebox.askyesno("Encrypted PDFs", msg):
            return
        path = filedialog.askopenfilename(
            title="Select password list (one password per line)",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            passwords, info = _pw.read_password_list(path)
        except OSError as e:
            messagebox.showerror("Cannot read password list", str(e))
            return
        app["password_manager"] = _pw.PasswordManager(passwords, info)
        app["password_list_info"] = info
        pw_list_var.set(f"Password list: {len(passwords)} "
                        f"\u2014 {os.path.basename(path)}")
        if session:
            session.log(f"Password list loaded (retry on {n} locked "
                        f"file(s)): {info['path']} (MD5 {info['md5']}): "
                        f"{len(passwords)} password(s)")
        log_to_gui(f"Retrying {n} encrypted file(s) with "
                   f"{len(passwords)} password(s)\u2026", "bold")
        mgr = app["password_manager"]
        opened = still = 0
        for pdf_path in locked:
            enc = _pw.resolve_file_password(conn, pdf_path, mgr,
                                            session=session, quiet=True,
                                            record_unopened_submission=False)
            if enc["skip"]:
                still += 1
                log_to_gui(f"  \U0001f512 {os.path.basename(pdf_path)} "
                           f"— still not opened", "skip")
                continue
            base = os.path.splitext(os.path.basename(pdf_path))[0]
            pdf_extract_dir = (os.path.join(out_dir, base)
                               if out_dir else None)
            try:
                summary = analyze_pdf(
                    pdf_path, db_val, extract_dir=pdf_extract_dir,
                    store_images=store_images_var.get(), conn=conn,
                    session=session, quiet=True, skip_duplicates=False,
                    force=True, password=enc["password"])
                if summary and not summary.get("skipped"):
                    opened += 1
                    record_submission(conn, pdf_path, "analysed",
                                      session=session)
                    if app["password_manager"] and summary.get("analysis_id"):
                        conn.execute(
                            "UPDATE encryption SET analysis_id=? WHERE "
                            "id=(SELECT MAX(id) FROM encryption WHERE "
                            "pdf_path=?)",
                            (summary["analysis_id"],
                             os.path.abspath(pdf_path)))
                        conn.commit()
                    log_to_gui(f"  \u2713 {os.path.basename(pdf_path)} "
                               f"— opened and analysed", "success")
            except Exception as e:
                still += 1
                if session:
                    session.log_pdf_error(pdf_path, e)
        log_to_gui(f"Encrypted retry: {opened} opened and analysed, "
                   f"{still} still not opened", "bold")
        if session:
            session.log(f"Encrypted retry: {opened} opened, {still} still "
                        f"not opened")
        if opened:
            _regenerate_present_reports(db_val, out_dir, session)
        from pdf_forensics.reports.case_index import refresh_case_index
        refresh_case_index(session)

    def _regenerate_present_reports(db, out_dir, session):
        """After the retry opened encrypted files, rebuild the reports
        already generated for this database so they include those files
        (the Encrypted Files report in particular), instead of leaving a
        report that pre-dates the retry."""
        import glob
        from pdf_forensics.reports.queries import get_report_by_id
        from pdf_forensics.reports.renderer import generate_report
        rdir = (session.reports_dir if session and session.reports_dir
                else os.path.join(os.path.dirname(db), "reports"))
        if not os.path.isdir(rdir):
            return
        import re as _re
        done = 0
        for f in glob.glob(os.path.join(glob.escape(rdir), "*report-*.html")):
            m = _re.search(r"report-([A-Za-z0-9_]+)_\d{8}_\d{6}\.html$",
                           os.path.basename(f))
            if not m:
                continue
            rdef = get_report_by_id(m.group(1))
            if not rdef:
                continue
            try:
                generate_report(db, rdef, f, session=session)
                done += 1
            except Exception:
                pass
        # refresh the risk overview too, if present
        try:
            from pdf_forensics.reports.risk_overview import (
                generate_risk_overview_xlsx)
            for ov in glob.glob(os.path.join(glob.escape(rdir), "*risk-overview*.xlsx")):
                generate_risk_overview_xlsx(
                    db, ov, session=session,
                    case_number=(session.case_number if session else None))
        except Exception:
            pass
        if done:
            log_to_gui(f"  \u21bb Rebuilt {done} report(s) to include the "
                       f"newly opened file(s)", "dim")

    def _run_triage_mode():
        """Fast triage scan producing Excel output."""
        run_btn_a.config(state="disabled")
        status_var.set("Running triage...")
        status_label.config(fg=ACCENT)

        log_text.config(state="normal")
        log_text.delete("1.0", "end")
        log_text.config(state="disabled")

        session = app["session"]
        out_dir = output_dir_var.get()

        if not out_dir:
            out_dir = session.db_dir or os.getcwd()
            output_dir_var.set(out_dir)

        # Save triage Excel to the reports subfolder
        reports_dir = session.reports_dir or os.path.join(out_dir, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        xlsx_path = os.path.join(
            reports_dir,
            session.make_filename("triage", "xlsx"))

        # Reset counters
        count_selected.set(str(len(pdf_files)))
        count_processed.set("0")
        count_failed.set("0")
        count_images.set("0")

        log_to_gui(f"Triage: {len(pdf_files)} PDF(s)...", "bold")
        log_to_gui(f"Output: {xlsx_path}", "dim")
        log_to_gui("")
        progress_reset(len(pdf_files))

        try:
            triage_count = 0
            triage_failed = 0

            def _prompt_locked_triage(locked, xlsx_path, session, progress):
                from pdf_forensics import passwords as _pw
                n=len(locked)
                have=app.get("password_manager") is not None
                if have:
                    msg=(f"{n} encrypted PDF(s) could not be opened with the "
                         f"supplied password list, so their metadata could "
                         f"not be read.\n\nTry a different password list on "
                         f"those {n} file(s)?")
                else:
                    msg=(f"{n} PDF(s) are password-protected and no password "
                         f"list was supplied, so their metadata could not be "
                         f"read.\n\nSelect a password list and re-triage "
                         f"those {n} file(s) now?")
                if not messagebox.askyesno("Encrypted PDFs", msg):
                    return
                path=filedialog.askopenfilename(
                    title="Select password list (one password per line)",
                    filetypes=[("Text files","*.txt"),("All files","*.*")])
                if not path:
                    return
                try:
                    passwords,info=_pw.read_password_list(path)
                except OSError as e:
                    messagebox.showerror("Cannot read password list",str(e)); return
                app["password_manager"]=_pw.PasswordManager(passwords,info)
                app["password_list_info"]=info
                pw_list_var.set(f"Password list: {len(passwords)} "
                                f"\u2014 {os.path.basename(path)}")
                log_to_gui(f"Re-triaging {len(locked)} encrypted file(s) with "
                           f"{len(passwords)} password(s)\u2026","bold")
                p2,s2,o2,still=run_triage(
                    locked, xlsx_path, session=session, progress_callback=progress,
                    include_prior_versions=False,
                    password_manager=app["password_manager"])
                opened=len(locked)-len(still)
                log_to_gui(f"Encrypted re-triage: {opened} opened, "
                           f"{len(still)} still not opened. Note: this "
                           f"re-triage covers only those files; re-run triage "
                           f"on the full set to refresh the main spreadsheet.",
                           "bold")
                from pdf_forensics.reports.case_index import refresh_case_index
                refresh_case_index(session)

            def on_triage_progress(idx, total, filename):
                nonlocal triage_count, triage_failed
                triage_count = idx
                count_processed.set(str(idx))
                log_to_gui(f"  \u25cb {filename} ({idx}/{total})",
                           "dim")
                progress_set_file(idx - 1, total, filename)

            processed, skipped, out, locked = run_triage(
                list(pdf_files), xlsx_path,
                session=session,
                progress_callback=on_triage_progress,
                password_manager=app.get("password_manager"))

            count_processed.set(str(processed))
            count_failed.set(str(skipped))
            progress_done(processed, skipped)

            log_to_gui("")
            log_to_gui(
                f"Done: {processed} triaged, {skipped} skipped",
                "bold")
            if processed:
                log_to_gui(
                    f"\u2713 {os.path.basename(xlsx_path)}",
                    "success")

            status_var.set(
                f"Triage done. {processed} PDF(s) -> "
                f"{os.path.basename(xlsx_path)}")
            status_label.config(fg=SUCCESS)
            from pdf_forensics.reports.case_index import (
                refresh_case_index)
            if refresh_case_index(session):
                log_to_gui("\u2713 Case index updated", "dim")

            if locked:
                _prompt_locked_triage(locked, xlsx_path, session,
                                      on_triage_progress)

        except Exception as e:
            import traceback
            status_var.set(f"Error: {e}")
            status_label.config(fg=ACCENT)
            log_to_gui(f"\u2717 Error: {e}", "error")
            if session:
                session.log(f"Triage error: {e}", "error")
                session.log(traceback.format_exc(), "error")
        finally:
            run_btn_a.config(state="normal")

    run_btn_a = ttk.Button(action_row_a, text="Run analysis",
                           style="Accent.TButton", command=run_analysis)
    run_btn_a.pack(fill="x")

    # Apply initial triage state (default is triage=True)
    on_triage_toggle()

    # ===================================================================
    # GRAPH SUB-MENU FRAME (left-right split)
    # ===================================================================
    graph_frame = tk.Frame(content_area, bg=BG_DARK)
    frames["graph"] = graph_frame

    # Back button
    back_row_g = tk.Frame(graph_frame, bg=BG_DARK)
    back_row_g.pack(fill="x", padx=20, pady=(10, 6))
    ttk.Button(back_row_g, text="< Back to Main Menu",
               command=lambda: show_frame("main")).pack(side="left")

    # Horizontal split
    g_split = tk.Frame(graph_frame, bg=BG_DARK)
    g_split.pack(fill="both", expand=True, padx=20, pady=(0, 8))

    g_left = tk.Frame(g_split, bg=BG_DARK, width=420)
    g_left.pack(side="left", fill="y", padx=(0, 10))
    g_left.pack_propagate(False)

    g_right = tk.Frame(g_split, bg=BG_DARK)
    g_right.pack(side="left", fill="both", expand=True)

    # --- LEFT: controls ---

    # DB picker
    graph_db_var = tk.StringVar()
    gdb_body = make_panel(g_left, "Database")
    gdb_row = tk.Frame(gdb_body, bg=BG_PANEL)
    gdb_row.pack(fill="x")
    ttk.Entry(gdb_row, textvariable=graph_db_var).pack(
        side="left", fill="x", expand=True, padx=(0, 8))

    def choose_graph_db():
        path = filedialog.askopenfilename(
            title="Select PDF Forensics database",
            filetypes=[("SQLite database", "*.db *.sqlite *.sqlite3"),
                       ("All files", "*.*")])
        if path:
            graph_db_var.set(path)

    ttk.Button(gdb_row, text="Browse",
               command=choose_graph_db).pack(side="left")
    ttk.Label(gdb_body,
              text="Select the database generated by PDF analysis.",
              style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

    # Scope checkboxes
    scope_body = make_panel(g_left, "Scope (select one or more)")
    scope_vars = {
        "all_placements": tk.BooleanVar(value=True),
        "cross_page": tk.BooleanVar(value=True),
        "cross_document": tk.BooleanVar(value=True),
    }
    _scope_all = ttk.Checkbutton(
        scope_body, text="All placements (image appears 2+ times)",
        variable=scope_vars["all_placements"])
    _scope_all.pack(anchor="w")
    attach_tooltip(_scope_all,
                   "Graph every image that appears two or more times "
                   "anywhere in the analyzed set \u2014 the broadest view "
                   "of image reuse, including repeats within a single page.")
    _scope_cp = ttk.Checkbutton(
        scope_body, text="Cross-page (image on 2+ distinct pages)",
        variable=scope_vars["cross_page"])
    _scope_cp.pack(anchor="w")
    attach_tooltip(_scope_cp,
                   "Only graph images that recur on two or more different "
                   "pages, highlighting content reused across pages of a "
                   "document.")
    _scope_cd = ttk.Checkbutton(
        scope_body, text="Cross-document (image in 2+ documents)",
        variable=scope_vars["cross_document"])
    _scope_cd.pack(anchor="w")

    group_versions_var = tk.BooleanVar(value=True)
    _grp = ttk.Checkbutton(
        scope_body,
        text="Group prior versions by lineage (recommended)",
        variable=group_versions_var)
    _grp.pack(anchor="w", pady=(6, 0))
    attach_tooltip(_grp,
                   "In cross-document scope, treat a document and the prior "
                   "versions extracted from it as one lineage, so an image "
                   "shared only between a document and its own versions is "
                   "shown as version reuse (violet, dashed) rather than "
                   "counted as cross-document reuse. Uncheck to treat every "
                   "version as a separate document. Version placements are "
                   "always drawn with dashed edges regardless of this "
                   "setting.")

    attach_tooltip(_scope_cd,
                   "Only graph images that appear in two or more separate "
                   "documents \u2014 useful for spotting a shared stamp, "
                   "signature, or template across supposedly independent "
                   "files.")

    # Generate button
    action_row_g = tk.Frame(g_left, bg=BG_DARK)
    action_row_g.pack(fill="x", side="bottom", pady=(8, 4))

    # --- RIGHT: status log ---
    g_log_outer = tk.Frame(g_right, bg=BORDER, padx=1, pady=1)
    g_log_outer.pack(fill="both", expand=True)
    g_log_inner = tk.Frame(g_log_outer, bg=BG_PANEL)
    g_log_inner.pack(fill="both", expand=True)
    ttk.Label(g_log_inner, text="GENERATION LOG",
              style="Section.TLabel").pack(
        anchor="w", padx=10, pady=(8, 4))

    g_log_frame = tk.Frame(g_log_inner, bg=BG_PANEL)
    g_log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))
    g_log_scroll = tk.Scrollbar(g_log_frame)
    g_log_scroll.pack(side="right", fill="y")
    g_log_text = tk.Text(
        g_log_frame, wrap="word", bg=BG_INPUT, fg=TEXT_PRIM,
        insertbackground=TEXT_PRIM, highlightthickness=0,
        borderwidth=0, font=(FONT_FAMILY, 9), padx=8, pady=6,
        relief="flat", yscrollcommand=g_log_scroll.set)
    g_log_text.pack(fill="both", expand=True)
    g_log_scroll.config(command=g_log_text.yview)
    g_log_text.tag_configure("success", foreground=SUCCESS)
    g_log_text.tag_configure("error", foreground=ACCENT)
    g_log_text.tag_configure("dim", foreground=TEXT_DIM)
    g_log_text.tag_configure("bold",
                             font=(FONT_FAMILY, 9, "bold"))
    g_log_text.config(state="disabled")

    def g_log(msg, tag=None):
        g_log_text.config(state="normal")
        if tag:
            g_log_text.insert("end", msg + "\n", tag)
        else:
            g_log_text.insert("end", msg + "\n")
        g_log_text.see("end")
        g_log_text.config(state="disabled")
        root.update_idletasks()

    def run_graph():
        if not HAS_GRAPH:
            messagebox.showerror(
                "Missing dependency",
                "networkx and/or pyvis are not installed.\n\n"
                "Install with: pip install networkx pyvis")
            return
        db = graph_db_var.get()
        if not db or not os.path.isfile(db):
            messagebox.showerror("No database",
                                 "Please select a valid database file.")
            return
        if not app["session"]:
            messagebox.showerror("No case",
                                 "Please set a case number first.")
            return

        scopes = [k for k, v in scope_vars.items() if v.get()]
        if not scopes:
            messagebox.showerror("No scope",
                                 "Please select at least one scope.")
            return

        run_btn_g.config(state="disabled")
        status_var.set("Generating graph(s)...")
        status_label.config(fg=ACCENT)

        # Clear log
        g_log_text.config(state="normal")
        g_log_text.delete("1.0", "end")
        g_log_text.config(state="disabled")

        session = app["session"]
        try:
            conn = sqlite3.connect(db)
            validate_database(conn)

            g_log(f"Database: {os.path.basename(db)}", "dim")
            g_log(f"Scopes: {', '.join(scopes)}", "dim")
            g_log("")

            generated = []
            # Scopes are nested filters over the same duplicate-
            # image data, so two scopes can legitimately select
            # the identical dataset (e.g. no image repeats solely
            # within a single page). Track each scope's dataset so
            # the coincidence is reported at generation time
            # instead of being discovered later by hashing files.
            dataset_seen = {}
            for scope in scopes:
                session.log(f"Generating graph: scope={scope}")
                g_log(f"  Loading data for {scope}...")

                rows = load_data(
                    conn, scope=scope,
                    group_versions=group_versions_var.get())
                if not rows:
                    g_log(f"  \u2298 {scope} — no data", "dim")
                    session.log(f"  No data for scope {scope}")
                    continue

                md5_set = {row[6] for row in rows}
                g_log(f"  {len(rows)} placements, "
                      f"{len(md5_set)} unique images")

                dataset_key = tuple(rows)
                same_as = dataset_seen.get(dataset_key)
                if same_as:
                    note = (f"Note: {scope} selected the identical "
                            f"dataset as {same_as} for this "
                            f"database \u2014 the two graphs show "
                            f"the same relationships.")
                    g_log(f"  \u24d8 {note}", "dim")
                    session.log(f"  {note}")
                else:
                    dataset_seen[dataset_key] = scope

                image_bytes = load_image_bytes(conn, md5_set)
                findings_by_md5 = load_findings_for_md5s(conn, md5_set)

                g_log(f"  Generating thumbnails...")
                root.update_idletasks()
                thumbnails = {}
                for md5, (blob, ext, w, h) in image_bytes.items():
                    thumb = make_thumbnail_data_uri(blob, ext, w, h)
                    if thumb:
                        thumbnails[md5] = thumb

                g_log(f"  Building graph...")
                root.update_idletasks()
                G = build_graph(rows, thumbnails)
                image_meta = build_image_metadata(rows, findings_by_md5)
                doc_meta = build_document_metadata(rows)

                scope_label = scope.replace("_", "")
                out_path = session.make_graph_path(scope_label)
                if not out_path:
                    out_path = f"graph-{scope_label}.html"

                g_log(f"  Writing HTML...")
                root.update_idletasks()
                visualize_graph(
                    G, image_meta, thumbnails, db,
                    doc_meta=doc_meta,
                    output_path=out_path,
                    case_number=(session.case_number
                                 if session else None),
                    scope=scope,
                    group_versions=group_versions_var.get())

                session.register_output("graph", out_path)
                generated.append((scope, out_path))
                session.log(f"  Generated: {out_path}")
                g_log(f"  \u2713 {scope} — {os.path.basename(out_path)}",
                      "success")

            conn.close()

            g_log("")
            if generated:
                g_log(f"Done. {len(generated)} graph(s) generated.",
                      "bold")
                status_var.set(
                    f"Done. {len(generated)} graph(s) generated.")
                status_label.config(fg=SUCCESS)
                from pdf_forensics.reports.case_index import (
                    refresh_case_index)
                if refresh_case_index(session):
                    g_log("  \u2713 Case index updated", "dim")
            else:
                g_log("No data found for selected scopes.", "dim")
                status_var.set("No data found for selected scopes.")
                status_label.config(fg=TEXT_SEC)

        except Exception as e:
            status_var.set(f"Error: {e}")
            status_label.config(fg=ACCENT)
            g_log(f"\u2717 Error: {e}", "error")
            session.log(f"Graph error: {e}", "error")
        finally:
            run_btn_g.config(state="normal")

    run_btn_g = ttk.Button(action_row_g, text="Generate graph(s)",
                           style="Accent.TButton", command=run_graph)
    run_btn_g.pack(fill="x")

    # ===================================================================
    # REPORTS SUB-MENU FRAME (left-right split)
    # ===================================================================
    reports_frame = tk.Frame(content_area, bg=BG_DARK)
    frames["reports"] = reports_frame

    # Back button
    back_row_r = tk.Frame(reports_frame, bg=BG_DARK)
    back_row_r.pack(fill="x", padx=20, pady=(10, 6))
    ttk.Button(back_row_r, text="< Back to Main Menu",
               command=lambda: show_frame("main")).pack(side="left")

    # Horizontal split
    r_split = tk.Frame(reports_frame, bg=BG_DARK)
    r_split.pack(fill="both", expand=True, padx=20, pady=(0, 8))

    r_left = tk.Frame(r_split, bg=BG_DARK, width=560)
    r_left.pack(side="left", fill="y", padx=(0, 10))
    r_left.pack_propagate(False)

    r_right = tk.Frame(r_split, bg=BG_DARK)
    r_right.pack(side="left", fill="both", expand=True)

    # --- LEFT: controls ---

    # Generate button row — packed to the bottom FIRST so it always
    # remains visible regardless of how many panels are stacked above.
    action_row_r = tk.Frame(r_left, bg=BG_DARK)
    action_row_r.pack(fill="x", side="bottom", pady=(8, 4))

    # DB picker for reports
    report_db_var = tk.StringVar()
    rdb_body = make_panel(r_left, "Database")
    rdb_row = tk.Frame(rdb_body, bg=BG_PANEL)
    rdb_row.pack(fill="x")
    ttk.Entry(rdb_row, textvariable=report_db_var).pack(
        side="left", fill="x", expand=True, padx=(0, 8))

    def choose_report_db():
        path = filedialog.askopenfilename(
            title="Select PDF Forensics database",
            filetypes=[("SQLite database", "*.db *.sqlite *.sqlite3"),
                       ("All files", "*.*")])
        if path:
            report_db_var.set(path)

    ttk.Button(rdb_row, text="Browse",
               command=choose_report_db).pack(side="left")

    # Report checkboxes, grouped by analytical theme with tooltips.
    from pdf_forensics.reports.queries import (
        list_reports as _list_rpts,
        list_report_groups as _list_rpt_groups)

    rpt_body = make_panel(r_left, "Select reports")
    report_vars = {}

    # Render each group: a small header, then its reports in two columns.
    for _label, _items in _list_rpt_groups():
        hdr = tk.Label(rpt_body, text=_label.upper(), bg=BG_PANEL,
                       fg=ACCENT, font=(FONT_FAMILY, 8, "bold"),
                       anchor="w")
        hdr.pack(anchor="w", pady=(6, 1))
        grid = tk.Frame(rpt_body, bg=BG_PANEL)
        grid.pack(fill="x")
        grid.grid_columnconfigure(0, weight=1, uniform="rptcol")
        grid.grid_columnconfigure(1, weight=1, uniform="rptcol")
        half = (len(_items) + 1) // 2
        for _i, (rid, rname, rdesc) in enumerate(_items):
            var = tk.BooleanVar(value=True)
            report_vars[rid] = var
            col = 0 if _i < half else 1
            row = _i if _i < half else _i - half
            cb = ttk.Checkbutton(grid, text=rname, variable=var)
            cb.grid(row=row, column=col, sticky="w", padx=(0, 10), pady=1)
            attach_tooltip(cb, rdesc)

    # Select all / none buttons
    rpt_btns = tk.Frame(rpt_body, bg=BG_PANEL)
    rpt_btns.pack(fill="x", pady=(6, 0))

    def select_all_reports():
        for v in report_vars.values():
            v.set(True)

    def select_none_reports():
        for v in report_vars.values():
            v.set(False)

    ttk.Button(rpt_btns, text="Select all",
               command=select_all_reports).pack(side="left")
    ttk.Button(rpt_btns, text="Select none",
               command=select_none_reports).pack(
        side="left", padx=(8, 0))

    # Visual overlay report option
    visual_opts = make_panel(r_left, "Visual report")
    visual_report_var = tk.BooleanVar(value=True)
    _visual_cb = ttk.Checkbutton(
        visual_opts,
        text="Generate visual overlay report (annotated page images)",
        variable=visual_report_var)
    _visual_cb.pack(anchor="w")
    attach_tooltip(
        _visual_cb,
        "Renders flagged pages with detected text/image overlays "
        "highlighted, for non-technical review. Requires the source "
        "PDF(s) to be accessible.")

    # --- RIGHT: status log ---
    r_log_outer = tk.Frame(r_right, bg=BORDER, padx=1, pady=1)
    r_log_outer.pack(fill="both", expand=True)
    r_log_inner = tk.Frame(r_log_outer, bg=BG_PANEL)
    r_log_inner.pack(fill="both", expand=True)
    ttk.Label(r_log_inner, text="REPORT LOG",
              style="Section.TLabel").pack(
        anchor="w", padx=10, pady=(8, 4))

    r_log_frame = tk.Frame(r_log_inner, bg=BG_PANEL)
    r_log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))
    r_log_scroll = tk.Scrollbar(r_log_frame)
    r_log_scroll.pack(side="right", fill="y")
    r_log_text = tk.Text(
        r_log_frame, wrap="word", bg=BG_INPUT, fg=TEXT_PRIM,
        insertbackground=TEXT_PRIM, highlightthickness=0,
        borderwidth=0, font=(FONT_FAMILY, 9), padx=8, pady=6,
        relief="flat", yscrollcommand=r_log_scroll.set)
    r_log_text.pack(fill="both", expand=True)
    r_log_scroll.config(command=r_log_text.yview)
    r_log_text.tag_configure("success", foreground=SUCCESS)
    r_log_text.tag_configure("error", foreground=ACCENT)
    r_log_text.tag_configure("dim", foreground=TEXT_DIM)
    r_log_text.tag_configure("bold",
                             font=(FONT_FAMILY, 9, "bold"))
    r_log_text.config(state="disabled")

    def r_log(msg, tag=None):
        r_log_text.config(state="normal")
        if tag:
            r_log_text.insert("end", msg + "\n", tag)
        else:
            r_log_text.insert("end", msg + "\n")
        r_log_text.see("end")
        r_log_text.config(state="disabled")
        root.update_idletasks()

    def run_reports():
        db = report_db_var.get()
        if not db or not os.path.isfile(db):
            messagebox.showerror("No database",
                                 "Please select a valid database file.")
            return
        if not app["session"]:
            messagebox.showerror("No case",
                                 "Please set a case number first.")
            return

        selected = [rid for rid, var in report_vars.items()
                    if var.get()]
        # The visual overlay report can be run on its own — an
        # examiner who generated the standard reports earlier
        # should not have to re-select one to run the visual
        # report afterwards.
        if not selected and not visual_report_var.get():
            messagebox.showerror(
                "No reports",
                "Please select at least one report, or enable "
                "the visual overlay report.")
            return

        run_btn_r.config(state="disabled")
        status_var.set("Generating reports...")
        status_label.config(fg=ACCENT)

        # Clear log
        r_log_text.config(state="normal")
        r_log_text.delete("1.0", "end")
        r_log_text.config(state="disabled")

        session = app["session"]
        try:
            from pdf_forensics.reports.queries import get_report_by_id
            from pdf_forensics.reports.renderer import generate_report

            out_dir = session.reports_dir
            if not out_dir:
                out_dir = os.path.join(
                    os.path.dirname(db), "reports")
            os.makedirs(out_dir, exist_ok=True)

            r_log(f"Database: {os.path.basename(db)}", "dim")
            r_log(f"Output: {out_dir}", "dim")
            r_log(f"Reports: {len(selected)}", "dim")
            r_log("")

            results = []
            for rid in selected:
                report_def = get_report_by_id(rid)
                if not report_def:
                    r_log(f"  \u2717 {rid} — unknown report ID", "error")
                    continue

                r_log(f"  Generating {report_def['name']}...")
                root.update_idletasks()

                fname = session.make_filename(
                    f"report-{rid}", "html")
                out_path = os.path.join(out_dir, fname)

                try:
                    row_count = generate_report(
                        db, report_def, out_path, session=session)
                    results.append((rid, out_path, row_count))
                    r_log(f"  \u2713 {report_def['name']} — "
                          f"{row_count} rows", "success")
                except Exception as e:
                    r_log(f"  \u2717 {report_def['name']} — {e}",
                          "error")
                    session.log(f"Report error ({rid}): {e}", "error")

            r_log("")
            if results:
                r_log(f"Done. {len(results)} report(s) generated.",
                      "bold")
                status_var.set(
                    f"Done. {len(results)} report(s) generated.")
                status_label.config(fg=SUCCESS)
            else:
                r_log("No reports generated.", "dim")
                status_var.set("No reports generated.")
                status_label.config(fg=TEXT_SEC)

            # Visual overlay report (optional)
            if visual_report_var.get():
                r_log("")
                r_log("Generating visual overlay report...")
                root.update_idletasks()
                try:
                    from pdf_forensics.reports.visual import (
                        generate_visual_report)
                    vfname = session.make_filename(
                        "visual-overlays", "html")
                    vpath = os.path.join(out_dir, vfname)
                    n = generate_visual_report(
                        db, vpath, session=session)
                    if n > 0:
                        r_log(f"  \u2713 Visual overlay report — "
                              f"{n} finding(s)", "success")
                        if not results:
                            status_var.set(
                                "Done. Visual overlay report "
                                "generated.")
                            status_label.config(fg=SUCCESS)
                    else:
                        r_log("  No overlay findings to visualize.",
                              "dim")
                except Exception as e:
                    r_log(f"  \u2717 Visual report — {e}", "error")
                    session.log(f"Visual report error: {e}", "error")

            # Document Risk Overview (Excel) + report index page.
            r_log("")
            ov_path = None
            try:
                from pdf_forensics.reports.risk_overview import (
                    generate_risk_overview_xlsx)
                ov_path = os.path.join(
                    out_dir, session.make_filename("risk-overview", "xlsx"))
                nov = generate_risk_overview_xlsx(
                    db, ov_path, session=session,
                    case_number=session.case_number)
                session.register_output("risk_overview", ov_path)
                r_log(f"  \u2713 Document Risk Overview (xlsx) — "
                      f"{nov} document(s)", "success")
            except Exception as e:
                ov_path = None
                r_log(f"  Document Risk Overview skipped — {e}", "dim")
            from pdf_forensics.reports.case_index import (
                refresh_case_index)
            if refresh_case_index(session, log=lambda m: r_log(f"  {m}",
                                                                "dim")):
                r_log("  \u2713 Case index updated", "success")

        except Exception as e:
            status_var.set(f"Error: {e}")
            status_label.config(fg=ACCENT)
            r_log(f"\u2717 Error: {e}", "error")
            session.log(f"Report error: {e}", "error")
        finally:
            run_btn_r.config(state="normal")

    run_btn_r = ttk.Button(action_row_r, text="Generate reports",
                           style="Accent.TButton", command=run_reports)
    run_btn_r.pack(fill="x")


    # Sync report DB when analysis DB changes
    def sync_report_db(*_):
        v = db_path_var.get()
        if v and not report_db_var.get():
            report_db_var.set(v)
    db_path_var.trace_add("write", sync_report_db)

    # ===================================================================
    # CASE NUMBER PROMPT ON STARTUP
    # ===================================================================
    def setup_session(case, always_prompt_dir=False):
        """Create a session and pre-populate path fields.

        When always_prompt_dir is True (e.g. when the user changes the
        case number), the output directory chooser is always shown so the
        user explicitly confirms where this new case is saved, instead of
        silently reusing the previous case's folder and database.
        """
        session = Session(case)
        app["session"] = session
        app["case_var"].set(case)

        # Check if user already selected an existing DB
        current_db = db_path_var.get()
        user_selected_db = (
            current_db
            and current_db != "pdf_forensics.db"
            and os.path.isfile(current_db))

        if user_selected_db and not always_prompt_dir:
            # Use the existing DB's directory as the base
            base_dir = os.path.dirname(os.path.abspath(current_db))
        else:
            # Ask for base output directory. The user may pick an existing
            # folder or create a new one.
            base_dir = filedialog.askdirectory(
                title=f"Select output directory for case: {case}",
                mustexist=False)
            if not base_dir:
                base_dir = os.path.join(os.getcwd(), case)
            # A freshly chosen directory means we are no longer bound to a
            # previously selected database; let the session derive its own.
            if always_prompt_dir:
                user_selected_db = False

        session.set_db_dir(base_dir)

        if not user_selected_db:
            # Only set DB path if user hasn't already chosen one
            db_path_var.set(session.make_db_path())

        # Always set output dir, graph DB, and report DB
        output_dir_var.set(session.extracted_images_dir)
        os.makedirs(session.extracted_images_dir, exist_ok=True)
        graph_db_var.set(db_path_var.get())
        report_db_var.set(db_path_var.get())

        status_var.set(f"Session started for case: {case}")
        session.log(f"Output base directory: {base_dir}")

    def prompt_case_number():
        cfg = load_config()
        last_case = cfg.get("last_case", "")
        initial = initial_case or last_case

        case = simpledialog.askstring(
            "Case Number",
            "Enter a case number for this session:\n\n"
            "All output files will be organized under this case.",
            parent=root,
            initialvalue=initial)

        if not case or not case.strip():
            case = f"ADHOC_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        setup_session(case.strip())

    def show_first_run_acknowledgment(on_done):
        """On the first ever launch, show the full short-form disclaimer as a
        blocking dialog the user must acknowledge to proceed. On every launch
        thereafter this is skipped (the permanent status-bar reminder and the
        About dialog carry the disclaimer forward). Calls on_done() when the
        user may proceed."""
        from pdf_forensics import disclaimers as _disc
        from pdf_forensics import acknowledgement as _ack
        cfg = load_config()
        if not _ack.acknowledgement_needed(cfg):
            on_done()
            return
        _reason = _ack.reprompt_reason(cfg)

        dlg = tk.Toplevel(root)
        dlg.title("Disclaimer \u2014 Please Read")
        dlg.configure(bg=BG_DARK)
        dlg.transient(root)
        dlg.grab_set()   # modal / blocking
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)  # must acknowledge

        tk.Label(dlg, text="USE AT YOUR OWN RISK",
                 bg=BG_DARK, fg=ACCENT,
                 font=(FONT_FAMILY, 14, "bold")).pack(
                     anchor="w", padx=24, pady=(22, 8))

        if _reason:
            tk.Label(dlg, text=_reason, bg=BG_DARK, fg=TEXT_SEC,
                     justify="left", anchor="w", wraplength=560,
                     font=FONT_SUBTITLE).pack(anchor="w", padx=24,
                                              pady=(0, 10))

        msg = tk.Label(dlg, text=_disc.SHORT_DISCLAIMER, bg=BG_DARK,
                       fg=TEXT_PRIM, justify="left", anchor="w",
                       wraplength=560, font=FONT_SUBTITLE)
        msg.pack(anchor="w", padx=24, pady=(0, 12))

        tk.Label(dlg,
                 text="The full disclaimer is always available under "
                      "Help \u2192 About.",
                 bg=BG_DARK, fg=TEXT_SEC, justify="left", anchor="w",
                 wraplength=560, font=FONT_SUBTITLE).pack(
                     anchor="w", padx=24, pady=(0, 14))

        ack_var = tk.BooleanVar(value=False)
        ack = ttk.Checkbutton(
            dlg,
            text="I have read and understand this disclaimer.",
            variable=ack_var)
        ack.pack(anchor="w", padx=24, pady=(0, 14))

        btn_row = tk.Frame(dlg, bg=BG_DARK)
        btn_row.pack(fill="x", padx=24, pady=(0, 18))

        def proceed():
            cfg2 = load_config()
            cfg2["disclaimer_acknowledged"] = True
            # When, by whom, on which computer, against which disclaimer
            # text and with which build (written to every session log).
            cfg2["disclaimer_acknowledgement"] = _ack.make_record()
            save_config(cfg2)
            dlg.grab_release()
            dlg.destroy()
            on_done()

        def do_exit():
            dlg.grab_release()
            dlg.destroy()
            root.destroy()

        proceed_btn = ttk.Button(btn_row, text="I Agree \u2014 Continue",
                                 style="Accent.TButton",
                                 command=proceed, state="disabled")
        proceed_btn.pack(side="right")
        ttk.Button(btn_row, text="Exit",
                   style="Danger.TButton",
                   command=do_exit).pack(side="right", padx=(0, 8))

        def _toggle(*_):
            proceed_btn.config(
                state="normal" if ack_var.get() else "disabled")
        ack_var.trace_add("write", _toggle)

        dlg.update_idletasks()
        try:
            w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
            x = root.winfo_x() + (root.winfo_width() - w) // 2
            y = root.winfo_y() + (root.winfo_height() - h) // 3
            dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass
        dlg.wait_window()

    # ===================================================================
    # LAUNCH
    # ===================================================================
    show_frame("main")
    # First-run disclaimer acknowledgment, then the case-number prompt.
    root.after(
        100,
        lambda: show_first_run_acknowledgment(prompt_case_number))
    root.mainloop()

    # Write session summary on exit
    if app["session"]:
        app["session"].write_summary(db_path=db_path_var.get())
