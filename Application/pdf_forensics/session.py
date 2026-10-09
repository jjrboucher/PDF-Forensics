"""
Session management, configuration persistence, and forensic logging.

The Session class tracks a single analysis session tied to a case
number. All output files share a common timestamp and are organized
relative to the database location.

Folder structure (relative to DB location):
    {db_dir}/
        {case}_forensics_{timestamp}.db
        extracted_images/
        pdf_versions/
            {pdfname}_versions/
        logs/
            {case}_session_{timestamp}.log
        graph_reports/
            {case}_graph-crossdoc_{timestamp}.html
        reports/
            {case}_report-highrisk_{timestamp}.html
"""

import os
import sys
import json
import hashlib
import logging
import platform
from datetime import datetime, timezone

from pdf_forensics import __version__, __tool_name__, BUILD_DATE


# ===================================================================
# Configuration persistence
# ===================================================================

CONFIG_DIR = os.path.expanduser("~")
CONFIG_FILE = os.path.join(CONFIG_DIR, ".pdf_forensics_config.json")


def load_config():
    """Load persisted config (last case number, etc.)."""
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    """Persist config to disk."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# ===================================================================
# Session
# ===================================================================

class Session:
    """
    Manages a single analysis session tied to a case number.

    All output files produced during this session share the same
    timestamp and are organized relative to the database directory.
    """

    def __init__(self, case_number, db_dir=None):
        self.case_number = case_number
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.start_time = datetime.now()
        self.db_dir = db_dir  # Set later when DB path is chosen
        self.outputs = []     # list of (kind, path) tuples
        self.logger = None
        self.log_path = None

        # Persist last-used case
        cfg = load_config()
        cfg["last_case"] = case_number
        save_config(cfg)

    def set_db_dir(self, db_dir):
        """
        Set the base directory (where the DB lives). All other
        output folders are created relative to this path.
        Creates the directory structure if it doesn't exist.
        """
        self.db_dir = db_dir
        os.makedirs(db_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.graph_reports_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        # Initialize the logger now that we know where to write
        if self.logger is None:
            self._init_logger()

    @property
    def logs_dir(self):
        return os.path.join(self.db_dir, "logs") if self.db_dir else None

    @property
    def graph_reports_dir(self):
        return os.path.join(self.db_dir, "graph_reports") \
            if self.db_dir else None

    @property
    def reports_dir(self):
        return os.path.join(self.db_dir, "reports") \
            if self.db_dir else None

    @property
    def extracted_images_dir(self):
        return os.path.join(self.db_dir, "extracted_images") \
            if self.db_dir else None

    @property
    def pdf_versions_dir(self):
        return os.path.join(self.db_dir, "pdf_versions") \
            if self.db_dir else None

    def _init_logger(self):
        """Set up the per-session forensic log file."""
        if not self.logs_dir:
            return

        log_name = self.make_filename("session", "log")
        self.log_path = os.path.join(self.logs_dir, log_name)

        self.logger = logging.getLogger(
            f"pdf_forensics_{self.timestamp}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()

        fh = logging.FileHandler(self.log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S")
        fh.setFormatter(fmt)
        self.logger.addHandler(fh)

        # Write session header
        self.logger.info("=" * 70)
        self.logger.info(f"{__tool_name__} v{__version__}")
        self.logger.info(f"Build: {BUILD_DATE}")
        try:
            from pdf_forensics.acknowledgement import log_line as _ack_line
            self.logger.info(_ack_line(load_config()))
        except Exception:
            pass
        self.logger.info(f"Case: {self.case_number}")
        # Agency / investigator identity (from branding config) so the log
        # records who ran the analysis and under what authority.
        try:
            from pdf_forensics import branding as _bmod
            _cfg = _bmod.load_branding()
            _agency = (_cfg.get("agency_name") or "").strip()
            _unit = (_cfg.get("unit_name") or "").strip()
            _inv = (_cfg.get("investigator_name") or "").strip()
            _email = (_cfg.get("investigator_email") or "").strip()
            self.logger.info(f"Agency: {_agency or '(not set)'}")
            self.logger.info(f"Unit: {_unit or '(not set)'}")
            _inv_line = _inv or "(not set)"
            if _email:
                _inv_line += f" <{_email}>"
            self.logger.info(f"Investigator: {_inv_line}")
        except Exception:
            pass
        self.logger.info(f"Session started: {self.timestamp}")
        self.logger.info(f"Host: {platform.node()}")
        self.logger.info(f"OS: {platform.platform()}")
        self.logger.info(f"Python: {sys.version}")

        try:
            import pymupdf
            self.logger.info(f"PyMuPDF: {pymupdf.version}")
        except Exception:
            pass
        try:
            import pikepdf
            self.logger.info(f"pikepdf: {pikepdf.__version__}")
        except Exception:
            pass
        try:
            import PIL
            self.logger.info(f"Pillow: {PIL.__version__}")
        except Exception:
            pass
        try:
            import networkx
            self.logger.info(f"networkx: {networkx.__version__}")
        except Exception:
            pass

        self.logger.info(f"Base directory: {self.db_dir}")
        self.logger.info("=" * 70)

        self.register_output("log", self.log_path)

    def make_filename(self, kind, ext):
        """Generate: {case}_{kind}_{timestamp}.{ext}"""
        return f"{self.case_number}_{kind}_{self.timestamp}.{ext}"

    def make_db_path(self):
        """Generate the session-named database path."""
        if not self.db_dir:
            return None
        return os.path.join(
            self.db_dir, self.make_filename("forensics", "db"))

    def make_graph_path(self, scope_label):
        """Generate a graph output path."""
        if not self.graph_reports_dir:
            return None
        return os.path.join(
            self.graph_reports_dir,
            self.make_filename(f"graph-{scope_label}", "html"))

    def make_report_path(self, report_label):
        """Generate a report output path."""
        if not self.reports_dir:
            return None
        return os.path.join(
            self.reports_dir,
            self.make_filename(f"report-{report_label}", "html"))

    def register_output(self, kind, path):
        """Record an output file produced during this session."""
        self.outputs.append((kind, os.path.abspath(path)))

    def log(self, msg, level="info"):
        """Write to the forensic log."""
        if self.logger:
            getattr(self.logger, level, self.logger.info)(msg)

    def log_pdf_start(self, pdf_path, pdf_md5, pdf_size):
        """Log the start of a PDF analysis."""
        self.log(f"--- PDF Analysis Start ---")
        self.log(f"  File: {os.path.abspath(pdf_path)}")
        self.log(f"  MD5:  {pdf_md5}")
        self.log(f"  Size: {pdf_size:,} bytes")

    def log_pdf_complete(self, pdf_path, pages, images, findings,
                         high_risk_count=0):
        """Log the successful completion of a PDF analysis."""
        self.log(f"  Result: SUCCESS")
        self.log(f"  Pages: {pages}, Images: {images}, "
                 f"Findings: {findings}, High-risk: {high_risk_count}")
        self.log(f"--- PDF Analysis End ---")

    def log_pdf_error(self, pdf_path, error):
        """Log a failed PDF analysis with traceback."""
        import traceback
        self.log(f"  Result: FAILED — {error}", "error")
        self.log(f"  Traceback:\n{traceback.format_exc()}", "error")
        self.log(f"--- PDF Analysis End (ERROR) ---")

    def compute_db_md5(self, db_path):
        """Compute MD5 of the database file for chain of custody."""
        try:
            h = hashlib.md5()
            with open(db_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return "unavailable"

    def write_summary(self, stats=None, db_path=None):
        """Write the session-closing summary to the log."""
        if not self.logger:
            return

        stats = stats or {}
        end_time = datetime.now()
        duration = end_time - self.start_time

        self.logger.info("")
        self.logger.info("=" * 70)
        self.logger.info("SESSION SUMMARY")
        self.logger.info("=" * 70)
        self.logger.info(f"Case:     {self.case_number}")
        try:
            from pdf_forensics import branding as _bmod
            _cfg = _bmod.load_branding()
            _agency = (_cfg.get("agency_name") or "").strip()
            _unit = (_cfg.get("unit_name") or "").strip()
            _inv = (_cfg.get("investigator_name") or "").strip()
            _email = (_cfg.get("investigator_email") or "").strip()
            self.logger.info(f"Agency:   {_agency or '(not set)'}")
            self.logger.info(f"Unit:     {_unit or '(not set)'}")
            _inv_line = _inv or "(not set)"
            if _email:
                _inv_line += f" <{_email}>"
            self.logger.info(f"Investigator: {_inv_line}")
        except Exception:
            pass
        self.logger.info(
            f"Started:  {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(
            f"Ended:    {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"Duration: {duration}")

        if stats:
            self.logger.info("")
            for k, v in stats.items():
                self.logger.info(f"  {k}: {v}")

        if db_path and os.path.isfile(db_path):
            db_md5 = self.compute_db_md5(db_path)
            self.logger.info("")
            self.logger.info(f"Database MD5: {db_md5}")

        self.logger.info("")
        self.logger.info("Outputs produced:")
        for kind, path in self.outputs:
            self.logger.info(f"  [{kind}] {path}")
        self.logger.info("=" * 70)
