"""A long document's Visual Overlay report made in parts of consecutive
pages (build 2026-11-19e) is the same as when made whole: the same HTML
file (apart from its generation time), overlay numbers, log entries in the
same order, counts and MuPDF messages; and the planning splits only what
it should.

PyMuPDF is not needed: rendering is replaced by a stand-in that draws each
overlay as a box on a synthetic page, so the report's own code (page loop,
numbering, layers, measurements, self-check, joining and writing) runs as
it does for real documents."""
import io
import json
import os
import re
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PIL import Image, ImageDraw  # noqa: E402

from pdf_forensics.database import init_db  # noqa: E402
from pdf_forensics.reports import visual as V  # noqa: E402

PAGES = 7
W, H = 200, 260


def _boxes_on(page_index):
    """The overlays of a page: white boxes, a text-over-text, and none on
    page 4 (pages without findings are skipped by the report)."""
    if page_index == 3:
        return []
    n = 1 + page_index % 3
    out = [("white_box", (10 + 30 * k, 20 + 15 * page_index,
                          35 + 30 * k, 32 + 15 * page_index))
           for k in range(n)]
    out.append(("text_over_text", (120, 200, 180, 215)))
    return out


def _draw(page_index, present):
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    for y in range(10, H - 10, 9):                     # page text
        d.line([(8, y), (W - 8 - (y * 7 + page_index * 13) % 60, y)],
               fill=(30, 30, 30))
    for bbox in present:
        d.rectangle(bbox, fill="white")
        d.text((bbox[0] + 1, bbox[1]), "x", fill=(0, 0, 120))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def _all_boxes(page_index):
    return [tuple(float(v) for v in b) for _, b in _boxes_on(page_index)]


class _Rect:
    width, height = float(W), float(H)


class _Page:
    def __init__(self, index):
        self.index = index
        self.rect = _Rect()

    def get_pixmap(self, dpi=72, alpha=False):        # the quick drawing
        return _draw(self.index, _all_boxes(self.index))


class _Doc:
    def __init__(self, path):
        self.path = path

    def __len__(self):
        return PAGES

    def __getitem__(self, i):
        return _Page(i)

    def close(self):
        pass


def _fake_pymupdf():
    import importlib.machinery
    m = types.ModuleType("pymupdf")
    m.__spec__ = importlib.machinery.ModuleSpec("pymupdf", None)
    m.open = _Doc
    m.TOOLS = types.SimpleNamespace(
        mupdf_display_errors=lambda *a, **k: None,
        mupdf_warnings=lambda reset=False: "")
    return m


def _variant_bytes(page_index, present):
    return json.dumps({"p": page_index,
                       "present": [list(b) for b in present]}).encode()


def _patches():
    """Stand-ins for the functions that use PyMuPDF and pikepdf."""
    def render_page(page, dpi):
        return _draw(page.index, _all_boxes(page.index)), 1.0

    def render_revealed(pdf_bytes, page_index, dpi):
        d = json.loads(pdf_bytes)
        return _draw(d["p"], [tuple(b) for b in d["present"]])

    def single_page(fpath, page_index):
        return _variant_bytes(page_index, _all_boxes(page_index))

    def build_variant(fpath, page_index, remove, page_height, keep_ops=None,
                      single_page=False):
        gone = {tuple(float(v) for v in f["bbox"]) for f in remove}
        present = [b for b in _all_boxes(page_index) if b not in gone]
        return (_variant_bytes(page_index, present),
                {"recovered": len(gone), "skipped": 0})

    return {"_render_page_png": render_page,
            "_render_revealed_page_png": render_revealed,
            "_single_page": single_page,
            "_build_variant": build_variant,
            "_white_box": lambda *a, **k: None}


def _make_case(tmp, extra=0):
    """The long document, then `extra` one-page documents (the same page
    as the long document's first)."""
    db, aid = _make_long(tmp)
    if extra:
        conn = init_db(db)
        ft = conn.execute("SELECT id FROM finding_types WHERE code="
                          "'TEXT_OVERLAY'").fetchone()[0]
        for k in range(extra):
            src = os.path.join(tmp, f"short{k}.pdf")
            with open(src, "wb") as fh:
                fh.write(b"%PDF-1.7\n% synthetic stand-in\n")
            a2 = conn.execute(
                "INSERT INTO analyses (pdf_filename, pdf_path, "
                "pdf_size_bytes, pdf_md5, total_pages, analyzed_at) "
                "VALUES (?,?,?,?,?,?)",
                (f"short{k}.pdf", src, 1, f"{k:032x}", 1,
                 "2026-01-01")).lastrowid
            pid = conn.execute("INSERT INTO pages (analysis_id, "
                               "page_number) VALUES (?,1)",
                               (a2,)).lastrowid
            kind, bb = _boxes_on(0)[0]
            conn.execute(
                "INSERT INTO findings (page_id, finding_type_id, detail, "
                "bbox_x0, bbox_y0, bbox_x1, bbox_y1, overlay_kind) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (pid, ft, "short", *bb, kind))
        conn.commit()
        conn.close()
    return db, aid


def _make_long(tmp):
    src = os.path.join(tmp, "long.pdf")
    with open(src, "wb") as fh:
        fh.write(b"%PDF-1.7\n% synthetic stand-in\n")
    db = os.path.join(tmp, "case.db")
    conn = init_db(db)
    ft = conn.execute("SELECT id FROM finding_types WHERE code="
                      "'TEXT_OVERLAY'").fetchone()[0]
    aid = conn.execute(
        "INSERT INTO analyses (pdf_filename, pdf_path, pdf_size_bytes, "
        "pdf_md5, total_pages, analyzed_at) VALUES (?,?,?,?,?,?)",
        ("long.pdf", src, 1, "ab" * 16, PAGES, "2026-01-01")).lastrowid
    for p in range(PAGES):
        pid = conn.execute("INSERT INTO pages (analysis_id, page_number) "
                           "VALUES (?,?)", (aid, p + 1)).lastrowid
        for kind, bb in _boxes_on(p):
            conn.execute(
                "INSERT INTO findings (page_id, finding_type_id, detail, "
                "bbox_x0, bbox_y0, bbox_x1, bbox_y1, overlay_kind) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (pid, ft, f"{kind} on page {p + 1}", *bb, kind))
    conn.commit()
    conn.close()
    return db, aid


class _Log:
    """Records log entries and outputs as a session would."""
    case_number = "T-9"

    def __init__(self):
        self.entries = []

    def log(self, msg, level="info"):
        self.entries.append((level, msg))

    def register_output(self, kind, path):
        self.entries.append(("output", kind, os.path.basename(path)))

    def replay(self, records):
        for t, level, msg in records:          # as Session.replay
            if level == "__output__":
                self.register_output(*msg)
            else:
                self.entries.append((level, msg))


def _normalise(html):
    return re.sub(r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d[^<\"]*", "", html)


class SplitTest(unittest.TestCase):
    def setUp(self):
        self._saved = {k: getattr(V, k) for k in _patches()}
        for k, f in _patches().items():
            setattr(V, k, f)
        self._mod = sys.modules.get("pymupdf")
        sys.modules["pymupdf"] = _fake_pymupdf()
        self._fp = V._reveal.page_fingerprint
        V._reveal.page_fingerprint = lambda *a, **k: None

    def tearDown(self):
        for k, f in self._saved.items():
            setattr(V, k, f)
        if self._mod is None:
            sys.modules.pop("pymupdf", None)
        else:
            sys.modules["pymupdf"] = self._mod
        V._reveal.page_fingerprint = self._fp
        V.clear_render_cache()

    def _whole(self, db, aid, out):
        log = _Log()
        it = {"i": 1, "aid": aid, "pdf_filename": "long.pdf", "path": out}
        V.clear_render_cache()
        res = V._visual_one(db, it, log)
        return res, log.entries

    def _in_parts(self, db, aid, out, chunks):
        from pdf_forensics.analysis.parallel import RecordingSession
        it = {"i": 1, "aid": aid, "pdf_filename": "long.pdf", "path": out}
        outs = []
        for n, pages in enumerate(chunks):
            V.clear_render_cache()          # as in another process
            rs = RecordingSession({"case_number": "T-9"})
            r = V._visual_part(db, dict(it, part=n, parts=len(chunks),
                                        part_pages=pages), rs)
            r["logs"] = rs.take()
            outs.append(r)
        outs.reverse()                      # parts may arrive in any order
        res = V._join_parts(db, it, outs, _Log())
        log = _Log()
        log.replay(res["logs"])
        return res, log.entries

    def test_parts_give_the_same_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, aid = _make_case(tmp)
            whole_path = os.path.join(tmp, "whole.html")
            res_w, log_w = self._whole(db, aid, whole_path)
            self.assertNotIn("error", res_w)
            self.assertGreater(res_w["n"], 0)
            with open(whole_path, encoding="utf-8") as fh:
                whole = _normalise(fh.read())
            for chunks in ([[1, 2], [3, 5], [6, 7]], [[1], [2, 3, 5, 6, 7]],
                           [[1, 2, 3, 5, 6, 7]]):
                with self.subTest(chunks=chunks):
                    path = os.path.join(tmp, "parts.html")
                    res_p, log_p = self._in_parts(db, aid, path, chunks)
                    self.assertNotIn("error", res_p)
                    with open(path, encoding="utf-8") as fh:
                        self.assertEqual(_normalise(fh.read()), whole)
                    self.assertEqual(res_p["n"], res_w["n"])
                    for k in ("nothing", "measured", "fast", "fallback"):
                        self.assertEqual(res_p["stats"][k],
                                         res_w["stats"][k], k)
                    self.assertEqual(res_p["mupdf"], res_w["mupdf"])
                    self.assertEqual(res_p["parts"], len(chunks))
                    # same entries, same order; the output names differ
                    norm = lambda e: tuple(            # noqa: E731
                        x.replace("parts.html", "whole.html")
                        if isinstance(x, str) else x for x in e)
                    self.assertEqual([norm(e) for e in log_p], log_w)
            # overlay numbers run on across pages, as in the whole report
            nums = [int(n) for n in re.findall(r'data-num="(\d+)"', whole)]
            if nums:
                self.assertEqual(sorted(set(nums)), list(range(1, max(nums)
                                                               + 1)))

    def test_failed_part_fails_the_document(self):
        it = {"i": 4, "aid": 1, "pdf_filename": "x.pdf", "path": "/x.html"}
        res = V._join_parts(None, it, [
            {"i": 4, "part": 1, "error": "boom", "t_start": 1.0,
             "logs": [("info", "b")]},
            {"i": 4, "part": 0, "data": None, "t_start": 0.5,
             "logs": [("info", "a")]}], None)
        self.assertEqual(res["error"], "boom")
        self.assertEqual(res["n"], 0)
        self.assertEqual(res["logs"], [("info", "a"), ("info", "b")])


class _InlineExecutor:
    """Stands in for the process pool: runs each task here, at once, so
    the rendering stand-ins apply (they would not exist in a new
    process). Everything else in the parallel path runs as it does."""

    def __init__(self, max_workers=None, mp_context=None, initializer=None,
                 initargs=()):
        if initializer:
            initializer(*initargs)

    def map(self, fn, iterable):
        return [fn(x) for x in iterable]

    def shutdown(self, wait=True, cancel_futures=False):
        pass

    def submit(self, fn, *a):
        from concurrent.futures import Future
        f = Future()
        try:
            f.set_result(fn(*a))
        except Exception as e:
            f.set_exception(e)
        return f

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SplitRunTest(SplitTest):
    def test_one_at_a_time_and_split_give_the_same_results(self):
        import concurrent.futures as cf
        from pdf_forensics import session as _session
        from pdf_forensics.session import Session
        saved = cf.ProcessPoolExecutor
        saved_min = V.SPLIT_MIN_OVERLAYS
        out = {}
        try:
            cf.ProcessPoolExecutor = _InlineExecutor
            V.SPLIT_MIN_OVERLAYS = 1        # the test document is small
            with tempfile.TemporaryDirectory() as tmp:
                _session.CONFIG_FILE = os.path.join(tmp, "config.json")
                db, aid = _make_case(tmp, extra=6)
                for workers in (1, 4):
                    case = os.path.join(tmp, f"w{workers}")
                    s = Session("T-9")
                    s.set_db_dir(case)
                    idx = os.path.join(case, "visual.html")
                    seen = []
                    V.generate_visual_reports(db, idx, session=s,
                                              workers=workers,
                                              status=seen.append)
                    s.perf.close()
                    for h in list(s.logger.handlers):
                        h.close()
                    with open(s.log_path, encoding="utf-8") as fh:
                        log = [re.sub(r"^\S+ \S+ ", "", ln)
                               for ln in fh.read().splitlines()
                               if "isual" in ln
                               and "at a time" not in ln]
                    log = [ln.replace(case, "CASE") for ln in log]
                    with open(s.perf.path, encoding="utf-8") as fh:
                        perf = fh.read()
                    ev = [ln.split("\t") for ln in perf.splitlines()
                          if ln.startswith("EVENT\tvisual_overlay_doc")]
                    reports = {}
                    folder = os.path.join(case, "visual_files")
                    for name in sorted(os.listdir(folder)):
                        with open(os.path.join(folder, name),
                                  encoding="utf-8") as fh:
                            reports[name] = _normalise(fh.read())
                    with open(idx, encoding="utf-8") as fh:
                        index = _normalise(fh.read())
                    out[workers] = (log, [e[2] for e in ev], reports,
                                    index, perf, ev, seen)
        finally:
            cf.ProcessPoolExecutor = saved
            V.SPLIT_MIN_OVERLAYS = saved_min
        one, four = out[1], out[4]
        self.assertEqual(one[0], four[0])           # log entries, in order
        self.assertEqual(one[1], four[1])           # documents, in order
        self.assertEqual(one[2], four[2])           # every report
        self.assertEqual(one[3], four[3])           # the index
        self.assertEqual(len(one[2]), 7)
        self.assertIn("split by pages into", four[4])
        self.assertIn("work estimated from the drawings needed", four[4])
        long_ev = [e for e in four[5] if e[2] == "ab" * 16][0]
        self.assertTrue(any(f.startswith("est=") for f in long_ev))
        self.assertTrue(any(f.startswith("parts=") for f in long_ev))
        self.assertEqual(four[6][-1]["done"], 7)
        self.assertEqual(four[6][-1]["running"], {})


class PlanSplitTest(unittest.TestCase):
    def _it(self, i, page_over, src_ok=True):
        return {"i": i, "n_over": sum(page_over.values()),
                "page_over": page_over, "src_ok": src_ok,
                "pdf_filename": f"d{i}.pdf"}

    def test_long_document_split_into_balanced_runs(self):
        big = self._it(1, {p: 10 for p in range(1, 31)})          # 300
        small = [self._it(i, {1: 10}) for i in range(2, 12)]       # 10 each
        groups = [[big]] + [[s] for s in small]
        tasks = V._plan_visual_tasks(groups, workers=4)   # share = 100
        parts = [t[0] for t in tasks if "part_pages" in t[0]]
        # 300 / (half of 100) = 6 parts, but no more than the 4 processes
        self.assertEqual(len(parts), 4)
        self.assertEqual([p["part"] for p in parts], list(range(4)))
        pages = [pg for p in parts for pg in p["part_pages"]]
        self.assertEqual(pages, list(range(1, 31)))   # all, in order, once
        sizes = [p["n_over"] for p in parts]
        self.assertEqual(sum(sizes), 300)
        self.assertLessEqual(max(sizes) - min(sizes), 10)   # balanced
        self.assertTrue(all(p["parts"] == 4 for p in parts))
        tasks = V._plan_visual_tasks(groups, workers=12)  # share = 33
        parts = [t[0] for t in tasks if "part_pages" in t[0]]
        self.assertEqual(len(parts), 12)          # 300 / 16.7 = 18, cap 12
        # every document is still there exactly once
        whole = sorted({t[0]["i"] for t in tasks})
        self.assertEqual(whole, list(range(1, 12)))

    def test_not_split(self):
        big = self._it(1, {p: 10 for p in range(1, 31)})
        rest = [[self._it(i, {1: 10})] for i in range(2, 12)]
        for groups, workers in (([[big]] + rest, 1),      # one at a time
                                ([[dict(big, src_ok=False)]] + rest, 4),
                                ([[self._it(1, {1: 300})]] + rest, 4),
                                ([[self._it(1, {1: 20, 2: 15})]], 4)):
            tasks = V._plan_visual_tasks(groups, workers)
            self.assertFalse(any("part_pages" in it for t in tasks
                                 for it in t))

    def test_slow_pages_start_first_and_lineage_split(self):
        """This morning's case: two one-overlay pages that are very slow to
        draw, each with a prior version that reuses nothing, listed last.
        By overlays they are trivial; by measured drawing time they are
        the largest tasks, so the lineages are split and start first."""
        items, probes, meta = [], {}, {}
        for i in range(1, 21):                      # ordinary documents
            items.append(self._it(i, {1: 3, 2: 3}))
            probes[i] = {1: 0.02, 2: 0.02}
        for i, parent in ((21, None), (22, 21), (23, None), (24, 23)):
            items.append(self._it(i, {1: 1}))
            probes[i] = {1: 3.0}                    # slow to draw
            meta[i] = parent
        V._estimate_work(items, probes)
        self.assertGreater(items[-1]["work"], items[0]["work"] * 10)
        groups = []
        for it in items:
            if meta.get(it["i"]):
                next(g for g in groups if g[0]["i"] == meta[it["i"]]).append(
                    it)
            else:
                groups.append([it])
        tasks = V._plan_visual_tasks(groups, workers=8)
        first = [[x["i"] for x in t] for t in tasks[:4]]
        self.assertEqual(sorted(first), [[21], [22], [23], [24]])
        # without measurements, every page counts as ordinary
        V._estimate_work(items, {})
        self.assertAlmostEqual(items[-1]["work"], V.DRAW_S * 4)

    def test_heavy_lineage_split_by_pages_across_versions(self):
        """Build 2026-11-23: a heavy document and its versions are split
        by page range, each task holding those pages of every document
        (document first), so versions reuse its renders. Build 2026-11-20b
        sent each document to a different process; in a 12,745-file case a
        70-page document and its three versions were each drawn in full."""
        doc = [self._it(1, {p: 90 for p in range(1, 71)})]
        doc += [self._it(i, {p: 90 for p in range(1, 71)})
                for i in (2, 3, 4)]                     # its versions
        others = [[self._it(i, {1: 10, 2: 10})] for i in range(5, 300)]
        tasks = V._plan_visual_tasks([doc] + others, workers=18)
        lineage = [t for t in tasks if any(x["i"] in (1, 2, 3, 4)
                                           for x in t)]
        self.assertGreater(len(lineage), 1)
        for t in lineage:
            self.assertEqual([x["i"] for x in t], [1, 2, 3, 4])
            pages = {tuple(x["part_pages"]) for x in t}
            self.assertEqual(len(pages), 1)          # the same pages
        for i in (1, 2, 3, 4):
            parts = [x for t in lineage for x in t if x["i"] == i]
            self.assertEqual(sorted(x["part"] for x in parts),
                             list(range(len(parts))))
            self.assertTrue(all(x["parts"] == len(parts) for x in parts))
            self.assertEqual(sorted(p for x in parts for p in x["part_pages"]),
                             list(range(1, 71)))
        # A lineage within a share stays whole.
        small = [self._it(1, {1: 10, 2: 10}), self._it(2, {1: 10, 2: 10})]
        rest = [[self._it(i, {1: 50})] for i in range(3, 6)]
        tasks = V._plan_visual_tasks([small] + rest, workers=4)
        # share 47.5: the lineage's 40 is within it
        kept = [t for t in tasks if [x["i"] for x in t] == [1, 2]]
        self.assertEqual(len(kept), 1)
        self.assertFalse(any("part_pages" in x for x in kept[0]))

    def test_versions_that_share_nothing_still_spread(self):
        """Build 2026-11-23b: four 70-page versions whose pages all differ
        (no drawings reused) were kept in one process for 8,900 s because
        shared pages were counted once. All pages now count in full."""
        g = [self._it(i, {p: 40 for p in range(1, 71)}) for i in (1, 2, 3, 4)]
        # share about 3,600: the lineage's distinct pages (2,800) are
        # within it, all its pages (11,200) are not
        others = [[self._it(i, {1: 30, 2: 30})] for i in range(5, 900)]
        tasks = V._plan_visual_tasks([g] + others, workers=18)
        lineage = [t for t in tasks if any(x["i"] in (1, 2, 3, 4)
                                           for x in t)]
        self.assertGreaterEqual(len(lineage), 4)

    def test_many_overlays_on_quick_pages_still_split(self):
        """Build 2026-11-20 rated a 30-page document with 1,627 overlays
        on quick-to-draw pages as small (by quick drawing time alone), so
        it was not split and ran 773 s alone. Every overlay costs drawings
        whatever the page, so it is the largest task and is split."""
        items, probes = [], {}
        big = self._it(1, {p: 54 for p in range(1, 31)})          # 1,620
        items.append(big)
        probes[1] = {p: 0.004 for p in range(1, 31)}
        for i in range(2, 120):
            items.append(self._it(i, {1: 3, 2: 2}))
            probes[i] = {1: 0.02, 2: 0.02}
        V._estimate_work(items, probes)
        self.assertAlmostEqual(big["work"], V.DRAW_S * (1620 + 90))
        tasks = V._plan_visual_tasks([[it] for it in items], workers=16)
        parts = [t[0] for t in tasks if t[0]["i"] == 1]
        self.assertGreater(len(parts), 1)
        self.assertTrue(all("part_pages" in p for p in parts))
        self.assertEqual(tasks[0][0]["i"], 1)          # a part starts first

    def test_unmeasured_pages_count_as_ordinary(self):
        items = [self._it(1, {1: 2}), self._it(2, {1: 2, 2: 1})]
        V._estimate_work(items, {1: {1: 0.5, ("area", 1): 93.5}, 2: None})
        self.assertAlmostEqual(items[0]["page_work"][1],
                               V.DRAW_S * 5 + V.HEAVY_FACTOR * 0.5 * 5)
        self.assertAlmostEqual(items[1]["page_work"][1], V.DRAW_S * 5)
        self.assertAlmostEqual(items[1]["page_work"][2], V.DRAW_S * 4)
        self.assertIsNone(items[1]["probe_s"])
        self.assertEqual(items[0]["max_area"], 93.5)
        self.assertAlmostEqual(items[0]["probe_s"], 0.5)

    def test_page_chunks(self):
        po = {1: 100, 2: 1, 3: 1, 4: 1, 5: 50, 6: 50}
        ch = V._page_chunks(po, 3)
        self.assertEqual([p for c in ch for p in c], [1, 2, 3, 4, 5, 6])
        self.assertEqual(ch[0], [1])                 # a heavy page alone
        self.assertEqual(len(ch), 3)
        self.assertEqual(V._page_chunks({1: 5, 2: 5}, 5), [[1], [2]])


if __name__ == "__main__":
    unittest.main()
