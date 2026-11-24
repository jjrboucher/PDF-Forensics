"""
Trying user-supplied passwords against encrypted PDFs.

Scope and intent: this opens password-protected PDFs using a list of
candidate passwords the examiner already has (from the custodian, the
case file, lawful process, and so on). It is NOT a password cracker: it
makes one attempt per supplied password, in a deliberate order, and
stops at the first that works. It does not generate, mutate or brute
force passwords.

Order of attempts, per file:
  1. the empty password  -- opens "permissions only" files (encrypted to
     set permissions, openable with no password) at no list cost;
  2. passwords already shown to work in THIS run, most-recently-successful
     first -- custodians reuse passwords, so the one that opened the last
     file usually opens the next;
  3. the remaining supplied passwords, in the order given in the file.

A password that opens a file is promoted to the front of the known-good
list for the files that follow. Nothing is written to disk and no PDF is
modified; a file is only opened for reading.
"""
import hashlib
import os

SOFT_LIMIT = 1000   # a warning is advised above this; not a hard cap


def read_password_list(path):
    """
    Read candidate passwords from a text file. Each line is a password,
    taken EXACTLY as written apart from the trailing line break: leading
    and trailing spaces and a leading '#' are part of the password, so
    there are no comment lines. Completely empty lines are skipped (the
    empty password is always tried first anyway). Duplicates are kept in
    order but de-duplicated so a password is not tried twice.

    The file is read as UTF-8 (with or without a byte-order mark), then
    UTF-16, then the Windows legacy encoding, so a list saved by any
    common editor is read correctly.

    Returns (passwords, info) where info has: count, entries, encoding,
    md5, path. Raises OSError if the file cannot be read.
    """
    with open(path, "rb") as fh:
        raw = fh.read()
    text, enc = _decode(raw)
    seen = set()
    out = []
    entries = 0
    for line in text.split("\n"):
        pw = line.rstrip("\r")
        if pw == "":
            continue
        entries += 1
        if pw not in seen:
            seen.add(pw)
            out.append(pw)
    return out, {"count": len(out), "entries": entries, "encoding": enc,
                 "md5": hashlib.md5(raw).hexdigest(),
                 "path": os.path.abspath(path)}


def _decode(raw):
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", "replace"), "UTF-8 with BOM"
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16"), "UTF-16"
    try:
        return raw.decode("utf-8"), "UTF-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace"), "Windows-1252"


class PasswordManager:
    """
    Holds the supplied list and the passwords found to work in this run,
    and yields candidates for a file in the agreed order. One instance is
    shared across a whole batch so success carries forward.
    """

    def __init__(self, passwords=None, list_info=None):
        self._supplied = list(passwords or [])
        self._known_good = []          # most-recently-successful first
        self.list_info = list_info or {}
        self.attempts = 0              # total password attempts this run
        self.files_opened_with_password = 0

    def candidates(self):
        """Yield (label, password) in attempt order, without repeats.
        label identifies where the password came from, for the log."""
        yield ("empty", "")
        seen = {""}
        for pw in self._known_good:
            if pw not in seen:
                seen.add(pw)
                yield ("known-good", pw)
        for i, pw in enumerate(self._supplied, 1):
            if pw not in seen:
                seen.add(pw)
                yield (f"list line {self._line_of(pw)}", pw)

    def record_success(self, password):
        """Promote a working password to the front of the known-good list."""
        if password == "":
            return
        if password in self._known_good:
            self._known_good.remove(password)
        self._known_good.insert(0, password)

    def line_of(self, password):
        return self._line_of(password)

    def _line_of(self, password):
        try:
            return self._supplied.index(password) + 1
        except ValueError:
            return "?"

    @property
    def supplied_count(self):
        return len(self._supplied)


def _src(pdf):
    """A path, or the file's bytes (e.g. a prior version held in memory).
    Bytes get a fresh stream for every open, so each attempt reads from
    the start."""
    if isinstance(pdf, (bytes, bytearray, memoryview)):
        import io
        return io.BytesIO(bytes(pdf))
    return pdf


def try_open(pdf_path, manager, open_fn=None):
    """
    Find a password that opens an encrypted PDF.

    open_fn(path, password) -> True if the password opens the file, False
    if it is rejected. Defaults to a pikepdf-based check that opens the
    file read-only and makes no change. Any attempt that raises other than
    a password rejection is treated as "not this password" and the next is
    tried, so a single malformed attempt never aborts the file.

    Returns a dict:
      encrypted   : whether the file is encrypted at all
      opened      : whether a password (incl. empty) opened it
      password    : the password that worked (""=empty), or None
      label       : where that password came from (for the log)
      attempts    : attempts made on THIS file
    """
    if open_fn is None:
        open_fn = _pikepdf_opens

    enc = is_encrypted(pdf_path)
    if not enc:
        # Not encrypted: openable with the empty password, but report it
        # as not encrypted rather than "opened with empty password".
        return {"encrypted": False, "opened": True, "password": "",
                "label": "not encrypted", "attempts": 0}

    attempts = 0
    unreadable = None
    for label, pw in manager.candidates():
        attempts += 1
        manager.attempts += 1
        try:
            if open_fn(pdf_path, pw):
                manager.record_success(pw)
                if pw != "":
                    manager.files_opened_with_password += 1
                return {"encrypted": True, "opened": True, "password": pw,
                        "label": label, "attempts": attempts}
        except Exception as e:
            unreadable = e
            continue
    # Build 2026-11-23: pikepdf could not read the file at all (not a
    # wrong password). Four permissions-only files in a 12,745-file case
    # were recorded as "password required" and not analysed this way.
    # MuPDF, which repairs damaged files, decides which password opens it;
    # the analysis then reads MuPDF's repaired copy.
    if unreadable is not None and open_fn is _pikepdf_opens:
        doc = _mupdf_doc(pdf_path)
        if doc is not None:
            try:
                for label, pw in ([("empty password", "")]
                                  if not doc.needs_pass else
                                  list(manager.candidates())):
                    if doc.needs_pass:
                        attempts += 1
                        manager.attempts += 1
                        if not doc.authenticate(pw):
                            continue
                    manager.record_success(pw)
                    if pw != "":
                        manager.files_opened_with_password += 1
                    return {"encrypted": True, "opened": True,
                            "password": pw,
                            "label": f"{label} (opened by MuPDF; pikepdf "
                                     f"cannot read the file)",
                            "attempts": attempts, "unreadable": True}
            except Exception:
                pass
            finally:
                try:
                    doc.close()
                except Exception:
                    pass
    return {"encrypted": True, "opened": False, "password": None,
            "label": None, "attempts": attempts}


def _read_bytes(pdf):
    if isinstance(pdf, (bytes, bytearray, memoryview)):
        return bytes(pdf)
    with open(pdf, "rb") as fh:
        return fh.read()


def _mupdf_doc(pdf):
    """The file opened by MuPDF (path or bytes), or None."""
    try:
        import pymupdf
        try:
            from pdf_forensics import _mupdf as _mu
            _mu.silence()
        except Exception:
            pass
        if isinstance(pdf, (bytes, bytearray, memoryview)):
            return pymupdf.open(stream=bytes(pdf), filetype="pdf")
        return pymupdf.open(pdf)
    except Exception:
        return None


def is_encrypted(pdf_path):
    """True if the file declares encryption (an /Encrypt dictionary).

    Build 2026-11-23: the same answer for a path and for the file's bytes.
    When pikepdf cannot read the file at all, MuPDF decides (it asks for
    a password, or reports an encryption scheme); without MuPDF, the
    trailer's /Encrypt entry is looked for. Before, a path fell back to a
    raw search of the file and bytes fell back to nothing, so triage said
    "not encrypted" and analysis said "encrypted" for the same file."""
    try:
        import pikepdf
        try:
            with pikepdf.open(_src(pdf_path)) as pdf:
                # Opens with no password, but may still be encrypted:
                # a "permissions only" file has an /Encrypt dictionary and
                # an empty user password. is_encrypted is True for those.
                return bool(pdf.is_encrypted)
        except pikepdf.PasswordError:
            return True
    except Exception:
        pass
    doc = _mupdf_doc(pdf_path)
    if doc is not None:
        try:
            if doc.needs_pass:
                return True
            return bool((doc.metadata or {}).get("encryption"))
        except Exception:
            pass
        finally:
            try:
                doc.close()
            except Exception:
                pass
    try:
        return _encrypt_dict_text(_read_bytes(pdf_path)) is not None
    except Exception:
        return False


def _encrypt_dict_text(data):
    """The text of the file's last /Encrypt dictionary (from the trailer
    or cross-reference stream that names it), or None. The encryption
    dictionary is never itself encrypted or in an object stream, so it
    can be read without the password."""
    import re
    refs = list(re.finditer(rb"/Encrypt\s*(?:(\d+)\s+(\d+)\s+R|<<)",
                            data))
    if not refs:
        return None
    m = refs[-1]
    if m.group(1) is None:                      # dictionary written in place
        start = m.end() - 2
        depth, i = 0, start
        while i < len(data) - 1:
            two = data[i:i + 2]
            if two == b"<<":
                depth += 1
                i += 2
                continue
            if two == b">>":
                depth -= 1
                i += 2
                if depth == 0:
                    return data[start:i].decode("latin-1")
                continue
            i += 1
        return None
    num, gen = m.group(1).decode(), m.group(2).decode()
    objs = list(re.finditer(rb"(?<!\d)" + num.encode() + rb"\s+"
                            + gen.encode() + rb"\s+obj\b", data))
    if not objs:
        return None
    o = objs[-1]
    end = data.find(b"endobj", o.end())
    return data[o.end():end if end != -1 else o.end() + 4096].decode(
        "latin-1")


def scheme_from_bytes(data):
    """Encryption scheme read from the /Encrypt dictionary itself, without
    the password: as encryption_scheme describes it, or ''."""
    import re
    txt = _encrypt_dict_text(data)
    if not txt:
        return ""

    def num(key):
        m = re.search(r"/" + key + r"\s+(\d+)", txt)
        return int(m.group(1)) if m else None
    v, r, length = num("V"), num("R"), num("Length")
    cfm = re.search(r"/CFM\s*/(\w+)", txt)
    cfm = cfm.group(1) if cfm else ""
    filt = re.search(r"/Filter\s*/(\w+)", txt)
    if filt and filt.group(1) != "Standard":
        return f"{filt.group(1)} security handler (V{v} R{r})"
    if v == 5 or r in (5, 6) or cfm == "AESV3":
        algo = "AES-256"
    elif v == 4 or r == 4:
        algo = "AES-128" if cfm in ("AESV2", "") else f"RC4-128 ({cfm})"
    elif v in (1, 2) or r in (2, 3):
        algo = f"RC4-{length or 40}"
    else:
        algo = "unknown"
    return f"{algo} (V{v} R{r})" if v is not None else algo


def encryption_scheme(pdf_path, password=None):
    """Human-readable encryption scheme from the /Encrypt dictionary,
    readable without the password (the dictionary is not itself
    encrypted). Returns '' when it cannot be determined."""
    try:
        import pikepdf
        kw = {} if password is None else {"password": password}
        with pikepdf.open(_src(pdf_path), **kw) as pdf:
            enc = pdf.encryption
            if enc is None:
                return ""
            v, r = getattr(enc, "V", None), getattr(enc, "R", None)
            bits = getattr(enc, "bits", None)
            # Standard security handler scheme by /V and /R:
            #   V1/V2, R2/R3 -> RC4 (40 or 128-bit)
            #   V4, R4       -> AES-128 (AESV2 crypt filter)
            #   V5, R5/R6    -> AES-256 (AESV3 crypt filter)
            if v == 5 or r in (5, 6):
                algo = "AES-256"
            elif v == 4 or r == 4:
                algo = "AES-128"
            elif v in (1, 2) or r in (2, 3):
                algo = f"RC4-{bits or 40}"
            else:
                algo = "unknown"
            return (f"{algo} (V{v} R{r})" if v is not None else algo)
    except Exception:
        # A locked file (or one pikepdf cannot read): read the scheme from
        # the /Encrypt dictionary directly (build 2026-11-23; it was blank).
        try:
            return scheme_from_bytes(_read_bytes(pdf_path))
        except Exception:
            return ""


def _pikepdf_opens(pdf_path, password):
    import pikepdf
    try:
        with pikepdf.open(_src(pdf_path), password=password):
            return True
    except pikepdf.PasswordError:
        return False


def probe_file_password(pdf_path, manager):
    """
    The detection half of resolve_file_password: detects encryption and
    finds a password that opens the file, without writing to the database
    or the log. Used where those must happen later and in order (parallel
    analysis; see analysis/parallel.py). Never raises.

    Returns {"result": try_open's dict or None, "scheme": str,
             "supplied_count": int}; result is None for a file that is not
    encrypted (or could not be examined).
    """
    mgr = manager if manager is not None else PasswordManager()
    try:
        res = try_open(pdf_path, mgr)
    except Exception:
        return {"result": None, "scheme": "", "supplied_count":
                mgr.supplied_count}
    if not res["encrypted"]:
        return {"result": None, "scheme": "", "supplied_count":
                mgr.supplied_count}
    scheme = encryption_scheme(
        pdf_path, res["password"] if res["opened"] else None)
    return {"result": res, "scheme": scheme,
            "supplied_count": mgr.supplied_count}


def record_file_password(conn, pdf_path, probe, session=None, quiet=False,
                         record_unopened_submission=True, is_version=False):
    """
    The recording half of resolve_file_password: records the outcome of
    probe_file_password in the encryption table, logs it, and for a file
    that could not be opened records an 'encrypted_unopened' submission.
    Returns the same dict as resolve_file_password. Never raises.
    """
    from pdf_forensics.database import record_encryption, record_submission
    res = probe.get("result")
    if not res:
        return {"encrypted": False, "opened": True, "password": None,
                "skip": False, "scheme": ""}
    scheme = probe.get("scheme", "")
    name = os.path.basename(pdf_path)

    if not res["opened"]:
        # Distinguish "a list was tried and nothing worked" from "no list
        # was supplied, so the file was not attempted against a list".
        supplied = probe.get("supplied_count", 0)
        no_list = supplied == 0
        res["password_source"] = ("no password list supplied" if no_list
                                  else f"list exhausted "
                                       f"({supplied} supplied)")
        record_encryption(conn, pdf_path, res, session=session,
                          scheme=scheme, source=res["password_source"])
        if no_list:
            msg = (f"Encrypted, not opened: {name} "
                   f"({scheme or 'scheme unknown'}); password required and "
                   f"no password list was supplied")
        else:
            msg = (f"Encrypted, not opened: {name} "
                   f"({scheme or 'scheme unknown'}); no supplied password "
                   f"worked ({res['attempts']} tried)")
        if not quiet:
            print("  " + msg)
        if session:
            session.log(msg, "warning")
        if record_unopened_submission:
            record_submission(conn, pdf_path, "encrypted_unopened",
                              session=session, reason=scheme,
                              is_version=is_version)
        return {"encrypted": True, "opened": False, "password": None,
                "skip": True, "scheme": scheme}

    record_encryption(conn, pdf_path, res, session=session, scheme=scheme)
    if session:
        if res["password"] == "":
            session.log(f"Encrypted (permissions only), opened with no "
                        f"password: {name} ({scheme})")
        else:
            session.log(f"Encrypted, opened: {name} ({scheme}) with "
                        f"password \"{res['password']}\" ({res['label']})")
    return {"encrypted": True, "opened": True, "password": res["password"],
            "skip": False, "scheme": scheme}


def resolve_file_password(conn, pdf_path, manager, session=None,
                          quiet=False, record_unopened_submission=True,
                          is_version=False):
    """
    Shared encryption step for a single file, used by both the batch
    engine and the GUI's own analysis loop so the behaviour is identical.

    Detects encryption and tries to open the file (empty password first,
    then any passwords already found this run, then the supplied list).
    Records the outcome in the encryption table for the Encrypted Files
    report, logs it, and for a file that could not be opened records an
    'encrypted_unopened' submission (so it is accounted for) and returns
    skip=True. Runs even when no password list was supplied, so
    permissions-only files still open and genuinely locked files are
    still recorded, distinguished as 'no password list supplied'.

    manager may be None (equivalent to an empty list). Never raises.
    It is probe_file_password followed by record_file_password.

    Returns a dict:
      encrypted : the file declares encryption
      opened    : a password (incl. empty) opened it
      password  : the password to analyse the file with ('' = empty,
                  None if it could not be opened)
      skip      : True if the caller should not analyse this file
      scheme    : encryption scheme, or ''
    """
    probe = probe_file_password(pdf_path, manager)
    return record_file_password(
        conn, pdf_path, probe, session=session, quiet=quiet,
        record_unopened_submission=record_unopened_submission,
        is_version=is_version)
