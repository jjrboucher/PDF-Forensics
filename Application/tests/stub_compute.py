"""A stand-in for the PDF analysis, used to test analysis/parallel.py
without PyMuPDF. Files are small text files whose content drives the
behaviour:
  FAIL          the analysis raises an error
  CRASH         the worker process dies (os._exit), unless a marker file
                says it already crashed once and CRASH_ONCE is in the content
  VERSIONS n    n prior versions are 'extracted' (files written to
                versions_out/<stem>_versions/<stem>_version<i>.pdf); version
                i's content is the parent's first line + "-v<i>"
  IMAGES n      n fake images are written to the staging folder
  SLEEP s       the analysis takes s seconds
  HANG          the analysis never finishes and reports no progress
  PROGRESS n s  n pages, one every s seconds, each reported as progress
  UNPICKLABLE   the result cannot be pickled (except in the main process)
"""
import os


def _payload(spec, path, version_number, extract_dir):
    return {"pdf_path": path, "db_path": spec["db_path"], "total_pages": 1,
            "page_data": {}, "pdf_metadata": [("info", "stub", "1")],
            "pdf_versions": [(1, 10)], "store_images": False, "comments": [],
            "doc_risk": 0, "source_analysis_id": None,
            "version_number": version_number, "timeline_rows": None,
            "total_findings": 0, "total_extracted": 0,
            "extract_dir": extract_dir}


def _one(spec, path, stem, vnum, rs_logs):
    from pdf_forensics.analysis.parallel import _emit
    _emit("start", (spec["uid"], vnum or 0), os.path.basename(path), vnum,
          os.getpid())
    entry = _one_body(spec, path, stem, vnum)
    _emit("finished", (spec["uid"], vnum or 0))
    return entry


def _one_body(spec, path, stem, vnum):
    with open(path, "rb") as f:
        data = f.read()
    text = data.decode("utf-8", "replace")
    uid = spec["uid"]
    stage = (os.path.join(spec["stage_root"], f"{uid}_{vnum or 0}")
             if spec.get("out_dir") else None)
    final = os.path.join(spec["out_dir"], stem) if spec.get("out_dir") else None
    entry = {"path": path, "version_number": vnum, "stage_dir": stage,
             "extract_dir": final, "logs": [(0.0, "info", f"stub {stem}")],
             "perf": {"md5": "", "stages": {"open": 0.01}, "counts": {},
                      "mem": 1, "total": 0.01}}
    if "CRASH" in text:
        marker = path + ".crashed"
        if not ("CRASH_ONCE" in text and os.path.exists(marker)):
            open(marker, "w").close()
            os._exit(3)
    if "HANG" in text:
        import time
        time.sleep(3600)
    for line in text.splitlines():
        if line.startswith("PROGRESS"):
            import time
            from pdf_forensics.analysis.parallel import _emit
            _n, _s = int(line.split()[1]), float(line.split()[2])
            for _p in range(1, _n + 1):
                time.sleep(_s)
                _emit("page", (spec["uid"], vnum or 0), _p, _n)
        if line.startswith("SLEEP"):
            import time
            time.sleep(float(line.split()[1]))
    if "FAIL" in text:
        entry.update(status="failed", error="stub failure",
                     error_label="RuntimeError at stub")
        return entry
    n_img = 0
    for line in text.splitlines():
        if line.startswith("IMAGES"):
            n_img = int(line.split()[1])
    if stage and n_img:
        os.makedirs(stage, exist_ok=True)
        for i in range(n_img):
            with open(os.path.join(stage, f"img{i}.png"), "wb") as f:
                f.write(b"x")
    p = _payload(spec, path, vnum, final)
    p["total_extracted"] = n_img
    if "UNPICKLABLE" in text and os.environ.get("PDF_FORENSICS_TEST_MAIN") \
            != str(os.getpid()):
        p["comments"] = [lambda: None]      # cannot be pickled
    entry.update(status="ok", payload=p)
    return entry


def compute(spec):
    parent = _one(spec, spec["path"], spec["stem"], None, [])
    entries = [parent]
    written = []
    if parent["status"] == "ok" and spec.get("extract_versions"):
        with open(spec["path"], encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        n = 0
        for line in text.splitlines():
            if line.startswith("VERSIONS"):
                n = int(line.split()[1])
        first = text.splitlines()[0]
        vdir = os.path.join(spec["versions_out"], spec["stem"] + "_versions")
        if n:
            os.makedirs(vdir, exist_ok=True)
        for i in range(1, n + 1):
            vp = os.path.join(vdir, f"{spec['stem']}_version{i}.pdf")
            existed = os.path.exists(vp)
            with open(vp, "w", encoding="utf-8") as f:
                f.write(f"{first}-v{i}\n")
            written.append((vp, existed))
            e = _one(spec, vp, os.path.splitext(os.path.basename(vp))[0],
                     i, [])
            e["probe"] = {"result": None, "scheme": "", "supplied_count": 0}
            entries.append(e)
        parent["versions"] = n
        parent["post_logs"] = [(0.0, "info", f"extracted {n}")]
    return {"uid": spec["uid"], "entries": entries, "written": written}
