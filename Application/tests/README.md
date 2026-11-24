# Tests

Automated checks for the PDF Forensics Suite. They use only synthetic files
made by the tests themselves (no real case data) and the standard library's
`unittest`, so nothing extra needs installing beyond the application's own
requirements.

Run all of them from the `Application` folder:

```bash
python -m unittest discover -s tests -t .
```

(`python -m pytest tests` works too, if pytest is installed.)

| File | What it checks |
|---|---|
| `test_static.py` | Every module compiles, and no code uses a name that is never defined (a slip that only shows when that code runs, e.g. a GUI path). |
| `test_regressions.py` | Fixes made since 1.0: prior-version validation (a linearized file's first `%%EOF` is not a version), encryption checked on the bytes being triaged, `glob.escape` for folders with square brackets, the duplicate notice computed before the database is closed, strict PDF version format, metadata changes and ExifTool attribution, the timeline, Windows path lengths, `freeze_support` in every entry point. |
| `test_parallel_runner.py` | Parallel analysis with a stand-in analysis (`stub_compute.py`): results committed in submission order whatever the number of workers; identical copies (including copies of another file's prior version) skipped with nothing left behind; files with the same name kept apart; missing, failing and encrypted files; a worker process that crashes; log and performance-log entries; stopping a run. |
| `test_graph_parallel.py` | Graphs made at the same time are reported in the order listed, with no-data and error cases; with pyvis installed, the graph files are compared with those made one at a time. |
| `test_visual_hides.py` | The Visual Overlay report's measurement of what each white box hides, the collapsed *Hides nothing visible* group, and the index column. |
| `test_colour.py` | Fill colours in named colour spaces (spot colours, palettes, Lab), the fallback to the earlier reading, and the white-box detector on synthetic pages. |
| `test_visual_parallel.py` | Visual overlay reports made several at once give the same index, log entries and performance-log events as one at a time. |
| `test_gui_build.py` | Builds the whole window against stand-ins for tkinter and PyMuPDF (`fake_tk_build.py`), so an error that only shows when the window opens fails a test. |
| `test_graph_fast.py` | The fast way of handing a graph to pyvis gives exactly what pyvis's own `from_nx` gives (nodes, links, the written file), and the application falls back to pyvis's own when a sample differs. Uses pyvis where installed, otherwise the stand-in in `fake_pyvis/`, which follows pyvis 0.3.2. |
| `test_visual_speed.py` | The Visual Overlay report's layers, white-box measurements and self-check are identical, byte for byte, to the code before build 2026-11-19d. |
| `test_visual_split.py` | A long document's Visual Overlay report made in parts of consecutive pages is the same as made whole (report, overlay numbers, log entries in order, counts, index), with stand-ins for PyMuPDF's rendering; the planning of parts; and the drawing-time work estimate (slow pages and their prior versions start first). |
| `test_load_sampler.py` | The processor-load notes and speed check in the performance log (worker processes counted in this application's share), and the analysis runner's main-loop summary. |
| `test_doc_comparison.py` | The Document Comparison Matrix gives the same pairs as the SQL it replaced, lists at most the set number with the total stated, and states the cap in the written report. |
| `test_build_19b.py` | Live log lines (with a stand-in text widget, no Tk needed); *Auto* lowered when free memory is short or the processors are busy; one key for a file's start, finish and result in parallel analysis; the visual reports' progress callback and start and end times; the case index's MD5 digests hashed in threads against one at a time. |
| `test_content_ops.py` | The content-stream walks (image placements, transparency, white-box checks, forms, annotations) give the same results with pikepdf's instruction objects, plain tuples or no shared parse; synthetic pages. Before release they were compared with build 2026-11-20b: identical. |
| `test_image_boxes.py` | The overlap and off-page checks with image boxes read once per page and pairs found by a sweep give the same findings, in the same order, as one call per image and every pair; the self-check falls back when the two differ. Stand-in for PyMuPDF (`fake_mupdf_boxes.py`). |
| `test_watchdog.py` | A file making no progress is stopped and recorded as timed out, and one the examiner skips as skipped; files running alongside are sent again and analysed; results stay in submission order. Stand-in analysis. |
| `test_repaired_copy.py` | A file pikepdf cannot open (page tree without /Kids), or whose page count differs between the readers, is analysed from MuPDF's repaired copy with a structural warning that gives no file name; readable files are unchanged; a wrong password still fails. |
| `test_encryption_check.py` | Triage and analysis give the same encryption answer for a file's path and its bytes; schemes read without the password; a permissions-only file only MuPDF can read opens; the Encrypted Files report's MD5, scheme, copies and notice. |
| `test_byte_structure.py` | Cross-reference entries that do not point to their object, and zero runs outside streams (a zero-filled tail), on synthetic files. |
| `test_library_messages.py` | pikepdf's warnings and PyMuPDF's own messages (such as "unhandled font type ''") go to the session log with the document, not the console; stand-in for PyMuPDF. |
| `test_parallel_equivalence.py` | Real analyses of synthetic PDFs, one at a time against several at once, compared with `compare_databases.py`; triage spreadsheets one at a time against three at a time. |

Tests that need PyMuPDF are skipped where it is not installed (they run on
any machine set up to run the application).

## Comparing two case databases

`compare_databases.py` checks that two runs over the same files produced the
same results, for example after analysing a folder in the GUI once with
**Files processed at once** set to **1** and once with **Auto**:

```bash
python tests/compare_databases.py first_case.db second_case.db
```

It compares every table row by row (ids included), ignoring only run times
and the case-folder part of file paths, and prints table names, row ids and
column names, never file contents. Exit status 0 means the databases match.
