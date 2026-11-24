"""A stand-in for pyvis (tests only), following pyvis 0.3.2's from_nx,
add_node and add_edge, including add_edge's search through every link
already added. Used where pyvis is not installed, to test the fast build
in graph/visualization.py; where pyvis is installed, the tests also
compare against the real one."""
