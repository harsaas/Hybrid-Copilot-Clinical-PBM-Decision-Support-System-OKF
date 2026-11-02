import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
from unittest.mock import patch

from src.dashboard_api import DashboardHandler, load_dashboard_data


ROOT = Path(__file__).resolve().parents[1]


class DashboardApiTests(unittest.TestCase):
    def test_real_local_snapshot_preserves_source_data(self):
        if not (ROOT / "docs" / "okf" / "drug_fluconazole_oral_tablet_150_mg.md").is_file():
            self.skipTest("Generated local Markdown files are unavailable")
        data = load_dashboard_data()
        node = next(node for node in data["nodes"] if node["id"] == "drug_fluconazole_oral_tablet_150_mg")
        self.assertEqual(node["tier"], "Tier 1")
        self.assertTrue(node["restrictions"]["quantity_limit"])
        self.assertEqual(node["provenance"]["pages"], [9])
        self.assertEqual(
            node["markdown"],
            (ROOT / "docs" / "okf" / node["filename"]).read_text(encoding="utf-8"),
        )
        self.assertEqual(data["stats"]["markdown_files"], len(data["nodes"]))
        self.assertEqual(data["stats"]["edges"], len(data["edges"]))
        self.assertTrue(any("fluconazole" in chunk["text"].lower() for chunk in data["chunks"] if chunk["page"] == 9))
        self.assertTrue(all(0 < len(chunk["text"]) <= 500 for chunk in data["chunks"]))
        self.assertEqual(data["mode"], "local-source-inspection")
        self.assertNotIn("api_key", json.dumps(data).lower())

    def test_empty_data_has_explicit_warnings(self):
        with tempfile.TemporaryDirectory() as output:
            data = load_dashboard_data(Path(output))
        self.assertEqual(data["nodes"], [])
        self.assertEqual(data["chunks"], [])
        self.assertEqual(len(data["warnings"]), 2)

    def test_invalid_markdown_reports_error(self):
        with tempfile.TemporaryDirectory() as output:
            root = Path(output)
            directory = root / "docs" / "okf"
            directory.mkdir(parents=True)
            (directory / "bad.md").write_text("---\ntitle: Missing ID\n---\ntext", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Missing node ID"):
                load_dashboard_data(root)

    def test_http_json_and_explicit_failure(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(url + "/api/health", timeout=5) as response:
                self.assertEqual(json.load(response), {"status": "ok"})
            with patch("src.dashboard_api.load_dashboard_data", return_value={"nodes": []}):
                with urlopen(url + "/api/dashboard", timeout=5) as response:
                    self.assertEqual(json.load(response), {"nodes": []})
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
            with patch("src.dashboard_api.load_dashboard_data", side_effect=ValueError("bad source")):
                with self.assertLogs(level="ERROR"):
                    with self.assertRaises(HTTPError) as failure:
                        urlopen(url + "/api/dashboard", timeout=5)
                self.assertEqual(failure.exception.code, 500)
                self.assertIn("error", json.load(failure.exception))
            with self.assertRaises(HTTPError) as missing:
                urlopen(url + "/.env", timeout=5)
            self.assertIn(missing.exception.code, (404, 503))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
