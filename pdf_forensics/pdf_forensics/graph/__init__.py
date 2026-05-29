"""
Graph analysis engine — interactive HTML visualizations.
"""

try:
    import networkx
    import pyvis
    HAS_GRAPH = True
except ImportError:
    HAS_GRAPH = False
