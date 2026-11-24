"""The fast way of handing a graph to pyvis (build 2026-11-19d) gives
exactly what pyvis's own from_nx gives, and the application falls back to
pyvis's own when it would not.

Uses pyvis where installed (the comparison then runs against the real
library, including the written HTML file); otherwise a stand-in that
follows pyvis 0.3.2 (tests/fake_pyvis). All graphs are synthetic."""
import copy
import importlib
import os
import random
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import networkx as nx  # noqa: E402
from pdf_forensics.graph import visualization as V  # noqa: E402

try:
    import pyvis.network  # noqa: F401
    REAL_PYVIS = True
except ImportError:
    REAL_PYVIS = False

FAKE = os.path.join(HERE, "fake_pyvis")
Network = None
_saved = {}


def setUpModule():
    """Where pyvis is missing, the stand-in is visible only while these
    tests run (other tests decide from pyvis being importable)."""
    global Network
    if not REAL_PYVIS:
        sys.path.insert(0, FAKE)
    from pyvis.network import Network as _N
    Network = _N
    _saved["Network"] = V.__dict__.get("Network")
    V.Network = Network     # where pyvis was missing when V loaded


def tearDownModule():
    if _saved.get("Network") is None:
        V.__dict__.pop("Network", None)
    else:
        V.Network = _saved["Network"]
    if not REAL_PYVIS:
        sys.path.remove(FAKE)
        for m in [m for m in sys.modules
                  if m == "pyvis" or m.startswith("pyvis.")]:
            del sys.modules[m]


def make_net():
    return Network(height="100vh", width="100%", bgcolor="#1B1B1B",
                   font_color="#F0F0F0", notebook=False,
                   cdn_resources="remote")


def synthetic_graph(n_docs=40, n_images=600, links=2500, seed=7):
    """Document and image nodes, as the graphs have: string ids, some nodes
    with a size and some without, links with and without a weight, and an
    isolated node."""
    r = random.Random(seed)
    G = nx.Graph()
    docs = [f"doc:{k}" for k in range(n_docs)]
    imgs = [f"img:{k:04x}" for k in range(n_images)]
    for d in docs:
        G.add_node(d, label=d, shape="box", title=f"Document {d}",
                   color="#3A7BD5", size=25)
    for k, i in enumerate(imgs):
        attrs = {"shape": "image", "image": f"data:image/png;base64,{k}",
                 "title": f"Image {i}", "group": "image" if k % 5 else None}
        if k % 3:
            attrs["size"] = 12
        if attrs["group"] is None:
            del attrs["group"]
        G.add_node(i, **attrs)
    made = 0
    while made < links:
        d, i = r.choice(docs), r.choice(imgs)
        if G.has_edge(d, i):
            continue
        extra = {"weight": r.randint(1, 4)} if r.random() < 0.4 else {}
        G.add_edge(d, i, title=f"p{r.randint(1, 50)}", **extra)
        made += 1
    G.add_node("lonely", title="no links")
    return G


class FastGraphTest(unittest.TestCase):
    def test_same_records_and_same_graph_changes(self):
        G = synthetic_graph()
        g1, g2 = copy.deepcopy(G), copy.deepcopy(G)
        a, b = make_net(), make_net()
        a.from_nx(g1)
        V._fast_from_nx(b, g2)
        self.assertEqual(a.nodes, b.nodes)
        self.assertEqual(a.edges, b.edges)
        self.assertEqual(list(a.node_ids), list(b.node_ids))
        self.assertEqual(getattr(a, "node_map", None),
                         getattr(b, "node_map", None))
        # from_nx also changes the graph's attributes; the same changes
        self.assertEqual(dict(g1.nodes(data=True)), dict(g2.nodes(data=True)))
        self.assertEqual(list(g1.edges(data=True)), list(g2.edges(data=True)))
        # the instance's own add_edge is pyvis's again
        self.assertNotIn("add_edge", vars(b))
        self.assertTrue(V._fast_matches(make_net, G))

    def test_falls_back_when_not_identical(self):
        G = synthetic_graph(n_docs=5, n_images=50, links=120)
        self.assertFalse(V._fast_matches(make_net, nx.DiGraph(G)))
        self.assertFalse(V._fast_matches(make_net, nx.MultiGraph(G)))
        edge_mod = importlib.import_module("pyvis.edge")
        real_edge = edge_mod.Edge

        class OtherEdge(real_edge):          # a pyvis that differs
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.options["extra"] = 1
        edge_mod.Edge = OtherEdge
        try:
            self.assertFalse(V._fast_matches(make_net, G))
        finally:
            edge_mod.Edge = real_edge

    def test_visualize_records_path_and_same_file(self):
        G = synthetic_graph(n_docs=8, n_images=120, links=400)
        with tempfile.TemporaryDirectory() as tmp:
            outs = {}
            for path in ("fast", "pyvis"):
                saved = V._fast_matches
                if path == "pyvis":
                    V._fast_matches = lambda *a, **k: False
                try:
                    timings = {}
                    out = os.path.join(tmp, f"{path}.html")
                    V.visualize_graph(copy.deepcopy(G), {}, {}, "case.db",
                                      doc_meta={}, output_path=out,
                                      case_number="T-1", scope="all",
                                      group_versions=False,
                                      timings=timings)
                finally:
                    V._fast_matches = saved
                self.assertEqual(timings["network_path"], path)
                with open(out, encoding="utf-8") as fh:
                    html = fh.read()
                # the generation time differs between the two files
                import re
                outs[path] = re.sub(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d[^<\"]*",
                                    "", html)
            self.assertEqual(outs["fast"], outs["pyvis"])

    @unittest.skipUnless(REAL_PYVIS, "pyvis not installed")
    def test_large_graph_with_real_pyvis(self):
        G = synthetic_graph(n_docs=200, n_images=4000, links=12000)
        a, b = make_net(), make_net()
        a.from_nx(copy.deepcopy(G))
        V._fast_from_nx(b, copy.deepcopy(G))
        self.assertEqual(a.nodes, b.nodes)
        self.assertEqual(a.edges, b.edges)


if __name__ == "__main__":
    unittest.main()
