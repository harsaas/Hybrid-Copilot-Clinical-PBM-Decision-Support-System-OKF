import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import networkx as nx
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.hybrid_agent import HybridOKFAgent
from src.okf_reader import load_okf_graph
from src.okf_writer import parse_pdf_and_generate_okf


class HybridAgentTests(unittest.TestCase):
    def setUp(self):
        self.retriever = MagicMock()
        self.graph = nx.DiGraph()
        self.graph.add_node(
            "drug_sample", title="Sample drug", type="clinical_drug", content="Drug listing",
            provenance={"source": "test.pdf", "parsed_date": "2026-11-01", "pages": [9]},
        )
        self.graph.add_node("policy", content="Policy rules")
        self.graph.add_edge("drug_sample", "policy", relation="governing_policy")
        patcher = patch("src.hybrid_agent.ChatOpenAI")
        self.llm_class = patcher.start()
        self.addCleanup(patcher.stop)
        self.llm = self.llm_class.return_value
        self.llm.invoke.return_value.content = "Mock answer"
        self.agent = HybridOKFAgent(self.retriever, self.graph)

    def prompt(self):
        return self.llm.invoke.call_args.args[0]

    def test_explicit_link_traverses_graph(self):
        self.retriever.invoke.return_value = [
            Document(page_content="PDF snippet", metadata={"okf_node_link": "drug_sample"})
        ]
        self.assertEqual(self.agent.run("question"), "Mock answer")
        self.retriever.invoke.assert_called_once_with("question")
        self.assertIn("Node ID: drug_sample", self.prompt())
        self.assertIn("Policy rules", self.prompt())
        self.assertIn("PDF snippet", self.prompt())

    def test_empty_results(self):
        self.retriever.invoke.return_value = []
        self.agent.run("question")
        self.assertIn("No direct graph node found.", self.prompt())

    def test_missing_link_is_logged(self):
        self.retriever.invoke.return_value = [
            Document(page_content="text", metadata={"okf_node_link": "absent"})
        ]
        with self.assertLogs(level="WARNING"):
            self.agent.run("question")
        self.assertIn("No direct graph node found.", self.prompt())

    def test_source_page_and_title_match_current_vector_metadata(self):
        self.retriever.invoke.return_value = [
            Document(page_content="Listing: SAMPLE\ndrug | 1 | QL", metadata={"source": "test.pdf", "page": 9.0})
        ]
        self.agent.run("question")
        self.assertIn("Node ID: drug_sample", self.prompt())
        self.assertIn("Policy rules", self.prompt())

    def test_unrelated_sources_pages_and_titles_do_not_match(self):
        for source, page, text in (
            ("other.pdf", 9, "Sample drug"),
            ("test.pdf", 10, "Sample drug"),
            ("test.pdf", 9, "Another drug"),
            ("test.pdf", 9, "Sample drugstore"),
            ("test.pdf", None, "Sample drug"),
        ):
            with self.subTest(source=source, page=page, text=text):
                self.retriever.invoke.return_value = [
                    Document(page_content=text, metadata={"source": source, "page": page})
                ]
                self.agent.run("question")
                self.assertIn("No direct graph node found.", self.prompt())

    def test_later_results_and_duplicate_links(self):
        self.retriever.invoke.return_value = [
            Document(page_content="first"),
            Document(page_content="second", metadata={"okf_node_link": "drug_sample"}),
            Document(page_content="third", metadata={"okf_node_link": "drug_sample"}),
        ]
        self.agent.run("question")
        self.assertEqual(self.prompt().count("Node ID: drug_sample"), 1)
        self.assertIn("first\n---\nsecond\n---\nthird", self.prompt())

    def test_multiple_matched_nodes(self):
        self.graph.add_node(
            "drug_second", title="Second drug", type="clinical_drug", content="Second listing",
            provenance={"source": "test.pdf", "pages": [9]},
        )
        self.retriever.invoke.return_value = [
            Document(page_content="Sample drug; Second drug", metadata={"source": "test.pdf", "page": 9})
        ]
        self.agent.run("question")
        self.assertIn("Node ID: drug_sample", self.prompt())
        self.assertIn("Node ID: drug_second", self.prompt())

    def test_writer_provenance_is_preserved_without_verification_claim(self):
        self.retriever.invoke.return_value = [
            Document(page_content="text", metadata={"okf_node_link": "drug_sample"})
        ]
        self.agent.run("question")
        self.assertIn("'parsed_date': '2026-11-01'", self.prompt())
        self.assertIn("'pages': [9]", self.prompt())
        self.assertNotIn("Verified:", self.prompt())

    def test_errors_propagate(self):
        self.retriever.invoke.side_effect = RuntimeError("retrieval failed")
        with self.assertRaisesRegex(RuntimeError, "retrieval failed"):
            self.agent.run("question")
        self.llm.invoke.assert_not_called()
        self.retriever.invoke.side_effect = None
        self.retriever.invoke.return_value = []
        self.llm.invoke.side_effect = RuntimeError("generation failed")
        with self.assertRaisesRegex(RuntimeError, "generation failed"):
            self.agent.run("question")

    def test_real_pdf_writer_reader_and_splitter_integration(self):
        pdf_path = (
            Path(__file__).resolve().parents[1] / "data"
            / "MedMutual-2026-National-Preferred_National-Preferred-Plus-Prescription-Drug-Formulary.pdf"
        )
        if not pdf_path.is_file():
            self.skipTest("Local formulary PDF is not available")
        with tempfile.TemporaryDirectory() as output:
            chunks = parse_pdf_and_generate_okf(str(pdf_path), output)
            graph = load_okf_graph(output)
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        docs = []
        for page, text in chunks:
            docs.extend(splitter.create_documents([text], metadatas=[{"source": pdf_path.name, "page": page}]))
        nid, data = next((nid, data) for nid, data in graph.nodes(data=True) if data["type"] == "clinical_drug")
        title = " ".join(data["title"].split()).casefold()
        doc = next(
            doc for doc in docs
            if doc.metadata["page"] in data["provenance"]["pages"]
            and title in " ".join(doc.page_content.split()).casefold()
        )
        self.agent.graph = graph
        self.retriever.invoke.return_value = [doc]
        self.agent.run("What are the formulary requirements?")
        self.assertIn(f"Node ID: {nid}", self.prompt())
        self.assertIn("Target: rule_national_preferred_formulary", self.prompt())
        self.assertIn("'parsed_date':", self.prompt())


if __name__ == "__main__":
    unittest.main()
