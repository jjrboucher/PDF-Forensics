"""Fill colours in named colour spaces (1.3.0, build 2026-11-17).

Before 1.3.0 a single colour component set with sc/scn was read as grey, so
a spot colour (Separation) at full ink, 1 scn, was taken for white: table
borders and dark bands drawn that way were reported as white boxes with text
painted on them, and a spot colour at no ink (paper white) was missed.
analysis/colour.py evaluates the colour in its space where it can be done
exactly, and otherwise leaves the old reading in place. Synthetic files only.
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

import pikepdf                                                  # noqa: E402
from pikepdf import Name                                        # noqa: E402

from pdf_forensics.analysis.colour import (resolve_rgb, lookup_space,  # noqa
                                           eval_function, legacy_rgb)


def _pdf():
    return pikepdf.new()


def separation_type2(pdf, name="/Black"):
    fn = pdf.make_indirect(pikepdf.Dictionary(
        FunctionType=2, Domain=[0, 1], C0=[0, 0, 0, 0], C1=[0, 0, 0, 1], N=1))
    return pikepdf.Array([Name.Separation, Name(name), Name.DeviceCMYK, fn])


def separation_sampled(pdf):
    """Like the documents that showed the problem: a Separation /Black
    whose tint transform is a sampled function into RGB."""
    samples = bytes(v for t in range(256)
                    for v in (255 - t, 255 - t, 255 - t))
    fn = pdf.make_stream(samples, FunctionType=0, Domain=[0, 1],
                         Range=[0, 1, 0, 1, 0, 1], Size=[256],
                         BitsPerSample=8)
    return pikepdf.Array([Name.Separation, Name.Black, Name.DeviceRGB, fn])


def devicen_type4(pdf):
    # two inks; alternate CMYK = (c, m, 0, 0)
    fn = pdf.make_stream(b"{ 0 0 }", FunctionType=4, Domain=[0, 1, 0, 1],
                         Range=[0, 1, 0, 1, 0, 1, 0, 1])
    return pikepdf.Array([Name.DeviceN,
                          pikepdf.Array([Name.Cyan, Name.Magenta]),
                          Name.DeviceCMYK, fn])


class ResolveTest(unittest.TestCase):

    def test_separation_full_ink_is_dark_and_no_ink_is_white(self):
        pdf = _pdf()
        for cs in (separation_type2(pdf), separation_sampled(pdf)):
            self.assertLess(max(resolve_rgb(cs, [1.0])), 0.1)
            self.assertGreater(min(resolve_rgb(cs, [0.0])), 0.99)
            mid = resolve_rgb(cs, [0.5])
            self.assertTrue(0.3 < mid[0] < 0.7)

    def test_devicen_postscript(self):
        pdf = _pdf()
        cs = devicen_type4(pdf)
        self.assertEqual(resolve_rgb(cs, [0, 0]), (1.0, 1.0, 1.0))
        r = resolve_rgb(cs, [1, 0])
        self.assertLess(r[0], 0.01)                   # cyan: no red

    def test_indexed_palette(self):
        pal = pikepdf.String(bytes([0, 0, 0, 255, 255, 255]))
        cs = pikepdf.Array([Name.Indexed, Name.DeviceRGB, 1, pal])
        self.assertEqual(resolve_rgb(cs, [0]), (0.0, 0.0, 0.0))
        self.assertEqual(resolve_rgb(cs, [1]), (1.0, 1.0, 1.0))

    def test_lab(self):
        cs = pikepdf.Array([Name.Lab, pikepdf.Dictionary(
            WhitePoint=[0.9505, 1.0, 1.089])])
        self.assertGreater(min(resolve_rgb(cs, [100, 0, 0])), 0.99)
        self.assertLess(max(resolve_rgb(cs, [20, 0, 0])), 0.25)

    def test_device_spaces_match_the_old_reading(self):
        for name, vals in (("/DeviceGray", [0.95]), ("/DeviceRGB", [1, 1, 1]),
                           ("/DeviceCMYK", [0, 0, 0, 1])):
            self.assertEqual(resolve_rgb(Name(name), vals),
                             tuple(legacy_rgb(vals)))

    def test_cannot_evaluate_returns_none(self):
        pdf = _pdf()
        two_input_sampled = pdf.make_stream(
            b"\x00" * 16, FunctionType=0, Domain=[0, 1, 0, 1],
            Range=[0, 1], Size=[4, 4], BitsPerSample=8)
        cs = pikepdf.Array([Name.DeviceN,
                            pikepdf.Array([Name.A, Name.B]),
                            Name.DeviceGray, two_input_sampled])
        self.assertIsNone(resolve_rgb(cs, [1, 1]))
        self.assertIsNone(resolve_rgb(Name.Pattern, [1]))
        self.assertIsNone(resolve_rgb(None, [1]))
        self.assertIsNone(resolve_rgb(
            pikepdf.Array([Name.Separation, Name("/None"), Name.DeviceGray,
                           separation_type2(pdf)[3]]), [1]))
        bad = pdf.make_stream(b"{ 1 0 div }", FunctionType=4,
                              Domain=[0, 1], Range=[0, 1])
        self.assertIsNone(eval_function(bad, [1]))

    def test_lookup_in_resources(self):
        pdf = _pdf()
        res = pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(
            CS0=separation_type2(pdf)))
        cs = lookup_space(Name("/CS0"), res)
        self.assertLess(max(resolve_rgb(cs, [1], res)), 0.1)
        self.assertIsNone(lookup_space(Name("/Missing"), res))


# The detector itself, on a synthetic page. detectors.py imports PyMuPDF
# but this check only needs pikepdf; where PyMuPDF is not installed the
# test runs in a separate process with a minimal stand-in for it.
DETECTOR_SCRIPT = textwrap.dedent('''
    import sys, json
    sys.path.insert(0, sys.argv[1])
    try:
        import pymupdf  # noqa
    except ImportError:
        import types
        m = types.ModuleType("pymupdf")
        class Rect:
            def __init__(self, *a): pass
        m.Rect = Rect
        sys.modules["pymupdf"] = m
    import pikepdf
    from pdf_forensics.analysis import detectors as D
    class PageMu:
        rect = type("R", (), {"height": 792.0})()
    out = []
    for p in pikepdf.open(sys.argv[2]).pages:
        f1, f2 = [], []
        D.check_content_stream_text_overlay(p, PageMu(), 1, f1)
        D._check_content_stream_text_overlay_reference(p, PageMu(), 1, f2)
        assert [x["detail"] for x in f1] == [x["detail"] for x in f2]
        out.append(len(f1))
    print(json.dumps(out))
''')


def _page(pdf, content, colorspaces):
    font = pdf.make_indirect(pikepdf.Dictionary(
        Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica))
    pdf.add_blank_page(page_size=(612, 792))
    p = pdf.pages[-1]
    p.Resources = pikepdf.Dictionary(
        Font=pikepdf.Dictionary(F1=font),
        ColorSpace=pikepdf.Dictionary(colorspaces))
    p.Contents = pdf.make_stream(content)


class DetectorTest(unittest.TestCase):

    def _findings(self, pdf):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "synthetic.pdf")
            pdf.save(path)
            script = os.path.join(tmp, "run.py")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(DETECTOR_SCRIPT)
            r = subprocess.run([sys.executable, script, APP, path],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            import json
            return json.loads(r.stdout.strip().splitlines()[-1])

    def test_spot_colours(self):
        pdf = _pdf()
        sep = separation_sampled(pdf)
        text = b"BT /F1 12 Tf 1 1 1 rg 60 700 Td (Heading) Tj ET\n"
        # 1. dark band in spot black with white text: not a white box
        _page(pdf, b"/CS1 cs 1 scn 0 680 612 60 re f\n" + text,
              {"/CS1": sep})
        # 2. hairline table border in spot black next to text
        _page(pdf, b"/CS1 cs 1 scn 55 690 0.48 40 re f\n"
                   b"BT /F1 10 Tf 0 g 60 700 Td (Cell text) Tj ET\n",
              {"/CS1": sep})
        # 3. a box in spot colour at no ink (paper white) over text, with
        #    new text on it: a white box (missed before 1.3.0)
        _page(pdf, b"BT /F1 12 Tf 0 g 60 700 Td (1,250.00) Tj ET\n"
                   b"/CS1 cs 0 scn 55 690 80 25 re f\n"
                   b"BT /F1 12 Tf 0 g 60 700 Td (9,999.00) Tj ET\n",
              {"/CS1": sep})
        # 4. the same in device grey: unchanged
        _page(pdf, b"BT /F1 12 Tf 0 g 60 700 Td (1,250.00) Tj ET\n"
                   b"1 g 55 690 80 25 re f\n"
                   b"BT /F1 12 Tf 0 g 60 700 Td (9,999.00) Tj ET\n", {})
        # 5. a colour that cannot be evaluated is read as before (1 = white)
        two = pdf.make_stream(b"\x00" * 16, FunctionType=0,
                              Domain=[0, 1, 0, 1], Range=[0, 1],
                              Size=[4, 4], BitsPerSample=8)
        dn = pikepdf.Array([Name.DeviceN, pikepdf.Array([Name.A]),
                            Name.DeviceGray, two])
        _page(pdf, b"/CS1 cs 1 scn 55 690 80 25 re f\n"
                   b"BT /F1 12 Tf 0 g 60 700 Td (9,999.00) Tj ET\n",
              {"/CS1": dn})
        self.assertEqual(self._findings(pdf), [0, 0, 1, 1, 1])


if __name__ == "__main__":
    unittest.main()
