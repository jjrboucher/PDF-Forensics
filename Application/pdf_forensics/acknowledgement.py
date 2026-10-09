"""
Recording the user's acknowledgement of the disclaimer.

The acknowledgement is kept in the user's settings file
(~/.pdf_forensics_config.json) as a record of when, by which Windows user,
on which computer, against which disclaimer text and with which build it
was given. The disclaimer text is identified by a fingerprint (the first
12 hex characters of the SHA-256 of the text shown), so if the wording
ever changes the user is asked to acknowledge it again. Every session log
states the acknowledgement on record.
"""
import getpass
import hashlib
import platform
from datetime import datetime


def disclaimer_version():
    from pdf_forensics import disclaimers
    return hashlib.sha256(
        disclaimers.SHORT_DISCLAIMER.encode("utf-8")).hexdigest()[:12]


def acknowledgement_needed(cfg):
    rec = (cfg or {}).get("disclaimer_acknowledgement")
    return not (isinstance(rec, dict)
                and rec.get("disclaimer_version") == disclaimer_version())


def reprompt_reason(cfg):
    """Why an acknowledgement is being asked for again (None if first)."""
    cfg = cfg or {}
    rec = cfg.get("disclaimer_acknowledgement")
    if isinstance(rec, dict):
        return "The disclaimer has changed since you last acknowledged it."
    if cfg.get("disclaimer_acknowledged"):
        return ("Acknowledgements are now recorded with the date, user and "
                "disclaimer version; please acknowledge again so a record "
                "is kept.")
    return None


def make_record():
    from pdf_forensics import __version__, BUILD_DATE
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    return {"acknowledged_at":
                datetime.now().astimezone().isoformat(timespec="seconds"),
            "user": user, "host": platform.node(),
            "disclaimer_version": disclaimer_version(),
            "app_version": __version__, "build": BUILD_DATE}


def log_line(cfg):
    cfg = cfg or {}
    rec = cfg.get("disclaimer_acknowledgement")
    if isinstance(rec, dict) and rec.get("acknowledged_at"):
        cur = rec.get("disclaimer_version") == disclaimer_version()
        return (f"Disclaimer acknowledged: {rec['acknowledged_at']} by "
                f"{rec.get('user') or '(unknown user)'} on "
                f"{rec.get('host') or '(unknown host)'} (disclaimer version "
                f"{rec.get('disclaimer_version')}"
                + ("" if cur else f", superseded by {disclaimer_version()}")
                + f"; v{rec.get('app_version')} build {rec.get('build')})")
    if cfg.get("disclaimer_acknowledged"):
        return ("Disclaimer acknowledged: yes, before acknowledgements were "
                "recorded (no date, user or disclaimer version on record)")
    return ("Disclaimer acknowledged: not in this user profile (command-line "
            "runs display the disclaimer but do not ask for acknowledgement)")
