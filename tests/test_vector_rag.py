import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.okf_writer import parse_pdf_and_generate_okf
from src.vector_rag import initialize_vector_retriever


class VectorRetrieverTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "PINECONE_API_KEY": "test-key", "INDEX_NAME": "test-index"},
            clear=True,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.dotenv = patch("src.vector_rag.load_dotenv")
        self.dotenv.start()
        self.addCleanup(self.dotenv.stop)
        self.embeddings = patch("src.vector_rag.OpenAIEmbeddings")
        self.embedding_class = self.embeddings.start()
        self.addCleanup(self.embeddings.stop)
        self.pinecone = patch("src.vector_rag.PineconeVectorStore")
        self.store_class = self.pinecone.start()
        self.addCleanup(self.pinecone.stop)

    def test_all_chunks_metadata_automatic_ids_and_retriever(self):
        chunks = [(page, "Drug entry. " * 100) for page in range(1, 17)]
        retriever = initialize_vector_retriever(chunks, source="test.pdf")
        store = self.store_class.return_value
        call = store.add_documents.call_args
        docs = call.args[0]
        self.assertEqual({doc.metadata["page"] for doc in docs}, set(range(1, 17)))
        self.assertGreater(len(docs), len(chunks))
        self.assertTrue(all(0 < len(doc.page_content) <= 500 for doc in docs))
        self.assertTrue(all(doc.metadata["source"] == "test.pdf" for doc in docs))
        self.assertTrue(all("okf_node_link" not in doc.metadata for doc in docs))
        self.assertTrue(all("chunk_index" not in doc.metadata for doc in docs))
        self.assertNotIn("ids", call.kwargs)
        self.assertFalse(call.kwargs["async_req"])
        self.assertIs(retriever, store.as_retriever.return_value)
        store.as_retriever.assert_called_once_with(search_kwargs={"k": 2})
        self.embedding_class.assert_called_once_with(model="text-embedding-3-small")
        self.assertEqual(self.store_class.call_args.kwargs["index_name"], "test-index")
        first_namespace = self.store_class.call_args.kwargs["namespace"]
        initialize_vector_retriever(chunks, source="test.pdf")
        self.assertEqual(self.store_class.call_args.kwargs["namespace"], first_namespace)
        self.assertNotIn("ids", store.add_documents.call_args.kwargs)
        initialize_vector_retriever(chunks, source="other.pdf")
        self.assertNotEqual(self.store_class.call_args.kwargs["namespace"], first_namespace)

    def test_invalid_inputs_do_not_call_external_services(self):
        for chunks, source in (
            ([], "test.pdf"),
            ([(1, "text")], " "),
            ([(0, "text")], "test.pdf"),
            ([(True, "text")], "test.pdf"),
            ([(1, " ")], "test.pdf"),
        ):
            with self.subTest(chunks=chunks, source=source):
                with self.assertRaises(ValueError):
                    initialize_vector_retriever(chunks, source)
        self.embedding_class.assert_not_called()
        self.store_class.assert_not_called()

    def test_missing_configuration_names_are_reported(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY, PINECONE_API_KEY, INDEX_NAME"):
                initialize_vector_retriever([(1, "text")])
        self.store_class.assert_not_called()

    def test_storage_failure_is_not_hidden(self):
        self.store_class.return_value.add_documents.side_effect = RuntimeError("upsert failed")
        with self.assertRaisesRegex(RuntimeError, "upsert failed"):
            initialize_vector_retriever([(1, "text")])
        self.store_class.return_value.as_retriever.assert_not_called()

    def test_local_pdf_pages_are_all_passed_to_storage(self):
        pdf_path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "MedMutual-2026-National-Preferred_National-Preferred-Plus-Prescription-Drug-Formulary.pdf"
        )
        if not pdf_path.is_file():
            self.skipTest("Local formulary PDF is not available")
        with tempfile.TemporaryDirectory() as output:
            chunks = parse_pdf_and_generate_okf(str(pdf_path), output)
        initialize_vector_retriever(chunks, source=pdf_path.name)
        docs = self.store_class.return_value.add_documents.call_args.args[0]
        self.assertEqual({doc.metadata["page"] for doc in docs}, set(range(1, 16)))
        self.assertTrue(all(len(doc.page_content) <= 500 for doc in docs))


if __name__ == "__main__":
    unittest.main()
