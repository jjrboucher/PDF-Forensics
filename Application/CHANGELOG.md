# PDF Forensics Suite — Changelog

**Current: version 1.3.0 — 2026-11-24 (build 2026-11-24c)** · schema revision 10. Version 1.0.0 (build 2026-10-20) is frozen. Later changes are released as incremental updates (1.0.1, 1.0.2, …); for each, update `__version__` and `BUILD_DATE` in `pdf_forensics/__init__.py` and add a dated entry below. Dated entries record when each change was made and are kept as historical record.

## Version 1.3.0 — (2026-11-24, build 2026-11-24c)

Parallel processing; fill colours read in their colour space for the
white-box checks; white boxes that hide nothing grouped in the Visual
Overlay report. No database schema change (revision 10).

### Build 2026-11-24c: screens
Build 2026-11-24b on the damaged-file case: every file as intended
(`2e3adcb2…` analysed from its repaired copy for the 99 pages both
readers have; its unpaired page was page 84 of 100, and that of
`0f3b49b8…` page 2 of 5, so pairing by position would have mismatched
every page after them); visual reports 1,070 s with 18 processes (the
lineage of `925bdc8e…` done in 276 s; the rest is the damaged
`774066d4…`); nothing printed to the console. Changes to the screens only:
- **PDF Forensics Analysis:** the controls scroll when the window is too
  short and the Run button stays visible below them (it was squeezed);
  the screen opens taller (990 px, still limited to the screen).
- **Graph Analysis:** opens taller (700 px) so the controls fit.
- **Status bar:** always visible at the bottom of the window; a screen
  taller than the window could push it out of sight. Its message is reset
  to "Ready" when moving to another screen ("Done. 5 analysed …" stayed
  on the graph screen).

### Build 2026-11-24b: final checks
Build 2026-11-24 on a case of the damaged files and on the 325-file case
(no failures; triage 58 s, analysis 147 s, visual reports 318 s with 18
processes and 4 documents in 41 parts; nothing printed to the console).
On the small case the visual reports for `925bdc8e…` and its three
versions took 1,220 s (5,749 s in build 2026-11-23), the versions reusing
11,000 drawings; the damaged files came out as intended but one.
- **Pages paired by object number when the readers disagree.**
  `2e3adcb2…` failed: MuPDF lists 100 pages and pikepdf 99 even in the
  repaired copy (MuPDF's page list includes an entry pikepdf rejects as
  not a page). Such a copy is now analysed for the pages both readers
  have. Whenever the two count different pages, each MuPDF page is now
  paired with the pikepdf page of the same object number (`page_pairs`)
  rather than by position, which could put one page's text beside
  another page's content when the extra page is not the last; pages only
  one reader lists are named in the structural warning and not examined.
  Pages keep MuPDF's numbering.
- **Visual reports use all processes on small cases.** The number of
  processes was capped at the number of documents, so a case of one large
  document and its three versions ran 4, not 18; it is now capped at the
  pieces of work (pages that can be drawn separately). The status line
  says when documents are drawn in parts ("1 running in 6 parts"), and the
  session log gives the number of worker processes.
- **Forensic Reports screen.** The Visual report panel runs across the
  full width at the bottom, its checkbox and "Documents rendered at once"
  on one line, with the Generate button beneath; the Report Log beside
  the report choices ends level with them. The left-hand controls scroll
  when the window is too short. **Graph Analysis screen:** the controls
  scroll too, and the Generate button stays visible below them (it was
  cut off). **Tooltips** open above the pointer when there is no room
  below (allowing for the taskbar) and to its left near the right-hand
  edge; one ran off the bottom of a 24-inch screen.
- **Tests:** page pairing and the inconsistent repaired copy in
  `test_repaired_copy.py`.

### Build 2026-11-24: after the second 12,746-file run
Build 2026-11-23 on the same 12,745 files: triage 466 s plus 278 s for its
spreadsheet; analysis 1,405 s (13,150 s before; 15,614 s of work against
72,500 s; `129f8caa…` 66 s against 11,796 s, `89d75b74…` 64 s against
523 s); the one-pass image boxes matched get_image_rects on all 540
pages checked; Visual Overlay reports 8,909 s (5,874 s before). On the
325-file case: triage 65 s, analysis 201 s (626 s in build 2026-11-20),
visual reports 421 s. Files are named by MD5 here.
- **Visual reports: a regression fixed.** Build 2026-11-23 counted a page
  shared by a document's versions once, assuming they reuse its drawings.
  `925bdc8e…` and its three 70-page versions differ on every page and
  reuse nothing, so the four were kept in one process and drawn one after
  another (8,900 s, the whole of the step's last hour and a half). Every
  document's pages now count in full; a heavy lineage is still split by
  page range across its versions, so where versions share pages they
  still reuse the drawings.
- **Damaged page trees.** 26 documents failed with "Accessing nonexistent
  PDF page number": MuPDF's repaired copy kept the broken page tree, so
  pikepdf read fewer pages from it than MuPDF had found. MuPDF now
  rewrites the page tree from its own page list (`select`) before the
  copy is saved, and the copy is used only if both readers then count
  the same pages. If no such copy can be made but pikepdf read the
  original, the original is analysed for the pages both readers have,
  with a structural warning giving the numbers; that also covers files
  MuPDF could open but not save (2) and one where MuPDF finds no pages
  (which build 2026-11-20b reported as analysed, with no pages examined).
  A file neither reader can read (7 here: no pages for MuPDF and an
  unreadable page tree for pikepdf, or no trailer) fails with both
  reasons in plain words.
- **Malformed text matrix.** A `Tm` instruction with fewer than six
  numbers stopped one document in the white-box check (IndexError); it is
  ignored, as viewers do, there and in the visual reports.
- **Triage spreadsheet.** Its metadata sheet had 756 columns (one per
  field found in any file) and wrote and styled all 13.8 million cells,
  empty or not: 278 s. Only the fields a file has are written now (the
  same values, about 15 times faster in a comparison); empty cells have
  no border.
- **PyMuPDF's own messages** ("unhandled font type ''" from triage's font
  list, for an embedded font program whose type is missing) went to the
  console; they are written to the session log with the document, and
  MuPDF's warnings are no longer displayed (they were already logged).
- **Tests:** `test_library_messages.py`; repaired-copy fallbacks in
  `test_repaired_copy.py`; a malformed `Tm` in `test_content_ops.py`;
  versions that share no pages in `test_visual_split.py`.

### Build 2026-11-23: a 12,746-file case
From the build 2026-11-20b run on 12,745 submitted files (16.2 GB; 5,570
distinct documents, 2,632 prior versions; 18 processes): triage 504 s plus
350 s writing its spreadsheet, analysis 13,150 s, reports about 175 s,
Visual Overlay reports 5,874 s. Files are named by MD5 here.
- **Content walks read operator names first.** Every walk over a page's
  drawing operators (image placements, transparency, the white-box check,
  forms, annotations) unpacked each operator with its operands, building
  the operands as Python objects for every operator, though most are then
  ignored. On a 13-page drawing with 2.75 million operators that took 85 s
  per walk on the examiner's computer, against 7 s to parse the page, and
  each page was walked three times or more; these steps were 67% of all
  analysis time. The walks now read the name and fetch operands only for
  the operators they act on (`analysis/content_ops.py`): about 5 times
  faster here on a 780,000-operator page. A form drawn many times on a
  page is read once. Identical results to build 2026-11-20b on 20
  synthetic pages (2,624 white-box findings, 8,541 placements).
- **Three checks no longer grow with the square of a page's images.**
  `129f8caa…` (29 pages, 28,260 images) took 11,796 s, most of the
  analysis step. The overlap and off-page checks asked MuPDF for each
  image's boxes separately, and MuPDF decodes every image on the page to
  answer each time (8,661 s and 1,218 s): the boxes now come from one call
  per page, checked against the old call on each process's first pages
  with images (a difference sends that process back to the old call and is
  counted: `rects_verified`, `rects_mismatch` in the performance log).
  Overlapping pairs are found by a sweep instead of testing every pair, in
  the same order. The transparency step looked each image up by scanning
  the page's whole XObject list (1,850 s); it uses a map. Identical
  findings to build 2026-11-20b on six stand-in pages (21,328 findings).
- **Watchdog and Skip.** A file whose worker reports no progress (a page
  finished, images extracted) for 30 minutes is stopped and recorded as
  failed ("timed out", with the page it was on); *Skip a file…* below the
  progress bar does the same on request ("skipped by the examiner"). The
  files running alongside are sent again; the run continues.
  `--watchdog-minutes` sets the time on the command line (0 turns it off).
- **Damaged files are analysed from MuPDF's repaired copy.** 112 distinct
  documents (2%) were not analysed. 67 could not be opened by pikepdf
  ("root of pages tree has no /Kids array"), 13 had fewer pages for
  pikepdf than for MuPDF, and 4 were permissions-only encrypted with the
  same damage. When pikepdf cannot open a file or read its pages, or the
  two readers count different numbers of pages, the document is now
  analysed from a copy MuPDF has repaired (and decrypted). A structural
  warning says so and gives both page counts, since pages one reader finds
  and the other does not can be hidden pages. Visual reports use the same
  copy. Byte-level checks still read the original.
- **Missing objects are findings, not failures.** 28 documents stopped on
  a resource entry naming an object that does not exist (`'NoneType'
  object has no attribute 'get'`). Such entries are skipped (they draw
  nothing) and listed in a structural warning for the page.
- **New byte-level checks** (structural warnings): cross-reference entries
  that do not point to the object they name (typical of bytes changed
  after the file was written, or damage), and runs of zero bytes outside
  streams, such as a zero-filled tail (a file cut short or filled in by a
  recovery tool).
- **One encryption check for triage and analysis.** For a file pikepdf
  cannot read, triage (which reads bytes) said "not encrypted" and
  analysis (which reads the path) said "password required", and the file
  was skipped. Both now ask MuPDF in that case, and a structural error is
  no longer taken for a wrong password: the four permissions-only files
  open with no password and are analysed. The Encrypted Files report now
  shows the encryption scheme of locked files (read from the encryption
  dictionary, which needs no password) and every file's MD5. It also
  groups identical copies ("Files with this MD5") and states how many
  distinct documents there are.
- **XMP is read without side effects.** It was opened in a way that
  rewrote it in memory, and an XMP packet that is not well-formed XML was
  replaced by an empty one, with warnings on the console. It is now read
  strictly; if that fails, the metadata records "XMP present but could not
  be parsed" with the reason and the raw packet (up to 20,000 characters),
  and lists what a repairing parser can still recover, labelled as such.
- **Very large images:** header and EXIF reads no longer stop at PIL's
  decompression-bomb limit (nothing is decoded), so those images keep
  their EXIF, without console warnings.
- **Library messages in the session log.** pikepdf's warnings went to the
  console; they are now written to the session log with the document,
  like MuPDF's. The visual reports' quick drawing no longer prints MuPDF
  messages.
- **Visual reports: heavy lineages split by page range.** A document whose
  lineage was over a share of the work was split into its documents, each
  drawn in a different process, so versions could not reuse its renders
  (`925bdc8e…` and its three versions: four complete drawings of about
  3,200 s side by side; about 19,600 s of work across 72 versions). Such a
  lineage is now split by page range, each task drawing those pages of the
  document and then of its versions, and pages shared by versions count
  once in the estimate.
- **Performance log:** operators parsed per file (`operators`), the image
  box check counts, and the triage spreadsheet's metadata columns and
  cells (its 350 s will be looked at once known).
- **Not changed:** files are still started largest first. After these
  fixes the slowest files are the large vector drawings, which size
  already starts early; ordering by triage's image counts was not worth
  the added complexity.
- **Tests:** `test_content_ops.py`, `test_image_boxes.py`
  (`fake_mupdf_boxes.py`), `test_watchdog.py`, `test_repaired_copy.py`,
  `test_encryption_check.py`, `test_byte_structure.py`; lineage splitting
  in `test_visual_split.py`; the stand-in analysis can report progress and
  hang (`stub_compute.py`).

### Build 2026-11-20b: ready for a 12,746-file case
From the build 2026-11-20 run on the same 325 files (*Auto*: 17 and 16
processes, see below): triage 59 s, analysis 626 s, graphs about 53 s,
Visual Overlay reports 777 s.
- **Analysis: the hand-out thread is no longer held up.** Its 48,122
  progress messages took 0 s (the log is drawn by the window's timer), and
  analysis now ends with its longest file and its prior versions (604 s;
  that file is the largest and is started first). With every process busy
  each file is slower than when most were idle, so a shorter analysis now
  needs splitting the work inside one file; not planned.
- **Visual reports: work estimate corrected.** Build 2026-11-20 estimated
  work from the quick drawing alone; that missed the cost every overlay has
  whatever the page (building its variant, separating its layer, encoding
  it), so the 30-page document with 1,627 overlays was rated small, not
  split, and ran 773 s alone. The estimate is now about 0.4 s per drawing
  of a page (once per overlay plus three), plus, for a page that is slow to
  draw (its quick drawing took 0.2 s or more; an ordinary page takes about
  0.02 s), 110 times its quick drawing per drawing: fitted to that run, it
  follows the time each document took with a correlation of 0.93 (0.88 for
  either measure alone). Each document's largest page area is now in the
  performance log (`max_area=`, square inches), to see whether page size
  explains the two documents still underestimated.
- **Auto ignores light background load.** At 3 to 9% busy (including this
  application's own window), Auto had dropped to 17 and 16; load up to 10%
  is no longer counted.
- **Document Comparison Matrix at scale.** The query paired every placement
  of an image with every other placement of it, growing with the square of
  how often an image is used; it now pairs documents (each document's
  distinct images once): the same rows in the same order (ties now in
  document order), 15 to 20 times faster in tests. With thousands of
  documents, an image nearly all of them carry (a logo) makes almost every
  pair share something: 12,746 documents could give about 81 million
  pairs. The report now lists the 10,000 pairs sharing the most images and
  states the total at the top ("Showing the 10,000 pairs ... of N pairs");
  smaller cases are unchanged. The pairs are counted in one pass keeping
  only those 10,000 (about 2 million pairs in 1.7 s in a test).
- **Analysis log at scale.** A file's line in the Processing Log, once
  final, drops its own marker and leaves the list of lines updated each
  second, so the log costs the same with 25,000 finished lines as with 25.
- **Tests:** `test_doc_comparison.py` (against the previous SQL, the cap
  and its notice); the estimate tests (`test_visual_split.py`), Auto and
  line retirement (`test_build_19b.py`) updated.

### Build 2026-11-20: Auto by physical cores; analysis log off the busy thread; drawing-time estimate
From runs of build 2026-11-19e on the same 325 files on a computer with 18
cores (36 logical processors):
- Visual Overlay reports alone at 6, 18 and 24 processes: 708, 445 and
  583 s. More processes slow each one down (total work 3,553, 4,673 and
  6,341 s), so 18 did the work of about 13.6 processes running alone and
  24 about 13.5: no gain past the number of cores.
- The whole run at 18 against 12: triage 57 against 72 s, graphs about 38
  against 55 s, visual reports 439 against 697 s; analysis 781 against
  692 s, although its total work fell (4,122 against 5,547 s) and so did
  its longest file (429 against 632 s). This application used 17% of the
  machine during analysis at 18 (24% at 12): most processes were idle.
- **Auto uses physical cores.** One process per physical core (18 on
  that computer), still limited by memory (about 4 GB each) and now to 24
  (was 12). Without psutil, where cores are not known: logical processors
  less one, as before. The busy-processors rule now counts the share of
  cores that is idle. The ⓘ panel shows cores and logical processors,
  and why Auto counts cores.
- **Analysis log drawn by a timer.** The thread that hands out files and
  writes results also drew the Processing Log for every file's progress
  (up to four times a second per running file, each time forcing the
  window to redraw), so the more files at once, the less time it had to
  hand out work. It now only records progress; the window draws it once a
  second on its own thread, as the Generation and Report Logs do. Each
  file's line has an elapsed clock and, when done, the time it took; a
  file's prior-versions line is drawn under it.
- **The performance log says where the analysis main loop's time went:**
  checks before sending, writing results, progress messages (and how
  many), waiting for workers, and how many worker processes were busy on
  average.
- **Visual reports: work estimated from drawing time.** Before planning,
  the worker processes draw each page that has overlays once at 36 dpi
  and time it (a second or two in all). A page's work is that time
  multiplied by the number of times it is drawn (about once per overlay,
  plus three). Before, the number of overlays was the estimate, which
  rated four one-overlay pages that take 2 to 4 minutes each to draw as
  trivial: they started late, each after its prior version in the same
  process, and finished last. Tasks with more than half a process's share
  of the work now start first, largest first; the rest follow in listed
  order. A document and its prior versions are split into separate tasks
  when together they exceed a share, as before, now by this estimate.
  Each document's estimate is in the performance log (`est=`,
  `probe_s=`). If a page cannot be drawn quickly, the median is used; with
  no measurements at all, overlays are counted as before.
- **Speed check:** before each step, a fixed piece of work is timed and
  noted (Python code and compressing data), so runs at different times
  can be compared.

### Build 2026-11-19e: long documents split by pages; processor load
From the build 2026-11-19d run on the same 325 files (*Auto*, 12
processes): triage 71 s, analysis 655 s, graphs 38 s (from about 511 s:
handing the largest graph to pyvis took 1.1 s instead of 470 s, by the
fast way, with the real pyvis), Visual Overlay reports 805 s; about 1,620 s
in all. The visual reports' rendering and page building, which that build
did not change, were 45% slower than in the run before, so the computer was
busier during that step; the self-check, which it did change, went from
435 s to 193 s regardless. In both runs one 30-page document with 1,627
overlays was the last 150 to 180 seconds of the step, alone.
- **Visual Overlay reports: long documents split by pages.** A document
  with more than one process's share of all the overlays (and at least 40
  of them) is split into parts of consecutive pages, at most about half a
  share each and no more parts than processes, balanced by the number of
  overlays. The parts are rendered in different processes; the main
  process joins them in page order and writes the report when the last
  part is in. Every page is still read and numbered in each part, so the
  overlay numbers are those of the whole document; the report, its log
  entries (in the same order), the index and the counts are the same as
  when the document is made at once (tested: one at a time against split,
  with the parts finishing out of order). The performance log gives the
  number of parts for such a document (`parts=`) and a note of how many
  documents were split. One page is the smallest part: a single page with
  many overlays is not split.
- **Processor load in the performance log.** While triage, analysis, the
  graphs and the visual reports run, the machine's processor load is
  sampled every 2 seconds, with the share used by this application (its
  own process and its worker processes) and by other programs. Each step
  ends with a note, for example "processor load during visual reports:
  machine average 64%, highest 98%; this application average 61%; other
  programs average 3%, highest 9% over 10 s". Numbers only; needs psutil.
- **Tests.** `test_visual_split.py` (parts against the whole document,
  using stand-ins for PyMuPDF's rendering so the report's own code runs,
  and the planning of parts) and `test_load_sampler.py`.

### Build 2026-11-19d: graphs and visual reports faster
From the build 2026-11-19c run on the same 325 files (*Auto*, 12
processes): triage 67 s, analysis 644 s, graphs about 511 s, Visual
Overlay reports 680 s; about 1,950 s in all, against about 2,390 s for
build 2026-11-19.
- **Graphs.** 470 of the largest graph's 505 seconds (23,432 nodes,
  65,973 links) were spent handing the graph to pyvis: for every link,
  pyvis reads every link already added, looking for an identical one, so
  the time grows with the square of the number of links. A networkx graph
  never holds the same link twice, so that search never finds anything.
  The graph is now handed over without it, and with node ids looked up in
  a set rather than a list; the nodes and links are still made by pyvis's
  own code. Before each graph, a sample of it (400 nodes with their links)
  is built both ways, and the fast way is used only if the two are
  identical; otherwise pyvis's own method is used. A graph of that size
  is handed over in under a second (measured with a stand-in following
  pyvis 0.3.2). The performance log records which way was used
  (`network_path=fast` or `pyvis`).
- **Visual Overlay reports.** On a page with many overlays, the page with
  every overlay removed was decoded again for every overlay, and a white
  box's page again for its measurement and for each line painted on it;
  they are now decoded once per page (at most 192 MB of decoded images
  kept per process). The self-check, which rebuilt the page from every
  layer, decoded each layer image again just after making it; it now uses
  the part of each layer that is not transparent, kept from when it was
  made. Layers, measurements and self-check results are identical byte
  for byte (tested against the previous code). On a synthetic page with 54
  white boxes, each with two painted lines, this part of the work took
  about 30% less time; rendering the pages, the other large part, is
  unchanged. The longest document in the run above (30 pages, 1,627
  overlays) spent 408 of its 679 seconds in this part.
- **psutil.** Added to `requirements.txt`: without it *Auto* cannot see
  free memory or how busy the processors are, and uses the most the
  computer supports. The log line and the ⓘ panel now say when it is
  missing.
- **Status line wording.** "*N* analysed, waiting to be written to the
  database" (was "finished, waiting their turn"), and the same in each
  such file's log line.
- **Not done yet:** splitting a very long document's visual report by
  pages across processes (done in build 2026-11-19e).
- **Tests.** `test_graph_fast.py` (the fast way against pyvis's own, with
  the stand-in in `tests/fake_pyvis` or the real pyvis where installed,
  and the fallback when they differ) and `test_visual_speed.py` (layers,
  measurements and self-check against the previous code). The graph test
  that compares files made one at a time and several at once had a fault
  in its own setup (the same image numbered twice in one document), which
  showed only where pyvis is installed; fixed.

### Build 2026-11-19c: start-up fix
- Build 2026-11-19b stopped at start-up (`NameError: workers_cb`): a
  tooltip still referred to the setting's old drop-down. The tooltip is now
  part of the shared control, so it appears on all three screens.
- Why the tests missed it: the check for names that are never defined
  skipped any module using `import *`, and the interface module imports its
  colours that way, so it was not checked at all. The check now resolves
  `import *` from the package's own modules, and covers the interface.
  The window is also now built end to end against a stand-in for Tk
  before release.

### Build 2026-11-19b: the setting in view, live progress, visual order
From the build 2026-11-19 run on the same 325 files with *Auto* (12
processes): triage 60 s, analysis 659 s (peak 422 MB of finished results
held, none written to disk), graphs 647 s, Visual Overlay reports 882 s;
per-file results identical to earlier runs.
- **Files processed at once.** Every session starts at *Auto*; a number
  chosen for one run is no longer carried into the next (the saved choice
  had kept "1" after a comparison run). *Auto* is decided again at the
  start of each step (triage, analysis, graphs, visual reports): the
  machine's ceiling as before (one process per logical CPU less one, about
  4 GB of installed memory each, at most 12), lowered when free memory is
  short (about 2 GB free per process) or other programs are keeping the
  processors busy. Each step's log states the number and why, with the
  machine's numbers only (also in the performance log). The setting is
  shown on the analysis, graphs and reports screens (one setting), in
  amber with "not Auto" when a number is chosen, and an ⓘ panel shows
  this computer's processors and memory, what *Auto* would choose now and
  why, the trade-offs and the recommendation. The command line's `auto`
  adapts in the same way.
- **Analysis status line.** It counts files *written*, *running* and
  *finished, waiting their turn* (build 2026-11-19d: *analysed, waiting
  to be written to the database*), and states the order ("largest files
  first; results written in the order selected"). The old "51 being
  analysed (12 at once)" came from a mismatch: workers reported a file
  under its lineage number and results used its submission index, so
  files never left the running count, and each file's progress line stayed
  in the log beside its result line. One key is now used for both.
- **Generation Log (graphs).** A live line per graph, updated in place
  with its stage (loading, thumbnails *n* of *m*, building, laying out the
  network with its nodes and links, writing the file) and an elapsed
  clock, and marked done with its time as each graph finishes. Lines are
  redrawn once a second by a timer, so a step that sends no messages never
  looks frozen and the work is not slowed. Every stage is timed in the
  performance log (`t_load`, `t_thumbnails`, `t_build`, `t_network`,
  `t_write_html`, `t_custom_ui`, with node and link counts).
- **Report Log (Visual Overlay reports).** Progress is now in the Report
  Log itself, not only in the status bar at the bottom of the window,
  which a small window may not show: a live line with the documents done,
  running and an elapsed clock; a line under it for each document running
  longer than 30 seconds, with its own clock and its time when done; and a
  completion line.
- **Visual Overlay reports: order.** Starting every heavy document first
  (build 2026-11-19) ran them all at the same time, and they slowed each
  other: the longest went from 614 s to 881 s. Now the task with the most
  overlays starts first and the rest follow in their listed order, so the
  heavy documents are spread through the run. Each document's start and
  end, from the start of the step, are in the performance log. Splitting
  one very long document by pages is not done: such documents are
  uncommon.
- **Case index.** Files not already in the MD5 cache are hashed eight at a
  time in threads; the index lists the same digests in the same order.
- **New tests** (`tests/test_build_19b.py`): live lines (with a stand-in
  text widget), *Auto* under short memory and busy processors, one key for
  a file's start, finish and result, the visual reports' progress
  callback and start and end times, and the case index's digests threaded
  against one at a time.

### Build 2026-11-19: no waiting on the longest files
From the build 2026-11-17 runs on 325 files (696 analyses, 19,902 pages):
one at a time and *Auto* (12 processes) gave identical databases (all 16
tables, `tests/compare_databases.py`) and identical per-file results in the
performance logs; only the image-cache hit counts differ, as each process
has its own cache. Analysis took 3,485 s one at a time and 1,707 s with 12
processes; Visual Overlay reports 2,919 s and 837 s. The logs showed where
the remaining time went, and simulations from their per-file times
reproduce both runs (1,676 s and 838 s):
- **Analysis: largest files first, no fixed look-ahead.** Results must be
  written in submission order, and at most 24 finished lineages could wait;
  a 577 s file early in the selection filled that allowance, leaving on
  average 2.9 of 12 processes busy. Now the main-process checks run for
  every file first (in order, as before), lineages are sent to workers
  largest file first, and finished results wait as the bytes the worker
  sent, in memory up to 4 GB (or 15% of RAM) and in the staging folder
  beyond that. A lineage whose turn comes before it was sent is sent at
  once. Writing order, and so the database, is unchanged. Simulated on the
  same run: 1,707 s to about 580 s (the longest single lineage). The
  performance log notes the order, the peak held in memory and the number
  of results written to disk.
- **Visual Overlay reports: most overlays first; long lineages split.** A
  document and its prior versions are made in one process, so shared
  pages reuse renders; one lineage of three documents (829 s together) set
  the run's length. A lineage with more than one process's share of all
  overlays is now split into its documents, and work is started with the
  most overlays first (the overlay count predicts report time far better
  than the page count: r = 0.73 against 0.32). Reports are identical:
  reused renders are verified identical, and results are recorded in
  document order. Simulated: 837 s to about 620 s (the longest single
  document).
- **Graphs: made at the same time**, one process each
  (`graph/generate.py`, one function used one at a time too), reported in
  the order listed. The three graphs took 701 s one after another; about
  300 s at once.
- **Triage in parallel**, rows, comments, log entries and performance rows
  in the order given (`triage._triage_one`, used one at a time too). With a
  password list it runs one file at a time, so passwords are tried in the
  same order and the spreadsheet records the same password for each file.
  It took 479 s for the 325 files.
- **One at a time: fewer window updates.** The progress line was redrawn
  after every page and every image written, which cost about 380 s of the
  3,485 s run (timed under image writing and page handling); it is now
  redrawn at most four times a second and on a document's last page.
- **The setting** is now *Files processed at once*, shown in both modes
  (it applies to triage too); command line `triage --workers`.
- **New tests:** dispatch order against writing order, results identical
  whatever the order, look-ahead and memory budget (including results
  written to disk), the visual task plan, graphs in order with no data or
  errors, and triage spreadsheets one at a time against three at a time
  (needs PyMuPDF), graphs one against several (needs pyvis).

### Build 2026-11-17b: white boxes that hide nothing (Visual Overlay report)
- For each white box the report now measures, from its own renders,
  whether removing it reveals anything: the pixels the box changes, within
  its area, where the page beneath it (every overlay removed) is not blank
  (`_hidden_pixels`; same 10-level tolerance as the layers). Any pixel
  counts; the number is added to the box's description.
- A box that reveals nothing (blank paper beneath, typically a cell
  background or panel) is listed in a collapsed group, **Hides nothing
  visible**, below the main list. It is not removed: still ticked (so the
  page is still shown exactly as received), still toggleable, its layer
  still in the page, and its number, anchor and leader line shown on the
  page when the group is opened. Its description no longer says it covers
  page content. The summary beneath the page lists these boxes in a
  collapsed block; both open automatically for printing.
- Boxes that reveal content are tagged **hides content** with the number of
  pixels.
- Only white boxes are measured, and only on pages whose layers passed the
  self-check and from whose base image every overlay was removed (a box
  left in the base would otherwise measure 0); a box that cannot be
  measured, and every other kind of overlay, stays in the main list. Every
  document with overlay findings still gets its report.
- The page heading and the report's opening line give the number that hide
  nothing. The index page has a new, sortable **Hides content** column:
  the overlays not found to hide nothing.
- Performance log: each document's visual-report event records
  `white_boxes_measured` and `hide_nothing`.
- Tested with renders of a synthetic page by an independent renderer
  (Poppler): two layout boxes measure 0 and the altered amount's box 599
  pixels; the collapsed group, the toggles, All/None and printing checked
  in a browser. New tests: `tests/test_visual_hides.py`.
- HTML Reports technical guide 3.1 and Technical Reference Guide 7.4
  describe it.

### Build 2026-11-17: fill colours in named colour spaces
- The content-stream white-box check (Text Overlay, overlay kind
  white_box) decides whether a filled rectangle is white from its fill
  colour. Colours set with cs and sc/scn were read without regard to their
  colour space: one component as grey, three as RGB, four as CMYK. In a
  spot colour (Separation, DeviceN) a tint of 1 is full ink and 0 is no
  ink, the opposite of grey, so:
  - shapes drawn in a black spot colour at full ink (table borders, dark
    title bands) were reported as white boxes with text painted on them
    (false positives; one 29-page document gave 113, of which 110 were
    0.3-0.6 pt table borders and one a black band behind a white title);
  - a box in a spot colour at no ink (paper white) was not seen as white
    (missed white boxes).
- New `analysis/colour.py` evaluates the colour in its space where that
  can be done exactly: device spaces, ICC-based and calibrated spaces (by
  number of components), Lab, Indexed palettes, and Separation/DeviceN
  through their tint transform (function types 0 one-input, 2, 3 and 4).
  A colour that cannot be evaluated (a pattern, an unsupported function,
  a missing resource, the /None colorant) is read exactly as before, so no
  shape is treated differently from earlier versions unless its colour is
  known.
- Applied identically in the detector, its reference copy (verification
  mode) and the Visual Overlay report's layer separation
  (`reports/reveal.py`). Results are cached per page.
- Findings and risk scores change for documents that use such colours.
  Documents analysed with an earlier build must be analysed again for the
  change to apply.
- On the 29-page document above: 113 findings become 3; each of the 3 is a
  white box in a spot colour at no ink, and removing it changes no pixel
  when the page is rendered with an independent renderer (Poppler): white
  boxes over blank paper, not reported before.
- Technical Reference Guide 7.2.1 describes the colour evaluation.
- New tests: `tests/test_colour.py` (each colour-space family, the
  fallback to the old reading, and the detector and its reference copy on
  synthetic pages).

### Build 2026-11-15b
- Visual Overlay reports made several at once were not written: the
  report reads the case number from the session and registers its file
  as an output of the session, and the stand-in session used in worker
  processes provided neither, so each report failed in its worker (the
  index listed the documents without reports; the session log gave the
  reason). The stand-in now carries the case number, session timestamp
  and case folder, and records registered outputs, which the main process
  adds to the session in order. One at a time was not affected.
- New tests: the stand-in provides every session attribute used by code
  that runs in worker processes, and a visual report page is assembled
  with it.

### Build 2026-11-15

### Several files analysed at once
- Full parsing can analyse several PDFs at the same time, each in its own
  process (`analysis/parallel.py`). The analysis itself is the same code as
  before; what changes is where it runs.
- The unit of work is a submitted file together with its prior versions,
  which always run in the same process, parent first, so prior versions
  still reuse the parent's unchanged pages and images.
- Worker processes only compute. The main process writes everything, in
  the order the files were selected: the duplicate check, the encryption
  record, the database rows (`analysis/commit.py`), the session-log entries
  and the performance-log rows. Analysis ids, duplicate decisions and every
  table therefore come out as in a one-at-a-time run.
- Identical copies are decided when their turn comes, against what is
  already in the database. A file found to be a copy of one analysed
  earlier in the run is not analysed at all when this is known in advance;
  when it is only known later (for example a copy of another file's prior
  version), its results are discarded and nothing it wrote is kept, so the
  case folder is as a one-at-a-time run leaves it.
- Images are written by a worker to a staging folder inside the extracted
  images folder (`.pending_…`) and moved into the document's folder when
  its analysis is written; the staging folder is removed at the end of the
  run.
- Session-log entries are written with the time they were recorded, a
  file's entries together; the session log notes the number of worker
  processes. The performance log records `workers=N` in the run's options;
  each file's row gives that file's own processing time (they overlap), and
  the RUN line gives the elapsed time.
- A worker process that stops unexpectedly (for example a crash inside a
  PDF library) no longer ends the run: the files it was analysing are
  re-run one at a time, and a file that fails again on its own is recorded
  as failed. If a worker cannot pass its results back, the main process
  analyses that file itself. Closing the window during a run stops the
  worker processes at once.
- Equivalence is tested: the same files analysed one at a time and with
  several workers give identical databases (`tests/`,
  `tests/compare_databases.py`).

### Setting
- New option: **Files processed at once** (named *Files analysed at once*,
  under Full parsing, before build 2026-11-19). *Auto* (the
  default) uses one process per processor core, less one, limited by memory
  (about 4 GB per process) and to 12. *1* runs the one-at-a-time loop of
  earlier versions unchanged. The choice is remembered.
- Command line: `analyze --workers N|auto` (default auto) and
  `report --visual --workers N|auto`.

### Visual Overlay reports in parallel
- Per-document visual reports are made several at once with the same
  setting, a document and its prior versions in the same process (so
  unchanged pages still reuse renders). The reports, the index, the log
  entries and the performance-log events are the same, in the same order.
  Each process's render cache is a share of the previous single budget.

### Prior versions on the command line
- `analyze --prior-versions` extracts and analyses prior versions, as the
  GUI option does (previously GUI only).

### Files with the same name (also one at a time)
- Two submitted files with the same name (from different folders) shared
  one image folder and one prior-version folder: their images were mixed,
  and the second file's prior versions overwrote the first's, so the first
  file's database rows pointed to version files that now held other bytes.
  The second now gets `name_2` (the third `name_3`, …), compared
  case-insensitively as Windows does.

### Command line, small alignment
- With `--workers` above 1 or `--prior-versions`, an encrypted file that is
  an identical copy of one already analysed is recorded as an identical
  copy only, without an encryption-table row, as the GUI has always done.
  With `--workers 1` the command line behaves as before.

### Packaged executable
- `multiprocessing.freeze_support()` in every entry point
  (`pdf_forensics.py`, `pdf_forensics/__main__.py` and the single-file
  build's launcher), without which a packaged executable would start the
  application again in each worker process.

### Internal (no change in behaviour)
- `analyze_pdf(defer=True)` returns its results instead of writing them;
  `commit_analysis()` writes them (and is what `analyze_pdf` itself now
  calls). `passwords.resolve_file_password()` is now
  `probe_file_password()` followed by `record_file_password()`.
  `extract_prior_versions()` takes the name to base folders on and can
  report the files it wrote. `Session.replay()`, `PerfLog.file_resume()`
  and `PerfLog.stage_add()`, and `perf.RecordingPerf`, support results made
  in worker processes.

### Documentation
- Technical Reference Guide: the architecture table gave the database
  schema as revision 9; it is revision 10 (since 1.1.0, timeline events).
  The table now also lists the modules added since 1.0
  (`analysis/timeline.py`, `analysis/page_reuse.py`, `perf.py`,
  `pathutil.py`, `reports/timeline_xlsx.py`) and the new
  `analysis/parallel.py` and `analysis/commit.py`. Section 5.2 describes
  parallel analysis. Getting Started describes the new setting.
- The repository README's 1.2.0 entries gave build 2026-11-03; the 1.2.0
  build is 2026-11-12. Now 1.3.0, build 2026-11-15.
- `build_exe/` (scripts to build a Windows executable with PyInstaller,
  one folder or a single file) is now part of the application folder;
  see "Building an executable" in the README.

### Tests
- New `tests/` folder (standard-library `unittest`; synthetic files only):
  static checks (every module compiles; no undefined names), regression
  tests for the fixes made since 1.0, the parallel runner with a stand-in
  analysis (order, copies, same-name files, encryption, crashes, logs),
  visual reports one-at-a-time against several at once, and real analyses
  compared with `tests/compare_databases.py` (needs PyMuPDF). The
  comparison tool can also be run on two case databases.

### Not parallel
- Triage, graphs and the other reports run as before.
- A password found while opening a prior version in a worker is not
  offered first to the files analysed by other workers. This only changes
  the order in which passwords are tried (and so the attempt count
  recorded), not whether a file opens, and only when a prior version needs
  a different password from its parent.

## Version 1.2.0 — Release (2026-11-12, build 2026-11-12)

Performance. No database schema change; findings are unchanged.

### Build 2026-11-12

The timing breakdown added in build 2026-11-10 showed where the visual
reports' time goes on a 325-file case (8,142 s): building variants 53%,
decomposing white boxes 14%, rendering 15%, isolating layers 12%, the
composite check 4%.

#### Visual Overlay reports: each page opened and parsed once
- Building a layer's variant reopened the source PDF, re-parsed the page's
  content and its forms, and re-decided the operators of every finding on
  the page, for every layer; a page with 686 findings did all of that 686
  times, and the white-box decomposition opened and parsed the page again
  for each box. The page is now opened and parsed once and shared by its
  variants and by the white-box decomposition. Each build first restores
  the original page (its annotations, its content, and any form rewritten
  by an earlier variant), then runs the same steps as before; the
  decisions for a given set of findings are computed once and reused by
  the variants that remove the same findings (all the fill and line layers
  of a page). On a page with 300 white boxes, 601 variants build in 1.1 s
  instead of 28.8 s. The previous builder is kept as a reference:
  146 variants across pages and documents, including forms rewritten in
  place and annotations, compare identical. In verification mode
  (PDF_FORENSICS_VERIFY_REUSE=1) every variant is also built from scratch
  and compared. (`reports/reveal.py`, `reports/visual.py`)

#### MuPDF messages during visual reports
- Diagnostics MuPDF prints while rendering (for example "invalid ICC
  colorspace" for a malformed colour profile, which it replaces with a
  standard colour space) appeared in the terminal. They are now written to
  the session log with the document they came from, and counted per
  document in the performance log (mupdf_messages), as analysis and triage
  already did.

### Build 2026-11-10

Verification of build 2026-11-06 on a 325-file case: every analysis check
passed (reused pages 11,254, reused forms 14,754, image-less forms 21,939,
overlay detector on all 19,902 pages; no mismatches), findings identical to
the previous build file by file, and reused visual-report renders identical
to fresh ones. Visual Overlay reports took 7,615 s (13,015 s before); the
whole workflow 3.4 h (7.7 h in 1.1.6).

- Clipped layer renders withdrawn. Rendering each visual-report layer only
  around its overlay gave no measurable speed-up (the page render is not
  where a layer's time goes), and about 2% of clipped layers (410 of some
  13,000 compared) were not pixel-identical to a full render. Every layer
  is again rendered on the full page, and PDF_FORENSICS_VISUAL_CLIP is
  gone. Visual reports generated with build 2026-11-06 used clipped layers
  for some overlays and should be regenerated.
- The performance log's line for each document's visual report now also
  gives the seconds spent building variants (t_build), rendering
  (t_render), isolating layers including PNG encoding (t_isolate),
  decomposing white boxes (t_whitebox), the one-page check (t_single), the
  final composite check (t_check) and embedding images (t_encode).
  (`reports/visual.py`)

### Build 2026-11-06: from the build 2026-11-05 performance logs

Verification of build 2026-11-05 on a 325-file case: 11,254 reused pages
and 14,754 reused form analyses, no mismatches; all 54,690 image
placements present (the reuse fix holds).

#### Visual Overlay reports: renders reused across prior versions
- A prior version's page that is unchanged from an earlier document's page
  (same fingerprint) and has the same findings shows the same images, so
  its renders (the page as received, the revealed base, each layer) are
  reused; the version's own numbering and labels are built afresh. Each
  prior version used to redraw every page of its parent's report.

#### Visual Overlay reports: each layer rendered around its overlay only (withdrawn in the next build)
- Each layer used to need a full-page render; a page with hundreds of
  findings took over a second per finding. A layer differs from its
  background only where its overlay is, so the variant is now rendered
  only around the overlay (with a 24-point margin) and pasted onto the
  background at its exact pixel position. If any changed pixel touches an
  interior edge of that area, the overlay may extend beyond it and the
  layer is redone on the full page. Rotated pages, and pages whose
  coordinates do not start at the origin, always use full renders. The
  existing check that base plus layers reproduces the page as received
  still applies to every page. PDF_FORENSICS_VISUAL_CLIP=0 renders every
  layer in full.
- In verification mode (PDF_FORENSICS_VERIFY_REUSE=1) every reused render
  and every clipped layer is compared with a fresh full render; the
  performance log line of each document's visual report counts renders
  reused, layers clipped, clip fallbacks, verified and mismatches.

#### Form XObjects with no images: fast path
- On the slowest documents the form analysis cost came from individual
  forms, not repetition: each page has its own forms. Every finding of the
  form analysis except an unreadable stream concerns an image placed in
  the form, so a form with no images is now checked only for readability
  (its whole stream is still tokenised; no object is built per operator):
  about 9 times faster on a large vector form, same findings. Verification
  mode compares it with the full analysis (forms_fast_verified,
  forms_fast_mismatch).

#### Content-stream overlay detector: grid index
- For every text-drawing operation the detector compared the position with
  every white rectangle on the page. A grid index now limits the
  comparison to nearby rectangles, in their original order: same findings
  in the same order (40 random pages, 4,883 findings, identical); about 3
  times faster on a dense page. Verification mode compares it with the
  original detector (cs_overlay_verified, cs_overlay_mismatch).
  (`analysis/detectors.py`, `analysis/engine.py`, `reports/visual.py`,
  `reports/reveal.py`, `perf.py`)

### Build 2026-11-05

### Build 2026-11-05: from the performance logs of 1.1.6 and 1.2.0

#### Fix: images dropped from changed pages of prior versions
- In build 2026-11-03, a reused page registered its images in the
  document's image cache with their bytes only, without their format or
  size. A later, changed page of the same prior version that used one of
  those images (a logo, a letterhead) then failed to read it, and that
  page's images were dropped, with the findings that depend on them. On a
  325-file case this removed 2,186 image placements from 62 prior
  versions. Reused pages no longer write into that cache. Verification
  mode could not catch this, since it analyses every page in full; prior
  versions analysed with build 2026-11-03 without verification should be
  re-analysed. (`analysis/engine.py`)

#### Form XObjects analysed once per document
- The record of forms already analysed was reset on every page, so a form
  drawn on every page (a letterhead, a page template) was analysed again on
  each one: up to 2.9 s per page on some documents. Each form is now
  analysed once per document; later pages reuse its findings with their
  own image labels, the only page-specific part of them. Verification mode
  analyses each form every time and compares (forms_verified,
  forms_mismatch in the performance log). (`analysis/engine.py`)

#### Visual Overlay reports much faster
- Generating the per-document visual reports took nearly five hours on a
  325-file case: every layer variant opened the whole source PDF, edited
  one page and saved the whole document, which the renderer reopened. The
  source is now read from disk once per document, and a variant is written
  as a one-page PDF holding the edited page, with what its appearance can
  depend on elsewhere in the document (inherited page attributes, layer
  visibility, form-appearance settings). The one-page form is used for a
  page only after checking that the unedited one-page copy renders
  pixel-identically to the original page; otherwise that page uses the
  whole document as before. Layer images are saved with ordinary PNG
  compression rather than exhaustive optimisation (identical pixels).
  (`reports/reveal.py`, `reports/visual.py`)
- Each document's visual report is now timed in the performance log,
  identified by MD5, with its pages and how many used the fast path.

### Build 2026-11-03

### Prior versions: unchanged pages reused
- Prior versions took 58% of analysis time on a 325-file case, although
  most of their pages are identical to their parent's: an incremental
  update rewrites only the objects that change. Each page is now
  fingerprinted (a hash of the page object and every object it reaches:
  content streams, resources, fonts, images, annotations, form XObjects,
  and the attributes it inherits from the page tree). A prior version's
  page with the same fingerprint, page number and label numbering as a
  page already analysed in the same lineage reuses that page's results
  (images, transparency, findings, risk scores, fonts); its images are
  still written to the version's own folder. Any change in anything the
  page uses gives a different fingerprint, and the page is analysed in
  full. Results are snapshotted as soon as a page is finished and copied
  again when reused. (`analysis/page_reuse.py`, `analysis/engine.py`)
- Switches (environment variables): PDF_FORENSICS_PAGE_REUSE=0 analyses
  every page in full; PDF_FORENSICS_VERIFY_REUSE=1 also analyses each
  reused page in full and compares, counting matches and mismatches in
  the performance log and noting any mismatch in the session log.

### Performance log: one column per page detector
- The page detectors were timed together (half of all analysis time);
  each now has its own column (forms, image overlap, soft masks and
  off-page images, text overlays, content-stream overlays, text over
  text, redactions), plus page fingerprinting and reused pages, and
  counters for pages reused, verified and mismatched. Each analysis run
  records whether reuse and verification were on. (`perf.py`)

### Documentation
- Technical Reference Guide 5.2; README, "If processing is slow". All
  guides state version 1.2.0, build 2026-11-03.

## Version 1.1.6 — Release (2026-11-02, build 2026-11-02d)

No database schema change.

### Visual Overlay reports: one per document, with an index
- The Visual Overlay Report put every document's overlays into one HTML
  file, impractical with dozens or hundreds of documents. It is now one
  report per document that has overlay findings, in a folder beside an
  index page: {case}_visual-overlays_{timestamp}.html is the index, and
  {case}_visual-overlays_{timestamp}_files/ holds the reports, named
  NNN_{document name}_{first 8 characters of its MD5}.html (shortened and
  made Windows-safe when needed). Each report is the same page-by-page,
  layer-by-layer report as before.
- The index lists each document with its kind (submitted, or prior version
  N of its parent), overlays in total and by kind (text over text, white
  box, annotation), pages affected, document risk score and MD5, with
  sortable columns and a filter; Open report opens the document's report
  in a new tab. A document whose report could not be generated is shown as
  such. It carries the same classification banner, logos, case details,
  version, build, database name and database MD5 as the other reports.
- Case index: the Visual Overlay card opens the index and says how many
  documents it covers; every per-document report is listed with its MD5
  in the output manifest. The GUI shows which document is being rendered.
  (`reports/visual.py` `generate_visual_reports()`,
  `reports/case_index.py`, `gui/app.py`, `cli.py`)

### Image folders that Windows could not create
- A document's extracted images go into a folder named after it. A name
  ending in a space or a full stop (which Windows drops silently, so the
  folder got a different name from the one the application then wrote
  into), a character Windows forbids, a reserved device name (CON, NUL,
  COM1 ...) or a path beyond the Windows limit made the analysis fail
  with FileNotFoundError. Folder names are now made Windows-safe, and
  shortened with a hash of the original when the path would be too long;
  names that were already safe are unchanged. (`pathutil.py`
  `safe_name()`, `gui/app.py`, `analysis/engine.py`)

### Documentation
- Technical Reference Guide 7.4, HTML Reports guides (3.1), READMEs. All
  guides state version 1.1.6, build 2026-11-02d.

## Version 1.1.5 — Release (2026-11-02, build 2026-11-02c)

Performance. No database schema change; findings are unchanged.

### Build 2026-11-02c
- During a run every interactive control is now locked (file buttons, the
  PDF list, the processing choice and options, the database and output
  fields, Run and Back), and each is restored to its previous state when
  the run ends; only the log, its scrollbars and the counters stay live.
  In build 2026-11-02b only Run and navigation were blocked, so the PDF
  list could be cleared while the run was still reading it. (`gui/app.py`)
- Timeline Analysis (report and spreadsheet): the Raw value column now sits
  immediately before UTC (normalised), so each conversion can be checked
  at a glance. In the spreadsheet, UTC (normalised) is a real Excel
  date-time (dd-mmm-yyyy HH:mm:ss) rather than text, so it sorts, filters
  and calculates as a date. (`reports/queries.py`,
  `reports/timeline_xlsx.py`)


### Build 2026-11-02b: the window stays responsive
- Analysis, triage, reports and graphs ran on the window's own thread,
  which only redrew between steps and never handled input. After a few
  seconds Windows marked the window "Not Responding" and showed a frozen
  snapshot of an earlier document and page, while processing carried on;
  clicking made it worse, and long report queries froze it entirely. Runs
  now execute on a background thread, so the window keeps handling its
  events throughout. The run code updates the window as before: with a
  threaded Tcl (standard Python builds) tkinter passes those updates to
  the window's thread; with a non-threaded Tcl, runs execute as before.
- While a run is in progress, a second run cannot be started and the
  screen cannot be left; closing the window asks for confirmation, since
  the document being processed would not be saved (completed documents
  are). An error during a run is shown instead of being lost.
- The progress line shows the images written for the current document
  ("page 12/412 · 3,180 image(s) written"), updated about four times a
  second, so a long document visibly keeps moving. (`gui/app.py`,
  `analysis/engine.py` `image_callback`)
- Getting Started guide: the progress line and the run-time behaviour.

### Build 2026-11-02
- Status bar: a shorter status message left the end of the previous,
  longer one visible beside it. The message now spans the width of the
  bar and repaints its whole area on every change. (`gui/app.py`)
- README, "If processing is slow": storing images in the database is a
  significant cost on a slower drive, and is needed only for thumbnails
  in the reports and graph.


### Build 2026-10-29b: from the first performance log (325 files)

#### Reports up to a hundred times faster: database indexes
- The database had no indexes on the columns the reports join on, so
  reports that correlate findings, pages and analyses scanned whole tables
  for every row (Concealment Overview took 133 s, Document Comparison
  35 s, Document Risk Summary 27 s on a 693-analysis case). Twenty indexes
  are now created whenever a database is opened, so existing databases
  gain them too; they change no data.
- Indexes alone can make SQLite choose a slower plan (Document Risk
  Summary became four times slower in testing), so planner statistics
  (ANALYZE) are gathered at the end of each analysis run, while the
  database is being written anyway, and once before reports for a database
  that has none. On a synthetic case of the same size the five slowest
  reports went from 77 s to under 4 s in total, with identical results.
  (`database.py` `_INDEXES`, `refresh_statistics()`)

#### Malformed text no longer fails an analysis
- Two files failed with UnicodeEncodeError, one after five minutes of
  work. Malformed PDFs can contain text with unpaired UTF-16 surrogates
  (half a character); SQLite cannot store it and refused the whole save.
  Every database write now stores such characters as visible escapes
  (e.g. \udc8f), so the save succeeds and the examiner can still see
  what the PDF contained; the session log notes how many values were
  escaped. (`database.py` `SafeConnection`)

#### Performance log fixes
- Files skipped as identical copies of files already analysed were
  logged as "interrupted" with no MD5; they are now logged as "skipped
  (identical copy)" with the MD5.
- Case index regeneration was not logged (its session was passed by
  position); it now is.
- Memory read as "None" on Windows without psutil: the Windows memory
  call was made without its 64-bit handle types and failed silently.
- A failure now records where it occurred (module, function, line),
  still without the error message, which can contain file names.
- README: a removable (USB) drive is listed with network drives as a
  common cause of slow processing.

### Earlier in 1.1.5 (build 2026-10-29)

### Images extracted once per document
- The extraction cache and the database's image map were reset for every
  page, so an image placed on many pages (a logo, a letterhead, a page
  background) was extracted from the PDF, hashed, opened to read its EXIF
  and recorded once per page, and a copy of its bytes was held in memory
  for every page until the document was saved. Each image is now
  extracted, hashed and read once per document, and every placement shares
  one copy of its bytes. Each placement still gets its own file in the
  output folder and its own row in the database.
  (`analysis/images.py`, `analysis/engine.py`, `database.py`)
- Its EXIF metadata rows were also inserted once per page: duplicate rows
  in image_metadata. They are now written once per image.
- Camera and capture-date extraction runs once per image, so a photograph
  repeated across pages appears once in the timeline instead of once per
  placement.

### Prior versions reuse their parent's images
- A prior version usually contains most of its parent's images. Images
  are now cached across documents by content (the MD5 of the image's raw
  stream and its dictionary), so a prior version reuses identical images
  already extracted from its parent, and their EXIF metadata, instead of
  extracting and parsing them again. The cache holds up to 512 MB, least
  recently used first out, and is emptied at the start of each run.
- Prior versions are now processed immediately after their parent rather
  than at the end of the batch, so the parent's images are still cached
  (and the log reads in a natural order). (`gui/app.py`)

### New: performance log
- Each session writes `logs/performance_{timestamp}.log` beside the
  session log: system details (operating system, CPU count, memory,
  Python and library versions, whether the case folder is on a local or a
  network drive), the options of each run, one row per file with its
  size, pages, images, unique images, cache reuse, findings, revisions,
  memory and the seconds spent in each processing stage, and one line per
  report, spreadsheet, graph and case index generated. Triage runs are
  logged the same way.
- It contains no case number, file names or paths, so it can be shared to
  diagnose slow processing; files are identified by MD5, which matches the
  database and the case index. It is listed with the logs in the case
  index. (`perf.py`, `session.py`, and the timing points in the engine,
  triage, GUI, command line and report generators)

### Documentation
- Application README: "If processing is slow" (what the performance log
  holds and how to share it).
- All guides' covers state version 1.1.5, build 2026-10-29.

## Version 1.1.4 — Release (2026-10-22, build 2026-10-22g)

No database schema change.

### Paths written one consistent way
- On Windows, Tk's file and folder dialogs return forward slashes and
  os.path.join adds backslashes, so a path could be shown and recorded with
  both (for example O:/pdf-forensics/work\extracted_images). Windows
  accepts either, but paths are part of the forensic record, so every path
  is now normalised (absolute, native separators: O:\pdf-forensics\work\
  extracted_images) where it enters the application: file and folder
  dialogs, typed path fields when read (and shown normalised), command-line
  arguments, path-list files, and the case folder. Paths built from them
  are consistent too. Wildcards, bracketed exhibit prefixes and network
  (UNC) paths are preserved. (`pathutil.py`, `gui/app.py`, `cli.py`,
  `pathlist.py`, `session.py`)

### GUI: Processing mode as two choices
- The analysis screen had a "Triage mode" checkbox, ticked by default;
  unticking it enabled three analysis options that were otherwise greyed
  out and unticked. The choice is now made with two radio buttons under
  Processing: Triage (the default) and Full parsing. Selecting Full
  parsing reveals its three options and, below them, the database, which
  has moved from its own panel because only full parsing writes to the
  database. The options keep their settings while triage is selected.
  The Output folder stays visible in both modes, since triage writes its
  spreadsheet there. (`gui/app.py`)
- A note under the two options says what the selected mode produces:
  triage writes a spreadsheet only and nothing to the database; full
  parsing builds the case database and does not write a triage
  spreadsheet (run Triage separately for one). Full parsing could
  otherwise be mistaken for "triage plus more".
- The radio buttons are styled like the checkboxes. Without their own
  style they fell back to Tk's default, which painted a white box behind
  the selected option's label. (`gui/theme.py`)
- The counters are in two rows (Selected, Processed, Prior versions,
  Failed; then Copies, Locked, Images) on one grid, so the columns line
  up, and the window opens wide enough
  for the top row, measured from the widgets so it holds at any display
  scaling; seven counters on one row did not fit. (`gui/app.py`)

### Triage spreadsheets no longer overwrite each other
- Output names used the session's start time, so a second triage run in
  the same session (even on different files) wrote to the same file name
  and silently replaced the first spreadsheet. Each triage run's
  spreadsheet is now named with the time of that run, with _2, _3 ...
  added if two runs start in the same second. A file named with -o on
  the command line is used as given. Reports, which are regenerated from
  the same database, still replace their earlier copies by design.
  (`session.py` `make_run_path()`, `gui/app.py`, `cli.py`)

### GUI: a Prior versions counter
- Triage and analysis process the prior versions recovered from
  incremental updates, and counted them in Processed, so Processed could
  exceed Selected with no explanation (in triage it jumped at the end of
  the run to the number of spreadsheet rows). Processed now counts the
  selected files only, and a new Prior versions counter beside it counts
  the versions recovered from them, in both modes and after a retry. The
  triage completion line says so: "Done: 8 of 8 selected PDF(s) triaged,
  plus 3 prior version(s) recovered from them (11 rows in the
  spreadsheet)". (`gui/app.py`)

### Documentation
- Application README: new section "A caveat about metadata". The
  application reports what is written in the PDF, which may or may not be
  accurate, for reasons from anti-forensics to software that writes a
  field incorrectly or not at all; a document edited with several
  applications, or by software that omits fields, produces findings with a
  proper explanation.
- Getting Started guide: the processing choice, where the database is
  chosen, and the Prior versions counter.
- All guides' covers state version 1.1.4, build 2026-10-22g.

## Version 1.1.3 — Release (2026-10-22, build 2026-10-22f)

No database schema change. Re-analyse documents to apply the changes.

### ExifTool attribution: tied to each change, checked, and caveated
- 1.1.2 reported ExifTool's update marker and the metadata changes as
  separate findings, leaving the examiner to connect them by byte offset.
  The revision ExifTool wrote is now named in METADATA_REVISED ("written
  by ExifTool per its update marker") and labelled in the Timeline
  Analysis report and spreadsheet ("[written by ExifTool per its update
  marker]"), including in a silent-edit flag.
- Each %EndExifToolUpdate marker is checked against the file's structure:
  its number must equal the end of a revision, and the marker must sit
  inside the update that follows. Only then is that update attributed to
  ExifTool. A marker that fails (a number matching no revision boundary,
  or one that names the whole file as the original) is reported as not
  consistent with the file's structure, and nothing is attributed to it.
- Every report that attributes an update to ExifTool states the caveat:
  the marker is ordinary text that anyone could add, remove or alter, so
  it corroborates rather than proves which tool made a change. The
  findings and guides no longer call the marker a "definitive trace".
  (`analysis/doc_checks.py`, `analysis/timeline.py`, `reports/queries.py`)

### Documentation
- Technical Reference Guide 4.6 and risk-weight table; Risk Scoring and
  HTML Reports technical guides. All guides state version 1.1.3, build
  2026-10-22f.

## Version 1.1.2 — Release (2026-10-22, build 2026-10-22e)

No database schema change. Two new finding types are added to existing
databases automatically. Re-analyse documents to apply the new checks.
Prompted by a file edited with
`exiftool -PDFVersion="1.05" -Creator=... -Author=... -Producer=...`,
of which 1.1.1 reported only VERSION_CONFLICT.

### Version format: "1.05" is invalid, and no longer masks an anachronism
- Declared versions were read leniently, so ExifTool's XMP pdf:PDFVersion
  "1.05" counted as 1.5. That raised the highest declared version to 1.5
  and hid a genuine 1.5 anachronism (cross-reference streams under a 1.4
  header) that the same file's prior version still showed. A version must
  now be written as one digit, a dot and one digit (1.0 to 1.7, 2.0);
  anything else is VERSION_INVALID and excluded from the comparison.
  (`analysis/doc_checks.py`)

### Info vs XMP: six text fields compared
- METADATA_MISMATCH compared only Producer and the two dates. It now also
  compares Creator with xmp:CreatorTool, Author with dc:creator, Title with
  dc:title, Subject with dc:description and Keywords with pdf:Keywords,
  ignoring case, spacing and list separators; one finding per field.
  ExifTool's -Creator writes the Info Creator and XMP dc:creator (the
  author) and leaves xmp:CreatorTool unchanged; both disagreements are now
  reported.

### New: metadata changed by a later revision (METADATA_REVISED)
- Each revision's text metadata (Info dictionary and XMP) is compared with
  the revision before; every field added, changed or removed is listed
  with both values (MEDIUM, risk +15). A revision that changes metadata
  but keeps every modification date is called out as a silent edit.
- Timeline: the silent edit is also flagged there, on the unchanged
  modification dates of that revision. (`analysis/timeline.py`)

### New: ExifTool updates identified (EXIFTOOL_EDIT)
- ExifTool ends each update with `%EndExifToolUpdate` and the original
  file length. The marker is now reported (MEDIUM, risk +15), naming the
  prior version that is the original file, and the Incremental Updates
  report has an Editing Tool Identified column. (`reports/queries.py`)

### XMP arrays stored correctly
- XMP properties that are unordered lists (rdf:Bag, such as dc:creator in
  some files) were stored as Python set text, e.g. {'Steve Miller Band'}.
  They are now stored as plain text in analysis and triage.
  (`analysis/metadata.py`, `analysis/triage.py`)

### Documentation
- Technical Reference Guide: new section 4.6 (metadata changes across
  revisions, silent edits, ExifTool markers) with a table-of-contents
  entry; 4.4 (version format), 4.5 (silent edits); finding-type and
  risk-weight tables. Risk Scoring technical guide and HTML Reports
  technical guide updated. All guides state version 1.1.2, build
  2026-10-22e.

## Version 1.1.1 — Release (2026-10-22, build 2026-10-22d)

No database schema change (still revision 10). Re-analyse documents to
record their timelines revision by revision.

### Timeline Analysis: every revision listed in full
- 1.1.0 listed each distinct timestamp once, with the span of revisions
  in which it appeared ("revision 2 to current"). The checks did cover
  every revision, but the report did not show it: a prior version's
  timestamps had no rows of their own unless they changed, and the
  prior-version sections said only "included in parent". The timeline
  now lists every timestamp of every revision, including values
  unchanged from the revision before. (`analysis/timeline.py`)
- Each prior version's section lists the timestamps of its revision, with
  its own verdict (CONSISTENT or INCONSISTENT, as checked within its
  parent's timeline), so filtering on a prior version shows its place in
  the timeline directly.
- The parent's summary states the revisions examined, naming each by its
  extracted file ("revision 2 (..._version2.pdf)"), and explains any
  %%EOF marker that is not a revision (for example the first marker of a
  linearized file). The Revision column now follows the UTC column.
- A comment edited in a later revision is now checked against that
  revision's save as well as the revision where it first appeared.
- A problem that persists across revisions is reported once in the
  TIMELINE_INCONSISTENT finding, while every revision's row is flagged.
- Databases from 1.1.0 still display; their rows keep the old spans.
  (`reports/queries.py`)

### New: Timeline Analysis spreadsheet
- An Excel workbook with the same content, generated with the reports
  (GUI and command line) and listed under Spreadsheets in the case index:
  a timeline sheet (flagged rows and verdicts highlighted, filters,
  frozen header) and a summary sheet (one row per document: verdict,
  timestamps, flagged, timestamps assumed UTC). A note above each sheet
  states that all times are normalised to UTC. Rebuilt with the reports
  after a password retry. (`reports/timeline_xlsx.py`, `gui/app.py`,
  `cli.py`, `reports/case_index.py`)

### Documentation
- Technical Reference Guide 4.5, Risk Scoring technical guide 5.5, HTML
  Reports guides (Timeline Analysis report and the new spreadsheet);
  all guides' covers state version 1.1.1, build 2026-10-22d.

## Version 1.1.0 — Release (2026-10-22, build 2026-10-22c)

First feature release after 1.0. Database schema revision 10: a new
`timeline_events` table, added to existing databases automatically when
they are opened. Re-analyse documents to build their timelines.

### New report: Timeline Analysis
- Every timestamp in each submitted document, across all its revisions
  (each prior version recovered from an incremental update, and the
  current file), in chronological order. Sources: Info dictionary
  CreationDate and ModDate; XMP CreateDate, ModifyDate and MetadataDate;
  the XMP edit history (xmpMM:History); annotation /CreationDate and /M;
  digital signature signing times; embedded file dates; and photo EXIF
  DateTimeOriginal and DateTimeDigitized. Each distinct value is listed
  once with the span of revisions in which it appears.
- All timestamps are normalised to UTC, and the report says so. A value
  with no timezone is assumed to be UTC, compared and flagged like any
  other, and marked "none (assumed UTC)".
- Checks: created not after modified (Info, XMP, annotations, embedded
  files; photos digitised not before taken); creation date unchanged
  across revisions; modification dates never going backwards from one
  revision to the next; XMP history in order and not after the
  revision's last save; comments and signatures not dated before the
  document was created; a comment not dated after the save of the
  revision that added it; no revision saved after a signature but dated
  before it; no photo taken after the document's last modification; no
  date in the future or before 1993. Different sources allow 60 seconds.
- Each document opens with a SUMMARY row: CONSISTENT, INCONSISTENT,
  INCLUDED IN PARENT (prior versions) or NOT AVAILABLE (analysed before
  1.1.0). (`analysis/timeline.py`, `reports/queries.py`)
- New finding **TIMELINE_INCONSISTENT** (HIGH, risk +20), one per
  document, listed in the Document Risk Summary and counted in the
  Document Risk Dossier. An Info ModDate before the Info CreationDate in
  the current revision on its own is not counted twice (it is already
  METADATA_DATE_ANOMALY). (`analysis/engine.py`, `analysis/risk.py`,
  `database.py`)
- The Reports screen lists 22 reports; its checkbox rows are tighter so
  the list still fits a 1080p screen. (`gui/app.py`)

### Info vs XMP date columns
- The triage spreadsheet's pdf-metadata sheet and the PDF Metadata report
  have two new columns, CreationDate: Info = XMP and ModDate: Info = XMP:
  TRUE when both values denote the same moment within 60 seconds after
  conversion to UTC, FALSE (bold red in the spreadsheet) when they do
  not, blank when either is missing. (`analysis/triage.py`,
  `reports/queries.py`)

### EXIF capture dates
- EXIF extraction read only the main image directory, so DateTimeOriginal,
  DateTimeDigitized, their offsets and the other Exif sub-IFD tags
  (exposure, lens) never reached the EXIF & GPS report. They are now
  extracted. (`analysis/metadata.py`)

### Documentation
- Technical Reference Guide: section 4.3 explains the three places a
  version can be declared and how a metadata tool's edit lands in a later
  revision; new section 4.5 Timeline Analysis; a note in 4.2 on the Info =
  XMP columns; new Annex A, PDF Versions (each version's specification,
  publication date and main features, from the bibliographies of ISO
  32000-1 and 32000-2); table of contents entries for 4.4, 4.5 and Annex
  A (4.4 had none); finding-type and risk-weight tables.
- Risk Scoring technical guide: TIMELINE_INCONSISTENT weight; section 5.5
  Timeline Events (schema revision 10).
- HTML Reports guides: new Timeline Analysis section; PDF Metadata
  columns; Document Risk Summary list; report count 22. The plain-language
  guide's report table also gained its missing Encrypted Files row.
- All guides' cover lines, headers and footers state version 1.1.0, build
  2026-10-22c.

## Version 1.0.3 — Release (2026-10-22, build 2026-10-22b)

Third incremental update. No database schema change (still revision 9).
Two new finding types are added to existing databases automatically when
they are opened. The build marker carries a letter because 1.0.2 was
built the same day.

### Version checks: invalid and conflicting PDF versions
- A declared PDF version that does not exist was not reported. The
  Version Anachronism check only compared the declared version with the
  features present, and a file whose header and XMP were edited to 0.3
  passed if it used none of the features on its list. New finding
  **VERSION_INVALID** (HIGH, risk +25): any declared version (header,
  Catalog /Version or XMP pdf:PDFVersion) outside the published versions
  1.0 to 1.7 and 2.0.
- Invalid values no longer take part in the anachronism comparison. That
  comparison uses the highest declared version, so a fictitious high
  value (e.g. a header edited to 9.9) would have hidden any genuine gap.
- Versions are parsed whole: 1.10 was read as 1.1.
- New finding **VERSION_CONFLICT** (MEDIUM, risk +15): the XMP
  pdf:PDFVersion disagrees with the version in effect (the later of the
  header and the Catalog /Version), or a later incremental update added,
  changed or removed the XMP pdf:PDFVersion, or lowered, removed or
  invalidated the Catalog /Version. Metadata tools such as ExifTool append
  an update rather than editing the original bytes and cannot change the
  header, so an attempted version change left the header as it was and
  went unreported. The Detail lists each revision's declarations. Not
  reported: a Catalog /Version raised by an update (the standard upgrade,
  still reported as VERSION_MISMATCH) and an XMP version written by an
  update that equals the version in effect without lowering an earlier
  value. An invalid XMP value is reported once, as VERSION_INVALID. The
  revision comparison runs on submitted files, not on prior versions
  analysed in their own right. (`analysis/doc_checks.py`,
  `analysis/engine.py`, `analysis/risk.py`, `database.py`)
- The Version Anachronism report now lists all three finding types, with
  a new Type column, so every version problem is in one report. The
  Document Risk Dossier counts and lists the new types.
  (`reports/queries.py`)

### Case index: same-day build markers
- The case index read build markers as a strict date, so a build such as
  2026-10-22b would have been read as 2026-10-22 and its warning about
  outputs from more than one build would have missed it. It now reads the
  optional letter. (`reports/case_index.py`)

### Documentation
- Technical Reference Guide section 4.4 (comparison, invalid versions,
  conflicting declarations), finding-type and risk-weight tables; Risk
  Scoring technical guide (weights table); HTML Reports guides (Version
  Anachronism report, Dossier). All guides' cover lines, headers and
  footers state version 1.0.3, build 2026-10-22b.

## Version 1.0.2 — Release (2026-10-22, build 2026-10-22)

Second incremental update. No database schema change (still revision 9);
databases from 1.0.0 and 1.0.1 open unchanged.

### Command line: wildcards now work on Windows
- `analyze` and `triage` accept patterns such as `*.pdf`, but did not
  expand them: macOS and Linux shells expand a pattern before the program
  sees it, while Windows (cmd and PowerShell) passes it through unchanged,
  so `triage *.pdf` reported "*.pdf" as not found.
- Patterns containing `*` or `?` are now expanded by the application
  itself, the same way on every platform. Square brackets are matched
  literally first, so exhibit prefixes work (`"[010]*.pdf"`); only if that
  finds nothing are they treated as a character class. An argument that
  names an existing file is always used as is. A pattern that matches
  nothing is still reported as not found. Matches are sorted, a file
  already listed is not added twice, and each pattern's match count is
  printed and written to the session log. (`cli.py`)

### GUI: the Locked counter
- After a password retry opened a locked file, the Locked counter still
  counted it, and Processed and Images did not include it. Each file the
  retry opens now moves from Locked to Processed, with its images added,
  so the counters match the run summary.
- The Locked counter was not reset at the start of a run, so a run could
  start showing the previous run's locked files. It is now reset with the
  other counters.
- Triage never set the Locked counter; it now shows the files triage could
  not open, and is updated after the triage retry.
- The triage retry reused the main run's progress handler, which set
  Processed to the retry's own count (1, 2, …). It now logs its progress
  only, and afterwards Processed shows the rows in the merged spreadsheet.
  (`gui/app.py`)

### Documentation
- All seven in-app guides and the Technical Reference Guide: cover line,
  running header and footer now state version 1.0.2, build 2026-10-22.
- README files and release notes updated for 1.0.2; the application
  README's command-line section notes that wildcards work on every
  platform.

## Version 1.0.1 — Release (2026-10-21, build 2026-10-21)

First incremental update to 1.0.0. No database schema change (still
revision 9); databases from 1.0.0 open unchanged.

### Triage: PyMuPDF messages now written to the session log
- Build 2026-10-14 stopped PyMuPDF's parser messages (e.g. "corrupt object
  stream") printing to the terminal and wrote them to the session log
  instead, but only analysis wrote them to the log. During triage they
  were suppressed from the console and then either never logged or logged
  later against the next file analysed in the session.
- Triage now writes them to the session log after each file and after
  each prior version it triages, labelled with the file they came from
  (e.g. `[triage: [001.1] Example Bank Letter_version1.pdf]`). Messages
  left over from earlier processing in the session are logged first,
  labelled "before triage", so they are not attributed to the first file
  triaged.
- Logging only; analysis is unchanged. (`analysis/triage.py`)

### Triage: prior versions of encrypted files now use the password list
- Triage reconstructs each prior version in memory and triages it, but did
  not pass on the run's password list or the password that opened the
  current version. A prior version of a file that needs a password
  (an incremental update to an encrypted file is encrypted in the same
  way) therefore could not be opened: its metadata was missing from the
  spreadsheet, and its Encryption Status read "Not opened — no password
  list supplied" even when a list had been supplied and had opened the
  current version.
- A prior version is now tried first with the password that opened the
  current version, as analysis already does, then in the usual order
  (empty password, passwords already found this run, the supplied list).
  The Encryption Status shows "Opened with the parent document's password"
  when that password opened it, and the Password column shows the password.
- A prior version that still cannot be opened is now also noted in the
  session log as an encrypted, unopened prior version. The end-of-run
  retry prompt offers the files whose current version could not be
  opened; a prior version that stays locked although its file opened is
  reported but not offered for retry.
- Changes triage results: prior versions of encrypted files that were
  previously reported as not opened can now be opened and their metadata
  read. Re-run triage on affected cases. Analysis was not affected; it
  already tries the parent's password on prior versions.
  (`analysis/triage.py`)

### Triage: the end-of-run retry is merged into the spreadsheet
- When triage met encrypted files it could not open, the end-of-run prompt
  (GUI) offered to re-triage them with a password list. That re-triage
  saved to the same file as the main run, so it replaced the whole triage
  spreadsheet with one holding only the re-triaged files, without their
  prior versions; the other files' rows and the comments sheet were lost.
  The log then advised re-running triage on the full set to "refresh" the
  spreadsheet that had already been overwritten.
- The re-triage is now merged into the main spreadsheet. The rows for each
  re-triaged file (current version, prior versions and comments) are
  replaced in place, in their original position, and every other row is
  kept unchanged. A file whose re-triage produces no row keeps its earlier
  rows, and if no file can be re-triaged the spreadsheet is left
  untouched. The re-triage includes prior versions whenever the main run
  did. The session log records the merge (files re-triaged, rows replaced,
  rows now in the spreadsheet), and the spreadsheet is listed once in the
  session's outputs. (`analysis/triage.py` `run_triage(run_state=...)`,
  `gui/app.py`)

### Triage: comments from opened encrypted files
- Triage extracted reviewer comments by opening each file without a
  password, so no comments were ever read from an encrypted file that
  needs one, even after triage had opened it. Comments are now extracted
  with the password that opened the file (or prior version). Files that
  could not be opened are skipped quietly, as they are already reported
  as not opened. (`analysis/triage.py`)

### Triage: no crash when nothing could be triaged
- When no file produced a row, `run_triage()` returned three values where
  every caller expects four, which would have raised an error in the GUI
  and on the command line. It now returns four values, writes no
  spreadsheet, and leaves an existing one unchanged. (`analysis/triage.py`)

### Documentation
- All seven in-app guides and the Technical Reference Guide: cover line,
  running header and footer now state version 1.0.1, build 2026-10-21.
  The Risk Scoring technical guide's introduction names v1.0.1.
- Six in-app guides (01a, 01b, 02a, 02b, 03a, 03b) stated "Released under
  the MIT License" on the cover. The application is licensed under the
  Apache License, Version 2.0 (see `LICENSE`); the covers now say so, as
  00 Getting Started already did. No licensing terms changed.
- Technical Reference Guide: the authorship section said the repository
  was private during the beta review period; it is now public, and the
  Guide says so.
- README files and release notes updated for 1.0.1. The application
  README's Encrypted PDFs section now states how prior versions of
  encrypted files are opened, that the triage retry updates the same
  spreadsheet, and that comments are read from opened encrypted files. The version comments
  in `pdf_forensics/__init__.py` now describe the release policy instead of
  the pre-release one.

## Version 1.0.0 — Release (2026-10-21, build 2026-10-20)

First frozen release. The application code is build 2026-10-20 unchanged;
this release adds the README and release notes. Highlights of what 1.0
contains:

- Forensic analysis of PDFs: text overlays (annotations, stacked
  box-and-replace annotations, white boxes with painted text, text over
  text), image overlap/off-page/soft-mask concealment, DPI anomalies, font
  consistency, version anachronism, unapplied redactions, signature
  coverage and structural integrity.
- Metadata, creator/producer, XMP and timeline analysis; incremental-update
  analysis with validated prior-version extraction and analysis.
- 21 HTML reports, the Visual Overlay Report (verified, toggleable layers),
  relationship graphs, triage and Document Risk Overview spreadsheets, and
  the case index with an output manifest.
- Every submitted file accounted for (analysed, identical copy, encrypted
  and not opened, failed, not found), with duplicates noted on all reports.
- Encrypted PDFs opened with an examiner-supplied password list, recorded
  in the Encrypted Files report.
- Recorded disclaimer acknowledgement; version and build on every output;
  complete session logging.
- Seven in-app guides and the standalone Technical Reference Guide (v1.2),
  all stating build 2026-10-20.

Verified by the author on real case material before release, including
password-list decryption, prior-version validation, long and bracketed
file names, and duplicate handling.

### Documentation errata corrected at re-issue
- The database is at schema revision 9. Revision 9 was introduced with
  build 2026-10-14 and added the `encryption` table: one row per encrypted
  file handled in a run, recording whether it was opened, the password
  that worked and its source, the encryption scheme, the number of
  passwords tried, and the linked analysis. It feeds the Encrypted Files
  report. The bump was not recorded in this CHANGELOG at the time, so the
  header line above, the release notes and the Technical Reference Guide's
  architecture table stated revision 8. All three now state revision 9.
- Risk Scoring technical guide (01a): added section 5.4, Encryption Record
  (schema revision 9), with the table's columns.
- Documentation only; no code change. Databases created by build
  2026-10-14 or later already have the table, and older databases gain it
  automatically when opened.

## v1.0.0 — Update (2026-10-20)

### Prior versions: false positives and invalid fragments no longer extracted
- Every %%EOF marker before the last was treated as the end of a prior
  version. In a linearized ("fast web view") PDF the first %%EOF ends the
  first-page section near the start of the file (often with startxref 0),
  so these files produced a "prior version" of a few hundred bytes that is
  not a PDF. For an encrypted file the fragment also carried the /Encrypt
  entry and was reported as a password-protected version that could not be
  opened. In one test batch every reported prior version was such a
  fragment.
- New classify_prior_versions (metadata.py) validates each candidate: its
  startxref must point to a cross-reference section inside the bytes, and
  the bytes must open without recovery and contain at least one page.
  Outcomes: valid; password-protected (structurally valid, needs a
  password; the parent document’s password is tried first); not a prior
  version (linearized first-page section); not a usable prior version
  (with the reason). Only valid and password-protected versions are
  extracted, triaged or analysed; the others are logged with the reason.
- Triage: a new Prior-Version Check column on each file’s row explains
  how each %%EOF marker was treated. Triage also now checks encryption on
  the bytes being triaged; a prior version previously inherited its parent
  file’s encryption status.
- Analysis passes the parent document’s password into version
  extraction.

### Case index: encrypted outcomes counted and labelled correctly
- A prior version that could not be opened was recorded as a submitted
  file rather than as a prior version, inflating the submitted count. The
  encryption step now records whether the file is a prior version.
- "encrypted_unopened" is shown as "Encrypted — not opened (password
  required)" and counted in the summary line, which previously did not add
  up when such files were present.
- When the end-of-run retry opens a locked file, its existing record is
  updated to "analysed" instead of a second record being added.

### Documentation
- Technical Reference Guide 5.2 (validation of prior versions) and Getting
  Started (Prior-Version Check column). All documents state build
  2026-10-20.

## v1.0.0 — Update (2026-10-15b)

### Case index: prior versions with bracketed names now listed
- Extracted Material showed "0 prior version(s)" for every document even
  when versions were on disk. The index listed each version folder’s
  files with glob, but an exhibit number like [010] in the folder name is
  a glob character class, so the pattern matched nothing. Directory paths
  are now escaped (glob.escape) in every index scan, so names containing
  square brackets are listed correctly. The same escaping was applied to
  the report-rebuild scan in the GUI.

### Duplicate (identical-copy) documents flagged on all reports
- A document not analysed because it is a byte-identical copy of another
  (e.g. [025] identical to [010]) appeared only in the case index
  overview and the Duplicate Submissions report. On other reports it was
  simply absent, which could read as the document having been missed.
- Every per-document report now carries a note when the database contains
  such copies: how many there are, an example (which file is identical to
  which), that they were recorded as duplicates rather than re-analysed
  and were not missed, and a pointer to the Duplicate Submissions report.
  The note is omitted from the Duplicate Submissions report itself and
  when there are no duplicates (and on databases predating the
  submissions record).

## v1.0.0 — Update (2026-10-15)

### Prior-version extraction: Windows long-path failure fixed
- Extracted prior versions were not written for documents with long
  names in a deeply nested case folder. The document name appears twice
  in the path (the "<name>_versions" folder and each
  "<name>_versionN.pdf" file), which on top of a deep path (e.g. a
  OneDrive case folder) exceeded the Windows 260-character limit. Python
  reported the write as succeeding, but pikepdf/PyMuPDF could not reopen
  the over-limit path, so analysis of the version failed with "No such
  file or directory", the version folder appeared empty, and the index
  showed the version as a failed submission. Short-named documents were
  unaffected; triage still listed the versions because it reconstructs
  them in memory rather than on disk.
- extract_prior_versions now keeps the path within the limit: when the
  full name would not fit, it shortens the base used for the folder and
  files and appends a short hash of the original name for uniqueness,
  preserving the "_versionN.pdf" suffix used to identify the version.
  Short names are unchanged. Writes are now wrapped so a version that
  still cannot be written is logged and skipped rather than queued as a
  non-existent file (which had produced a spurious "failed" row).
- Re-run analysis on affected cases to extract the versions that were
  missed; the spurious failed-submission rows will not recur.

## v1.0.0 — Update (2026-10-14)

### Encrypted-PDF fixes from field testing
- Triage now detects encrypted PDFs. Detection used PyMuPDF opening the
  file from a byte stream, which fails on imperfect-but-readable files, so
  locked documents were missed and no password prompt appeared. Triage now
  uses the same pikepdf-based detection as analysis (which also identifies
  permissions-only encryption), accepts a password list (GUI "Password
  list…" button, CLI -p/--password-list), opens files the list can open
  and reads their metadata with the password, and offers the same
  end-of-run prompt. Two columns were added to the triage spreadsheet:
  Encryption Status and Password.
- Encrypted Files report no longer goes stale after the end-of-run
  retry. When the prompt opens locked files after the main run, the
  reports already generated for that database are now rebuilt (previously
  only the case index was refreshed), so the report reflects the files the
  supplied password opened instead of still showing "no password list
  supplied".
- PyMuPDF messages (e.g. "corrupt object stream") no longer print to the
  terminal. They are suppressed from the console and written to the
  session log instead, so the record is kept without alarming output.
- The analysis window is taller so the Run button is not clipped after the
  password-list row was added.

## v1.0.0 — Update (2026-10-13c)

### Technical Reference Guide: Encrypted PDFs is now its own section
- The Encrypted PDFs material was numbered 9a (a sub-number) and so did
  not appear in the table of contents. It is now section 10 in its own
  right, with sub-sections 10.1-10.4, listed in the table of contents.
- Former sections 10-16 are renumbered 11-17 (Risk Scoring Model is now
  11; SQLite Query Reference is now 17), with their sub-sections,
  heading bookmarks and table-of-contents entries updated to match.
- Internal cross-references updated accordingly: former Chapter 12
  (Counter-Verification) is referenced as Chapter 13, and former
  Sections 12.3/12.4/12.5 and 15.5 as 13.3/13.4/13.5 and 16.5.
  References to ISO 32000-2:2020 clauses (e.g. §14.3.3) are unchanged.

## v1.0.0 — Update (2026-10-13b)

### Encrypted PDFs: open with a supplied password list
- When a submitted PDF is password-encrypted, the application now tries
  to open it using a text file of candidate passwords the examiner
  supplies. Not a password cracker: one attempt per supplied password, in
  order, stopping at the first that works; no guessing or brute force; the
  file is only opened for reading and never modified.
- Order per file: the empty password (opens permissions-only files),
  then passwords already found this run (most-recent first), then the
  supplied list in order. A password that works is promoted to the front
  of the known-good list for the files that follow. Soft limit of 1,000
  with a warning. Passwords read verbatim (leading/trailing spaces and a
  leading # are part of the password; no comment lines); UTF-8/UTF-16/
  Windows encodings detected.
- Permissions-only encryption is now detected (via the /Encrypt
  dictionary) even though such files open with the empty password;
  previously they were treated as unencrypted and not recorded.
- Five recorded outcomes per file: not encrypted; opened with no
  password; opened with a supplied password; not opened (no supplied
  password worked); not opened (no password list supplied) — the last
  two kept distinct so a reviewer can tell a file was never attempted
  against a list.
- New Encrypted Files report (Document Overview & Provenance; 21 reports
  now): every encrypted PDF, its status, the password that opened it
  (shown verbatim, as evidence and a repeatable step), the source, the
  scheme and the attempt count. The report header carries a visible
  caution that it contains passwords. A database analysed before this
  build shows an explanatory row.
- GUI: a "Password list…" button and a Locked counter; locked files are
  set aside and, at the end of the run, the application offers to try a
  password list on just those files and analyse any it opens (so a batch
  never stops to wait mid-run). CLI: -p / --password-list on analyze and
  triage; with no list, locked files are recorded as "no list supplied".
- The successful password, the list file path and the list MD5 are
  written to the session log; the password list itself is not stored and
  is not kept between cases.
- Documentation: Technical Reference Guide chapter 9a (Encrypted PDFs),
  architecture table (passwords.py) and section 13.1; HTML Reports
  technical 2.5.1 and plain-language 2.21; Getting Started.

## v1.0.0 — Update (2026-10-13)

### Text-over-text detector: OCR spacing no longer reported
- On OCR-converted documents (a scanned page converted into real text over
  a background image), the OCR application squeezes each recognised word
  into the width it had on the scan, so neighbouring letters overlap. The
  text-over-text check compared every character with every nearby
  character and reported these neighbours as text drawn over text: in one
  case every finding on two documents was a letter overlapping the next
  letter of the same word or label (e.g. "UN" under "NI" in "UNI...").
- Fix: each extracted line is divided into runs wherever the drawing
  position steps backwards; within a run, a character drawn later and
  further along the line is the next character of the same text, however
  tightly spaced, and the pair is skipped. Text drawn over existing text
  is still compared: it appears as a separate line, or steps back within
  the line and starts a new run (including overprinting offset from the
  original). The faux-bold / drop-shadow exclusion is unchanged.
- Tested against squeezed words, compressed placeholders, unmappable OCR
  glyphs, words or letters drawn as separate pieces and vertical text
  (all reported by build 2026-10-09, none now), and against text drawn
  separately over old text, text redrawn over itself within one line, and
  the same offset by a third of a letter (all still reported).
- Re-analyse documents processed with earlier builds to clear these
  findings and their effect on the document risk score.
- Documentation: Technical Reference Guide 7.3.1 (new exclusion) and
  section 11 (OCR-converted documents, including what to check instead);
  HTML Reports technical 2.16. All documents now state build 2026-10-13.

## v1.0.0 — Update (2026-10-09b)

### Fictitious example names
- Example file names, paths and reference numbers in the guides, code
  comments, report descriptions and this CHANGELOG were taken from a real
  case. All are replaced with fictitious ones, e.g.
  D:\Cases\2026-EXAMPLE\Source\[001.1] Example Bank Letter.pdf and
  [001.2] / [002.1] Invoice 0000123.pdf. Affected: Getting Started (section
  4), HTML Reports technical (2.20) and plain-language (2.20), the
  Duplicate Submissions report description (shown in the report and the
  case index), database.py comments and earlier CHANGELOG entries.

## v1.0.0 — Update (2026-10-09)

### PDF selection lists (From list, -l / --pdf-list)
- One shared reader (pdf_forensics/pathlist.py) for the GUI From list
  button and the command-line --pdf-list option of analyze and triage.
- Quoted paths now load. File Explorer's "Copy as path" wraps each path
  in quotation marks; these (and typographic quotes) are removed.
  Previously every quoted line was counted as not found.
- Text encoding is detected from the file: UTF-8 with or without a
  byte-order mark, UTF-16 (e.g. Excel "Unicode Text"), or the Windows
  legacy encoding. Previously the list was always read in the Windows
  legacy encoding, so paths with accented characters in a UTF-8 list (the
  current Notepad default) were not found, and UTF-16 lists failed.
- A line copied from several spreadsheet cells (tab-separated) is
  accepted: the first cell that is an existing file is used.
- Duplicates are detected regardless of slashes or letter case.
- Paths not found are listed by name (GUI message and console), not just
  counted, and every one is written to the session log.
- The session log records each list loaded: its path and MD5, the
  encoding detected, and the counts added, ignored and not found.

### Disclaimer acknowledgement record
- The acknowledgement now records when it was given (with time zone),
  the Windows user, the computer, the disclaimer version (first 12 hex
  characters of the SHA-256 of the disclaimer text shown) and the
  application version and build. Previously only a true/false flag was
  stored.
- Every session log header states the acknowledgement on record, or
  that none is on record (command-line runs display the disclaimer but
  do not ask for acknowledgement).
- Users are asked again if the disclaimer wording changes. Users who
  acknowledged under the old true/false flag are asked once more so that
  a record is created; the dialog explains why.

### Documentation
- Getting Started section 3 (acknowledgement record) and section 4 (From
  list: quotes, encodings and spreadsheet cells accepted; missing paths
  shown and logged; the "without quotation marks" caveat removed).
  Technical Reference Guide section 13.1: the acknowledgement and
  selection-list records. All documents now state build 2026-10-09.

## v1.0.0 — Update (2026-10-08i)

### Getting Started guide
- Section 3: the disclaimer acknowledgement is stored in the user’s
  .pdf_forensics_config.json, so it is shown once per Windows user
  account, not once per computer.
- Section 4: documents the existing "From list" button (one full path per
  line; blank and # lines ignored; duplicates added once; missing paths
  counted) and the triage-first workflow: triage everything, copy the
  triage spreadsheet’s Path column for the files that warrant full
  analysis into a text file, load it with From list.
- Section 6: the command-line -l / --pdf-list option for analyze and
  triage.

## v1.0.0 — Update (2026-10-08h)

### Documentation brought in sync with build 2026-10-08
- Every guide now states on its cover the application version and build
  it applies to ("Applies to PDF Forensics Suite v1.0.0, build
  2026-10-08"), dated October 8, 2026. The standalone Technical Reference
  Guide is revised to Version 1.2 and its running footer, which still read
  "v1.0 — June 2026", now carries the version and build.
- HTML Reports (technical): report count corrected to twenty; new
  sections 2.16-2.20 for Text Overlay Detection, Font Consistency
  Analysis, Document Comments, Concealment Overview and Duplicate
  Submissions, with SQL and columns taken from the report definitions; new
  chapter 3 (Visual Overlay Report, Document Risk Overview spreadsheet,
  case index, submitted-files record). Later chapters renumbered.
- HTML Reports (plain language): counts corrected (the guide said both
  sixteen and eighteen); overview table extended from 12 to 20 reports;
  plain-language sections for the five reports above and a new chapter on
  the visual report, risk spreadsheet, case index and file accounting.
- Getting Started: identical-copy handling, the run summary and Copies
  counter, the case index as the starting point, and Copy path.
- Risk Scoring (technical): how overlays are counted (a white box with
  painted text scores once; stacked annotations score separately); schema
  sections for revision 7 (lineage columns) and revision 8 (submissions).
  Risk Scoring (plain language): "one change is counted once".
- Graph Reports (both): graphs appear in the case index, which refreshes
  after each graph run; each graph records its build.
- Technical Reference Guide: architecture table (schema revision 8, twenty
  reports, reveal.py role, new rows for visual.py, case_index.py and
  risk_overview.py); 7.1.1 stacking rule and /Stamp; 7.2.1 white-box
  consolidation; 7.3.2 worked example corrected (threshold 0.55, one
  finding per cluster; it said 0.8 and one per pair); 7.4 rewritten (it
  described colour-coded boxes, zoomed crops and a before/after toggle);
  10.2.2 counting note; 13.1-13.3 build date, submitted-files record and
  output manifest; 15.6-15.9 quick-start steps updated.

### Application text
- The Text Overlay Detection report described itself as covering only
  annotations with an opaque background. Its description (shown in the
  report header and on the case index) now covers all three kinds,
  including stacked annotations and white boxes reported once per box.

### Remaining step
- Tables of contents must be refreshed in Word (right-click the table of
  contents, Update Field, Update entire table) for the new and renumbered
  sections to appear in them.

## v1.0.0 — Update (2026-10-08g)

### Every submitted file is now accounted for (schema revision 8)
- Problem: with "Skip PDFs already in the database" on (the default), a
  file byte-identical to one already analysed was skipped with only an
  on-screen note. It was not written to the session log, not counted in
  the run summary and not recorded in the database, so the submitted
  filename appeared nowhere in the case record. In one case, 12 files
  were submitted, 6 were identical copies, and the case index reported
  "Documents analysed: 10" (6 documents plus 4 prior versions) with no
  trace of the copies.
- New submissions table records every file submitted for analysis with
  its outcome: analysed; identical copy of a file already analysed (with
  the file it matches); failed (with the error); or not found. Recorded
  in the GUI and command line, for original files and prior versions.
- Session log: each skipped copy is logged with the file it matches, and
  each run ends with a summary line, e.g. "12 submitted: 6 analysed, 6
  skipped as identical copies of files already analysed, 0 failed; plus
  4 prior version(s) extracted and analysed". The GUI run summary uses
  the same wording and gains a "Copies" counter.
- Case index Overview: "Documents analysed" is replaced by "Submitted
  files" (the reconciliation above, with an expandable list of every
  submitted file, its outcome and MD5) and "Analyses in database" (e.g.
  "10 (6 submitted documents + 4 prior versions)"). Databases analysed
  before this build show the analyses breakdown and state that submitted
  files were not recorded.
- New report: Duplicate Submissions (Cross-Document & Review). Same
  content, different name: byte-identical files submitted under
  different filenames. Same name, different content: files whose names
  match once a leading reference such as "[001.2]" is ignored but whose
  content differs. Prior versions are excluded. On a database analysed
  before this build it shows an explanatory row rather than an empty
  table, so it cannot be read as "no duplicates".
- Existing databases gain the (empty) submissions table on next open;
  re-run the analysis to record submissions for an earlier batch.

## v1.0.0 — Update (2026-10-08f)

### Case index: Copy path instructions
- The Copy path note and tooltip no longer suggest pasting into Excel’s
  File > Open dialog. In testing, a pasted full file path failed there
  ("You can’t open this location using this program"), while Win+R and
  the File Explorer address bar both opened the original file. The note
  now names only those two.

## v1.0.0 — Update (2026-10-08e)

### Case index: spreadsheets and databases
- Clicking a spreadsheet in the case index prompted to save it instead of
  opening Excel. Browsers will not launch desktop applications from a web
  page; they can only download file types they cannot display. Setting the
  browser to "always open" .xlsx files is not a fix for case work: Chrome
  and Edge open a copy saved to the Downloads folder, not the original.
- Spreadsheets (.xlsx/.xls/.csv) and databases (.db) now show a "Copy path"
  button instead of a link, with a note explaining why. The copied full
  path can be pasted into Excel (File > Open), the File Explorer address
  bar or Win+R to open the original file in place. The path is worked out
  when clicked, from the index’s own location, so it stays correct if the
  case folder is moved or copied; Windows drive, network share (UNC) and
  macOS/Linux paths are handled. Logs keep their Open link and also get
  Copy path. HTML reports, PDFs and image folders open in the browser as
  before.

## v1.0.0 — Update (2026-10-08d)

### Case index at the root of the case folder
- The report index is replaced by a case index, {case}_index.html, at the
  root of the case folder (next to the databases). It links to every
  output for the case: forensic reports, the visual overlay report,
  relationship graphs, the triage and risk-overview spreadsheets,
  extracted images, prior versions, session logs and databases.
  Previously the index lived in reports/ and covered only the catalogue
  reports, graphs and the risk overview; the visual overlay report and
  triage spreadsheet were missing from it.
- Layout: one self-contained HTML file with a sidebar menu (Overview,
  Forensic Reports, Visual & Graphs, Spreadsheets, Extracted Material,
  Logs & Provenance). No frames, server or external libraries; works from
  local disk or a zipped folder. Each section has its own address
  (#reports etc.). Reports open in a new tab as standalone exhibits.
- Outputs are grouped by the analysis database they came from, read from
  the file itself (so a report generated in a later session is filed
  under the database it was built from). The latest database is shown by
  default with a selector for earlier ones. Each output shows the build
  that produced it, and the overview warns when one database’s outputs
  come from more than one build. Outputs whose database is not in the
  folder are listed separately.
- Output manifest: size and MD5 of each database, report, graph,
  spreadsheet, log and prior version at the time the index was built.
  Extracted images are counted per folder, not hashed individually.
  Hashes are cached (.pdf_forensics_index_cache.json) by size and
  modification time so unchanged files are not re-hashed.
- The index is rebuilt automatically after every operation that writes to
  the case folder: analysis, triage, HTML reports and graphs, in both the
  GUI and the command line, through one function (refresh_case_index)
  that never interrupts the operation if it fails.
- Ordering and "Generated" times use the session timestamp in each
  filename, which survives copying the case folder (file modification
  times do not).
- Session logs now record the build ("Build: YYYY-MM-DD") in their header,
  and the visual overlay report now states its build like every other
  report. The visual report filename is now "visual-overlays" from both
  the GUI and the command line (the command line used "visual_overlays").
- reports/index_page.py removed; any {case}_index.html left in reports/ by
  an earlier build is removed when the case index is written.

## v1.0.0 — Update (2026-10-08c)

### Report index: always current, one file
- Removed the "Rebuild index" button from the HTML Reports tab. It was
  redundant (the index is rebuilt automatically at the end of every report
  run) and it pushed the visual-report option out of view in the window.
- The index is now also refreshed automatically after graph generation
  (GUI and CLI), since it lists graphs under "Other Artifacts". This was
  the one case the button covered.
- The index is written to a single stable file, {case}_index.html, and
  overwritten on each refresh. Previously each rebuild wrote a new
  timestamped file, so the reports folder accumulated several indexes.
- When not told which Document Risk Overview spreadsheet to link, the
  index links the newest one in the reports folder.

## v1.0.0 — Update (2026-10-08b)

### Visual overlay report: white-box alterations shown step by step
- A white-box alteration is still counted as ONE finding (database, risk
  score and tabular reports are unchanged), but the visual report now
  shows its component edits as separate, toggleable steps: the white box
  itself, then each line of text painted on it, labelled 1a, 1b, 1c...
  under an "Alteration 1" heading. Each painted line is labelled with its
  text where the font encoding allows (e.g. "PAYEE : EXAMPLE TRADING
  LTD"); otherwise it is labelled "Painted text" with a note.
  Previously the box and its text were a single layer, so the report
  could only show the final page or the original, not the painted text.
- This lets the examiner see every state: the original; the blank box
  hiding it; the painted text alone over the original (box unticked);
  any single line on the box; and the final page.
- How the layers are built: the box layer is the box rendered on its own
  compared with the original; each text layer is the box plus that line
  compared with the box alone. Measuring text against the box captures
  painted glyphs completely, including where they sit directly on top of
  original text of the same colour. The existing self-check (all layers
  must reproduce the page as received) still applies.
- reveal.py: new white_box_components() identifies the fill operations
  and the painted-text operations of an inline white box, grouping the
  text into lines; build_revealed_pdf_bytes() gains keep_ops to leave
  chosen operations in place. Operations are identified by stream
  position in walk order, which is stable across separate opens. White
  boxes wrapped in a container Form XObject together with their text are
  still shown as a single layer.

### Documentation (queued, not yet updated)
- Section 7.4 of the Technical Reference Guide must also describe the
  step-by-step display of white-box alterations.

## v1.0.0 — Update (2026-10-08)

### Visual overlay report: correct rendering of white-box alterations

A white box drawn over original text with new text painted on it was
rendered incorrectly: the "all overlays shown" view did not match the
page as opened in a PDF viewer, and the "all removed" view deleted
genuine original text. Three causes, three fixes.

- One alteration was reported as many. Text extraction still returns the
  original glyphs hidden under a white box, so the text-over-text detector
  also fired on the new text, and its 25-pt clustering split one replaced
  block into many findings (one real case: 1 white box + 11
  text-over-text). New merge_text_over_white_box() folds any
  text-over-text cluster with >= 80% of its area inside a white box into
  that single white-box finding, preserving the original-vs-painted glyph
  samples in its detail. Applied in the analysis engine (so the database,
  Text Overlay report, Dossier, Concealment Overview and risk score count
  one edit) and again in the visual report (so databases analysed before
  this build also render correctly).
  NOTE: document risk scores change for affected files on re-analysis
  (e.g. a page previously capped at 100 by many duplicate TEXT_OVERLAY
  findings now scores 35 for one white-box alteration). This is a
  correction. Re-analyse to update counts and scores.
- The text-over-text removal deleted genuine text. reveal._decide_text_inline
  kept only the earliest-drawn text in a region and dropped everything
  later, regardless of source, so multi-line regions lost original lines.
  It now treats the stream (page content or Form XObject) that drew the
  earliest text as the underlying layer, keeps all of its text, and drops
  only text from a different stream drawn after it. When all text in a
  region comes from one stream it skips the region and reports it as
  skipped rather than guessing.
- Unverified reconstructions were shown as fact. The reveal step reports a
  destructive removal as a success, so a per-overlay "isolated" flag could
  not catch this. Replaced with a self-check: the base plus all overlay
  layers must reproduce the page as received (within the overlay areas).
  If it does not, the page is shown exactly as received, the overlay
  toggles are disabled, and the reason is stated on the page. When it does,
  the page renders as layers as before, and with every overlay ticked the
  as-received render itself is displayed, so the opening view always
  matches what a PDF viewer shows.
- Layer isolation now measures pixel change by per-channel maximum rather
  than luminance; luminance under-weighted blue, so e.g. dark-blue text
  painted over black text could be dropped from its layer.

### Visual overlay report: markers
- New "Show numbers & lines" checkbox per page hides every badge, anchor
  dot and leader line, to view (or print) the page unobstructed.
- Unticking an overlay now also hides its leader line (previously only the
  badge was hidden, leaving a stray line on the page).
- Printing now shows the page exactly as toggled on screen (a print rule
  that forced every overlay layer visible was removed).

### Documentation (not yet updated; queued)
- Technical Reference Guide section 7.4 still describes colour-coded boxes
  drawn on the page, zoomed crops and a before/after toggle; the report now
  uses verified per-overlay layers, toggles and draggable badges.
- The in-app HTML Reports guides do not describe the visual overlay report.

## v1.0.0 — Update (2026-10-06d)

### Report index page, Concealment Overview, and risk overview sheet
- New Report Index page: a single catalogue-complete landing page a
  reviewer opens to navigate a case. It lists EVERY report grouped by
  category, marks each as generated (with a link that opens in a new
  tab and a timestamp) or not-yet-generated, and carries the same
  case/agency banner as the individual reports. Aggregate reports show
  "Combines: …" and detail reports show "Also summarized in: …", a
  many-to-many relationship expressed in words rather than a numbering
  scheme. Written/refreshed automatically at the end of every report
  run and via a new "Rebuild index" button (GUI); the index is a
  navigation aid, not evidence.
- New Concealment Overview report (aggregate, summarize-and-link): one
  row per document combining the two concealment mechanisms —
  image-over-image overlaps (incl. full-concealment count) and
  annotation/box-over-content overlays, plus unapplied redactions —
  so a reviewer has one place to see all concealment rather than
  cross-referencing Overlap & Concealment and Text Overlay separately.
  It leads the Manipulation & Alteration group.
- Report relationship metadata (REPORT_COMPOSED_OF, with report_part_of
  derived) added as the single source of truth for which detail reports
  make up each aggregate, keyed by stable report id (no renumbering).
- New Document Risk Overview spreadsheet (Option B): a NEW Excel file
  written at report time with one row per analyzed document — filename,
  risk score, and per-category signal counts (the Document Risk Dossier
  data) — with auto-filter and a frozen header for sorting/filtering by
  risk. Deliberately a separate artifact rather than editing the triage
  sheet after the fact, to avoid an after-the-stated-time modification.
- CLI report runs also emit the risk overview and index.
- Render-testing caveat unchanged: the index/overview generation,
  discovery logic, and Concealment Overview query were unit-tested; the
  banner visuals reuse the existing report branding block.

## v1.0.0 — Update (2026-10-06c)

### Visual overlay report: legibility + draggable badges
- Overlay summary is now black text on a white card, on screen and in
  print, so it stays legible when the report is printed or saved to PDF
  (previously light grey on the dark theme, readable only on hover).
- Number badges are now draggable, graph-style: each badge can be moved
  anywhere on the page and a leader line traces back to the overlay’s
  true location (marked with an anchor dot), so an examiner can move a
  badge off important content and still see what it refers to. Dragged
  positions are kept for printing.
- Badges now start close to their overlay instead of being fanned far
  away (which had pushed later badges in a stack, e.g. #7, well away
  from their target); coincident badges still get a small offset so
  each is individually grabbable, and dragging handles the rest.
- Hover-linking retained (hovering a badge/row highlights the matching
  items and leader line), but no longer required for legibility.

## v1.0.0 — Update (2026-10-06b)

### Visual overlay report: interactive per-overlay layers
- The visual overlay report is now an interactive layered view. The
  page renders as a true-original base (all overlays removed) with one
  transparent, independently toggleable layer per detected overlay,
  stacked in z-order. A left-hand checkbox panel (one box per overlay,
  plus All/None) shows or hides each overlay live; the page defaults to
  all overlays shown (the document as received) and peels to the
  recovered original as boxes are unticked. This replaces the fixed
  "remove one" / "remove all" modes and the per-overlay reveal crops.
- Overlay numbers are now DOM badges rather than pixels baked into the
  image, so stacked overlays no longer hide each other’s numbers.
  Colliding badges are fanned apart with leader-dot anchors, and
  hovering a badge, checkbox, or summary row highlights all three.
  Overlays are numbered in stacking order (1 = bottom).
- Per-overlay layers are isolated precisely: "only overlay k present"
  is produced by removing every other overlay BY OBJECT REFERENCE,
  which separates stacked annotations that share the same /Rect (the
  box-and-replace case) — rectangle matching alone could not. The
  layer is then the pixel difference from the base, so compositing the
  chosen layers over the base reproduces any subset of overlays.
- The per-overlay summary (type, geometry, object locator, and the
  annotation’s text — the fabricated value) is kept beneath the page;
  only the reveal crops were removed. Overlays that cannot be cleanly
  isolated (e.g. some content-stream overlays) are listed and labelled
  rather than given a misleading independent toggle.
- reveal.build_revealed_pdf_bytes / _suppress_annotations now accept
  object-reference targets (obj_num/obj_gen from the finding) with
  rectangle matching retained as a fallback.
- Not render-tested in the build environment (no PyMuPDF/pyvis there);
  the object-reference removal, layer compositing, and HTML/JS were
  unit-tested, and the rendering reuses the existing proven page-render
  path. Validate on a real document before evidentiary use.

## v1.0.0 — Update (2026-10-06)

### Stacked annotation overlay detection (box-and-replace tampering)
- check_text_overlays now detects STACKED overlay annotations, the
  signature of box-and-replace tampering: an opaque box hides the
  original value and a (usually transparent) text annotation supplies
  a replacement on top. Previously only the opaque box was flagged
  (FreeText/Widget required an opaque background), so the
  replacement-value layer was missed and the visual reveal removed
  the box but left the false text — never showing the true original.
- New rule: an overlay-subtype annotation (/FreeText, /Widget,
  /Square, /Redact, and now /Stamp) is flagged when it overlaps
  another overlay annotation in the same region with at least one of
  the pair opaque — regardless of its own background opacity. The
  existing rule (opaque background + overlaps page text) is unchanged,
  so prior findings keep their exact wording, with a stacking note
  appended where a box is now known to be paired with a replacement
  layer.
- The replacement annotation’s text (/Contents) — the fabricated
  value — is captured in the finding detail, so the report shows the
  false value alongside the original page text it covers.
- Consequence without any further change: the Text Overlay report now
  lists both layers, and the visual overlay report’s "remove all
  overlays" reveal now strips the box and the replacement text
  together, showing the true underlying original. /Stamp added to the
  reveal’s removable subtypes.
- Precision preserved: a lone transparent text annotation that is not
  stacked on a box is still not flagged (avoids false positives on
  legitimate callouts/comments).
- Next iteration (not in this build): interactive per-overlay toggle
  and z-order step-through in the visual report, to view intermediate
  states and peel stacked layers one at a time.

## v1.0.0 — Update (2026-07-10b)

### Version anachronism: accuracy refinements
- AES-256 (/AESV3) temporal year corrected. It was mapped to PDF
  1.7's publication year (2006), but AES-256 shipped in Adobe
  Extension Level 3 in 2008, so 2006 was too early and could miss a
  temporal contradiction. Added a per-feature year override (AES-256
  -> 2008, its true earliest) used by both the temporal check and the
  displayed year; all other features continue to use their base
  version's publication year. A file claiming a pre-2008 creation
  date while using AES-256 now correctly flags the temporal
  contradiction. (2008 is also safer than the 2009 the guide
  previously cited, which could have falsely flagged a legitimately-
  2008 file.)
- JBIG2 / JPEG2000 detection limitation documented. Unlike the
  storage/cross-reference/encryption markers (always plaintext), an
  image filter name can sit inside a compressed object stream, so a
  raw-byte scan may under-report those two (never over-report). The
  detector comment and the Technical Reference Guide now state this
  conservative, safe-direction limitation explicitly.
- Tests extended to 26 checks (added AES-256 2007->temporal,
  2009->no-temporal, and non-override year guards). Technical Guide
  §4.4 updated (AES year 2008, reliability/limitation wording).

## v1.0.0 — Update (2026-07-10)

### Version anachronism detection + aggregate risk dossier
- New VERSION_ANACHRONISM detector (analysis/doc_checks.py): flags
  files whose structural features require a newer PDF version than they
  declare. The declared version (header, Catalog /Version, XMP) is
  trivially editable; the features present cannot be lowered without
  re-authoring the file, so they set a hard minimum version and, via
  each feature’s publication year, an earliest-possible date.
- Detected features (reliable storage/encoding/encryption markers read
  from the raw bytes, plus Catalog checks): object streams and xref
  streams (1.5), JBIG2 (1.4), JPXDecode (1.5), AES-128 /AESV2 (1.6),
  AES-256 /AESV3 (1.7+/2.0), optional content (1.5), portfolios (1.7),
  XFA (1.5). Compared conservatively against max(header, Catalog, XMP).
- Temporal contradiction: when the claimed creation date predates the
  required feature’s year, the finding says so explicitly — the
  strongest form. Bare gaps carry the hard-coded-header caveat and read
  as requires-review. Feeds document risk at +15 (MEDIUM); distinct
  from VERSION_MISMATCH (header vs Catalog).
- New reports: Version Anachronism (detail, Provenance group) and
  Document Risk Dossier (aggregate) — one row per document composing
  every document-level signal behind its score into a single view so
  the number is legible as the sum of named, individually-caveated
  contributions. 18 reports total.
- Empirical note recorded in the Technical Reference Guide (new section
  4.4): the Info dictionary has no version field; a conformant producer
  raises the header when it writes a newer feature, so a legitimate
  1.4->1.7 edit updates the header — an anachronism therefore means a
  non-conformant producer or a deliberately lowered version string.
- Guides updated: Technical Reference Guide (section 4.4, category and
  weight tables, caveats); Risk Scoring technical/broader (weight,
  finding list, FP note); HTML Reports technical/broader (two report
  sections, count 16->18).

## v1.0.0 — Update (2026-07-09b)

### Documentation correction
- Graph guides (technical and broader): the cross-document image
  border was described as "orange (#FFA500), width 3" but the tool
  actually renders it bright red (#FA0F00, width 4) — the colour
  the examiner sees in the legend and graph. Corrected all border
  references (body text, the vis.js code snippet, manual-validation
  step) and retitled two broader-guide headings ("The Orange Border"
  -> "The Cross-Document Border"; "Red-with-Orange-Border Nodes" ->
  "High-Risk Cross-Document Nodes"). The MID risk-tier colour, which
  is genuinely amber/orange (#EF9F27), is unchanged. The broader
  guide's table of contents should be refreshed in Word (the two
  retitled headings).

## v1.0.0 — Update (2026-07-09)

### Graph: prior-version lineage handling
- Image reuse in the relationship graph is now classified by
  LINEAGE rather than raw document count. A document and the prior
  versions extracted from it form one lineage; an image shared only
  within a lineage is treated as version reuse, not cross-document
  reuse, so an expected overlap between a document and its own
  versions no longer appears as a false cross-document flag.
- Schema revision 7 adds analyses.source_analysis_id and
  analyses.version_number, recording each extracted version's parent
  and version number at analysis time (additive, idempotent
  migration). Lineage is recorded explicitly rather than inferred
  from filenames. save_to_db now returns the analysis id;
  analyze_pdf accepts and records the lineage.
- Cross-document scope groups prior versions by lineage by default
  (COUNT(DISTINCT COALESCE(source_analysis_id, id)) > 1). A toggle
  reverts to the legacy per-document count: GUI "Group prior
  versions by lineage" (on by default); CLI --separate-versions.
- Within-lineage (version) reuse is shown, not hidden: a violet
  dashed border on the image node, dashed edges for any placement in
  a prior version, and a muted-blue "(prior vN)" label on
  prior-version document nodes. This preserves the forensically
  useful case of an image present in a prior version but removed
  from the current one (a shared node reaching only into the dashed
  version subtree).
- New legend entries (Version reuse, Prior version) and a cross-doc
  tooltip clarifying it means cross-lineage. The grouping state,
  prior-version document count, and version-reuse / cross-document
  image counts are embedded in each exhibit (toolbar + printable
  cover) per the exhibit-provenance discipline.
- Graph guides (technical and broader) document the lineage grouping,
  the version-reuse visual encoding, and the toggle.

## v1.0.0 — Update (2026-07-03b)

### Triage: prior-version metadata in the Excel output
- The triage spreadsheet now includes the metadata of prior
  (incremental-update) versions, matching the coverage the HTML
  metadata report already had. For each triaged PDF that contains
  two or more %%EOF markers, every prior version is reconstructed in
  memory (byte-identical to what the version-extraction feature
  writes to disk) and scanned by the same method as the current
  version, so its metadata appears as its own row.
- A new Source column on the pdf-triage, pdf-metadata, and comments
  worksheets labels each row "Current" or "Prior v1", "Prior v2",
  etc. Prior-version rows use the filename basename_versionN.pdf, the
  same convention as the extracted-version files.
- triage_pdf was refactored into a bytes-based core (triage_pdf_bytes)
  so prior versions are scanned from memory without writing temporary
  files. A reconstruct_prior_versions() helper mirrors the existing
  extract_prior_versions() truncation logic exactly.
- Enabled by default; the CLI gains --no-prior-versions to opt out.
  Reviewer comments are also extracted per prior version.
- Getting Started guide updated to describe the Source column and
  prior-version rows.

## v1.0.0 — Update (2026-07-03)

### Documentation refresh
- All seven in-app guides brought current with the 2026-07-02 code
  changes. Getting Started notes the visual-only report run. Risk
  Scoring guides: false-positive conditions for the document-level
  detections (technical); extended document-score description, an
  unapplied-redaction entry in 4.7, a new plain-language section 4.8
  on document-record checks, and updated weight rationale (broader).
  HTML Reports guides: Incremental Updates report sections document
  the Linearized column, updated SQL, and the linearization exclusion
  rule; Document Risk Summary sections state the full document-score
  formula (page maximum + document-level weights + comment flag) and
  correct the previous comment-flag-only difference explanation.
- The standalone Technical Reference Guide was updated separately to
  Version 1.1 (July 2026) with the same content changes.

## v1.0.0 — Update (2026-07-02d)

### Per-page processing speed
- Page text is now extracted once per page instead of three times.
  A single rawdict extraction (using the library's default flag set,
  with span-level text synthesized from the per-character data) is
  shared by the annotation-overlay, text-over-text, and font-
  collection detectors. Each detector keeps a self-extraction
  fallback, so standalone use and per-detector error behaviour are
  unchanged. Shared-vs-fallback outputs verified identical by test.
- The page content stream is now parsed once per page instead of
  three times. The engine parses once and shares the operator list
  with image-placement mapping, z-order/graphics-state analysis, and
  the white-box overlay detector (each with a self-parse fallback).
  Benchmark on a 48,000-operator page: the parse workload drops
  ~3x (measured 5-9x wall-clock on the parsing portion depending on
  cache warmth); savings scale with content-stream size.
- Behaviour note: the annotation-overlay detector previously
  extracted text with only the preserve-whitespace flag; it now
  shares the default-flag extraction, which additionally preserves
  ligatures and applies the library's default MediaBox clipping.
  Effect: ligature glyphs appear unexpanded in overlap details, and
  text lying entirely outside the MediaBox (which is never rendered,
  so cannot be visually concealed by an annotation) is no longer
  considered. Detection outcomes are otherwise identical.

## v1.0.0 — Update (2026-07-02c)

### New document-level detections (analysis/doc_checks.py)
- METADATA_DATE_ANOMALY (HIGH, +25): Info dictionary ModDate precedes
  CreationDate. Dates are parsed timezone-aware; unparseable values
  produce no comparison, and comparisons that relied on assuming UTC
  for a designator-less date say so in the finding.
- METADATA_MISMATCH (MEDIUM, +15 per field): Info dictionary and XMP
  stream disagree on Producer, CreationDate, or ModDate. Dates are
  compared as instants, so equivalent times in different timezones do
  not false-positive.
- VERSION_MISMATCH (INFO, +5): header %PDF-N.M differs from the
  Document Catalog /Version entry.
- XMP_ID_ANOMALY (INFO, +5): xmpMM:DocumentID equals xmpMM:InstanceID.
- MIXED_CAMERA (MEDIUM, +15): images carry EXIF Make/Model from two or
  more distinct capture devices (guide 8.3 previously required this
  comparison to be done manually). EXIF-less images are not counted
  either way and the finding states how many images were assessable.
- REDACT_UNAPPLIED (HIGH, +35, page-level): /Redact annotation present
  but not applied — the covered content remains recoverable in the
  file. One finding per annotation with rect and object locator.
- SIGNED_THEN_MODIFIED (HIGH, +35): file bytes extend beyond the last
  digital signature's /ByteRange coverage — content was appended
  after signing. Structural check only (no cryptographic validation,
  which remains out of scope); a signature whose ByteRange cannot be
  evaluated is reported as explicitly INDETERMINATE.
- STRUCTURAL_WARNING (INFO, +5): the qpdf structural check reported
  warnings (stream /Length discrepancies, damaged xref data, etc.);
  up to ten are listed in the finding, all in the session log.
- Document-level findings add their weights directly to the document
  risk score (doc_risk = MIN(MAX(page score) + SUM(document-level
  weights) + comment flag, 100)) and are stored attached to page 1,
  identified as document-level in their detail text and excluded from
  page 1's page-level score by construction. The Document Risk
  Summary report's Contributing Findings column includes the new
  codes. New finding types are seeded with INSERT OR IGNORE, so
  existing databases gain them on next open (no schema change).

### GUI fix
- The visual overlay report can now be run on its own from the HTML
  report menu. Previously at least one standard report had to be
  selected even when only the visual report was wanted; the validation
  now requires a standard report OR the visual report, and the status
  line correctly reports success for a visual-only run.

## v1.0.0 — Update (2026-07-02b)

### Graph exhibit provenance and scope transparency
- Graph HTML files now self-describe. Each generated graph embeds its
  scope name, the scope definition, the generation timestamp, and
  node/edge/image/document counts. The scope appears as a badge in the
  toolbar (hover for the definition and generation time) and on the
  printable report cover, whose title also names the scope.
- The "Generated" timestamp on the printable cover is now captured at
  file-generation time and embedded in the exhibit. Previously it was
  computed by JavaScript when the file was VIEWED, so every viewing of
  an exhibit displayed a fresh "generated" time — misleading for a
  file that may be presented in proceedings.
- The GUI now reports when two selected scopes select the identical
  dataset for a database (the scopes are nested filters, so this is
  legitimate — e.g. All Placements and Cross-Page coincide when no
  image repeats solely within a single page). The coincidence is
  stated in the generation log and session log instead of being left
  to be discovered by hashing the output files.
- Because the scope is embedded, identical datasets no longer produce
  byte-identical files across scopes; each file identifies itself.
- Graph guides (technical and broader) now explain the nested-scope
  relationship and the embedded provenance.

## v1.0.0 — Update (2026-07-02)

### Detection accuracy fixes
- Linearization-aware incremental update analysis. Linearized
  (web-optimized) PDFs legitimately carry two %%EOF markers; the file
  head is now checked for the /Linearized marker, the state is recorded
  in pdf_metadata (True/False/indeterminate), and the Incremental
  Updates report excludes linearized files with exactly two markers and
  shows a Linearized column. Previously every web-optimized PDF was a
  false positive in this report.
- Form XObject analysis rewritten with correct graphics-state tracking.
  The CTM is now composed through q/Q/cm (previously each cm operator
  was tested in isolation, mis-locating images under nested transforms
  and flagging matrices unrelated to any image), and clipping paths are
  carried as part of the saved/restored graphics state. BBOX_CROP is
  evaluated per image Do using the composed placement geometry.
- EXPLICIT_CLIP is now geometry-aware. A rectangular clip that fully
  contains the image is no longer reported (it conceals nothing); a
  cropping clip reports the hidden percentage; and non-rectangular clip
  paths — previously not reported at all due to a rect-only code path —
  are reported with an explicit note that the extent of concealment is
  undetermined and requires manual review.
- White-box overlay detection: fill colour is tracked correctly. CMYK
  white (0 0 0 0 k) and scn-set colours are now recognized; SC/SCN
  (stroking-colour operators) are no longer misread as fill; the fill
  colour is saved/restored with q/Q; and setting a colour space (cs)
  conservatively resets the colour to non-white.
- Overlap detection uses exact rotated footprints. When one or both
  images are rotated, the overlap is computed by convex-polygon
  intersection of the transformed placement rectangles, eliminating the
  documented false positives from axis-aligned bounding boxes on
  rotated content. Where a transform cannot be recovered, the finding
  explicitly states its figures are an upper bound requiring manual
  verification.
- Findings now state uncertainty explicitly wherever geometry cannot be
  fully determined (rotated placements assessed by bounding box,
  non-rectangular clips, unresolved XObject subtypes).
- Documentation aligned with implemented behaviour: the Technical
  Reference Guide and the Risk Scoring Technical guide now state the
  actual thresholds (HIDDEN_THRESHOLD_PTS = 0.5; text-over-text overlap
  ratio 0.55 with 1.5-point same-glyph exclusion), the sixteen-report
  count, schema revision 6, and the new clip/overlap semantics.

## v1.0.0 — Update (2026-06-23)

### Document-level risk scoring and Document Risk Summary report
- New document-level risk dimension. Findings that describe a page or the
  document as a whole rather than a single image — text overlays
  (TEXT_OVERLAY) and font anomalies (FONT_ANOMALY) — are now scored
  separately from per-image risk, alongside a small informational flag for
  the presence of reviewer comments. Each finding type contributes to
  exactly one dimension, so nothing is double-counted and nothing is
  detected-but-unscored.
- Scoring (analysis/risk.py): added compute_document_risk(), producing a
  per-page score (sum of document-level finding weights, capped at 100) and
  a document score (the maximum page score plus the comment flag, capped at
  100). TEXT_OVERLAY (+35) and FONT_ANOMALY (+15) moved out of the per-image
  weight table into DOC_RISK_WEIGHTS; COMMENT_RISK_WEIGHT is +5. Per-image
  scores are unchanged.
- Schema revision 6: added analyses.doc_risk_score and pages.risk_score
  (both INTEGER DEFAULT 0). The migration is additive and idempotent;
  opening an older database upgrades it in place with no data loss.
- New "Document Risk Summary" report (report id document_risk): one row per
  analyzed PDF, ranked by document risk, showing the highest page risk, the
  contributing document-level finding types, and the comment count. It leads
  the Document Overview & Provenance report group.
- Documentation: the Risk Scoring guides (technical and broader) gain a
  section on the document-level dimension and its weights; the HTML Reports
  guides (technical and broader) document the new report.

## v1.0.0 — Update (2026-06-22b)

### Font consistency report, report reorganization, tooltips, progress bar
- New "Font Consistency Analysis" report (ANAL-03): a document-level
  detector flags text spans whose font is inconsistent with the
  document's dominant body font, an independent indicator of in-place
  edits. Added a FONT_ANOMALY finding type (Medium severity); the report
  is selected by default in the Reports menu.
- The Reports list is reorganized into a logical, workflow-based order
  grouped under headings: Document Overview & Provenance, Manipulation &
  Alteration, Image Analysis, and Cross-Document & Review. The Visual
  Report panel moves down to accommodate the grouped list.
- Hover tooltips with brief descriptions were added to every report in the
  Reports menu, to the graph scope options, and to the analysis options in
  the PDF analysis menu.
- GUI-03: batch analysis and triage now show a determinate progress bar
  with a per-file status label (file N of M, and current page), replacing
  the text-only progress indication.
- Fixed the Reports window being too short for the grouped report list:
  the window is taller, the Visual Report panel's description moved to a
  hover tooltip to reclaim space, and window sizes are now clamped to the
  display so a tall window never extends off smaller laptop screens.

## v1.0.0 — Update (2026-06-22)

### Add a folder of PDFs
- The PDF files panel gains an "Add folder" button. After choosing a
  folder, a Yes / No / Cancel prompt asks whether to search subfolders
  recursively (Yes = this folder and all subfolders, No = this folder
  only, Cancel = add nothing). Discovered PDFs are added to the list,
  de-duplicated against entries already present, with a short summary of
  how many were added or skipped.
- The PDF files button row now uses an equal-weight grid so all five
  buttons share the panel width evenly and cannot be clipped, and the
  analysis window / left panel were widened to fit the row comfortably.

## v1.0.0 — Update (2026-06-19)

### Licensing, authorship, and disclaimers (release prep)
- Added the Apache License 2.0 full text as `LICENSE` at the repository
  root, and a standard `NOTICE` file identifying the application, copyright
  holder, and year.
- Added `README.md` at the repository root with project description,
  install/usage instructions, an Apache 2.0 license badge/section, a link
  to `LICENSE`/`NOTICE`, the medium-form disclaimer, and the author/contact
  block.
- New `pdf_forensics/disclaimers.py` holds the approved, verbatim
  disclaimer and authorship text shared across the suite.
- GUI: on first launch the short disclaimer is shown as a blocking
  acknowledgment the user must accept to proceed; the acknowledgment is
  remembered, and on every launch thereafter a permanent reminder line
  ("Use at your own risk — see About for full disclaimer") appears in the
  status bar and opens the full disclaimer when clicked.
- GUI: the Help → About dialog now shows the full disclaimer and the
  author / contact / repository / license information, with the environment
  diagnostics retained below it (now a scrollable dialog).
- CLI: a short disclaimer banner is printed to stderr at the start of a
  command run (suppressed for `--version`, `--help`, `--quiet`, and the
  report `--list` listing) so headless users see it too.

## v1.0.0 — Update (2026-06-04)

### Comments, identity logging, validation locators (schema rev 5)
- Log files now record the agency name, unit name, and investigator
  (name and email) from the branding config alongside the case number,
  in both the session header and the closing summary.
- Excel triage workbook: the "pdf-metadata" sheet is now frozen at B2 so
  it matches the "pdf-triage" sheet (header row + filename column).
- Excel triage workbook: a new "comments" worksheet lists reviewer
  comments / markup annotations extracted from the examined PDFs, with
  columns Filename, Path, Page, Type, Author, Date/Time, Created,
  Modified, Comment, and Object (the PDF object number, for validation).
  Frozen at B2. The sheet is omitted entirely if no comments are found in
  any examined PDF.
- New "Document Comments" HTML report listing the same extracted comments.
- The Text Overlay Detection and Manipulation Detail reports now include an
  "Object / Stream (for validation)" column identifying where the flagged
  overlay lives: the annotation object number for annotation overlays, or
  the page content-stream object number (with a note that the overlying
  glyphs may be nested in a Form XObject) for content-stream overlays. An
  examiner can use this to validate findings in peepdf / qpdf / mutool.

### Database schema — revision 5
- Added a `comments` table (page, subtype, author, contents, creation and
  modification dates, object/generation number), linked to `analyses`.
- Added `obj_num`, `obj_gen`, and `obj_locator` columns to `findings` to
  record where each overlay finding can be validated in the source file.
- Existing rev-4 databases are migrated automatically (new columns and the
  comments table are added in place).

## v1.0.0 — Update (2026-06-01b)

### Menu / GUI refinements
- Changing the case number now always prompts for an output folder (the
  user may pick an existing folder or create a new one), instead of
  silently reusing the previous case's folder and database. The processing
  log window is also cleared, since a new case begins a fresh session.
- The header on every menu now shows the agency name, unit name, and
  investigator name alongside the case number, so the operator can confirm
  at a glance that the stored identity details are theirs before running
  anything. Missing fields are shown in amber as a prompt to set them, and
  the header updates immediately after branding is edited.
- The "Select reports" list is now laid out in two columns so the full
  list (and the controls beneath it) stays visible on smaller laptop
  screens.

## v1.0.0 — Update (2026-06-01)

### Visual Overlay Report — Before/After Reveal
- The visual overlay report can now show, for recoverable overlays, what is
  hidden beneath them. The page (or an individual region) is re-rendered
  with the overlay suppressed and offered alongside the normal view via a
  toggle.
- Two independent reveal modes are provided:
  - A page-level toggle on each full page image ("As displayed" vs
    "Overlays removed") that suppresses every recoverable overlay on the
    page at once.
  - A per-finding toggle on each detail card ("As displayed" vs
    "Hidden beneath") that suppresses only that one flagged overlay.
- Suppression is performed by the new `reports/reveal.py` module. It handles
  the common real-world case (e.g. PDFium-edited files) where an alteration
  is composited on top of the original through deeply nested Form XObjects
  as a TWO-part construct: a patch (a white rectangle, or one or more
  vector/image patch forms) that hides the original glyphs, plus forged text
  drawn over the patch. The module walks the entire content tree (page
  stream and every nested form) in draw order, then for each flagged region
  suppresses the whole edit group — patch and forged text together — at the
  container level, exposing the untouched original beneath. Simpler inline
  overlays (a masking rectangle drawn directly in a stream, or text painted
  over text without nesting) are handled as a fallback. The original
  underlying content is never modified.
- Evidentiary safety: if the underlying content for a region cannot be
  cleanly isolated from legitimate co-located content, the reveal is SKIPPED
  for that finding rather than shown partially. No toggle is offered for
  such findings and the detail card is labelled accordingly; the detection
  itself still stands. Hairline fills that the detector flags as "white box"
  but that mask no text (e.g. separator rules) are likewise skipped.
- When printed, both states are shown stacked with captions so a filed PDF
  preserves the comparison.

## v1.0.0 — Update (2026-05-31)

### Report Branding & Agency Information
- New "Branding / agency info" dialog on the main menu to configure
  the agency logo, investigator name / email / phone, agency name,
  unit name, agency address, and an optional classification caveat
- Settings persist to `branding.json` in the application folder
  (falls back to the home directory if that folder is not writable)
  and are applied automatically by both the GUI and the CLI
- HTML reports now carry a three-column banner: report title (left),
  case/agency information (centre), and the agency logo (right)
- The visual overlay report uses the same banner
- Graph reports now open with a professional cover page (agency name
  and unit, logo, case/investigator details, and a generated-on /
  database-integrity strip), printed as its own page
- Optional configurable classification strip (e.g. "Law Enforcement
  Sensitive") across the top of every report and the graph cover
- Per-page print footer (case number, investigator, database MD5) on
  HTML reports, the visual report, and graph reports; repeats on each
  page in Chromium-based browsers
- Page numbers ("Page X of Y") via the CSS `@page` margin box
  (rendered by Firefox and PDF print engines)
- Database MD5 shown on the graph cover and in report footers for
  chain-of-custody
- New cached `compute_file_md5()` helper so the evidence database is
  hashed once per session rather than once per report

### Output Folder Change
- Extracted prior PDF versions are now written to a `pdf_versions/`
  sub-folder (each file's versions under `{name}_versions/`) instead
  of inside `extracted_images/`, for a clearer folder layout

## v1.0.0 — Update (2026-05-29)

### Text Overlay Detection
- Added three independent text-overlay detectors, each catching a
  different document-alteration technique:
  - `check_text_overlays` — annotation-based overlays (FreeText,
    Widget, Square, Redact annotations with opaque backgrounds over
    existing page text)
  - `check_content_stream_text_overlay` — white (or near-white)
    rectangles painted over content in the page content stream,
    followed by replacement text
  - `check_text_over_text` — new text painted directly over existing
    text with no masking rectangle (detected via per-character bounding
    box overlap from PyMuPDF rawdict; excludes faux-bold and drop-shadow
    rendering effects)
- New `TEXT_OVERLAY` finding type (HIGH severity, risk weight 35)
- New report 13: "Text Overlay Detection"
- Findings now record a bounding box (`bbox_x0/y0/x1/y1`) and
  `overlay_kind` to support visual reporting (schema revision 4,
  auto-migrated)

### Visual Overlay Report (new)
- New self-contained HTML report that visually shows detected overlays
  to a non-technical reader:
  - Full annotated page images with each detected overlay highlighted
    in a colour-coded box and numbered marker (red = text-over-text,
    orange = white-box masking, blue = annotation)
  - Per-finding detail cards with a high-resolution zoomed crop of the
    affected region and a plain-language description
  - Legend, intro caveats, and print-optimised CSS for browser
    "Print to PDF"
- Available via the GUI Reports panel ("Generate visual overlay
  report" checkbox, on by default) and the CLI (`report --visual`)
- Gracefully degrades to a text-only section when a source PDF cannot
  be located

### Fixes
- Triage Excel output now saved to the `reports/` subfolder instead of
  `extracted_images/`
- Fixed crash ("'NoneType' object has no attribute 'split'") when
  scoring or saving findings that are not image-specific (e.g.
  TEXT_OVERLAY); `f.get("image")` now coerces `None` to an empty string
  in both `analysis/risk.py` and `database.py`

## v1.0.0 (2026-04-19)

### Initial Release — Unified Package

Merged standalone PDF forensics analysis and graph analysis scripts
into a single unified toolkit, refactored into a Python package.

#### Package Structure
- 22 modules across 5 subpackages (`analysis/`, `graph/`, `reports/`,
  `gui/`, plus core)
- Thin `pdf_forensics.py` launcher script for backwards compatibility
- `python -m pdf_forensics` entry point
- Each module is 50–450 lines (largest is `graph/visualization.py`
  at ~1,670 lines for the JavaScript injection)

#### Case & Session Management
- Case number prompted at launch; displayed in GUI header
- Per-case output folder structure relative to database location:
  `logs/`, `graph_reports/`, `reports/`, `extracted_images/`
- Filename convention: `{case}_{kind}_{timestamp}.{ext}`
- Single timestamp per session shared across all outputs
- Session switching with confirmation dialog; clears state cleanly
- Last-used case persisted in `~/.pdf_forensics_config.json`

#### Forensic Logging
- Per-session timestamped log file in `logs/` subfolder
- Environment capture: tool version, Python, OS, library versions
- Per-PDF detail: file path, MD5, size, results, error tracebacks
- Session summary: counts, duration, output file list, database MD5

#### Duplicate PDF Detection
- PDFs already in the database (by MD5 match) are flagged
- GUI: dialog asking whether to re-process
- CLI: skipped by default; `--force` flag to override

#### PDF Analysis Engine
- Image manipulation detection: BBOX_CROP, EXPLICIT_CLIP, OVERLAP,
  OFFPAGE, SOFT_MASK, IMAGE_SMASK, COMPLEX_TRANSFORM, PARSE_ERROR
- PDF metadata extraction (Info Dict, XMP, Catalog)
- Prior version detection via %%EOF markers
- Image metadata extraction (EXIF, GPS via Pillow)
- MD5 hashing of PDFs and each unique image
- Per-image risk scoring (0–100) based on finding types/severity
- Per-PDF error handling: one bad file doesn't crash the batch

#### Graph Analysis Engine
- Interactive HTML visualizations via vis.js / pyvis
- Three duplicate-detection scopes: all placements, cross-page,
  cross-document
- Embedded image thumbnails in node tooltips
- Risk-based node coloring: green (low), amber (mid), red (high)
- Orange border for cross-document image reuse
- Right-click context menu: exclude images/documents, add to report
- Excluded items panel with tabbed Images/Documents views
- Printable HTML report generation from selected images
- Document exclusion with orphan cleanup
- GUI: checkboxes to generate multiple scopes in one run

#### Unified GUI
- Adobe Acrobat-inspired dark theme (centralized in `gui/theme.py`)
- Main menu with three module cards: Analysis, Graph, Reports
- Path pre-population: case entry → directory picker → DB, output,
  graph paths all auto-filled
- PDF list import from text files (`--pdf-list` CLI, GUI button)
- Reports sub-menu placeholder for future release

#### CLI
- Subcommands: `analyze`, `graph`
- `--pdf-list` / `-l` for bulk file ingestion from text files
- `--case` for case number assignment
- `--force` to override duplicate detection
- `--version` flag
- GUI launches by default; `--gui` for explicit mode

#### Database Schema (Revision 2)
- `schema_version` table for version tracking with revision history
- `risk_score` column on `images` table
- `OFFPAGE` finding type
- Automatic schema migration for older databases
- `check_pdf_already_analyzed()` for duplicate detection
