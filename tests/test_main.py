import contextlib
import io
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class MainTests(unittest.TestCase):
    def test_pipeline_passes_matching_source_and_reports_stages(self):
        with (
            tempfile.TemporaryDirectory() as output,
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True),
            patch("dotenv.load_dotenv") as load_env,
            patch("src.okf_writer.download_real_pdf") as download,
            patch("src.okf_writer.parse_pdf_and_generate_okf") as writer,
            patch("src.okf_reader.load_okf_graph") as reader,
            patch("src.vector_rag.initialize_vector_retriever") as vectorizer,
            patch("src.hybrid_agent.HybridOKFAgent") as agent,
        ):
            pdf = Path(output) / "formulary.pdf"
            pdf.write_bytes(b"%PDF-test")
            chunks = [(1, "test page")]
            writer.return_value = chunks
            agent.return_value.run.return_value = "test answer"
            captured = io.StringIO()
            with patch("os.path.getsize", return_value=pdf.stat().st_size):
                with contextlib.redirect_stdout(captured):
                    state = runpy.run_module("src.main", run_name="__main__")
            load_env.assert_called_once_with(Path(state["__file__"]).resolve().parents[1] / ".env")
            download.assert_called_once_with(state["REAL_PDF_URL"], state["LOCAL_PDF_PATH"])
            writer.assert_called_once_with(state["LOCAL_PDF_PATH"], state["OKF_DIR"])
            reader.assert_called_once_with(state["OKF_DIR"])
            vectorizer.assert_called_once_with(chunks, source=os.path.basename(state["LOCAL_PDF_PATH"]))
            agent.assert_called_once_with(vectorizer.return_value, reader.return_value)
            agent.return_value.run.assert_called_once_with(
                "What tier and requirements are listed for fluconazole oral tablet 150 mg?"
            )
            for stage in range(1, 6):
                self.assertIn(f"[{stage}/5]", captured.getvalue())
            self.assertIn("test answer", captured.getvalue())

    def test_missing_key_stops_before_download(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("dotenv.load_dotenv"),
            patch("src.okf_writer.download_real_pdf") as download,
        ):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY is missing"):
                runpy.run_module("src.main", run_name="__main__")
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
