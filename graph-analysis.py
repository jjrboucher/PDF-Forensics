import sqlite3
import networkx as nx
from pyvis.network import Network

DB_PATH = "C:/Users/Forensics/Documents/Python Scripts/pdf-image-forensics/PDFs-006.2.2.x.db"  # <-- change this

def load_data(conn):
    query = """
    SELECT
        a.id AS analysis_id,
        a.pdf_filename,
        p.id AS page_id,
        p.page_number,
        i.id AS image_id,
        idata.md5_hash
    FROM image_data idata
    JOIN images i   ON i.image_data_id = idata.id
    JOIN pages p    ON p.id = i.page_id
    JOIN analyses a ON a.id = p.analysis_id
    WHERE idata.md5_hash IN (
    SELECT md5_hash
    FROM image_data
    GROUP BY md5_hash
    HAVING COUNT(*) > 1
    """
    return conn.execute(query).fetchall()


def build_graph(rows):
    G = nx.Graph()

    for row in rows:
        analysis_id, pdf_filename, page_id, page_number, image_id, md5 = row

        doc_node = f"doc_{analysis_id}"
        page_node = f"page_{page_id}"
        image_node = f"img_{md5}"

        # --- Add document node ---
        if not G.has_node(doc_node):
            G.add_node(
                doc_node,
                label=pdf_filename,
                title=f"Document: {pdf_filename}",
                color="blue"
            )

        # --- Add page node ---
        if not G.has_node(page_node):
            G.add_node(
                page_node,
                label=f"Page {page_number}",
                title=f"{pdf_filename} - Page {page_number}",
                color="green"
            )

        # --- Add image node ---
        if not G.has_node(image_node):
            G.add_node(
                image_node,
                label=md5[:8],  # short hash
                title=f"MD5: {md5}",
                color="red"
            )

        # --- Edges ---
        G.add_edge(doc_node, page_node)
        G.add_edge(page_node, image_node)

    return G


def enhance_image_tooltips(G):
    """
    Add richer info to image nodes:
    show all pages where image appears
    """
    image_usage = {}

    for node1, node2 in G.edges():
        if node1.startswith("page_") and node2.startswith("img_"):
            image_usage.setdefault(node2, []).append(node1)
        elif node2.startswith("page_") and node1.startswith("img_"):
            image_usage.setdefault(node1, []).append(node2)

    for img_node, pages in image_usage.items():
        page_list = ", ".join(pages[:20])
        if len(pages) > 20:
            page_list += "..."

        G.nodes[img_node]["title"] += f"<br>Used on {len(pages)} pages:<br>{page_list}"


def visualize_graph(G):
    net = Network(height="800px", width="100%", bgcolor="#222222", font_color="white")

    net.from_nx(G)

    # Physics settings for better layout
    net.set_options("""
    var options = {
      "physics": {
        "forceAtlas2Based": {
          "gravitationalConstant": -50,
          "centralGravity": 0.01,
          "springLength": 100
        },
        "minVelocity": 0.75,
        "solver": "forceAtlas2Based"
      }
    }
    """)

    net.show("image_relationship_graph.html")


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading data...")
    rows = load_data(conn)

    print(f"Loaded {len(rows)} rows")

    print("Building graph...")
    G = build_graph(rows)

    print("Enhancing tooltips...")
    enhance_image_tooltips(G)

    print("Rendering...")
    visualize_graph(G)

    print("Done. Open image_relationship_graph.html in your browser.")


if __name__ == "__main__":
    main()