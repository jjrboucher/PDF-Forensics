"""Static checks over the whole package: every module compiles, and no
function uses a name that is never defined (a mistake that compiles but
fails when that code runs, e.g. in a GUI path that cannot be exercised
headless). Uses only the standard library (symtable)."""
import ast
import builtins
import os
import symtable
import unittest

PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), "pdf_forensics")
ALLOWED = {"__file__", "__name__", "__doc__", "__spec__", "__builtins__",
           "__path__", "__package__", "__loader__", "WindowsError"}


def _sources():
    for dirpath, _, files in os.walk(PKG):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def _top_names(path, seen=None):
    """Names a module defines at top level, including those it takes
    from the package's own modules with 'import *'."""
    seen = seen if seen is not None else set()
    if path in seen:
        return set(), True
    seen.add(path)
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    top = symtable.symtable(src, path, "exec")
    names = {s.get_name() for s in top.get_symbols()
             if s.is_assigned() or s.is_imported() or s.is_namespace()}
    resolved = True
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.ImportFrom)
                and any(a.name == "*" for a in node.names)):
            mod = node.module or ""
            if not mod.startswith("pdf_forensics"):
                resolved = False        # outside the package: unknown
                continue
            rel = mod.split(".")[1:]
            target = os.path.join(PKG, *rel) + ".py"
            if not os.path.isfile(target):
                target = os.path.join(PKG, *rel, "__init__.py")
            more, ok = _top_names(target, seen)
            names |= {n for n in more if not n.startswith("_")}
            resolved = resolved and ok
    return names, resolved


def undefined_names(path):
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    top = symtable.symtable(src, path, "exec")
    # 'import *' from the package's own modules is resolved (build
    # 2026-11-19b: app.py, which imports the theme that way, was not being
    # checked at all, and a removed name slipped through)
    module_names, resolved = _top_names(path)
    star = not resolved
    out = []

    def walk(tab):
        for sym in tab.get_symbols():
            n = sym.get_name()
            if (tab is not top and sym.is_global() and sym.is_referenced()
                    and n not in module_names and not hasattr(builtins, n)
                    and n not in ALLOWED):
                out.append((tab.get_name(), tab.get_lineno(), n))
        for child in tab.get_children():
            walk(child)
    walk(top)
    # names used at module level only
    for sym in top.get_symbols():
        n = sym.get_name()
        if (sym.is_referenced() and not (sym.is_assigned() or
                sym.is_imported() or sym.is_namespace())
                and not hasattr(builtins, n) and n not in ALLOWED):
            out.append(("<module>", 0, n))
    return [] if star else out


class StaticTest(unittest.TestCase):
    def test_compiles(self):
        for p in _sources():
            with self.subTest(p=p):
                with open(p, encoding="utf-8") as fh:
                    compile(fh.read(), p, "exec")

    def test_no_undefined_names(self):
        problems = []
        for p in _sources():
            for scope, line, name in undefined_names(p):
                problems.append(f"{os.path.relpath(p, PKG)}: {name} "
                                f"(in {scope}, line {line})")
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
