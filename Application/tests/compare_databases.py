#!/usr/bin/env python3
"""
Compare two case databases made from the same files, table by table and row
by row, to confirm that two runs produced the same results: for example one
file at a time (Files processed at once: 1) against several at once (Auto).

Ignored, because they are expected to differ between runs:
  * run times: analyses.analyzed_at, submissions.submitted_at and
    session_ts, encryption.recorded_at and session_ts,
    schema_version.created_at
  * the case folder part of file paths (with --paths name, the default,
    paths are compared by file name; --paths full compares them in full)

Everything else is compared, including ids, so rows must also be in the same
order. Image bytes are compared by hash.

Usage:
  python tests/compare_databases.py FIRST.db SECOND.db [--paths name|full]
                                    [--show N]

Exit status 0 if the databases match, 1 if they differ. Prints no file
contents, only table names, row ids and column names (and, for a
difference, the two values, shortened).
"""
import argparse
import hashlib
import os
import sqlite3
import sys

IGNORED = {
    "analyses": {"analyzed_at"},
    "submissions": {"submitted_at", "session_ts"},
    "encryption": {"recorded_at", "session_ts"},
    "schema_version": {"created_at"},
}
PATH_COLUMNS = {"pdf_path"}
SKIP_TABLES = {"sqlite_sequence", "sqlite_stat1", "sqlite_stat4"}


def _tables(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        if r[0] not in SKIP_TABLES]


def _columns(conn, table):
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def _norm(col, value, paths):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "md5:" + hashlib.md5(bytes(value)).hexdigest()
    if col in PATH_COLUMNS and paths == "name" and isinstance(value, str):
        return os.path.basename(value.replace("\\", "/"))
    return value


def _short(v, n=80):
    s = repr(v)
    return s if len(s) <= n else s[:n - 3] + "..."


def compare(db_a, db_b, paths="name", show=5, out=print):
    a = sqlite3.connect(f"file:{db_a}?mode=ro", uri=True)
    b = sqlite3.connect(f"file:{db_b}?mode=ro", uri=True)
    same = True
    try:
        ta, tb = _tables(a), _tables(b)
        for t in sorted(set(ta) ^ set(tb)):
            out(f"Table {t}: only in {'first' if t in ta else 'second'}")
            same = False
        for t in [x for x in ta if x in tb]:
            ca, cb = _columns(a, t), _columns(b, t)
            if ca != cb:
                out(f"Table {t}: columns differ ({ca} vs {cb})")
                same = False
                continue
            cols = [c for c in ca if c not in IGNORED.get(t, set())]
            sel = ", ".join(f'"{c}"' for c in cols)
            order = "id" if "id" in cols else "rowid"
            ra = a.execute(f'SELECT {sel} FROM "{t}" ORDER BY {order}')
            rb = b.execute(f'SELECT {sel} FROM "{t}" ORDER BY {order}')
            n_a = n_b = diffs = 0
            while True:
                x, y = ra.fetchone(), rb.fetchone()
                if x is None and y is None:
                    break
                n_a += x is not None
                n_b += y is not None
                if x is None or y is None:
                    continue
                for c, v1, v2 in zip(cols, x, y):
                    v1, v2 = _norm(c, v1, paths), _norm(c, v2, paths)
                    if v1 != v2:
                        diffs += 1
                        if diffs <= show:
                            rid = x[cols.index("id")] if "id" in cols else "?"
                            out(f"Table {t}, id {rid}, column {c}: "
                                f"{_short(v1)} != {_short(v2)}")
                        break
            if n_a != n_b:
                out(f"Table {t}: {n_a} row(s) in the first, {n_b} in the "
                    f"second")
                same = False
            if diffs:
                out(f"Table {t}: {diffs} row(s) differ")
                same = False
            elif n_a == n_b:
                out(f"Table {t}: {n_a} row(s), identical")
    finally:
        a.close()
        b.close()
    out("RESULT: the databases match" if same
        else "RESULT: the databases differ")
    return same


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("first")
    ap.add_argument("second")
    ap.add_argument("--paths", choices=("name", "full"), default="name")
    ap.add_argument("--show", type=int, default=5,
                    help="differences shown per table (default 5)")
    args = ap.parse_args(argv)
    return 0 if compare(args.first, args.second, args.paths,
                        args.show) else 1


if __name__ == "__main__":
    sys.exit(main())
