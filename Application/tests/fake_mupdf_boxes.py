"""A stand-in for the parts of PyMuPDF the image-box checks use."""
import math, random, types, sys

class Rect:
    def __init__(self, *a):
        if len(a) == 1: a = tuple(a[0])
        self.x0, self.y0, self.x1, self.y1 = (float(v) for v in a)
    def __and__(self, o):
        return Rect(max(self.x0, o.x0), max(self.y0, o.y0), min(self.x1, o.x1), min(self.y1, o.y1))
    @property
    def is_empty(self): return self.x0 >= self.x1 or self.y0 >= self.y1
    @property
    def is_infinite(self): return False
    def get_area(self): return 0.0 if self.is_empty else (self.x1-self.x0)*(self.y1-self.y0)
    def __repr__(self): return f"Rect({self.x0}, {self.y0}, {self.x1}, {self.y1})"
    __str__ = __repr__
    def __iter__(self): return iter((self.x0, self.y0, self.x1, self.y1))

class Page:
    def __init__(self, seed, n_img, n_xref, rot_share=0.2, w=612, h=792):
        R = random.Random(seed)
        self.rect = self.cropbox = Rect(0, 0, w, h)
        self.info = []
        for k in range(n_img):
            xref = 10 + R.randrange(n_xref)
            sw, sh = R.uniform(5, 150), R.uniform(5, 150)
            ang = R.uniform(0, math.pi) if R.random() < rot_share else 0.0
            c, s = math.cos(ang), math.sin(ang)
            e, f = R.uniform(-40, w), R.uniform(-40, h)
            m = (sw*c, sw*s, -sh*s, sh*c, e, f)
            xs = [m[4], m[4]+m[0], m[4]+m[2], m[4]+m[0]+m[2]]
            ys = [m[5], m[5]+m[1], m[5]+m[3], m[5]+m[1]+m[3]]
            self.info.append({"xref": xref, "bbox": (min(xs), min(ys), max(xs), max(ys)), "transform": m})
        self.calls = 0
    def get_images(self, full=False):
        return [(x,) for x in sorted({i["xref"] for i in self.info})]
    def get_image_info(self, xrefs=False, hashes=False):
        self.calls += 1
        return [dict(i) for i in self.info]
    def get_image_rects(self, xref, transform=False):
        self.calls += 1
        got = [i for i in self.get_image_info(xrefs=True) if i["xref"] == xref]
        if transform:
            return [(Rect(i["bbox"]), i["transform"]) for i in got]
        return [Rect(i["bbox"]) for i in got]

def install():
    m = types.ModuleType("pymupdf"); m.Rect = Rect; m.Matrix = lambda t: tuple(t)
    sys.modules["pymupdf"] = m
