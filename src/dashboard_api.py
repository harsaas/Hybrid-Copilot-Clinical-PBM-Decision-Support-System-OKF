import json
import logging
from functools import lru_cache
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import frontmatter
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.okf_reader import load_okf_graph
from src.okf_writer import _extract_pdf_data


ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def _pdf_chunks(path: str, modified: int, size: int) -> list[dict]:
    pages, _ = _extract_pdf_data(path)
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = []
    for page, text in pages:
        for index, content in enumerate(splitter.split_text(text)):
            chunks.append({"page": page, "index": index, "text": content, "source": Path(path).name})
    return chunks


def load_dashboard_data(root: Path = ROOT) -> dict:
    directory = root / "docs" / "okf"
    nodes = []
    for path in sorted(directory.glob("*.md")):
        markdown = path.read_text(encoding="utf-8")
        post = frontmatter.loads(markdown)
        if not isinstance(post.get("id"), str) or not isinstance(post.get("title"), str):
            raise ValueError(f"Missing node ID or title in {path.name}")
        nodes.append({
            "id": post["id"],
            "title": post["title"],
            "type": post.get("type"),
            "tier": post.get("tier"),
            "restrictions": post.get("restrictions", {}),
            "raw_codes_found": post.get("raw_codes_found", []),
            "raw_requirements": post.get("raw_requirements", ""),
            "provenance": post.get("provenance", {}),
            "links": post.get("links", {}),
            "content": post.content,
            "markdown": markdown,
            "filename": path.name,
        })
    if len({node["id"] for node in nodes}) != len(nodes):
        raise ValueError("Duplicate Markdown node IDs")
    graph = load_okf_graph(str(directory))
    edges = [
        {"source": source, "target": target, "relation": attrs.get("relation")}
        for source, target, attrs in graph.edges(data=True)
    ]
    pdf = root / "data" / "real_clinical_formulary.pdf"
    chunks = []
    if pdf.is_file():
        stat = pdf.stat()
        chunks = _pdf_chunks(str(pdf), stat.st_mtime_ns, stat.st_size)
    warnings = []
    if not nodes:
        warnings.append("No generated Markdown files. Run the PDF writer using the local-data command in README.md first.")
    if not chunks:
        warnings.append("No cached real_clinical_formulary.pdf. PDF snippet preview is unavailable.")
    known_ids = {node["id"] for node in nodes}
    if any(edge["source"] not in known_ids or edge["target"] not in known_ids for edge in edges):
        warnings.append("Some graph links reference nodes without a Markdown file.")
    return {
        "nodes": nodes,
        "edges": edges,
        "chunks": chunks,
        "stats": {
            "pages": len({chunk["page"] for chunk in chunks}),
            "chunks": len(chunks),
            "markdown_files": len(nodes),
            "drug_files": sum(node["type"] == "clinical_drug" for node in nodes),
            "graph_nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
        },
        "warnings": warnings,
        "mode": "local-source-inspection",
        "source": pdf.name,
    }


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "dist"), **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/dashboard":
            try:
                data = load_dashboard_data()
            except (OSError, ValueError, TypeError, KeyError) as error:
                logging.exception("Could not load local dashboard data")
                self._json(500, {"error": f"Could not load local dashboard data ({type(error).__name__}). Check the server console."})
                return
            self._json(200, data)
        elif path == "/api/health":
            self._json(200, {"status": "ok"})
        elif path.startswith("/api/"):
            self._json(404, {"error": "Unknown API endpoint"})
        elif not (ROOT / "dist" / "index.html").is_file():
            self._json(503, {"error": "Frontend not built. Run npm install and npm run build, then reload."})
        else:
            super().do_GET()

    def list_directory(self, path):
        self.send_error(404, "Directory listing is disabled")
        return None

    def _json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    server = ThreadingHTTPServer(("127.0.0.1", 8000), DashboardHandler)
    print("OKF React dashboard: http://127.0.0.1:8000", flush=True)
    print("Local inspection only: no embeddings, Pinecone requests, or LLM calls.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
