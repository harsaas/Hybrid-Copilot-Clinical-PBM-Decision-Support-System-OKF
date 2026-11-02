import os
import frontmatter
import networkx as nx

def load_okf_graph(okf_dir: str) -> nx.DiGraph:
    """Scans docs/okf/, parses YAML frontmatter, and loads into NetworkX graph."""
    g = nx.DiGraph()
    if not os.path.exists(okf_dir):
        return g
        
    for root, _, files in os.walk(okf_dir):
        for file in files:
            if file.endswith(".md"):
                path = os.path.join(root, file)
                post = frontmatter.load(path)
                nid = post.get("id", file)
                
                g.add_node(nid, title=post.get("title"), type=post.get("type"), 
                           provenance=post.get("provenance", {}), content=post.content)
                
                for rel, targets in post.get("links", {}).items():
                    targets = targets if isinstance(targets, list) else [targets]
                    for t in targets:
                        g.add_edge(nid, t, relation=rel)
                        
    print(f"Loaded NetworkX Graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges.")
    return g