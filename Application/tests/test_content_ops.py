"""Content-stream walks read operator names first (build 2026-11-23).

Unpacking each parsed instruction (``for operands, operator in ops``)
builds its operand list every time; on a drawing with 2.75 million
operators that took 85 s per walk on Windows. The walks now read the
operator name and fetch operands only where they act on them
(analysis/content_ops.py). Every walk must give the same results whether
it is handed pikepdf's instruction objects or plain (operands, operator)
tuples, and with or without a shared parse. Before release the walks
were also compared with build 2026-11-20b on 20 such pages: identical.
Synthetic files only.
"""
import contextlib
import os
import random
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

@contextlib.contextmanager
def _mupdf_as(stub):
    """sys.modules["pymupdf"] is stub inside the block, and as before
    after it (other tests check whether PyMuPDF is installed)."""
    had = "pymupdf" in sys.modules
    old = sys.modules.get("pymupdf")
    sys.modules["pymupdf"] = stub
    try:
        yield
    finally:
        if had:
            sys.modules["pymupdf"] = old
        else:
            sys.modules.pop("pymupdf", None)


_STUB = types.ModuleType("pymupdf")
_STUB.Rect = lambda *a: tuple(a)
try:
    import pymupdf as _REAL  # noqa: F401
except ImportError:
    _REAL = None

import pikepdf                                                  # noqa: E402
from pikepdf import Name, Dictionary, Array                     # noqa: E402

with _mupdf_as(_REAL or _STUB):
    from pdf_forensics.analysis.content_ops import (            # noqa: E402
        op_names, operands_of, named_ops, OpView)
    from pdf_forensics.analysis.transparency import (           # noqa: E402
        get_zorder_and_graphics_state)
    from pdf_forensics.analysis.images import (                 # noqa: E402
        find_image_placements)
    from pdf_forensics.analysis import detectors as D           # noqa: E402


def build(seed, n=1500):
    """A page of random drawing, images, forms, graphics states, colour
    spaces and text, plus white boxes painted over text."""
    R=random.Random(seed); pdf=pikepdf.new()
    img=pikepdf.Stream(pdf,b'\xff\x00\x00'*4); img.Type=Name.XObject; img.Subtype=Name.Image; img.Width=2; img.Height=2; img.ColorSpace=Name.DeviceRGB; img.BitsPerComponent=8
    img2=pikepdf.Stream(pdf,b'\x00'*4); img2.Type=Name.XObject; img2.Subtype=Name.Image; img2.Width=2; img2.Height=2; img2.ColorSpace=Name.DeviceGray; img2.BitsPerComponent=8
    sm=pikepdf.Stream(pdf,b'\x80'*4); sm.Subtype=Name.Image; sm.Width=2; sm.Height=2; sm.ColorSpace=Name.DeviceGray; sm.BitsPerComponent=8
    img2.SMask=pdf.make_indirect(sm)
    imgr=pdf.make_indirect(img); img2r=pdf.make_indirect(img2)
    form=pikepdf.Stream(pdf,b'q 0 0 50 50 re W n 100 0 0 100 -20 -20 cm /Im0 Do Q q 10 0 0 10 5 5 cm /Im1 Do Q')
    form.Type=Name.XObject; form.Subtype=Name.Form; form.BBox=[0,0,200,200]
    form.Resources=Dictionary(XObject=Dictionary(Im0=imgr, Im1=img2r)); form.Group=Dictionary(S=Name.Transparency)
    formr=pdf.make_indirect(form)
    pdf.add_blank_page(page_size=(612,792)); pg=pdf.pages[0]
    pg.Resources=Dictionary(XObject=Dictionary(Im0=imgr,Im1=img2r,Fm0=formr),
        ExtGState=Dictionary(GS0=Dictionary(ca=0.5), GS1=Dictionary(BM=Name.Multiply, SMask=Name('/None')), GS2=Dictionary(ca=1)),
        Font=Dictionary(F1=Dictionary(Type=Name.Font,Subtype=Name.Type1,BaseFont=Name.Helvetica)),
        ColorSpace=Dictionary(CS0=Name.DeviceRGB, CS1=Array([Name.Separation, Name('/Spot'), Name.DeviceCMYK, Dictionary(FunctionType=2, Domain=[0,1], C0=[0,0,0,0], C1=[0,0,0,1], N=1)])))
    f=lambda a,b: f"{R.uniform(a,b):.2f}"
    parts=[]; depth=0
    for _ in range(n):
        k=R.random()
        if k<0.08: parts.append('q'); depth+=1
        elif k<0.16 and depth: parts.append('Q'); depth-=1
        elif k<0.24: parts.append(' '.join([f(-2,2),f(-1,1),f(-1,1),f(-2,2),f(0,500),f(0,700)])+' cm')
        elif k<0.30: parts.append(R.choice(['/GS0','/GS1','/GS2'])+' gs')
        elif k<0.38: parts.append(R.choice(['/Im0','/Im1','/Fm0'])+' Do')
        elif k<0.50:
            col=R.choice(['1 1 1 rg','0.95 g','0 0 0 0 k','0.2 0.3 0.4 rg','/CS0 cs 1 1 1 sc','/CS1 cs 0 scn','/CS1 cs 1 scn','1 G'])
            parts.append(col)
        elif k<0.62: parts.append(f"{f(0,500)} {f(0,700)} {f(10,200)} {f(10,80)} re "+R.choice(['f','F','B','S','n','W n','f*']))
        elif k<0.75: parts.append(f"BT /F1 {R.choice([8,10,12])} Tf {f(0,500)} {f(0,700)} Td (Text {R.randint(0,99)}) Tj ET")
        elif k<0.80: parts.append(f"BT /F1 10 Tf 1 0 0 1 {f(0,500)} {f(0,700)} Tm [(A) -20 (B)] TJ ET")
        elif k<0.90: parts.append(f"{f(0,500)} {f(0,700)} m {f(0,500)} {f(0,700)} l {f(0,500)} {f(0,700)} {f(0,500)} {f(0,700)} {f(0,500)} {f(0,700)} c h S")
        elif k<0.93: parts.append("BI /W 1 /H 1 /CS /G /BPC 8 ID \x80 EI")
        else: parts.append(R.choice(['0.5 w','1 0 0 RG','[] 0 d','2 J']))
    parts+= ['Q']*depth
    pre=[]
    for j in range(R.randint(3,8)):
        x,y=R.uniform(50,400),R.uniform(50,700)
        fill=R.choice(['1 1 1 rg','1 g','0 0 0 0 k','/CS0 cs 1 1 1 sc','/CS1 cs 0 scn','/CS1 cs 1 scn','0.5 g'])
        pre.append(f"BT /F1 12 Tf {x+10:.1f} {y+5:.1f} Td (Original {j}) Tj ET q {fill} {x:.1f} {y:.1f} 200 25 re {R.choice(['f','f','B','S'])} Q BT /F1 12 Tf {x+10:.1f} {y+5:.1f} Td (Replaced {j}) Tj ET")
    pg.Contents=pdf.make_stream(('\n'.join(pre+parts)).encode('latin-1'))
    ap=pikepdf.Stream(pdf,b'1 1 1 rg 0 0 100 20 re f BT /F1 10 Tf 2 5 Td (x) Tj ET'); ap.Type=Name.XObject; ap.Subtype=Name.Form; ap.BBox=[0,0,100,20]
    annot=Dictionary(Type=Name.Annot,Subtype=Name.FreeText,Rect=[100,100,200,120],AP=Dictionary(N=pdf.make_indirect(ap)))
    pg.Annots=pdf.make_indirect(Array([pdf.make_indirect(annot)]))
    return pdf


class _R:
    height = 792.0
    width = 612.0


class _MU:
    rect = _R()


def _results(page, ops):
    res = {"z": get_zorder_and_graphics_state(page, content_ops=ops),
           "pl": find_image_placements(page, content_ops=ops)}
    for name, fn in (("cs", D.check_content_stream_text_overlay),
                     ("ref", D._check_content_stream_text_overlay_reference)):
        f = []
        fn(page, _MU(), 1, f, content_ops=ops)
        res[name] = f
    return res


class OpViewTest(unittest.TestCase):
    def test_names_and_operands(self):
        pdf = pikepdf.new()
        pdf.add_blank_page()
        page = pdf.pages[0]
        page.Contents = pdf.make_stream(
            b"q 1 0 0 1 5 6 cm 0 0 10 10 re f Q BT /F1 9 Tf (a) Tj ET")
        ops = list(pikepdf.parse_content_stream(page))
        tuples = [(list(o), op) for o, op in ops]
        self.assertEqual(op_names(ops), op_names(tuples))
        self.assertEqual(op_names(ops)[:4], ["q", "cm", "re", "f"])
        self.assertEqual([float(x) for x in operands_of(ops[1])],
                         [1, 0, 0, 1, 5, 6])
        view = OpView(ops)
        self.assertEqual(len(view), len(ops))
        self.assertEqual(view[1][0], "cm")
        self.assertEqual([float(x) for x in view[1][1][:2]], [1, 0])
        self.assertFalse(view[0][1])          # q has no operands
        self.assertEqual(len(view[2][1]), 4)
        self.assertEqual([n for n, _ in view], view.names)
        names, lst = named_ops(iter(ops))
        self.assertEqual(len(lst), len(ops))


class WalkEquivalenceTest(unittest.TestCase):
    def test_instruction_objects_and_tuples_agree(self):
        totals = {"z": 0, "pl": 0, "cs": 0}
        for seed in range(6):
            pdf = build(seed)
            page = pdf.pages[0]
            ops = list(pikepdf.parse_content_stream(page))
            tuples = [(list(o), op) for o, op in ops]
            a = _results(page, ops)
            b = _results(page, tuples)
            c = _results(page, None)
            self.assertEqual(a, b, f"seed {seed}")
            self.assertEqual(a, c, f"seed {seed}")
            self.assertEqual(a["cs"], a["ref"], f"seed {seed}")
            for k in totals:
                totals[k] += len(a[k])
        # The pages exercise every walk.
        self.assertGreater(totals["z"], 100)
        self.assertGreater(totals["pl"], 100)
        self.assertGreater(totals["cs"], 10)

    def test_malformed_text_matrix_ignored(self):
        """A Tm with fewer than six numbers stopped the analysis of a
        damaged file (IndexError); it is ignored (build 2026-11-23b)."""
        pdf = pikepdf.new()
        pdf.add_blank_page()
        page = pdf.pages[0]
        page.Resources = Dictionary(Font=Dictionary(F1=Dictionary(
            Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica)))
        page.Contents = pdf.make_stream(
            b"BT /F1 12 Tf 1 0 0 Tm (x) Tj ET "
            b"q 1 1 1 rg 0 0 200 50 re f Q")
        for fn in (D.check_content_stream_text_overlay,
                   D._check_content_stream_text_overlay_reference):
            f = []
            with _mupdf_as(_REAL or _STUB):
                fn(page, _MU(), 1, f)

    def test_form_and_annotation_walks(self):
        pdf = build(3)
        page = pdf.pages[0]
        form = page.Resources.XObject.Fm0
        fast, full = [], []
        D.analyze_form_xobject(form, "/Fm0", 1, fast, {"Im0": "p1_img1"})
        D.analyze_form_xobject(form, "/Fm0", 1, full, {"Im0": "p1_img1"},
                               fast=False)
        self.assertEqual(fast, full)
        self.assertTrue(fast)
        self.assertTrue(D._has_opaque_background(page.Annots[0]))


if __name__ == "__main__":
    unittest.main()
