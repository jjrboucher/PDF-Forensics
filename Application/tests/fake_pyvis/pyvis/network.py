import networkx as nx
from .node import Node
from .edge import Edge


class Network(object):
    def __init__(self, height="600px", width="100%", directed=False,
                 notebook=False, bgcolor="#ffffff", font_color=False,
                 cdn_resources="local", **kw):
        self.nodes = []
        self.edges = []
        self.height = height
        self.width = width
        self.directed = directed
        self.node_ids = []
        self.node_map = {}
        self.bgcolor = bgcolor
        self.font_color = font_color
        self.options = None

    def get_nodes(self):
        return self.node_ids

    def add_node(self, n_id, label=None, shape="dot", color="#97c2fc",
                 **options):
        assert isinstance(n_id, str) or isinstance(n_id, int)
        node_label = label if label else n_id
        if n_id not in self.node_ids:
            if "group" in options:
                n = Node(n_id, shape, label=node_label,
                         font_color=self.font_color, **options)
            else:
                n = Node(n_id, shape, label=node_label, color=color,
                         font_color=self.font_color, **options)
            self.nodes.append(n.options)
            self.node_ids.append(n_id)
            self.node_map[n_id] = n.options

    def add_edge(self, source, to, **options):
        edge_exists = False
        assert source in self.get_nodes()
        assert to in self.get_nodes()
        if not self.directed:
            for e in self.edges:
                frm = e["from"]
                dest = e["to"]
                if ((source == dest and to == frm) or
                        (source == frm and to == dest)):
                    edge_exists = True
        if not edge_exists:
            e = Edge(source, to, self.directed, **options)
            self.edges.append(e.options)

    def from_nx(self, nx_graph, node_size_transf=(lambda x: x),
                edge_weight_transf=(lambda x: x), default_node_size=10,
                default_edge_weight=1, show_edge_weights=True,
                edge_scaling=False):
        assert isinstance(nx_graph, nx.Graph)
        edges = nx_graph.edges(data=True)
        nodes = nx_graph.nodes(data=True)
        if len(edges) > 0:
            for e in edges:
                if "size" not in nodes[e[0]].keys():
                    nodes[e[0]]["size"] = default_node_size
                nodes[e[0]]["size"] = int(node_size_transf(
                    nodes[e[0]]["size"]))
                if "size" not in nodes[e[1]].keys():
                    nodes[e[1]]["size"] = default_node_size
                nodes[e[1]]["size"] = int(node_size_transf(
                    nodes[e[1]]["size"]))
                self.add_node(e[0], **nodes[e[0]])
                self.add_node(e[1], **nodes[e[1]])
                if "value" not in e[2] or "width" not in e[2]:
                    width_type = "value" if edge_scaling else "width"
                    if "weight" not in e[2].keys():
                        e[2]["weight"] = default_edge_weight
                    e[2][width_type] = edge_weight_transf(e[2]["weight"])
                    e[2][width_type] = e[2].pop("weight")
                self.add_edge(e[0], e[1], **e[2])
        for node in nx.isolates(nx_graph):
            if "size" not in nodes[node].keys():
                nodes[node]["size"] = default_node_size
            self.add_node(node, **nodes[node])

    def set_options(self, options):
        self.options = options

    def write_html(self, name, notebook=False, open_browser=False):
        import json
        with open(name, "w", encoding="utf-8") as fh:
            fh.write("<html><body><script>var nodes = "
                     + json.dumps(self.nodes) + "; var edges = "
                     + json.dumps(self.edges) + ";</script></body></html>")
