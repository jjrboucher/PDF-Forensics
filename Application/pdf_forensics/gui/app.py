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
    from pdf_forensics.pathutil import (norm_path, NormalisingDialogs,
                                        safe_name)
    # Every dialog returns paths with native separators (see pathutil).
    filedialog = NormalisingDialogs(filedialog)
    initial_db = norm_path(initial_db)
    initial_output = norm_path(initial_output)
    if initial_pdfs:
        initial_pdfs = [norm_path(p) for p in initial_pdfs]

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
    # The status message spans the remaining width of the bar, so it
    # repaints its whole area (background included) on every change. Sized
    # to its text, a shorter message left the end of the previous, longer
    # one visible beside it. Re-packed after the reminder so the reminder
    # keeps its space.
    status_label.pack_forget()
    status_label.pack(side="left", padx=14, fill="both", expand=True)
    # The status bar keeps its place at the bottom whatever the screen
    # (build 2026-11-24b): packed before the content area, so a screen
    # taller than the window no longer pushes it out of sight.
    content_area.pack_forget()
    content_area.pack(fill="both", expand=True)

    # ---------------------------------------------------------------
    # Background runs (keeps the window responsive)
    #
    # Analysis, triage, reports and graphs run on a background thread so
    # the window keeps handling its events. Without this, Windows marked
    # the window "Not Responding" during long runs and showed a frozen
    # snapshot of an earlier document and page while processing went on.
    #
    # The run code updates widgets as before. With a threaded Tcl (the
    # standard Python builds), tkinter hands every widget call made from
    # another thread to the main thread and waits for it, so this is safe
    # while the main thread is in mainloop(). With a non-threaded Tcl the
    # run executes on the main thread as it always did.
    # ---------------------------------------------------------------
    import threading as _threading
    try:
        _tcl_threaded = bool(root.tk.getboolean(
            root.tk.call("set", "tcl_platform(threaded)")))
    except Exception:
        _tcl_threaded = False
    _busy = {"job": None, "locked": []}

    # Every interactive control is locked for the duration of a run, so
    # nothing the run is still reading (the PDF list, the database, the
    # options) can change under it. Only the log, its scrollbars and the
    # counters stay live. Each control is restored to the state it had.
    _LOCKABLE = (ttk.Button, ttk.Checkbutton, ttk.Radiobutton, ttk.Entry,
                 ttk.Combobox, ttk.Spinbox, tk.Button, tk.Checkbutton,
                 tk.Radiobutton, tk.Entry, tk.Listbox, tk.Spinbox, tk.Scale)

    def _lock_ui():
        locked = []
        stack = list(root.winfo_children())
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            if not isinstance(w, _LOCKABLE):
                continue
            try:
                if isinstance(w, ttk.Widget):
                    if not w.instate(["disabled"]):
                        w.state(["disabled"])
                        locked.append(w)
                elif str(w.cget("state")) != "disabled":
                    w.configure(state="disabled")
                    locked.append(w)
            except Exception:
                pass
        _busy["locked"] = locked

    def _unlock_ui():
        for w in _busy.get("locked") or []:
            try:
                if isinstance(w, ttk.Widget):
                    w.state(["!disabled"])
                else:
                    w.configure(state="normal")
            except Exception:
                pass
        _busy["locked"] = []

    def run_in_background(name, fn):
        """Run fn (a GUI run function) on a background thread; one run at
        a time. Errors are shown rather than lost."""
        if _busy["job"]:
            messagebox.showinfo(
                "Processing in progress",
                f"{_busy['job']} is still running. Please wait until it "
                f"finishes.")
            return
        if not _tcl_threaded:
            fn()
            return
        _busy["job"] = name
        _lock_ui()

        def _target():
            try:
                fn()
            except Exception as e:
                try:
                    messagebox.showerror(
                        "Error", f"{name} stopped because of an error:\n{e}")
                except Exception:
                    pass
            finally:
                _busy["job"] = None
                # Restore the controls on the window's own thread.
                try:
                    root.after(0, _unlock_ui)
                except Exception:
                    pass

        _threading.Thread(target=_target, name=name, daemon=True).start()

    def _on_close():
        if _busy["job"] and not messagebox.askyesno(
                "Processing in progress",
                f"{_busy['job']} is still running. If you close the "
                f"application now, the documents being processed will not "
                f"be saved (documents already completed are saved).\n\n"
                f"Close anyway?"):
            return
        runner = app.get("parallel_runner")
        if runner is not None:          # stop worker processes at once
            runner.terminate()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)

    # ---------------------------------------------------------------
    # Frame switching
    # ---------------------------------------------------------------
    frames = {}

    # Per-frame minimum widths measured from the widgets (filled in once
    # the frames are built): {name: function returning a width}.
    frame_min_width = {}

    # Per-frame window sizes: (width, height)
    frame_sizes = {
        "main":     (780, 540),
        "analysis": (1200, 990),
        "graph":    (1060, 700),
        "reports":  (1180, 1030),  # 22 reports; clamped to the screen
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
        # No navigation while a run is in progress (the run's own screen
        # stays visible and its controls are not re-entered).
        if _busy.get("job"):
            messagebox.showinfo(
                "Processing in progress",
                f"{_busy['job']} is still running. Please wait until it "
                f"finishes before leaving this screen.")
            return
        if app["current_frame"]:
            app["current_frame"].pack_forget()
        # A finished run's message belongs to its own screen (build
        # 2026-11-24b: "Done. 5 analysed ..." stayed on the graph screen).
        try:
            status_var.set("Ready")
            status_label.config(fg=TEXT_SEC)
        except Exception:
            pass
        frame = frames[name]
        frame.pack(in_=content_area, fill="both", expand=True)
        app["current_frame"] = frame
        w, h = frame_sizes.get(name, (780, 620))
        if name in frame_min_width:
            try:
                w = max(w, frame_min_width[name]())
            except Exception:
                pass
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

    def scroll_column(parent, width):
        """A fixed-width column whose contents scroll when they are taller
        than the window (build 2026-11-24b: on a 24-inch screen the report
        and graph screens' controls could run off the bottom). Returns
        (outer, inner, footer): put the panels in inner; footer stays at
        the bottom, always visible (for the screen's main button). The
        scroll bar shows only when needed; the mouse wheel scrolls the
        column while the pointer is over it."""
        outer = tk.Frame(parent, bg=BG_DARK, width=width)
        outer.pack_propagate(False)
        footer = tk.Frame(outer, bg=BG_DARK)
        footer.pack(side="bottom", fill="x")
        canvas = tk.Canvas(outer, bg=BG_DARK, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        inner = tk.Frame(canvas, bg=BG_DARK)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        state = {"shown": False}

        def _update(_e=None):
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
                need = inner.winfo_reqheight() > canvas.winfo_height() + 1
            except Exception:
                return
            if need and not state["shown"]:
                sb.pack(side="right", fill="y", before=canvas)
                state["shown"] = True
            elif not need and state["shown"]:
                sb.pack_forget()
                canvas.yview_moveto(0)
                state["shown"] = False

        def _resize(e):
            try:
                canvas.itemconfigure(win, width=e.width)
            except Exception:
                pass
            _update()

        def _wheel(e):
            if not state["shown"]:
                return
            step = -1 if getattr(e, "delta", 0) > 0 or \
                getattr(e, "num", 0) == 4 else 1
            canvas.yview_scroll(step * 3, "units")

        def _enter(_e=None):
            canvas.bind_all("<MouseWheel>", _wheel)
            canvas.bind_all("<Button-4>", _wheel)
            canvas.bind_all("<Button-5>", _wheel)

        def _leave(_e=None):
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.unbind_all(ev)

        inner.bind("<Configure>", _update)
        canvas.bind("<Configure>", _resize)
        outer.bind("<Enter>", _enter)
        outer.bind("<Leave>", _leave)
        canvas.pack(side="left", fill="both", expand=True)
        return outer, inner, footer

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
                px = widget.winfo_pointerx()
                py = widget.winfo_pointery()
                sw = widget.winfo_screenwidth()
                sh = widget.winfo_screenheight()
            except Exception:
                return
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.configure(bg=BORDER)
            lbl = tk.Label(
                tip, text=text, justify="left", bg="#2B2B2B",
                fg=TEXT_PRIM, font=FONT_SUBTITLE,
                wraplength=min(wraplength, max(200, sw - 60)),
                padx=8, pady=6, bd=0)
            lbl.pack(padx=1, pady=1)
            # Keep the tip on the screen (build 2026-11-24b): above the
            # pointer when there is no room below (allowing for the
            # taskbar), and left of it when there is no room to the
            # right. It ran off the bottom of a 24-inch screen.
            x, y = px + 14, py + 18
            try:
                tip.update_idletasks()
                tw, th = tip.winfo_reqwidth(), tip.winfo_reqheight()
                if y + th > sh - 48:
                    y = max(0, py - th - 12)
                if x + tw > sw - 8:
                    x = max(0, sw - tw - 8)
            except Exception:
                pass
            tip.wm_geometry(f"+{x}+{y}")
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

    # Scrolling left column; the Run button stays visible below it
    # (build 2026-11-24b: the button was squeezed on a 24-inch screen).
    left_outer, left_panel, a_footer = scroll_column(split, 580)
    left_outer.pack(side="left", fill="y", padx=(0, 10))

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

    # Output folder panel (both modes: triage writes its spreadsheet here)
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

    # Processing panel: two modes as radio buttons. Full parsing reveals
    # its options and the database below them, since only full parsing
    # writes to the database.
    opt_body = make_panel(left_panel, "Processing")

    triage_var = tk.BooleanVar(value=True)     # read by run_analysis()
    mode_var = tk.StringVar(value="triage")
    triage_rb = ttk.Radiobutton(
        opt_body, text="Triage (quick scan to Excel)",
        variable=mode_var, value="triage")
    triage_rb.pack(anchor="w")
    full_rb = ttk.Radiobutton(
        opt_body, text="Full parsing (forensic analysis into the case database)",
        variable=mode_var, value="full")
    full_rb.pack(anchor="w", pady=(2, 0))

    # What the selected mode produces, and what it does not (so full
    # parsing is not mistaken for "triage plus more").
    MODE_NOTES = {
        "triage": ("Writes a triage spreadsheet only. Nothing is written "
                   "to the database and no reports are produced."),
        "full": ("Builds the case database for reports, graphs and the "
                 "case index. It does not write a triage spreadsheet; run "
                 "Triage separately if you want one."),
    }
    mode_note_var = tk.StringVar(value=MODE_NOTES["triage"])
    ttk.Label(opt_body, textvariable=mode_note_var, style="Hint.TLabel",
              wraplength=520, justify="left").pack(anchor="w",
                                                   padx=(22, 0),
                                                   pady=(4, 0))

    # Shown only for full parsing.
    full_frame = tk.Frame(opt_body, bg=BG_PANEL)
    full_opts = tk.Frame(full_frame, bg=BG_PANEL)
    full_opts.pack(fill="x", padx=(22, 0), pady=(6, 0))

    store_cb = ttk.Checkbutton(
        full_opts,
        text="Store extracted images in database",
        variable=store_images_var)
    store_cb.pack(anchor="w")
    extract_versions_var = tk.BooleanVar(value=True)
    versions_cb = ttk.Checkbutton(
        full_opts,
        text="Extract and process prior PDF versions",
        variable=extract_versions_var)
    versions_cb.pack(anchor="w")
    skip_duplicates_var = tk.BooleanVar(value=True)
    skip_cb = ttk.Checkbutton(
        full_opts,
        text="Skip PDFs already in the database",
        variable=skip_duplicates_var)
    skip_cb.pack(anchor="w")

    # Parallel workers: how many files are processed at once. "1" is the
    # one-file-at-a-time loop of earlier versions; results are the same
    # either way (analysis/parallel.py). Build 2026-11-19b: every session
    # starts at Auto (a number chosen for one run is not carried into the
    # next), Auto is decided again at the start of each step from free
    # memory and how busy the processors are, and the setting is shown on
    # the analysis, graphs and reports screens (one setting; amber when it
    # is not Auto), with an information panel.
    from pdf_forensics.analysis import parallel as _par
    _auto_n = _par.default_workers()
    WORKER_CHOICES = ([f"Auto (adapts, up to {_auto_n})",
                       "1 (one file at a time)"]
                      + [str(n) for n in range(2, (os.cpu_count() or 2) + 1)])
    workers_var = tk.StringVar(value=WORKER_CHOICES[0])
    _worker_marks = []          # (combobox, note label) on each screen

    def _fixed_workers():
        """The number chosen, or None for Auto."""
        v = workers_var.get()
        if v.startswith("Auto"):
            return None
        try:
            return max(1, int(v.split()[0]))
        except (ValueError, IndexError):
            return None

    def _refresh_worker_marks(*_):
        n = _fixed_workers()
        for cb, note in _worker_marks:
            try:
                cb.configure(style="TCombobox" if n is None
                             else "Warn.TCombobox")
                note.configure(text="" if n is None
                               else f"\u25cf not Auto ({n})")
            except Exception:
                pass
    workers_var.trace_add("write", _refresh_worker_marks)

    def _workers_info():
        """The information panel: this machine, what Auto would choose now
        and why, and the trade-offs."""
        st = _par.machine_state()
        n, why = _par.auto_choice(state=st)
        mem = (f"{st['ram_gb']:g} GB installed" if st.get("ram_gb")
               else "installed memory not known")
        if st.get("free_gb") is not None:
            mem += f", {st['free_gb']:g} GB free now"
        busy = (f"{st['busy_pct']:.0f}%" if st.get("busy_pct") is not None
                else "not known")
        reason = {
            "machine": (("the most this machine supports: one process per "
                         "physical processor core (a core's second thread "
                         "adds little for this work), " if st.get("cores")
                         else "the most this machine supports: one process "
                         "per logical processor, keeping one for the "
                         "database and this window (physical cores are not "
                         "known without psutil), ")
                        + "about "
                        f"{_par.RAM_PER_WORKER_GB} GB of installed memory "
                        f"per process, and at most {_par.MAX_AUTO_WORKERS}"),
            "free memory": ("lowered because free memory is short right "
                            f"now (Auto wants about "
                            f"{_par.FREE_GB_PER_WORKER} GB free per "
                            "process); the most this machine supports is "
                            f"{why['ceiling']}"),
            "busy processors": ("lowered because other programs are "
                                "keeping the processors busy right now; "
                                "the most this machine supports is "
                                f"{why['ceiling']}"),
        }[why["limit"]]
        fixed = _fixed_workers()
        current = ("Auto" if fixed is None
                   else f"{fixed} (chosen by you; not Auto)")
        sections = [
            ("h", "Files processed at once"),
            ("", f"Current setting: {current}"),
            ("", ""),
            ("b", "This computer"),
            ("", f"  Processor cores: "
                 f"{st['cores'] if st.get('cores') else 'not known'}; "
                 f"logical processors: {st['cpus']}"),
            ("", f"  Memory: {mem}"),
            ("", f"  Processors busy now: {busy}"),
        ] + ([
            ("", "  psutil is not installed, so Auto cannot see free "
                 "memory or how busy the processors are, and uses the "
                 "most this computer supports. To let it adapt, install "
                 "it (pip install psutil) and restart the application."),
        ] if st.get("free_gb") is None and st.get("busy_pct") is None
            else []) + [
            ("", ""),
            ("b", f"What Auto would choose now: {n} at once"),
            ("", f"  {reason[0].upper() + reason[1:]}."),
            ("", "  Auto is decided again at the start of each step "
                 "(triage, analysis, graphs, visual overlay reports), so "
                 "it lowers itself when other programs are using the "
                 "computer."),
            ("", ""),
            ("b", "More at once"),
            ("", "  + Much shorter runs on cases with many files."),
            ("", "  \u2212 More memory in use."),
            ("", "  \u2212 Each file takes longer on its own, because the "
                 "processes share the processors and the disk (typically "
                 "1.4 to 2 times), so one very large file can finish "
                 "later than it would alone."),
            ("", "  \u2212 The computer is less responsive for other work "
                 "during the run."),
            ("", ""),
            ("b", "One at a time"),
            ("", "  + Least memory; the computer stays responsive."),
            ("", "  \u2212 Slowest on large cases."),
            ("", ""),
            ("b", "Results"),
            ("", "  The results are identical either way: files are "
                 "written to the database, and reports produced, in the "
                 "order you selected them. Only the time taken changes."),
            ("", ""),
            ("b", "Recommendation"),
            ("", "  Leave it on Auto. Choose a lower number if you need "
                 "the computer for other work during a long run or "
                 "memory is tight; choose 1 to process files exactly as "
                 "earlier versions did. The setting is shared by the "
                 "analysis, graphs and reports screens, and returns to "
                 "Auto each time the application starts."),
        ]
        win = tk.Toplevel(root)
        win.title("Files processed at once")
        win.configure(bg=BG_DARK)
        win.transient(root)
        txt = tk.Text(win, wrap="word", bg=BG_PANEL, fg=TEXT_PRIM,
                      highlightthickness=0, borderwidth=0, width=72,
                      height=34, font=(FONT_FAMILY, 10), padx=14, pady=12,
                      relief="flat")
        txt.tag_configure("h", font=(FONT_FAMILY, 12, "bold"))
        txt.tag_configure("b", font=(FONT_FAMILY, 10, "bold"))
        for tag, line in sections:
            txt.insert("end", line + "\n", tag or ())
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        ttk.Button(win, text="Close", command=win.destroy).pack(
            pady=(0, 10))
        win.bind("<Escape>", lambda e: win.destroy())

    def workers_control(parent, label, bg=BG_PANEL):
        """The setting's row: label, choice, \u24d8 and the amber note."""
        row = tk.Frame(parent, bg=bg)
        ttk.Label(row, text=label, style="Panel.TLabel").pack(
            side="left", padx=(4, 8))
        cb = ttk.Combobox(row, textvariable=workers_var,
                          values=WORKER_CHOICES, state="readonly",
                          width=22)
        cb.pack(side="left")
        attach_tooltip(cb, "How many PDFs are processed at the same time, "
                           "each in its own process: triage, full parsing, "
                           "and the visual overlay reports and graphs. Auto "
                           "uses the processor cores and memory, and is "
                           "decided again at the start of each step. The "
                           "results are the same as one file at a time: "
                           "they are written in the order the files were "
                           "selected. Choose 1 for the one-file-at-a-time "
                           "behaviour of earlier versions. One setting for "
                           "the analysis, graphs and reports screens.")
        info = tk.Label(row, text="\u24d8", bg=bg, fg=TEXT_SEC,
                        cursor="hand2", font=(FONT_FAMILY, 12))
        info.pack(side="left", padx=(8, 0))
        info.bind("<Button-1>", lambda e: _workers_info())
        attach_tooltip(info, "What Auto chooses on this computer, and the "
                             "trade-offs. Click for details.")
        note = tk.Label(row, text="", bg=bg, fg=WARN,
                        font=(FONT_FAMILY, 9, "bold"))
        note.pack(side="left", padx=(8, 0))
        attach_tooltip(note, "A fixed number is in use instead of Auto. "
                             "It returns to Auto when the application "
                             "is next started.")
        _worker_marks.append((cb, note))
        _refresh_worker_marks()
        return row

    def _selected_workers(step="analysis", log=None):
        """The number to use for this step. Auto is decided now, from free
        memory and how busy the processors are; the choice and its reason
        go to log(msg, tag), if given, and to the performance log (numbers
        only, no names)."""
        fixed = _fixed_workers()
        if fixed is None:
            n, why = _par.auto_choice(step)
            msg = _par.describe_auto(n, why)
        else:
            n = fixed
            msg = (f"{n} at once (chosen by you, not Auto; Auto would allow "
                   f"up to {_auto_n} on this computer)")
        if log:
            try:
                log(msg, "dim")
            except Exception:
                pass
        try:
            from pdf_forensics import perf as _perf
            if app.get("session"):
                _perf.get(app["session"]).note(f"workers ({step}): {msg}")
        except Exception:
            pass
        return n

    # In both modes (triage, analysis), so packed in the panel itself,
    # above the full-parsing options.
    workers_row = workers_control(opt_body, "Files processed at once:")
    workers_row.pack(anchor="w", padx=(22, 0), pady=(6, 0))

    # Database, under the full-parsing options
    db_wrap = tk.Frame(full_frame, bg=BG_PANEL)
    db_wrap.pack(fill="x", padx=(22, 0), pady=(10, 0))
    ttk.Label(db_wrap, text="DATABASE", style="Section.TLabel").pack(
        anchor="w", pady=(0, 4))
    db_row = tk.Frame(db_wrap, bg=BG_PANEL)
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
    ttk.Label(db_wrap, text="Existing databases will be appended to.",
              style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

    attach_tooltip(triage_rb,
                   "Quick scan that writes a triage spreadsheet (Excel) "
                   "instead of running the full forensic analysis \u2014 a "
                   "fast overview of many files, with per-file metadata, "
                   "prior versions and any reviewer comments. Nothing is "
                   "written to the database.")
    attach_tooltip(full_rb,
                   "Full forensic analysis of every page, stored in the case "
                   "database, from which the reports, graphs and case index "
                   "are built.")
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

    def on_triage_toggle(*_):
        """Show the full-parsing options and database only for full
        parsing. The options keep their values while hidden; triage does
        not use them."""
        is_triage = mode_var.get() == "triage"
        if triage_var.get() != is_triage:
            triage_var.set(is_triage)
        mode_note_var.set(MODE_NOTES["triage" if is_triage else "full"])
        if is_triage:
            full_frame.pack_forget()
            run_btn_a.config(text="Run triage")
        else:
            full_frame.pack(fill="x")
            run_btn_a.config(text="Run analysis")

    mode_var.trace_add("write", on_triage_toggle)

    # Run button at bottom of left panel
    action_row_a = tk.Frame(a_footer, bg=BG_DARK)
    action_row_a.pack(fill="x", pady=(8, 4))

    # --- RIGHT SIDE: status log ---

    # Counter row
    counter_outer = tk.Frame(right_panel, bg=BORDER, padx=1, pady=1)
    counter_outer.pack(fill="x", pady=(0, 8))
    counter_inner = tk.Frame(counter_outer, bg=BG_PANEL)
    counter_inner.pack(fill="x")
    # Two rows on one grid, so the columns line up: the counts that
    # describe the selection on top, the others below, so the window need
    # not be very wide. Each counter takes two grid columns (number, label);
    # a column is as wide as its widest entry in either row.
    counter_row = tk.Frame(counter_inner, bg=BG_PANEL)
    counter_row.pack(anchor="w", padx=10, pady=8)

    count_selected = tk.StringVar(value="0")
    count_processed = tk.StringVar(value="0")
    count_failed = tk.StringVar(value="0")
    count_skipped = tk.StringVar(value="0")
    count_encrypted = tk.StringVar(value="0")
    count_images = tk.StringVar(value="0")
    # Prior versions recovered from incremental updates are counted
    # separately, so Processed never exceeds Selected.
    count_versions = tk.StringVar(value="0")

    def counter_label(row, col, label_text, var, color=TEXT_SEC):
        tk.Label(counter_row, textvariable=var, bg=BG_PANEL, fg=color,
                 font=(FONT_FAMILY, 14, "bold"),
                 width=5, anchor="e").grid(row=row, column=2 * col,
                                           sticky="e",
                                           pady=(0, 4) if row == 0 else 0)
        tk.Label(counter_row, text=f"  {label_text}", bg=BG_PANEL,
                 fg=TEXT_DIM, font=(FONT_FAMILY, 9), anchor="w").grid(
                     row=row, column=2 * col + 1, sticky="w",
                     padx=(0, 24), pady=(0, 4) if row == 0 else 0)

    counter_label(0, 0, "Selected", count_selected)
    counter_label(0, 1, "Processed", count_processed, SUCCESS)
    counter_label(0, 2, "Prior versions", count_versions, SUCCESS)
    counter_label(0, 3, "Failed", count_failed, ACCENT)
    counter_label(1, 0, "Copies", count_skipped)
    counter_label(1, 1, "Locked", count_encrypted, ACCENT)
    counter_label(1, 2, "Images", count_images)

    def _analysis_min_width():
        """Window width at which the top counter row (Selected to Failed)
        shows in full: left panel, gap and the row with its padding,
        measured from the widgets so it holds at any display scaling."""
        root.update_idletasks()
        return (20 + 580 + 10                       # split padding, form, gap
                + counter_row.winfo_reqwidth() + 2 * 10 + 2   # row, padding, border
                + 20 + 16)                          # split padding, margin

    frame_min_width["analysis"] = _analysis_min_width

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

    # Skip (build 2026-11-23): stop one file of a parallel analysis that is
    # taking too long; it is recorded as failed ("skipped by the
    # examiner") and the run continues. Shown only while one runs. The
    # watchdog does the same by itself after 30 minutes without progress.
    def _skip_dialog():
        runner = app.get("parallel_runner")
        if runner is None:
            return
        files = sorted(runner.running_files(), key=lambda f: -f[2])
        if not files:
            messagebox.showinfo("Skip a file",
                                "No file is being analysed at the moment.")
            return
        win = tk.Toplevel(root)
        win.title("Skip a file")
        win.transient(root)
        tk.Label(win, text="Files being analysed now (longest without "
                 "progress first):", anchor="w").pack(fill="x", padx=10,
                                                      pady=(10, 4))
        lb = tk.Listbox(win, width=90, height=min(12, len(files)))
        for idx, name, idle, page, pages in files:
            where = (f"page {page} of {pages}" if pages
                     else "first page not finished")
            lb.insert("end", f"{name} \u2014 {where}; "
                             f"{idle / 60:.1f} min since last progress")
        lb.selection_set(0)
        lb.pack(fill="both", expand=True, padx=10)

        def _go():
            sel = lb.curselection()
            if not sel:
                return
            idx, name = files[sel[0]][0], files[sel[0]][1]
            if not messagebox.askyesno(
                    "Skip a file",
                    f"Stop analysing {name}?\n\nIt will be recorded as "
                    f"failed (skipped by the examiner). Files running "
                    f"alongside it are restarted; the run continues.",
                    parent=win):
                return
            if not runner.skip(idx):
                messagebox.showinfo("Skip a file", "That file has already "
                                    "finished.", parent=win)
            win.destroy()
        btns = tk.Frame(win)
        btns.pack(fill="x", padx=10, pady=10)
        ttk.Button(btns, text="Skip selected file",
                   command=_go).pack(side="right")
        ttk.Button(btns, text="Close",
                   command=win.destroy).pack(side="right", padx=(0, 6))

    skip_btn = ttk.Button(progress_inner, text="Skip a file\u2026",
                          command=_skip_dialog)

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

    def _run_parallel(n_workers, conn, db_val, out_dir, session):
        """Analyse the selected files with n_workers processes
        (analysis/parallel.py). The log shows a line per file while it is
        analysed; lines are completed as results are written, in the order
        the files were selected. Returns the runner's stats.

        Build 2026-11-20: the runner's thread only records progress here;
        the window draws it once a second on its own thread (LiveLines).
        Drawing on every progress message took the runner's thread away
        from handing out work, so at 18 processes about two thirds of them
        sat idle and analysis was slower than at 12."""
        from pdf_forensics.analysis.parallel import ParallelRunner
        from pdf_forensics.gui.live import LiveLines, fmt_elapsed
        prog = {}                       # key -> {"page","pages","images"}
        names = {}
        took = {}                       # key -> seconds analysing
        st = {"total": len(pdf_files), "done": 0, "running": set(),
              "waiting": set(), "written": set(),
              "processed": 0, "versions": 0, "failed": 0, "skipped": 0,
              "images": 0, "encrypted": 0}

        def _status():
            analysis_progress.config(maximum=max(1, st["total"]),
                                     value=st["done"])
            # Build 2026-11-19b: "running" is only what a worker is
            # analysing now; a file finished early waits for those
            # selected before it to be written, and is counted apart.
            parts = [f"{st['done']} of {st['total']} file(s) written",
                     f"{len(st['running'])} running"]
            if st["waiting"]:
                parts.append(f"{len(st['waiting'])} analysed, waiting to "
                             f"be written to the database")
            progress_status_var.set(
                " \u00b7 ".join(parts) + " \u00b7 largest files first; "
                "results written in the order selected")

        def _counters():
            count_processed.set(str(st["processed"] - st["versions"]))
            count_versions.set(str(st["versions"]))
            count_failed.set(str(st["failed"]))
            count_skipped.set(str(st["skipped"]))
            count_images.set(str(st["images"]))
            count_encrypted.set(str(st["encrypted"]))

        def _tick():                    # Tk thread, once a second
            _status()
            _counters()

        live = LiveLines(root, log_text, on_tick=_tick)

        def _progress_text(key):
            p = prog.get(key) or {}
            txt = f"  \u25cb {names.get(key, '')} \u2014 "
            if p.get("pages"):
                txt += f"page {p['page']}/{p['pages']}"
            else:
                txt += "starting..."
            if p.get("images"):
                txt += f" \u00b7 {p['images']} image(s) written"
            return txt

        def on_event(evt):              # the runner's thread: no drawing
            t = evt["type"]
            key = evt.get("key")
            if (t in ("start", "progress", "images", "finished")
                    and key in st["written"]):
                return      # a late progress message for a file written
            if t == "start":
                names[key] = evt["name"]
                prog[key] = {"page": 0, "pages": 0, "images": 0}
                st["running"].add(key)
                live.set(key, _progress_text(key))
            elif t in ("progress", "images"):
                p = prog.setdefault(key, {"page": 0, "pages": 0,
                                          "images": 0})
                if t == "progress":
                    p["page"], p["pages"] = evt["page"], evt["pages"]
                else:
                    p["images"] = evt["images"]
                if key in names:
                    live.set(key, _progress_text(key))
            elif t == "finished":
                if key in st["running"]:
                    st["running"].discard(key)
                    st["waiting"].add(key)
                    took[key] = live.elapsed(key)
                    live.set(key, f"  \u25cb {names.get(key, '')} \u2014 "
                                  f"analysed in {fmt_elapsed(took[key])}; "
                                  f"waiting to be written to the database",
                             clock=False)
            elif t == "queued":
                st["total"] += evt["count"]
            elif t == "versions":
                live.set(("versions", key), "", clock=False, parent=key)
                live.done(("versions", key),
                          f"    \u21b3 {evt['count']} prior version(s) of "
                          f"{evt['name']} extracted and analysed",
                          "dim")
                # (drawn under the file's own line)
            elif t == "result":
                if key in st["running"]:
                    took[key] = live.elapsed(key)
                st["running"].discard(key)
                st["waiting"].discard(key)
                st["written"].add(key)
                st["done"] += 1
                name, oc = evt["name"], evt["outcome"]
                secs = (f" \u00b7 {fmt_elapsed(took[key])}"
                        if key in took else "")
                if oc == "analysed":
                    st["processed"] += 1
                    if evt.get("version") is not None:
                        st["versions"] += 1
                    st["images"] += evt.get("images", 0)
                    live.done(key, f"  \u2713 {name} \u2014 "
                                   f"{evt.get('images', 0)} img, "
                                   f"{evt.get('findings', 0)} findings"
                                   f"{secs}", "success")
                elif oc == "duplicate":
                    st["skipped"] += 1
                    live.done(key, f"  \u2298 {name} \u2014 identical copy "
                                   f"of {evt.get('duplicate_of')} (not "
                                   f"re-analysed)", "skip")
                elif oc == "encrypted":
                    st["encrypted"] += 1
                    scheme = evt.get("scheme") or "scheme unknown"
                    live.done(key, f"  \U0001f512 {name} \u2014 encrypted, "
                                   f"not opened ({scheme})", "skip")
                elif oc == "not_found":
                    st["failed"] += 1
                    live.done(key, f"  \u2717 {name} \u2014 not found",
                              "error")
                else:
                    st["failed"] += 1
                    live.done(key, f"  \u2717 {name} \u2014 "
                                   f"{evt.get('error')}", "error")

        log_to_gui(f"Analysing up to {n_workers} file(s) at a time, largest "
                   f"first; results are written in the order selected.",
                   "dim")
        versions_out = None
        if extract_versions_var.get():
            versions_out = (session.pdf_versions_dir
                            or os.path.join(out_dir, "pdf_versions"))
            os.makedirs(versions_out, exist_ok=True)
        runner = ParallelRunner(
            list(pdf_files), conn, db_val, session=session,
            workers=n_workers, out_dir=out_dir,
            store_images=bool(store_images_var.get()),
            skip_duplicates=bool(skip_duplicates_var.get()),
            extract_versions=bool(extract_versions_var.get()),
            versions_out=versions_out,
            password_manager=app.get("password_manager"),
            on_event=on_event)
        app["parallel_runner"] = runner
        root.after(0, live.start)
        root.after(0, lambda: skip_btn.pack(anchor="e", padx=10,
                                            pady=(0, 8)))
        try:
            stats = runner.run()
        finally:
            app["parallel_runner"] = None
            root.after(0, skip_btn.pack_forget)
            live.stop(wait=True)
        if stats.get("timed_out") or stats.get("skipped"):
            log_to_gui(f"  Note: {stats.get('timed_out', 0)} file(s) made no "
                       f"progress for {runner.watchdog_s / 60:g} minutes and "
                       f"{stats.get('skipped', 0)} were skipped; they are "
                       f"recorded as failed (see the session log).", "skip")
        if stats.get("worker_restarts"):
            log_to_gui(f"  Note: a worker process stopped unexpectedly "
                       f"{stats['worker_restarts']} time(s); the files it was "
                       f"analysing were re-run one at a time (see the "
                       f"session log).", "skip")
        return stats

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
        # Typed paths are normalised when read, and shown normalised.
        db_val = norm_path(db_path_var.get())
        out_dir = norm_path(output_dir_var.get())
        if db_val:
            db_path_var.set(db_val)
        if out_dir:
            output_dir_var.set(out_dir)

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
        count_versions.set("0")
        count_failed.set("0")
        count_skipped.set("0")
        count_images.set("0")
        count_encrypted.set("0")
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

        # Performance log: flags and counts only (no names or paths).
        from pdf_forensics import perf as _perf
        from pdf_forensics.analysis.images import clear_image_cache
        clear_image_cache()
        pf = _perf.get(session)
        n_workers = _selected_workers("analysis", log_to_gui)
        pf.run_begin("analysis", len(process_queue), interface="GUI",
                     workers=n_workers,
                     store_images=bool(store_images_var.get()),
                     extract_to_disk=bool(out_dir),
                     prior_versions=bool(extract_versions_var.get()),
                     skip_duplicates=bool(skip_duplicates_var.get()),
                     password_list=app.get("password_manager") is not None)
        perf_parent = {}   # extracted version path -> parent's log #
        # Files with the same name get their own image and prior-version
        # folders (name, name_2, ...), never a shared one.
        from pdf_forensics.analysis.parallel import unique_stems
        stem_of = {}
        for _p, _st in zip(pdf_files, unique_stems(pdf_files)):
            stem_of.setdefault(_p, _st)

        if n_workers > 1:
            r = _run_parallel(n_workers, conn, db_val, out_dir, session)
            processed = r["analysed"]
            versions_done = r["versions"]
            skipped_copies = r["duplicates"]
            failed = r["failed"]
            not_found = r["not_found"]
            total_imgs = r["images"]
            total_findings = r["findings"]
            encrypted_unopened.extend(r["encrypted_paths"])

        # One file at a time (also the reference for parallel analysis).
        while n_workers <= 1 and queue_idx < len(process_queue):
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

            base = (os.path.splitext(basename)[0] if this_is_version
                    else stem_of.get(pdf_path,
                                     os.path.splitext(basename)[0]))
            # A name Windows can create as given (see pathutil.safe_name)
            pdf_extract_dir = os.path.join(
                out_dir, safe_name(base, out_dir)) if out_dir else None
            this_perf_no = pf.file_begin(
                f"version {this_lineage[1]}" if this_lineage else "submitted",
                of=perf_parent.get(pdf_path))
            _pf_status = "ok"

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

            # Live progress line for this file: page x/y and the images
            # written so far, so a long run visibly keeps moving.
            _prog = {"page": 0, "pages": 0, "images": 0}

            def _show_progress(_idx=progress_idx, _name=basename,
                               _done=queue_idx - 1,
                               _total=len(process_queue), _p=_prog):
                imgs = (f" \u00b7 {_p['images']} image(s) written"
                        if _p["images"] else "")
                log_text.config(state="normal")
                log_text.delete(_idx, f"{_idx} lineend + 1 char")
                log_text.insert(_idx,
                    f"  \u25cb {_name} — "
                    f"page {_p['page']}/{_p['pages']}{imgs}\n", "dim")
                log_text.see("end")
                log_text.config(state="disabled")
                progress_set_file(_done, _total, _name,
                                  page=_p["page"], pages=_p["pages"])
                root.update_idletasks()

            # Redrawn at most four times a second (and on the last page):
            # redrawing after every page and every image took about a tenth
            # of a one-at-a-time run (1.3.0, build 2026-11-19).
            import time as _ptime

            def _due(_p, final=False):
                now = _ptime.monotonic()
                if final or now - _p.get("t", 0.0) >= 0.25:
                    _p["t"] = now
                    return True
                return False

            def on_page_progress(page_num, total_pages, _p=_prog,
                                 _show=_show_progress):
                _p["page"], _p["pages"] = page_num, total_pages
                if _due(_p, final=page_num >= total_pages):
                    _show()

            def on_images_written(n, _p=_prog, _show=_show_progress):
                _p["images"] = n
                if _due(_p):
                    _show()

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
                        if dup_info.get("pdf_md5"):
                            pf.set("md5", dup_info["pdf_md5"])
                        pf.file_end("skipped (identical copy)")
                        root.update_idletasks()
                        continue

                # Encryption: open permissions-only files with the empty
                # password, locked files with a supplied password; a
                # locked file no password opens is recorded and skipped,
                # and remembered so the user can supply a list afterwards.
                from pdf_forensics import passwords as _pw
                enc = _pw.resolve_file_password(
                    conn, pdf_path, app.get("password_manager"),
                    session=session, quiet=True,
                    is_version=this_is_version)
                pf.lap("encryption")
                if enc["skip"]:
                    pf.file_end("encrypted, not opened")
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
                    image_callback=on_images_written,
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
                            pdf_path, versions_out, session=session,
                            password=(enc.get("password") if enc else None),
                            name=base)
                        if version_paths:
                            log_to_gui(
                                f"    \u21b3 {len(version_paths)} prior "
                                f"version(s) extracted, queued",
                                "dim")
                            parent_aid = summary.get("analysis_id")
                            # Queue the versions right after their parent
                            # (not at the end of the batch), so they reuse
                            # the parent's images while still cached. The
                            # index-keyed maps shift to make room.
                            start_idx = queue_idx
                            nv = len(version_paths)
                            process_queue[start_idx:start_idx] = version_paths
                            shifted = {i + nv if i >= start_idx else i
                                       for i in is_extracted_version}
                            is_extracted_version.clear()
                            is_extracted_version.update(shifted)
                            moved = {(k + nv if k >= start_idx else k): v
                                     for k, v in version_lineage.items()}
                            version_lineage.clear()
                            version_lineage.update(moved)
                            for off, vpath in enumerate(version_paths):
                                vi = start_idx + off
                                perf_parent[vpath] = this_perf_no
                                is_extracted_version.add(vi)
                                m = re.search(r"_version(\d+)\.pdf$",
                                              os.path.basename(vpath))
                                vnum = int(m.group(1)) if m else None
                                version_lineage[vi] = (parent_aid, vnum)
                else:
                    failed += 1
                    _pf_status = "failed (no result)"
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
                _pf_status = f"failed ({_perf.error_label(e)})"
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

            pf.lap("prior_versions_extract")
            pf.file_end(_pf_status)
            root.update_idletasks()
            # Processed counts the selected files; prior versions extracted
            # from them are counted on their own.
            count_processed.set(str(processed - versions_done))
            count_versions.set(str(versions_done))
            count_failed.set(str(failed))
            count_images.set(str(total_imgs))

        # Planner statistics for the new indexes (database.refresh_statistics).
        import time as _time
        from pdf_forensics.database import refresh_statistics
        _t_stats = _time.perf_counter()
        refresh_statistics(conn)
        pf.event("database", "statistics", _time.perf_counter() - _t_stats)
        conn.close()

        progress_done(processed, failed)

        log_to_gui("")
        submitted = len(pdf_files)
        originals_done = processed - versions_done
        pf.run_end()
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
            pdf_extract_dir = (os.path.join(out_dir,
                                            safe_name(base, out_dir))
                               if out_dir else None)
            try:
                summary = analyze_pdf(
                    pdf_path, db_val, extract_dir=pdf_extract_dir,
                    store_images=store_images_var.get(), conn=conn,
                    session=session, quiet=True, skip_duplicates=False,
                    force=True, password=enc["password"])
                if summary and not summary.get("skipped"):
                    opened += 1
                    # The file is no longer locked: move it from the Locked
                    # counter to Processed and add its images, so the
                    # counters match the run summary after the retry.
                    count_processed.set(str(int(count_processed.get() or 0) + 1))
                    count_images.set(str(int(count_images.get() or 0)
                                         + (summary.get("total_extracted") or 0)))
                    count_encrypted.set(str(max(0, len(locked) - opened)))
                    root.update_idletasks()
                    # Update the file's earlier "not opened" record rather
                    # than adding a second row, so it is counted once.
                    cur = conn.execute(
                        "UPDATE submissions SET outcome='analysed', "
                        "analysis_id=?, reason=NULL WHERE id=(SELECT MAX(id) "
                        "FROM submissions WHERE pdf_path=? AND "
                        "outcome='encrypted_unopened')",
                        (summary.get("analysis_id"),
                         os.path.abspath(pdf_path)))
                    conn.commit()
                    if cur.rowcount == 0:
                        record_submission(conn, pdf_path, "analysed",
                                          session=session,
                                          analysis_id=summary.get("analysis_id"))
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
        count_encrypted.set(str(still))
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
        # and the Timeline Analysis spreadsheet, if present
        try:
            from pdf_forensics.reports.timeline_xlsx import (
                generate_timeline_xlsx)
            for tx in glob.glob(os.path.join(glob.escape(rdir), "*timeline-analysis*.xlsx")):
                generate_timeline_xlsx(
                    db, tx, session=session,
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
        out_dir = norm_path(output_dir_var.get())
        if out_dir:
            output_dir_var.set(out_dir)

        if not out_dir:
            out_dir = session.db_dir or os.getcwd()
            output_dir_var.set(out_dir)

        # Save triage Excel to the reports subfolder
        reports_dir = session.reports_dir or os.path.join(out_dir, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        # Timed per run, so a later triage run in the same session keeps
        # the earlier spreadsheet instead of replacing it.
        xlsx_path = session.make_run_path(reports_dir, "triage", "xlsx")

        # Reset counters
        count_selected.set(str(len(pdf_files)))
        count_processed.set("0")
        count_versions.set("0")
        count_failed.set("0")
        count_images.set("0")
        count_encrypted.set("0")

        def _triage_counts():
            """(selected files triaged, prior versions triaged, rows)."""
            rows = triage_state.get("results") or []
            vers = sum(1 for r in rows if r.get("version_number") is not None)
            return len(rows) - vers, vers, len(rows)

        log_to_gui(f"Triage: {len(pdf_files)} PDF(s)...", "bold")
        log_to_gui(f"Output: {xlsx_path}", "dim")
        log_to_gui("")
        progress_reset(len(pdf_files))

        try:
            triage_count = 0
            triage_failed = 0
            # Rows of this triage run, kept so the end-of-run retry of
            # encrypted files is merged into the same spreadsheet instead
            # of replacing it.
            triage_state = {}

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
                # Merged into the main spreadsheet: the rows for these files
                # (and their prior versions and comments) are replaced in
                # place; every other row is kept.
                def _retry_progress(idx, total, filename):
                    log_to_gui(f"  \u25cb {filename} ({idx}/{total})", "dim")
                p2,s2,o2,still=run_triage(
                    locked, xlsx_path, session=session,
                    progress_callback=_retry_progress,
                    password_manager=app["password_manager"],
                    run_state=triage_state)
                opened=len(locked)-len(still)
                # Counters after the merge: Processed = rows now in the
                # spreadsheet, Locked = files still not opened.
                count_encrypted.set(str(len(still)))
                if p2:
                    files_n, vers_n, _rows = _triage_counts()
                    count_processed.set(str(files_n))
                    count_versions.set(str(vers_n))
                    log_to_gui(f"Encrypted re-triage: {opened} opened, "
                               f"{len(still)} still not opened. Their rows in "
                               f"{os.path.basename(xlsx_path)} were updated; "
                               f"all other rows are unchanged.",
                               "bold")
                else:
                    log_to_gui(f"Encrypted re-triage: no file could be "
                               f"re-triaged; {os.path.basename(xlsx_path)} "
                               f"is unchanged.", "bold")
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
                password_manager=app.get("password_manager"),
                run_state=triage_state,
                workers=_selected_workers("triage", log_to_gui))

            files_n, vers_n, rows_n = _triage_counts()
            count_processed.set(str(files_n))
            count_versions.set(str(vers_n))
            count_failed.set(str(skipped))
            count_encrypted.set(str(len(locked)))
            progress_done(processed, skipped)

            log_to_gui("")
            log_to_gui(
                f"Done: {files_n} of {len(pdf_files)} selected PDF(s) "
                f"triaged"
                + (f", plus {vers_n} prior version(s) recovered from them "
                   f"({rows_n} rows in the spreadsheet)" if vers_n else "")
                + f"; {skipped} skipped",
                "bold")
            if processed:
                log_to_gui(
                    f"\u2713 {os.path.basename(xlsx_path)}",
                    "success")

            status_var.set(
                f"Triage done. {files_n} PDF(s)"
                + (f" + {vers_n} prior version(s)" if vers_n else "")
                + f" -> {os.path.basename(xlsx_path)}")
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
                           style="Accent.TButton",
                           command=lambda: run_in_background(
                               "Processing", run_analysis))
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

    # Scrolling left column with the Generate button kept below it,
    # always visible (build 2026-11-24b: the button was cut off).
    g_left_outer, g_left, g_footer = scroll_column(g_split, 420)
    g_left_outer.pack(side="left", fill="y", padx=(0, 10))

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
    workers_control(scope_body, "Graphs made at once:").pack(
        anchor="w", pady=(8, 0))
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
    action_row_g = tk.Frame(g_footer, bg=BG_DARK)
    action_row_g.pack(fill="x", pady=(8, 4))

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
        db = norm_path(graph_db_var.get())
        if db:
            graph_db_var.set(db)
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
            from pdf_forensics import perf as _perf
            from pdf_forensics.graph.generate import generate_scopes
            _gpf = _perf.get(session)
            specs = []
            for scope in scopes:
                scope_label = scope.replace("_", "")
                out_path = (session.make_graph_path(scope_label)
                            or f"graph-{scope_label}.html")
                specs.append({"db": db, "scope": scope,
                              "group_versions": group_versions_var.get(),
                              "out_path": out_path,
                              "case_number": session.case_number})
            # Several graphs are made at once, one process each (1.3.0);
            # results are reported in the order the scopes are listed.
            n_g = min(len(specs), _selected_workers("graphs", g_log))
            g_log(f"Building {len(specs)} graph(s)"
                  + (f", {n_g} at a time" if n_g > 1 else "") + ":")
            for scope in scopes:
                session.log(f"Generating graph: scope={scope}")

            # A live line per graph, updated in place with its stage and
            # an elapsed-time clock (build 2026-11-19b).
            from pdf_forensics.gui.live import LiveLines, fmt_elapsed
            g_state = {"done": 0, "failed": 0}
            STAGE_TEXT = {
                "loading": lambda i: "loading data\u2026",
                "loaded": lambda i: (f"{i['placements']:,} placements, "
                                     f"{i['unique_images']:,} unique "
                                     f"images"),
                "thumbnails": lambda i: (f"thumbnails {i['done']:,} / "
                                         f"{i['total']:,}"),
                "building": lambda i: "building the graph\u2026",
                "network": lambda i: (f"laying out the network "
                                      f"({i['nodes']:,} nodes, "
                                      f"{i['edges']:,} links)"),
                "write_html": lambda i: "writing the HTML file\u2026",
                "custom_ui": lambda i: "adding the viewer controls\u2026",
            }

            def _g_tick():
                running = len(specs) - g_state["done"] - g_state["failed"]
                status_var.set(
                    f"Generating graphs: {g_state['done']} of {len(specs)} "
                    f"done \u00b7 {running} running \u00b7 "
                    f"{fmt_elapsed(_time_mod.monotonic() - g_live.t0)}")
                status_label.config(fg=ACCENT)

            import time as _time_mod
            g_live = LiveLines(root, g_log_text, on_tick=_g_tick)
            for scope in scopes:
                g_live.set(scope, f"  \u25cb {scope}: waiting\u2026")
            root.after(0, g_live.start)

            def _g_progress(scope, stage, info):
                if stage == "finished":
                    g_state["done"] += 1
                    if info.get("rows"):
                        g_live.done(scope, f"  \u2713 {scope}: built in "
                                    f"{fmt_elapsed(info['elapsed'])}")
                    else:
                        g_live.done(scope, f"  \u2298 {scope}: no data",
                                    "dim")
                elif stage == "failed":
                    g_state["failed"] += 1
                    g_live.done(scope, f"  \u2717 {scope}: "
                                f"{info.get('error')}", "error")
                elif stage in STAGE_TEXT:
                    try:
                        txt = STAGE_TEXT[stage](info)
                    except Exception:
                        txt = stage
                    g_live.set(scope, f"  \u25cb {scope}: {txt}")

            _gpf.load_begin()
            try:
                g_results = list(generate_scopes(specs, workers=n_g,
                                                 on_progress=_g_progress))
            finally:
                g_live.stop()
                _gpf.load_end("graphs")
            g_log("")
            for spec, res in g_results:
                scope = spec["scope"]
                if isinstance(res, Exception):
                    session.log(f"Graph error ({scope}): {res}", "error")
                    continue
                if not res["rows"]:
                    session.log(f"  No data for scope {scope}")
                    continue
                g_log(f"  {scope}: {res['rows']} placements, "
                      f"{res['unique_images']} unique images")
                same_as = dataset_seen.get(res["digest"])
                if same_as:
                    note = (f"Note: {scope} selected the identical "
                            f"dataset as {same_as} for this "
                            f"database \u2014 the two graphs show "
                            f"the same relationships.")
                    g_log(f"  \u24d8 {note}", "dim")
                    session.log(f"  {note}")
                else:
                    dataset_seen[res["digest"]] = scope
                _gpf.event("graph_thumbnails", scope, res["t_thumb"],
                           images=res["thumb_images"])
                out_path = res["out_path"]
                session.register_output("graph", out_path)
                generated.append((scope, out_path))
                session.log(f"  Generated: {out_path}")
                _gpf.event("graph", scope, res["elapsed"],
                           placements=res["rows"],
                           unique_images=res["unique_images"],
                           nodes=res.get("nodes"), edges=res.get("edges"),
                           **{k: (round(v, 2) if isinstance(v, float)
                                  else v) for k, v in
                              res.get("timings", {}).items()})
                g_log(f"    \u2192 {os.path.basename(out_path)}", "dim")

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
                           style="Accent.TButton",
                           command=lambda: run_in_background(
                               "Graph generation", run_graph))
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

    # Layout (build 2026-11-24b): the Visual report panel and the Generate
    # button run across the full width at the bottom, packed FIRST so
    # they always stay visible; above them, the database and report
    # choices (left, scrolling if the window is short) beside the Report
    # Log, which ends level with them.
    r_bottom = tk.Frame(reports_frame, bg=BG_DARK)
    r_bottom.pack(side="bottom", fill="x", padx=20, pady=(0, 8))

    r_split = tk.Frame(reports_frame, bg=BG_DARK)
    r_split.pack(fill="both", expand=True, padx=20, pady=(0, 0))

    r_left_outer, r_left, _r_footer = scroll_column(r_split, 560)
    r_left_outer.pack(side="left", fill="y", padx=(0, 10))

    r_right = tk.Frame(r_split, bg=BG_DARK)
    r_right.pack(side="left", fill="both", expand=True, pady=(0, 12))

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
            # pady=0: the 22nd report (1.1.0) adds a row; tighter rows keep
            # the list within a 1080p screen, where the height is clamped.
            cb.grid(row=row, column=col, sticky="w", padx=(0, 10), pady=0)
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

    # Visual overlay report option: full width, one line.
    visual_opts = make_panel(r_bottom, "Visual report")
    visual_report_var = tk.BooleanVar(value=True)
    _visual_row = tk.Frame(visual_opts, bg=BG_PANEL)
    _visual_row.pack(fill="x")
    _visual_cb = ttk.Checkbutton(
        _visual_row,
        text="Generate visual overlay report (annotated page images)",
        variable=visual_report_var)
    _visual_cb.pack(side="left")
    workers_control(_visual_row, "Documents rendered at once:").pack(
        side="left", padx=(40, 0))

    # Generate button, under the Visual report panel.
    action_row_r = tk.Frame(r_bottom, bg=BG_DARK)
    action_row_r.pack(fill="x", pady=(0, 4))
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
        db = norm_path(report_db_var.get())
        if db:
            report_db_var.set(db)
        if not db or not os.path.isfile(db):
            messagebox.showerror("No database",
                                 "Please select a valid database file.")
            return
        # A database from an earlier version gets its indexes and planner
        # statistics once (init_db creates any missing indexes).
        try:
            from pdf_forensics.database import init_db, refresh_statistics
            _c = init_db(db)
            refresh_statistics(_c, only_if_missing=True)
            _c.close()
        except Exception:
            pass
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
                r_log("Generating visual overlay reports...")
                root.update_idletasks()
                try:
                    from pdf_forensics.reports.visual import (
                        generate_visual_reports)
                    vfname = session.make_filename(
                        "visual-overlays", "html")
                    vpath = os.path.join(out_dir, vfname)

                    # Progress in the Report Log itself (build
                    # 2026-11-19b), not only in the status bar, which a
                    # small window may not show: a live line with the
                    # count and a clock, a line under it for each
                    # document running longer than LONG_DOC_S, and a
                    # completion line.
                    import threading as _thr
                    import time as _vt
                    from pdf_forensics.gui.live import LiveLines, fmt_elapsed
                    LONG_DOC_S = 30
                    v_lock = _thr.Lock()
                    v_state = {"done": 0, "total": None, "running": {}}
                    v_shown = {}            # i -> name, long-running lines

                    def _v_render():
                        with v_lock:
                            done, total = v_state["done"], v_state["total"]
                            running = dict(v_state["running"])
                        now = _vt.time()
                        if total is None:
                            v_live.set("vis", "  \u25cb Visual overlay "
                                       "reports: finding documents\u2026")
                        else:
                            v_live.set("vis", f"  \u25cb Visual overlay "
                                       f"reports: {done} of {total} "
                                       f"document(s) \u00b7 "
                                       f"{_running_text(running)}")
                        for i, (name, t0) in running.items():
                            if i in v_shown or now - t0 < LONG_DOC_S:
                                continue
                            v_shown[i] = (name, t0)
                            v_live.set(("doc", i), f"      \u25cb {name}: "
                                       f"rendering", parent="vis",
                                       started=_vt.monotonic() - (now - t0))
                        for i, (name, t0) in list(v_shown.items()):
                            if i not in running and t0 is not None:
                                v_live.done(("doc", i), f"      \u2713 "
                                            f"{name}: "
                                            f"{fmt_elapsed(now - t0)}",
                                            "dim")
                                v_shown[i] = (name, None)

                    def _running_text(running):
                        """'2 running', or '1 running in 4 parts' when
                        documents are drawn in parts (runs of pages) by
                        several processes at once (build 2026-11-24b)."""
                        docs = {k[0] if isinstance(k, tuple) else k
                                for k in running}
                        if len(running) > len(docs):
                            return (f"{len(docs)} running in "
                                    f"{len(running)} parts")
                        return f"{len(docs)} running"

                    def _v_status(info):
                        with v_lock:
                            v_state.update(info)
                        _v_render()

                    def _v_tick():
                        _v_render()
                        with v_lock:
                            done, total = v_state["done"], v_state["total"]
                            nrun = _running_text(v_state["running"])
                        if total is not None:
                            status_var.set(
                                f"Visual overlay reports: {done} of {total} "
                                f"done \u00b7 {nrun} \u00b7 "
                                f"{fmt_elapsed(_vt.monotonic() - v_live.t0)}")
                            status_label.config(fg=ACCENT)

                    def _vis_progress(i, total):
                        pass        # counts come from _v_status

                    nv = _selected_workers("visual reports", r_log)
                    v_live = LiveLines(root, r_log_text, on_tick=_v_tick)
                    _v_render()
                    root.after(0, v_live.start)
                    _vt0 = _vt.monotonic()
                    try:
                        ndocs, n = generate_visual_reports(
                            db, vpath, session=session,
                            progress=_vis_progress, workers=nv,
                            status=_v_status)
                    except Exception:
                        v_live.done("vis", "  \u2717 Visual overlay "
                                    "reports stopped", "error")
                        v_live.stop()
                        raise
                    with v_lock:
                        total = v_state["total"] or 0
                    v_live.done("vis", f"  \u2713 Visual overlay reports: "
                                f"{total} document(s) done in "
                                f"{fmt_elapsed(_vt.monotonic() - _vt0)}",
                                "dim")
                    v_live.stop()
                    if n > 0:
                        r_log(f"  \u2713 Visual overlay reports — "
                              f"{ndocs} document(s), {n} finding(s); "
                              f"index {vfname}", "success")
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
            # Timeline Analysis (Excel), listed under Spreadsheets in the
            # case index.
            try:
                from pdf_forensics.reports.timeline_xlsx import (
                    generate_timeline_xlsx)
                tl_path = os.path.join(
                    out_dir, session.make_filename("timeline-analysis", "xlsx"))
                ntl = generate_timeline_xlsx(
                    db, tl_path, session=session,
                    case_number=session.case_number)
                session.register_output("timeline_xlsx", tl_path)
                r_log(f"  \u2713 Timeline Analysis (xlsx) — "
                      f"{ntl} document(s)", "success")
            except Exception as e:
                r_log(f"  Timeline Analysis spreadsheet skipped — {e}", "dim")
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
                           style="Accent.TButton",
                           command=lambda: run_in_background(
                               "Report generation", run_reports))
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
