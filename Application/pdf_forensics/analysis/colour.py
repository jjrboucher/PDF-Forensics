"""
Fill colours as they appear on the page, for the white-box checks.

The content-stream checks need to know whether a filled shape is white. For
colours given directly in DeviceGray, DeviceRGB or DeviceCMYK (g, rg, k)
that is simple. Colours set with cs + sc/scn are in a named colour space,
and their components mean different things in each:

  * Separation and DeviceN (spot colours): a tint of 1 is full ink and 0 is
    no ink, the opposite of grey. Before 1.3.0 a single component was read
    as grey, so full black ink (1 scn) was taken for white, and paper white
    (0 scn) for black.
  * Indexed: the component is an index into a palette.
  * Lab: the components are L*, a*, b*.

resolve_rgb() converts a colour to RGB (0..1) where the space can be
evaluated exactly: device, ICC-based (by component count, as the device
space), calibrated, Lab, Indexed, and Separation/DeviceN through their tint
transform (function types 0, 2, 3 and 4). It returns None whenever it cannot
(a pattern, a missing resource, an unsupported function, anything
malformed); the caller then reads the components exactly as before 1.3.0,
so a colour that cannot be evaluated is never treated differently from
earlier versions.
"""

import math

import pikepdf
from pikepdf import Name

_DEVICE_N = {"/DeviceGray": 1, "/DeviceRGB": 3, "/DeviceCMYK": 4,
             "/G": 1, "/RGB": 3, "/CMYK": 4}


def legacy_rgb(vals):
    """The interpretation used before 1.3.0 (and still used whenever the
    colour space cannot be evaluated): 1 component = grey, 3 = RGB,
    4 = CMYK; anything else is treated as black (not white)."""
    if len(vals) == 1:
        return (vals[0],) * 3
    if len(vals) == 3:
        return tuple(vals)
    if len(vals) == 4:
        c, m, y, k = vals
        return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return (0.0, 0.0, 0.0)


def lookup_space(name, resources):
    """The colour space object for a cs operand: a device name, or the
    entry in the resources' /ColorSpace dictionary. None if not found."""
    try:
        s = str(name)
        if s in _DEVICE_N or s == "/Pattern":
            return Name(s)
        if resources is None:
            return None
        csd = resources.get("/ColorSpace")
        if csd is None:
            return None
        return csd.get(s)
    except Exception:
        return None


def resolve_rgb(space, vals, resources=None, _depth=0, cache=None):
    """RGB (each 0..1) of colour components vals in colour space `space`
    (as returned by lookup_space), or None if it cannot be evaluated.

    cache: optional dict, used for one page (one document) only, to avoid
    re-evaluating the same colour (sampled functions are decompressed on
    each evaluation)."""
    if space is None or _depth > 6:
        return None
    if cache is not None:
        try:
            key = (space.unparse() if isinstance(space, pikepdf.Array)
                   else str(space),
                   tuple(float(v) for v in vals))
        except Exception:
            key = None
        if key is not None:
            if key not in cache:
                cache[key] = resolve_rgb(space, vals, resources, _depth)
            return cache[key]
    try:
        vals = [float(v) for v in vals]
        if isinstance(space, Name) or isinstance(space, str):
            s = str(space)
            if s in _DEVICE_N:
                if len(vals) != _DEVICE_N[s]:
                    return None
                return _clip(legacy_rgb(vals))
            if s == "/Pattern":
                return None
            # a name referring to another resource entry
            return resolve_rgb(lookup_space(s, resources), vals, resources,
                               _depth + 1)
        if not isinstance(space, pikepdf.Array) or len(space) == 0:
            return None
        fam = str(space[0])
        if fam == "/ICCBased":
            n = int(space[1].get("/N"))
            if n not in (1, 3, 4) or len(vals) != n:
                return None
            return _clip(legacy_rgb(vals))
        if fam == "/CalGray":
            return _clip(legacy_rgb(vals[:1])) if len(vals) == 1 else None
        if fam == "/CalRGB":
            return _clip(legacy_rgb(vals[:3])) if len(vals) == 3 else None
        if fam == "/Lab":
            if len(vals) != 3:
                return None
            wp = [float(x) for x in space[1].get("/WhitePoint",
                                                 [0.9505, 1.0, 1.089])]
            return _lab_to_rgb(vals, wp)
        if fam == "/Indexed":
            base, hival, lookup = space[1], int(space[2]), space[3]
            if len(vals) != 1:
                return None
            data = (bytes(lookup.read_bytes()) if isinstance(
                lookup, pikepdf.Stream) else bytes(lookup))
            idx = max(0, min(hival, int(round(vals[0]))))
            n = _components(base, resources)
            if not n:
                return None
            raw = data[idx * n:(idx + 1) * n]
            if len(raw) != n:
                return None
            comps = [b / 255.0 for b in raw]
            if _family(base, resources) == "/Lab":
                rng = [float(x) for x in _resolved(base, resources)[1].get(
                    "/Range", [-100, 100, -100, 100])]
                comps = [comps[0] * 100.0,
                         rng[0] + comps[1] * (rng[1] - rng[0]),
                         rng[2] + comps[2] * (rng[3] - rng[2])]
            return resolve_rgb(base, comps, resources, _depth + 1)
        if fam in ("/Separation", "/DeviceN"):
            names = space[1]
            n_in = 1 if fam == "/Separation" else len(names)
            if len(vals) != n_in:
                return None
            if fam == "/Separation" and str(names) == "/None":
                return None              # paints nothing; leave as before
            alt, fn = space[2], space[3]
            out = eval_function(fn, vals)
            if out is None:
                return None
            return resolve_rgb(alt, out, resources, _depth + 1)
    except Exception:
        return None
    return None


def _resolved(space, resources):
    if isinstance(space, Name) and str(space) not in _DEVICE_N:
        r = lookup_space(space, resources)
        return r if r is not None else space
    return space


def _family(space, resources):
    space = _resolved(space, resources)
    if isinstance(space, Name):
        return str(space)
    try:
        return str(space[0])
    except Exception:
        return None


def _components(space, resources):
    space = _resolved(space, resources)
    if isinstance(space, Name):
        return _DEVICE_N.get(str(space))
    fam = str(space[0])
    if fam == "/ICCBased":
        return int(space[1].get("/N"))
    return {"/CalGray": 1, "/CalRGB": 3, "/Lab": 3}.get(fam)


def _clip(rgb):
    return tuple(min(1.0, max(0.0, v)) for v in rgb)


def _lab_to_rgb(lab, wp):
    L, a, b = lab
    fy = (L + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0

    def finv(t):
        return t ** 3 if t > 6.0 / 29 else 3 * (6.0 / 29) ** 2 * (t - 4.0 / 29)
    X, Y, Z = wp[0] * finv(fx), wp[1] * finv(fy), wp[2] * finv(fz)
    r = 3.2406 * X - 1.5372 * Y - 0.4986 * Z
    g = -0.9689 * X + 1.8758 * Y + 0.0415 * Z
    bl = 0.0557 * X - 0.2040 * Y + 1.0570 * Z

    def gamma(c):
        c = max(0.0, c)
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return _clip((gamma(r), gamma(g), gamma(bl)))


# ---------------------------------------------------------------------------
# PDF functions (ISO 32000-1 7.10): types 0 (sampled, one input), 2, 3, 4
# ---------------------------------------------------------------------------

def eval_function(fn, inputs, _depth=0):
    """Evaluate a PDF function, or return None if it cannot be."""
    if _depth > 6:
        return None
    try:
        if isinstance(fn, pikepdf.Array):        # one function per output
            outs = []
            for f in fn:
                o = eval_function(f, inputs, _depth + 1)
                if o is None or len(o) != 1:
                    return None
                outs.extend(o)
            return outs
        ftype = int(fn.get("/FunctionType"))
        dom = [float(x) for x in fn.get("/Domain")]
        x = [min(dom[2 * i + 1], max(dom[2 * i], v))
             for i, v in enumerate(inputs)]
        rng = fn.get("/Range")
        rng = [float(v) for v in rng] if rng is not None else None
        if ftype == 2:
            c0 = [float(v) for v in fn.get("/C0", [0.0])]
            c1 = [float(v) for v in fn.get("/C1", [1.0])]
            n = float(fn.get("/N"))
            t = x[0] ** n
            out = [a + t * (b - a) for a, b in zip(c0, c1)]
        elif ftype == 0:
            out = _sampled(fn, x, dom, rng)
        elif ftype == 3:
            out = _stitching(fn, x[0], dom, _depth)
        elif ftype == 4:
            out = _postscript(fn, x)
        else:
            return None
        if out is None:
            return None
        if rng:
            out = [min(rng[2 * i + 1], max(rng[2 * i], v))
                   for i, v in enumerate(out)]
        return out
    except Exception:
        return None


def _sampled(fn, x, dom, rng):
    size = [int(v) for v in fn.get("/Size")]
    if len(size) != 1 or len(x) != 1 or rng is None:
        return None
    bps = int(fn.get("/BitsPerSample"))
    n_out = len(rng) // 2
    enc = [float(v) for v in fn.get("/Encode", [0, size[0] - 1])]
    dec = [float(v) for v in fn.get("/Decode", rng)]
    data = bytes(fn.read_bytes())
    e = enc[0] + (x[0] - dom[0]) * (enc[1] - enc[0]) / ((dom[1] - dom[0])
                                                         or 1.0)
    e = min(size[0] - 1, max(0.0, e))
    i0 = int(math.floor(e))
    i1 = min(size[0] - 1, i0 + 1)
    frac = e - i0
    maxv = (1 << bps) - 1

    def sample(i, j):
        bit = (i * n_out + j) * bps
        if bps >= 8 and bps % 8 == 0:
            nb = bps // 8
            pos = bit // 8
            chunk = data[pos:pos + nb]
            if len(chunk) != nb:
                raise ValueError("short sample data")
            return int.from_bytes(chunk, "big")
        byte = data[bit // 8]
        shift = 8 - bps - (bit % 8)
        return (byte >> shift) & maxv
    out = []
    for j in range(n_out):
        s = sample(i0, j) + frac * (sample(i1, j) - sample(i0, j))
        out.append(dec[2 * j] + s * (dec[2 * j + 1] - dec[2 * j]) / maxv)
    return out


def _stitching(fn, x, dom, depth):
    funcs = fn.get("/Functions")
    bounds = [float(v) for v in fn.get("/Bounds", [])]
    enc = [float(v) for v in fn.get("/Encode")]
    k = len(funcs)
    i = 0
    while i < k - 1 and x >= bounds[i]:
        i += 1
    lo = dom[0] if i == 0 else bounds[i - 1]
    hi = dom[1] if i == k - 1 else bounds[i]
    e0, e1 = enc[2 * i], enc[2 * i + 1]
    xe = e0 if hi == lo else e0 + (x - lo) * (e1 - e0) / (hi - lo)
    return eval_function(funcs[i], [xe], depth + 1)


_PS_MAX_STEPS = 20000


def _postscript(fn, x):
    """Type 4 (PostScript calculator) functions."""
    import re
    src = bytes(fn.read_bytes()).decode("latin-1")
    toks = re.findall(r"[{}]|[^\s{}]+", src)
    pos = 0

    def parse():
        nonlocal pos
        out = []
        while pos < len(toks):
            t = toks[pos]
            pos += 1
            if t == "{":
                out.append(parse())
            elif t == "}":
                return out
            else:
                out.append(t)
        return out
    prog = parse()
    if len(prog) == 1 and isinstance(prog[0], list):
        prog = prog[0]
    stack = list(x)
    steps = [0]

    def run(code):
        i = 0
        while i < len(code):
            steps[0] += 1
            if steps[0] > _PS_MAX_STEPS:
                raise ValueError("function too long")
            t = code[i]
            if isinstance(t, list):
                # if / ifelse take the procedures that precede them
                if i + 1 < len(code) and code[i + 1] == "if":
                    if stack.pop():
                        run(t)
                    i += 2
                    continue
                if (i + 2 < len(code) and isinstance(code[i + 1], list)
                        and code[i + 2] == "ifelse"):
                    run(t if stack.pop() else code[i + 1])
                    i += 3
                    continue
                raise ValueError("unexpected procedure")
            _ps_op(t, stack)
            i += 1
    run(prog)
    return [float(v) for v in stack]


def _ps_op(t, s):
    try:
        s.append(float(t) if any(c in t for c in ".eE") else int(t))
        return
    except ValueError:
        pass
    if t == "true":
        s.append(True); return
    if t == "false":
        s.append(False); return
    b = None
    if t in ("add", "sub", "mul", "div", "idiv", "mod", "exp", "atan",
             "eq", "ne", "gt", "ge", "lt", "le", "and", "or", "xor",
             "bitshift"):
        b = s.pop()
        a = s.pop()
        r = {"add": lambda: a + b, "sub": lambda: a - b,
             "mul": lambda: a * b, "div": lambda: a / b,
             "idiv": lambda: int(a / b), "mod": lambda: int(math.fmod(a, b)),
             "exp": lambda: a ** b,
             "atan": lambda: math.degrees(math.atan2(a, b)) % 360,
             "eq": lambda: a == b, "ne": lambda: a != b,
             "gt": lambda: a > b, "ge": lambda: a >= b,
             "lt": lambda: a < b, "le": lambda: a <= b,
             "and": lambda: (a and b) if isinstance(a, bool) else int(a) & int(b),
             "or": lambda: (a or b) if isinstance(a, bool) else int(a) | int(b),
             "xor": lambda: (a != b) if isinstance(a, bool) else int(a) ^ int(b),
             "bitshift": lambda: (int(a) << int(b)) if b >= 0
             else (int(a) >> -int(b))}[t]()
        s.append(r)
        return
    if t in ("abs", "neg", "ceiling", "floor", "round", "truncate", "sqrt",
             "sin", "cos", "ln", "log", "cvi", "cvr", "not"):
        a = s.pop()
        r = {"abs": lambda: abs(a), "neg": lambda: -a,
             "ceiling": lambda: math.ceil(a), "floor": lambda: math.floor(a),
             "round": lambda: math.floor(a + 0.5),
             "truncate": lambda: math.trunc(a), "sqrt": lambda: math.sqrt(a),
             "sin": lambda: math.sin(math.radians(a)),
             "cos": lambda: math.cos(math.radians(a)),
             "ln": lambda: math.log(a), "log": lambda: math.log10(a),
             "cvi": lambda: int(a), "cvr": lambda: float(a),
             "not": lambda: (not a) if isinstance(a, bool) else ~int(a)}[t]()
        s.append(r)
        return
    if t == "dup":
        s.append(s[-1])
    elif t == "pop":
        s.pop()
    elif t == "exch":
        s[-1], s[-2] = s[-2], s[-1]
    elif t == "copy":
        n = int(s.pop())
        if n:
            s.extend(s[-n:])
    elif t == "index":
        n = int(s.pop())
        s.append(s[-1 - n])
    elif t == "roll":
        j = int(s.pop())
        n = int(s.pop())
        if n:
            part = s[-n:]
            j %= n
            s[-n:] = part[-j:] + part[:-j] if j else part
    else:
        raise ValueError(f"unsupported operator {t}")
