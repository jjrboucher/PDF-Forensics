"""
Agency / investigator branding configuration.

Stores the information that personalises generated reports — the
agency logo, investigator details, agency and unit names, and an
optional classification caveat. Persisted as JSON in the application
folder (next to the package), with a graceful fallback to the user's
home directory if the application folder is not writable.

The same saved branding is picked up by every report generator
(HTML reports, the visual overlay report, and graph reports) and by
both the GUI and the CLI, so configuring it once applies everywhere.
"""

import os
import json
import base64

# Application folder = the directory that contains this package.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_PRIMARY_PATH = os.path.join(_APP_DIR, "branding.json")
_FALLBACK_PATH = os.path.join(
    os.path.expanduser("~"), ".pdf_forensics_branding.json")

# Field keys and human-readable labels. The order here is the order
# fields are displayed in the GUI dialog and in report banners.
FIELDS = [
    ("agency_name",        "Agency name"),
    ("unit_name",          "Unit name"),
    ("investigator_name",  "Investigator name"),
    ("investigator_email", "Investigator email"),
    ("investigator_phone", "Investigator phone (optional)"),
    ("agency_address",     "Agency address (optional)"),
    ("classification",     "Classification caveat (optional)"),
    ("agency_logo_path",   "Agency logo file"),
]

# Fields that may be left blank without affecting report validity.
OPTIONAL_FIELDS = {
    "investigator_phone", "agency_address",
    "classification", "agency_logo_path",
}

_DEFAULTS = {key: "" for key, _ in FIELDS}

# Simple in-process cache for the encoded logo so we don't re-read the
# file for every report in a batch. Keyed by (path, mtime, size).
_logo_cache = {}


def _config_path():
    """
    Return the path to read/write branding from.

    Prefers the application folder; if a branding.json already exists
    in the home-directory fallback location (and not in the app
    folder), use that instead so previously-saved settings are found.
    """
    if os.path.isfile(_PRIMARY_PATH):
        return _PRIMARY_PATH
    if os.path.isfile(_FALLBACK_PATH):
        return _FALLBACK_PATH
    return _PRIMARY_PATH


def load_branding():
    """
    Load branding from disk, returning a dict with every known field
    present (missing fields default to an empty string). Never raises.
    """
    cfg = dict(_DEFAULTS)
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key, _ in FIELDS:
                if key in data and data[key] is not None:
                    cfg[key] = str(data[key])
    except Exception:
        pass
    return cfg


def save_branding(cfg):
    """
    Persist branding to the application folder. Falls back to the
    home directory if the application folder is not writable.

    Returns the path actually written to, or None on failure.
    """
    clean = {}
    for key, _ in FIELDS:
        clean[key] = str(cfg.get(key, "") or "").strip()

    for path in (_PRIMARY_PATH, _FALLBACK_PATH):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(clean, f, indent=2)
            return path
        except Exception:
            continue
    return None


def _mime_for(path):
    ext = os.path.splitext(path)[1].lower()
    return {
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif":  "image/gif",
        ".webp": "image/webp",
        ".bmp":  "image/bmp",
        ".svg":  "image/svg+xml",
    }.get(ext, "image/png")


def get_agency_logo_data_uri(cfg=None):
    """
    Return the configured agency logo as a base64 data URI suitable
    for embedding in HTML, or None if no logo is set or readable.

    Result is cached by file path + mtime + size.
    """
    cfg = cfg or load_branding()
    path = (cfg.get("agency_logo_path") or "").strip()
    if not path or not os.path.isfile(path):
        return None
    try:
        st = os.stat(path)
        cache_key = (path, st.st_mtime, st.st_size)
        if cache_key in _logo_cache:
            return _logo_cache[cache_key]
        with open(path, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode("ascii")
        uri = f"data:{_mime_for(path)};base64,{b64}"
        _logo_cache[cache_key] = uri
        return uri
    except Exception:
        return None


def has_branding(cfg=None):
    """True if any non-optional branding field is filled in."""
    cfg = cfg or load_branding()
    for key, _ in FIELDS:
        if key in OPTIONAL_FIELDS:
            continue
        if (cfg.get(key) or "").strip():
            return True
    return False


def case_info_pairs(case_number=None, cfg=None):
    """
    Return an ordered list of (label, value) tuples for the report
    banner. Only non-empty fields are included. The case number is
    supplied separately because it comes from the session, not the
    saved branding.
    """
    cfg = cfg or load_branding()
    pairs = []
    if case_number:
        pairs.append(("Case", case_number))
    order = [
        ("investigator_name",  "Investigator"),
        ("investigator_email", "Email"),
        ("investigator_phone", "Phone"),
        ("agency_name",        "Agency"),
        ("unit_name",          "Unit"),
        ("agency_address",     "Address"),
    ]
    for key, label in order:
        val = (cfg.get(key) or "").strip()
        if val:
            pairs.append((label, val))
    return pairs


def classification_text(cfg=None):
    """Return the classification caveat string, or '' if not set."""
    cfg = cfg or load_branding()
    return (cfg.get("classification") or "").strip()


def footer_text(case_number=None, cfg=None):
    """
    Build the per-page footer string: case number and investigator
    name, joined by a separator. Empty components are skipped.
    """
    cfg = cfg or load_branding()
    parts = []
    if case_number:
        parts.append(f"Case {case_number}")
    inv = (cfg.get("investigator_name") or "").strip()
    if inv:
        parts.append(inv)
    return "  \u00b7  ".join(parts)
