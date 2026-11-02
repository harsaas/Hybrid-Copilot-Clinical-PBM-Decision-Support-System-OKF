import logging
import re

import networkx as nx
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

class HybridOKFAgent:
    def __init__(self, retriever, graph: nx.DiGraph):
        self.retriever = retriever
        self.graph = graph
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
        self.prompt = ChatPromptTemplate.from_template("""
You are an expert PBM clinical decision-support copilot.
Answer the clinician query using the PDF vector snippets and any matched OKF source listings.
These listings are extracted formulary information, not independently verified clinical rules.
If no graph node matches, explicitly state that graph context is unavailable.
Do not invent coverage requirements or treat a parsed date as clinical verification.

Clinician Query: {query}

---
[Real PDF Table/Text Vector RAG Context]:
{vector_context}

---
[OKF Source Listings Traversed via NetworkX]:
{okf_graph_context}
""")

    def run(self, query: str):
        docs = self.retriever.invoke(query)
        v_context = "\n---\n".join([d.page_content for d in docs])
        
        matched_ids = []
        for doc in docs:
            linked_id = doc.metadata.get("okf_node_link")
            if linked_id:
                if linked_id in self.graph:
                    if linked_id not in matched_ids:
                        matched_ids.append(linked_id)
                    continue
                logging.warning("Retrieved graph link %r does not exist", linked_id)

            source = doc.metadata.get("source")
            page = doc.metadata.get("page")
            if not isinstance(source, str) or not isinstance(page, (int, float)) or isinstance(page, bool):
                continue
            snippet = " ".join(doc.page_content.split()).casefold()
            for nid, data in self.graph.nodes(data=True):
                provenance = data.get("provenance", {})
                title = data.get("title")
                if (
                    data.get("type") != "clinical_drug"
                    or provenance.get("source") != source
                    or page not in provenance.get("pages", [])
                    or not isinstance(title, str)
                    or not title.strip()
                ):
                    continue
                title = " ".join(title.split()).casefold()
                if re.search(rf"(?<!\w){re.escape(title)}(?!\w)", snippet) and nid not in matched_ids:
                    matched_ids.append(nid)

        contexts = []
        for nid in matched_ids:
            ndata = self.graph.nodes[nid]
            prov = ndata.get("provenance", {})
            rules = []
            for nbr, edata in self.graph[nid].items():
                rules.append(f"- Relation: [{edata.get('relation')}] -> Target: {nbr} | Content: {self.graph.nodes[nbr].get('content')}")
            contexts.append(f"""
Node ID: {nid} | Title: {ndata.get('title')}
Provenance: {prov}
Content: {ndata.get('content')}
Traversed Rules:\n{chr(10).join(rules)}
""")
        graph_context = "\n---\n".join(contexts) if contexts else "No direct graph node found."

        prompt_filled = self.prompt.format(query=query, vector_context=v_context, okf_graph_context=graph_context)
        return self.llm.invoke(prompt_filled).content