"""Faster overlay separation in the Visual Overlay report (build
2026-11-19d) gives byte-identical layers, the same white-box measurements
and the same self-check results as the code before it (kept below as the
reference). Synthetic page images only; PyMuPDF is not needed."""
import io
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PIL import Image, ImageChops, ImageDraw  # noqa: E402

from pdf_forensics.reports import visual as V  # noqa: E402


# -- the code before build 2026-11-19d --------------------------------------
def ref_isolate(base_png, with_overlay_png, tolerance=10):
    base = Image.open(io.BytesIO(base_png)).convert("RGB")
    over = Image.open(io.BytesIO(with_overlay_png)).convert("RGB")
    if base.size != over.size:
        over = over.resize(base.size)
    r, g, b = ImageChops.difference(base, over).split()
    diff = ImageChops.lighter(ImageChops.lighter(r, g), b)
    mask = diff.point(lambda v: 255 if v > tolerance else 0)
    layer = over.convert("RGBA")
    layer.putalpha(mask)
    out = io.BytesIO()
    layer.save(out, format="PNG", compress_level=6)
    return out.getvalue()


def ref_composite_image(base_png, layer_pngs, size):
    comp = Image.open(io.BytesIO(base_png)).convert("RGBA")
    for lp in layer_pngs:
        if not lp:
            continue
        lay = Image.open(io.BytesIO(lp)).convert("RGBA")
        if lay.size != comp.size:
            lay = lay.resize(comp.size)
        comp.alpha_composite(lay)
    return comp


# -- synthetic pages -------------------------------------------------------
W, H = 612, 792            # a letter page at 72 dpi keeps the test quick


def _png(im):
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def _text_page(seed):
    r = random.Random(seed)
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    for y in range(40, H - 40, 14):
        for x in range(40, W - 40, 6):
            if r.random() < 0.6:
                d.rectangle([x, y, x + 4, y + 8],
                            fill=(r.randint(0, 60),) * 3)
    return im


def _page_with(base_im, boxes, lines=()):
    im = base_im.copy()
    d = ImageDraw.Draw(im)
    for b in boxes:
        d.rectangle(b, fill="white")
    for (x, y, t) in lines:
        d.text((x, y), t, fill=(0, 0, 90))
    return im


class SameOutputTest(unittest.TestCase):
    def setUp(self):
        V._decoded_clear()

    def test_layers_measurements_and_check_identical(self):
        page = _text_page(1)
        # one box on text (hides content), one on the margin (hides
        # nothing), each with painted lines; and a plain overlay
        boxes = [(100, 100, 260, 130), (20, 700, 30, 760)]
        base_png = _png(page)
        layers, layers_ref = [], []
        for k, bx in enumerate(boxes):
            fill_png = _png(_page_with(page, [bx]))
            new = V._isolate_layer_png(base_png, fill_png)
            old = ref_isolate(base_png, fill_png)
            self.assertEqual(new, old)
            layers.append(new)
            layers_ref.append(old)
            zoom = 1.0
            hp = V._hidden_pixels(base_png, fill_png, bx, zoom)
            V._decoded_clear()
            self.assertEqual(hp, V._hidden_pixels(base_png, fill_png, bx,
                                                  zoom))
            if k == 0:
                self.assertGreater(hp, 0)
            else:
                self.assertEqual(hp, 0)
            for j in range(3):
                line_png = _png(_page_with(page, [bx],
                                           [(bx[0] + 2, bx[1] + 2 + j,
                                             f"line {j}")]))
                new = V._isolate_layer_png(fill_png, line_png)
                self.assertEqual(new, ref_isolate(fill_png, line_png))
                layers.append(new)
                layers_ref.append(new)
        plain_png = _png(_page_with(page, [], [(300, 300, "added")]))
        layers.append(V._isolate_layer_png(base_png, plain_png))
        self.assertEqual(layers[-1], ref_isolate(base_png, plain_png))

        asis = _page_with(page, boxes, [(bx[0] + 2, bx[1] + 2 + j,
                                         f"line {j}") for bx in boxes
                                        for j in range(3)]
                          + [(300, 300, "added")])
        asis_png = _png(asis)
        ok, frac = V._composite_matches(base_png, layers, asis_png)
        comp_ref = ref_composite_image(base_png, layers, asis.size)
        # the reference's decision, from its own composite
        diff = ImageChops.difference(comp_ref.convert("RGB"), asis)
        r, g, b = diff.split()
        mx = ImageChops.lighter(ImageChops.lighter(r, g), b)
        differ = mx.point(lambda v: 255 if v > V.COMPOSITE_PIXEL_TOL
                          else 0).histogram()[255]
        self.assertAlmostEqual(frac, differ / (W * H))
        # and a layer that does not belong is still caught
        bad = layers[:-1] + [V._isolate_layer_png(
            base_png, _png(_page_with(page, [(0, 0, 600, 780)])))]
        self.assertFalse(V._composite_matches(base_png, bad, asis_png)[0])

    def test_check_from_kept_layers_same_as_decoded(self):
        """The self-check composites layers kept from when they were made;
        the result equals decoding every layer, including a fully
        transparent layer, a layer listed twice, and pages of a different
        size (where layers are resized and so decoded)."""
        page = _text_page(2)
        base_png = _png(page)
        bx = (50, 50, 200, 80)
        over_png = _png(_page_with(page, [bx], [(52, 52, "x")]))
        same_png = _png(page)
        for asis_im in (_page_with(page, [bx], [(52, 52, "x")]),
                        _page_with(page, [bx], [(52, 52, "x")]).resize(
                            (W + 10, H + 10))):
            asis_png = _png(asis_im)
            results = []
            for kept in (True, False):
                V._decoded_clear()
                lay = V._isolate_layer_png(base_png, over_png)
                empty = V._isolate_layer_png(base_png, same_png)
                if not kept:
                    V._decoded_clear()          # forces decoding
                results.append(V._composite_matches(
                    base_png, [lay, empty, lay, None], asis_png,
                    [(40, 40, 210, 90)]))
            self.assertEqual(results[0], results[1])
        self.assertEqual(len(V._LAYERS), 0)

    def test_cache_is_bounded(self):
        saved = V._DECODED_BUDGET
        try:
            V._DECODED_BUDGET = W * H * 3 * 3       # room for three
            pngs = [_png(_text_page(s)) for s in range(5)]
            for p in pngs:
                V._decoded_rgb(p)
            self.assertLessEqual(V._DECODED_BYTES[0], V._DECODED_BUDGET)
            self.assertEqual(len(V._DECODED), 3)
            self.assertIs(V._decoded_rgb(pngs[-1]),
                          V._decoded_rgb(pngs[-1]))
            # an equal copy (another bytes object) is decoded on its own
            other = bytes(bytearray(pngs[-1]))
            self.assertIsNot(V._decoded_rgb(other), V._decoded_rgb(pngs[-1]))
            V._decoded_clear()
            self.assertEqual((len(V._DECODED), V._DECODED_BYTES[0]), (0, 0))
        finally:
            V._DECODED_BUDGET = saved
            V._decoded_clear()


if __name__ == "__main__":
    unittest.main()
