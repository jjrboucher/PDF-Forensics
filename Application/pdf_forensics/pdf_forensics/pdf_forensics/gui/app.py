"""
Main application GUI — unified launcher with main menu and sub-menus.
"""

import os
import sys
import sqlite3
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import datetime

from pdf_forensics import __version__, __tool_name__, SCHEMA_REVISION
from pdf_forensics.session import Session, load_config
from pdf_forensics.database import (
    validate_database, init_db, check_pdf_already_analyzed,
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
    }
    pdf_files = list(initial_pdfs) if initial_pdfs else []
    db_path_var = tk.StringVar(value=initial_db or "pdf_forensics.db")
    output_dir_var = tk.StringVar(value=initial_output or "")
    store_images_var = tk.BooleanVar(value=initial_store_images)

    # ---------------------------------------------------------------
    # Persistent header bar
    # ---------------------------------------------------------------
    header = tk.Frame(root, bg=BG_DARK, height=96)
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
    tk.Label(title_block, text=f"v{__version__}", bg=BG_DARK,
             fg=TEXT_DIM, font=FONT_SUBTITLE).pack(anchor="w")

    # Case badge (right side of header)
    case_frame = tk.Frame(header, bg=BG_DARK)
    case_frame.pack(side="right", padx=24, pady=14)
    tk.Label(case_frame, text="CASE:", bg=BG_DARK, fg=TEXT_SEC,
             font=(FONT_FAMILY, 9, "bold")).pack(side="left")
    case_label = tk.Label(case_frame, textvariable=app["case_var"],
                          bg=BG_DARK, fg=ACCENT,
                          font=(FONT_FAMILY, 12, "bold"))
    case_label.pack(side="left", padx=(6, 0))

    # Help button (right side, before case badge)
    def show_about():
        import platform as pf
        env_lines = [
            f"{__tool_name__} v{__version__}",
            "",
            f"Python: {sys.version.split()[0]}",
            f"OS: {pf.platform()}",
        ]
        try:
            import pymupdf
            env_lines.append(f"PyMuPDF: {pymupdf.version}")
        except Exception:
            env_lines.append("PyMuPDF: not installed")
        try:
            import pikepdf
            env_lines.append(f"pikepdf: {pikepdf.__version__}")
        except Exception:
            env_lines.append("pikepdf: not installed")
        try:
            import PIL
            env_lines.append(f"Pillow: {PIL.__version__}")
        except Exception:
            env_lines.append("Pillow: not installed")
        try:
            import networkx
            env_lines.append(f"networkx: {networkx.__version__}")
        except Exception:
            env_lines.append("networkx: not installed")
        try:
            import pyvis
            env_lines.append(
                f"pyvis: {getattr(pyvis, '__version__', 'installed')}")
        except Exception:
            env_lines.append("pyvis: not installed")

        env_lines.append("")
        env_lines.append(f"Schema revision: {SCHEMA_REVISION}")

        if app["session"]:
            env_lines.append(f"Case: {app['case_var'].get()}")
            s = app["session"]
            if s.db_dir:
                env_lines.append(f"Output: {s.db_dir}")
            if s.log_path:
                env_lines.append(f"Log: {s.log_path}")

        messagebox.showinfo("About", "\n".join(env_lines))

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

    # ---------------------------------------------------------------
    # Frame switching
    # ---------------------------------------------------------------
    frames = {}

    # Per-frame window sizes: (width, height)
    frame_sizes = {
        "main":     (780, 540),
        "analysis": (1060, 860),
        "graph":    (1060, 540),
        "reports":  (1060, 800),
    }

    def center_window(w, h):
        """Position window centered horizontally, biased toward top."""
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
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
                    f"a new session.\n\nAny case-wide counters "
                    f"will reset, and a new log file will be "
                    f"created.\n\nContinue?"):
                    return
                app["session"].write_summary(
                    db_path=db_path_var.get())
            pdf_files.clear()
            try:
                pdf_listbox.delete(0, "end")
            except Exception:
                pass
            setup_session(new_case)

    ttk.Button(main_btns, text="Change case number",
               command=change_case).pack(side="left")
    ttk.Button(main_btns, text="Exit", style="Danger.TButton",
               command=root.destroy).pack(side="right")

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

    left_panel = tk.Frame(split, bg=BG_DARK, width=420)
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

    def add_pdfs_from_list():
        path = filedialog.askopenfilename(
            title="Select text file with PDF paths",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        added = 0
        missing = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if os.path.isfile(line):
                    if line not in pdf_files:
                        pdf_files.append(line)
                        pdf_listbox.insert("end", line)
                        added += 1
                else:
                    missing.append(line)
        msg = f"Added {added} PDF(s)."
        if missing:
            msg += f"\n{len(missing)} file(s) not found."
        messagebox.showinfo("Import Complete", msg)

    def remove_pdfs():
        selected = list(pdf_listbox.curselection())
        for idx in reversed(selected):
            del pdf_files[idx]
            pdf_listbox.delete(idx)

    def remove_all_pdfs():
        pdf_files.clear()
        pdf_listbox.delete(0, "end")

    pdf_btns = tk.Frame(pdf_body, bg=BG_PANEL)
    pdf_btns.pack(fill="x")
    ttk.Button(pdf_btns, text="Add files",
               command=add_pdfs).pack(side="left")
    ttk.Button(pdf_btns, text="From list",
               command=add_pdfs_from_list).pack(side="left", padx=(6, 0))
    ttk.Button(pdf_btns, text="Remove",
               command=remove_pdfs).pack(side="left", padx=(6, 0))
    ttk.Button(pdf_btns, text="Clear all",
               command=remove_all_pdfs).pack(side="left", padx=(6, 0))

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
    counter_label(counter_row, "Images", count_images)

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
        failed = 0
        total_imgs = 0
        total_findings = 0

        count_processed.set("0")
        count_failed.set("0")
        count_images.set("0")
        update_counters()

        log_to_gui(f"Processing {len(pdf_files)} PDF(s)...", "bold")
        log_to_gui(f"Database: {os.path.basename(db_val)}", "dim")
        log_to_gui("")

        # Build a processing queue so extracted versions can be added.
        # Track which entries are extracted versions so we don't
        # cascade (extract versions from versions).
        process_queue = list(pdf_files)
        is_extracted_version = set()  # indices of extracted versions
        queue_idx = 0

        while queue_idx < len(process_queue):
            pdf_path = process_queue[queue_idx]
            this_is_version = queue_idx in is_extracted_version
            queue_idx += 1
            basename = os.path.basename(pdf_path)

            if not os.path.isfile(pdf_path):
                log_to_gui(f"  \u2717 {basename} — not found", "error")
                failed += 1
                count_failed.set(str(failed))
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
            root.update_idletasks()

            def on_page_progress(page_num, total_pages,
                                 _idx=progress_idx, _name=basename):
                log_text.config(state="normal")
                log_text.delete(_idx, f"{_idx} lineend + 1 char")
                log_text.insert(_idx,
                    f"  \u25cb {_name} — "
                    f"page {page_num}/{total_pages}\n", "dim")
                log_text.see("end")
                log_text.config(state="disabled")
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
                            f"  \u2298 {basename} — already in DB "
                            f"({dup_info['analyzed_at']})\n", "skip")
                        log_text.see("end")
                        log_text.config(state="disabled")
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
                    force=True)

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
                    log_text.insert(progress_idx,
                        f"  \u2713 {basename} — "
                        f"{imgs} img, {finds} findings\n",
                        "success")

                    # Extract prior versions only from original
                    # PDFs, not from already-extracted versions
                    # (which are subsets of the parent file)
                    if (extract_versions_var.get()
                            and not this_is_version):
                        version_paths = extract_prior_versions(
                            pdf_path, out_dir, session=session)
                        if version_paths:
                            log_to_gui(
                                f"    \u21b3 {len(version_paths)} prior "
                                f"version(s) extracted, queued",
                                "dim")
                            start_idx = len(process_queue)
                            process_queue.extend(version_paths)
                            for vi in range(start_idx,
                                            len(process_queue)):
                                is_extracted_version.add(vi)
                else:
                    failed += 1
                    log_text.insert(progress_idx,
                        f"  \u2717 {basename} — no result\n",
                        "error")

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

            root.update_idletasks()
            count_processed.set(str(processed))
            count_failed.set(str(failed))
            count_images.set(str(total_imgs))

        conn.close()

        log_to_gui("")
        log_to_gui(
            f"Done: {processed} processed, {failed} failed, "
            f"{total_imgs} images, {total_findings} findings", "bold")

        status_var.set(
            f"Done. {processed} PDF(s), "
            f"{total_findings} finding(s), "
            f"{total_imgs} image(s).")
        status_label.config(fg=SUCCESS)
        run_btn_a.config(state="normal")

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

        try:
            triage_count = 0
            triage_failed = 0

            def on_triage_progress(idx, total, filename):
                nonlocal triage_count, triage_failed
                triage_count = idx
                count_processed.set(str(idx))
                log_to_gui(f"  \u25cb {filename} ({idx}/{total})",
                           "dim")

            processed, skipped, out = run_triage(
                list(pdf_files), xlsx_path,
                session=session,
                progress_callback=on_triage_progress)

            count_processed.set(str(processed))
            count_failed.set(str(skipped))

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
    ttk.Checkbutton(scope_body,
                    text="All placements (image appears 2+ times)",
                    variable=scope_vars["all_placements"]).pack(anchor="w")
    ttk.Checkbutton(scope_body,
                    text="Cross-page (image on 2+ distinct pages)",
                    variable=scope_vars["cross_page"]).pack(anchor="w")
    ttk.Checkbutton(scope_body,
                    text="Cross-document (image in 2+ documents)",
                    variable=scope_vars["cross_document"]).pack(anchor="w")

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
            for scope in scopes:
                session.log(f"Generating graph: scope={scope}")
                g_log(f"  Loading data for {scope}...")

                rows = load_data(conn, scope=scope)
                if not rows:
                    g_log(f"  \u2298 {scope} — no data", "dim")
                    session.log(f"  No data for scope {scope}")
                    continue

                md5_set = {row[6] for row in rows}
                g_log(f"  {len(rows)} placements, "
                      f"{len(md5_set)} unique images")

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
                    output_path=out_path)

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

    r_left = tk.Frame(r_split, bg=BG_DARK, width=420)
    r_left.pack(side="left", fill="y", padx=(0, 10))
    r_left.pack_propagate(False)

    r_right = tk.Frame(r_split, bg=BG_DARK)
    r_right.pack(side="left", fill="both", expand=True)

    # --- LEFT: controls ---

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

    # Report checkboxes
    from pdf_forensics.reports.queries import list_reports as _list_rpts
    report_list = _list_rpts()

    rpt_body = make_panel(r_left, "Select reports")
    report_vars = {}
    for rid, rname, rdesc in report_list:
        var = tk.BooleanVar(value=True)
        report_vars[rid] = var
        ttk.Checkbutton(rpt_body, text=rname,
                        variable=var).pack(anchor="w")

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

    # Generate button
    action_row_r = tk.Frame(r_left, bg=BG_DARK)
    action_row_r.pack(fill="x", side="bottom", pady=(8, 4))

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
        if not selected:
            messagebox.showerror("No reports",
                                 "Please select at least one report.")
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
    def setup_session(case):
        """Create a session and pre-populate path fields."""
        session = Session(case)
        app["session"] = session
        app["case_var"].set(case)

        # Check if user already selected an existing DB
        current_db = db_path_var.get()
        user_selected_db = (
            current_db
            and current_db != "pdf_forensics.db"
            and os.path.isfile(current_db))

        if user_selected_db:
            # Use the existing DB's directory as the base
            base_dir = os.path.dirname(os.path.abspath(current_db))
        else:
            # Ask for base output directory
            base_dir = filedialog.askdirectory(
                title=f"Select output directory for case: {case}",
                mustexist=False)
            if not base_dir:
                base_dir = os.path.join(os.getcwd(), case)

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

    # ===================================================================
    # LAUNCH
    # ===================================================================
    show_frame("main")
    root.after(100, prompt_case_number)
    root.mainloop()

    # Write session summary on exit
    if app["session"]:
        app["session"].write_summary(db_path=db_path_var.get())
