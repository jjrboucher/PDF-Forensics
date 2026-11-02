"""
Performance log: how long the application takes for each processing task.

Written to the session's logs folder as performance_{timestamp}.log, for
diagnosing slow processing. It is meant to be shareable outside the case,
so it contains NO case-specific information: no case number, no file names
and no paths. Files are identified by their MD5 (the hash the database and
the case index also record), so the examiner can identify a slow file in
their own case without the log revealing it.

Contents:
  * system details (operating system, CPU, memory, Python and library
    versions, the type of drive the case folder is on: local or network)
  * the options in effect for each run
  * one row per processed file: size, pages, images, unique images, cache
    reuse, findings, revisions, memory, and the time spent in each stage
  * one row per report, spreadsheet or graph generated
  * run totals

Stage timing works by laps: code marks the end of each stage with
lap("stage"), and the time since the previous mark is credited to that
stage. Nothing here changes what the application does.
"""

import os
import sys
import time
import platform
from datetime import datetime

from pdf_forensics import __version__, __tool_name__, BUILD_DATE, SCHEMA_REVISION

# Stages of a full analysis, in order (columns of the FILES table).
ANALYSIS_STAGES = (
    "open", "image_map", "image_files", "transparency", "page_detectors",
    "page_other", "font_dpi", "comments", "doc_checks", "metadata_history",
    "version_checks", "timeline", "risk", "db_save", "finish",
    "encryption", "prior_versions_extract",
)
TRIAGE_STAGES = ("triage_scan", "triage_versions", "triage_comments")
COUNTERS = ("size_mb", "pages", "image_placements", "unique_images",
            "cache_hits", "image_mb", "findings", "revisions")


def _rss_mb():
    """Resident memory of this process in MB, best effort (None if the
    platform gives no cheap way to read it)."""
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1048576, 1)
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD),
                            ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            k32 = ctypes.windll.kernel32
            # 64-bit handle types: without them the pseudo-handle of the
            # current process is truncated and the call fails silently.
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            h = k32.GetCurrentProcess()
            fn = getattr(k32, "K32GetProcessMemoryInfo", None)
            if fn is None:
                fn = ctypes.windll.psapi.GetProcessMemoryInfo
            fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC),
                           wintypes.DWORD]
            fn.restype = wintypes.BOOL
            if fn(h, ctypes.byref(pmc), pmc.cb):
                return round(pmc.WorkingSetSize / 1048576, 1)
        except Exception:
            return None
    try:
        with open("/proc/self/statm") as fh:
            pages = int(fh.read().split()[1])
        return round(pages * os.sysconf("SC_PAGE_SIZE") / 1048576, 1)
    except Exception:
        return None


def _total_ram_gb():
    try:
        import psutil
        return round(psutil.virtual_memory().total / 1073741824, 1)
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = MS()
            ms.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            return round(ms.ullTotalPhys / 1073741824, 1)
        except Exception:
            return None
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1048576, 1)
    except Exception:
        pass
    return None


def _drive_type(path):
    """'local fixed', 'network', 'removable', ... for the drive holding
    path, without recording the path itself."""
    if not path:
        return "unknown"
    if sys.platform == "win32":
        try:
            import ctypes
            root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
            if root.startswith("\\\\"):
                return "network (UNC path)"
            t = ctypes.windll.kernel32.GetDriveTypeW(root)
            return {2: "removable", 3: "local fixed", 4: "network",
                    5: "optical", 6: "RAM disk"}.get(t, f"unknown ({t})")
        except Exception:
            return "unknown"
    try:
        p = os.path.abspath(path)
        best, fstype = "", ""
        with open("/proc/mounts") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) > 2 and p.startswith(parts[1]) and \
                        len(parts[1]) > len(best):
                    best, fstype = parts[1], parts[2]
        if fstype in ("nfs", "nfs4", "cifs", "smbfs", "smb3", "sshfs",
                      "fuse.sshfs"):
            return f"network ({fstype})"
        return f"local ({fstype})" if fstype else "unknown"
    except Exception:
        return "unknown"


def _free_gb(path):
    try:
        import shutil
        return round(shutil.disk_usage(path).free / 1073741824, 1)
    except Exception:
        return None


def _lib_versions():
    out = []
    for label, mod, attr in (("PyMuPDF", "pymupdf", "VersionBind"),
                             ("pikepdf", "pikepdf", "__version__"),
                             ("qpdf", "pikepdf", "__libqpdf_version__"),
                             ("Pillow", "PIL", "__version__"),
                             ("openpyxl", "openpyxl", "__version__"),
                             ("networkx", "networkx", "__version__"),
                             ("psutil", "psutil", "__version__")):
        try:
            m = __import__(mod)
            out.append(f"{label} {getattr(m, attr)}")
        except Exception:
            out.append(f"{label} (not installed)")
    return out


class PerfLog:
    """One performance log per session. All methods are safe to call at
    any time; failures to write never interrupt processing."""

    def __init__(self, path, case_folder=None):
        self.path = path
        self._fh = open(path, "w", encoding="utf-8")
        self._file = None
        self._n = 0
        self._run = None
        self._t_last = None
        self._header(case_folder)

    # -- writing ------------------------------------------------------
    def _w(self, line=""):
        try:
            self._fh.write(line + "\n")
            self._fh.flush()
        except Exception:
            pass

    def _header(self, case_folder):
        self._w("=" * 72)
        self._w(f"{__tool_name__} performance log")
        self._w("Contains no case number, file names or paths; files are "
                "identified by MD5.")
        self._w("=" * 72)
        self._w(f"Started:        {datetime.now():%Y-%m-%d %H:%M:%S} (local time)")
        self._w(f"Application:    v{__version__} (build {BUILD_DATE}), "
                f"schema {SCHEMA_REVISION}")
        self._w(f"OS:             {platform.platform()}")
        self._w(f"Machine:        {platform.machine()}; "
                f"processor: {platform.processor() or 'unknown'}")
        self._w(f"Logical CPUs:   {os.cpu_count()}")
        ram = _total_ram_gb()
        self._w(f"RAM:            {ram if ram is not None else 'unknown'} GB")
        self._w(f"Python:         {platform.python_version()} "
                f"({platform.python_implementation()}, "
                f"{'64' if sys.maxsize > 2**32 else '32'}-bit)")
        self._w(f"Libraries:      {', '.join(_lib_versions())}")
        if case_folder:
            free = _free_gb(case_folder)
            self._w(f"Case folder:    on a {_drive_type(case_folder)} drive, "
                    f"{free if free is not None else 'unknown'} GB free")
        self._w(f"Memory at start: {_rss_mb()} MB")
        self._w("")

    # -- runs ---------------------------------------------------------
    def run_begin(self, mode, n_files, **options):
        """mode: 'analysis' or 'triage'. options: flags and counts only."""
        self._run = {"mode": mode, "t0": time.perf_counter(), "files": 0,
                     "pages": 0, "images": 0}
        stages = ANALYSIS_STAGES if mode == "analysis" else TRIAGE_STAGES
        self._run["stages"] = stages
        self._w("-" * 72)
        self._w(f"RUN {mode} started {datetime.now():%H:%M:%S}: "
                f"{n_files} file(s) selected")
        if options:
            self._w("Options: " + ", ".join(f"{k}={v}" for k, v in
                                           sorted(options.items())))
        self._w("FILES (times in seconds)")
        self._w("\t".join(("#", "kind", "of#", "md5", "status", "total")
                          + COUNTERS + ("mem_mb",) + stages))

    def run_end(self):
        r = self._run
        if not r:
            return
        el = time.perf_counter() - r["t0"]
        self._w(f"RUN {r['mode']} finished: {r['files']} file(s), "
                f"{r['pages']} page(s), {r['images']} image placement(s) in "
                f"{el:.1f} s"
                + (f" ({r['files'] / el * 60:.1f} files/min)" if el else "")
                + f"; memory {_rss_mb()} MB")
        self._run = None

    # -- files --------------------------------------------------------
    def file_begin(self, kind="submitted", of=None):
        """Start a file's record. kind: 'submitted' or 'version N'; of:
        the # of the submitted file a prior version came from. Returns
        this file's #."""
        if self._file is not None:
            self.file_end("interrupted")
        self._n += 1
        self._file = {"n": self._n, "kind": kind, "of": of, "md5": "",
                      "t0": time.perf_counter(), "stages": {}, "counts": {}}
        self._t_last = time.perf_counter()
        return self._n

    def set(self, key, value):
        if self._file is not None:
            if key == "md5":
                self._file["md5"] = value
            else:
                self._file["counts"][key] = value

    def add(self, key, n=1):
        if self._file is not None:
            c = self._file["counts"]
            c[key] = c.get(key, 0) + n

    def lap_reset(self):
        self._t_last = time.perf_counter()

    def lap(self, stage):
        """Credit the time since the previous mark to stage."""
        if self._file is None:
            return
        now = time.perf_counter()
        st = self._file["stages"]
        st[stage] = st.get(stage, 0.0) + (now - (self._t_last or now))
        self._t_last = now

    def file_end(self, status="ok"):
        f = self._file
        if f is None:
            return
        total = time.perf_counter() - f["t0"]
        stages = self._run["stages"] if self._run else ANALYSIS_STAGES
        c = f["counts"]
        row = [str(f["n"]), f["kind"], str(f["of"] or ""), f["md5"] or "-",
               status, f"{total:.2f}"]
        row += [str(c.get(k, "")) for k in COUNTERS]
        mem = _rss_mb()
        row.append("" if mem is None else str(mem))
        row += [f"{f['stages'][s]:.2f}" if s in f["stages"] else ""
                for s in stages]
        self._w("\t".join(row))
        if self._run:
            self._run["files"] += 1
            self._run["pages"] += int(c.get("pages", 0) or 0)
            self._run["images"] += int(c.get("image_placements", 0) or 0)
        self._file = None

    # -- other timed events (reports, spreadsheets, graphs, index) ----
    def event(self, kind, name, seconds, **counts):
        """kind: report, spreadsheet, graph, case_index ...; name: a
        report id or similar, never a file or case name."""
        extra = "".join(f"\t{k}={v}" for k, v in counts.items())
        self._w(f"EVENT\t{kind}\t{name}\t{seconds:.2f}{extra}")

    def note(self, text):
        """A free-text line. Callers must not pass names or paths."""
        self._w(f"NOTE\t{text}")

    def close(self):
        try:
            self._w(f"Closed {datetime.now():%Y-%m-%d %H:%M:%S}; "
                    f"memory {_rss_mb()} MB")
            self._fh.close()
        except Exception:
            pass


def error_label(exc):
    """'ExceptionType at module.py:function:line' for the innermost frame
    of this application, without the exception message (which can
    contain file names or paths)."""
    name = type(exc).__name__
    try:
        tb, where = exc.__traceback__, None
        while tb is not None:
            fn = tb.tb_frame.f_code.co_filename.replace("\\", "/")
            if "/pdf_forensics/" in fn:
                where = (f"{fn.rsplit('/pdf_forensics/', 1)[1]}:"
                         f"{tb.tb_frame.f_code.co_name}:{tb.tb_lineno}")
            tb = tb.tb_next
        return f"{name} at {where}" if where else name
    except Exception:
        return name


class _NullPerf:
    """Stand-in when no performance log is open: every call is a no-op."""

    def __getattr__(self, name):
        return lambda *a, **k: None


NULL = _NullPerf()


def get(session):
    """The session's performance log, or a no-op stand-in."""
    p = getattr(session, "perf", None) if session else None
    return p if p is not None else NULL


def timed(kind, name=None):
    """Decorator: log an EVENT with the call's duration to the session's
    performance log. The function must take a session= keyword. name is a
    fixed label or a function of the call's arguments returning one; it
    must never be a file or case name."""
    import functools

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                try:
                    label = name(*args, **kwargs) if callable(name) else (
                        name or fn.__name__)
                    sess = kwargs.get("session")
                    if sess is None:   # passed positionally
                        sess = next((a for a in args
                                     if hasattr(a, "perf")), None)
                    get(sess).event(kind, label, time.perf_counter() - t0)
                except Exception:
                    pass
        return wrapper
    return deco
