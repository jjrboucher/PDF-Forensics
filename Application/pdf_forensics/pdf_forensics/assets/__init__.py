"""
Asset loading helpers for the PDF Forensics Suite.

Provides access to the logo and icon images bundled with the package.
"""

import os
import base64

_ASSETS_DIR = os.path.dirname(__file__)


def get_logo_path():
    """Return the path to the logo PNG file."""
    return os.path.join(_ASSETS_DIR, "logo.png")


def get_icon_path():
    """Return the path to the icon PNG file."""
    return os.path.join(_ASSETS_DIR, "icon.png")


def get_icon_ico_path():
    """Return the path to the icon ICO file (Windows)."""
    return os.path.join(_ASSETS_DIR, "icon.ico")


def get_logo_base64():
    """Return the logo as a base64-encoded JPEG data URI string."""
    logo_path = get_logo_path()
    if not os.path.isfile(logo_path):
        return None
    with open(logo_path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"
