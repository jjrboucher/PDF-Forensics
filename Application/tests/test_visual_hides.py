"""Visual Overlay report (1.3.0): white boxes that hide nothing visible are
measured from the report's own renders and listed in a collapsed group,
never removed. Images are drawn here; no PDF library is needed."""
import io
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PIL import Image, ImageDraw                                # noqa: E402

from pdf_forensics.reports import visual as V                   # noqa: E402

ZOOM = 2.0          # 144 dpi: 2 pixels per point


def _png(draw_fn, size=(400, 300)):
    im = Image.new("RGB", size, "white")
    draw_fn(ImageDraw.Draw(im))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def _nothing(d):
    pass


class HiddenPixels(unittest.TestCase):
    BOX = (50, 50, 100, 70)          # points -> pixels 100..200 x 100..140

    def test_box_on_blank_paper_hides_nothing(self):
        base = _png(_nothing)
        with_box = _png(_nothing)    # white on white: no change
        self.assertEqual(V._hidden_pixels(base, with_box, self.BOX, ZOOM), 0)

    def test_box_over_text_hides_content(self):
        base = _png(lambda d: d.rectangle((120, 110, 170, 130), fill="black"))
        with_box = _png(_nothing)    # the box paints the text out
        self.assertEqual(V._hidden_pixels(base, with_box, self.BOX, ZOOM),
                         51 * 21)

    def test_light_content_counts(self):
        base = _png(lambda d: d.rectangle((120, 110, 121, 111),
                                          fill=(240, 240, 240)))
        self.assertEqual(V._hidden_pixels(base, _png(_nothing), self.BOX,
                                          ZOOM), 4)

    def test_single_pixel_counts(self):
        base = _png(lambda d: d.point((150, 120), fill="black"))
        self.assertEqual(V._hidden_pixels(base, _png(_nothing), self.BOX,
                                          ZOOM), 1)

    def test_only_the_box_area_is_measured(self):
        base = _png(lambda d: d.rectangle((300, 200, 320, 220), fill="black"))
        self.assertEqual(V._hidden_pixels(base, _png(_nothing), self.BOX,
                                          ZOOM), 0)

    def test_cannot_measure(self):
        base = _png(_nothing)
        other = _png(_nothing, size=(10, 10))
        self.assertIsNone(V._hidden_pixels(base, other, self.BOX, ZOOM))
        self.assertIsNone(V._hidden_pixels(b"not a png", base, self.BOX,
                                           ZOOM))


def _overlays():
    det = ("White-filled rectangle at (1,1) to (2,2) (area 1 sq pts) covers "
           "existing page content; new text painted on top at (1,1). This "
           "pattern is characteristic of in-place text alteration without "
           "using an annotation.")
    return [
        # 1: white box + painted line, hides nothing
        {"number": "1a", "group": 1, "part": "box", "kind": "white_box",
         "title": "White box", "detail": "x", "bbox": (1, 1, 2, 2),
         "hidden_px": 0, "group_detail": det},
        {"number": "1b", "group": 1, "part": "line", "kind": "text_over_text",
         "title": "Painted text", "detail": "y", "bbox": (1, 1, 2, 2),
         "line_text": "Example"},
        # 2: white box (single layer), hides content
        {"number": "2", "group": 2, "part": None, "kind": "white_box",
         "title": None, "detail": det, "bbox": (3, 3, 4, 4),
         "hidden_px": 17},
        # 3: white box that could not be measured: stays in the main list
        {"number": "3", "group": 3, "part": None, "kind": "white_box",
         "title": None, "detail": det, "bbox": (5, 5, 6, 6),
         "hidden_px": None},
        # 4: another kind of overlay: never classified
        {"number": "4", "group": 4, "part": None, "kind": "text_over_text",
         "title": None, "detail": "z", "bbox": (7, 7, 8, 8),
         "hidden_px": 0},
        # 5: white box, hides nothing
        {"number": "5", "group": 5, "part": None, "kind": "white_box",
         "title": None, "detail": det, "bbox": (9, 9, 10, 10),
         "hidden_px": 0},
    ]


class Classify(unittest.TestCase):

    def test_classification(self):
        ovs = _overlays()
        self.assertEqual(V._classify_white_boxes(ovs, True), 2)
        nothing = [o["number"] for o in ovs if o.get("nothing")]
        self.assertEqual(nothing, ["1a", "1b", "5"])
        self.assertTrue(ovs[2].get("hides"))
        self.assertIn("17 pixel(s)", ovs[2]["detail"])
        self.assertNotIn("covers existing page content", ovs[5]["detail"])
        self.assertNotIn("covers existing page content",
                         ovs[0]["group_detail"])
        self.assertFalse(ovs[3].get("nothing") or ovs[3].get("hides"))
        self.assertFalse(ovs[4].get("nothing") or ovs[4].get("hides"))

    def test_unverified_page_classifies_nothing(self):
        ovs = _overlays()
        self.assertEqual(V._classify_white_boxes(ovs, False), 0)
        self.assertFalse(any(o.get("nothing") for o in ovs))


class Html(unittest.TestCase):

    def _section(self):
        ovs = _overlays()
        n = V._classify_white_boxes(ovs, True)
        for z, o in enumerate(ovs, 1):
            o["z"] = z
            o["layer_uri"] = "data:image/png;base64,"
        pb = {"page_num": 1, "uid": "9-1", "mode": "layered",
              "asis_uri": "a", "base_uri": "b", "base_all_removed": True,
              "page_w": 612.0, "page_h": 792.0, "overlays": ovs,
              "count": 5, "nothing": n}
        return V._render_doc_section("example.pdf", "0" * 32, [pb]), ovs

    def test_everything_listed_and_ticked(self):
        html, ovs = self._section()
        for o in ovs:
            self.assertIn(f'data-ov="9-1-{o["number"]}" data-page="9-1" '
                          f'checked', html)
            self.assertIn(f'id="layer-9-1-{o["number"]}"', html)
        self.assertIn("2 hide nothing visible", html)
        self.assertIn('<details class="ov-nothing" data-page="9-1">'
                      '<summary>Hides nothing visible (2)</summary>', html)
        self.assertIn("2 white boxes that hide nothing visible", html)
        self.assertIn('class="tag-hides"', html)
        # the collapsed group's markers carry the class the CSS hides
        for n in ("1a", "1b", "5"):
            self.assertRegex(html, r'class="ov-badge nothing" data-ov="9-1-'
                             + n + '"')
        for n in ("2", "3", "4"):
            self.assertRegex(html, r'class="ov-badge" data-ov="9-1-'
                             + n + '"')
        # main list comes before the collapsed group
        details = html.index('<details class="ov-nothing"')
        self.assertLess(html.index('data-ov="9-1-2"'), details)
        self.assertGreater(html.index('data-ov="9-1-5"'), details)

    def test_index_column(self):
        rows = [{"n": 1, "file": "a.pdf", "kind": "Submitted", "hides": 3,
                 "pages": 1, "overlays": 5, "tot": 0, "wb": 5, "ann": 0,
                 "other": 0, "risk": 10, "md5": "", "href": "x.html"},
                {"n": 2, "file": "b.pdf", "kind": "Submitted", "hides": 0,
                 "pages": 1, "overlays": 2, "tot": 0, "wb": 2, "ann": 0,
                 "other": 0, "risk": 5, "md5": "", "href": "y.html"}]
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "case.db")
            open(db, "wb").close()
            html = V._index_html(rows, db)
        self.assertIn(">Hides content</th>", html)
        self.assertRegex(html, r'<td class="num hides hit">3</td>')
        self.assertRegex(html, r'<td class="num hides">0</td>')
        self.assertEqual(len(re.findall(r">Open report</a>", html)), 2)


if __name__ == "__main__":
    unittest.main()
