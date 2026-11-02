import tempfile
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pdfplumber
import yaml

from src.okf_writer import _extract_pdf_data, parse_pbm_restrictions, parse_pdf_and_generate_okf


class RestrictionTests(unittest.TestCase):
    def test_codes_and_explicit_tier(self):
        result = parse_pbm_restrictions([None, "Tier 2", "pa; QL / st"])
        self.assertEqual(result["tier"], "Tier 2")
        self.assertEqual(result["raw_codes_found"], ["PA", "QL", "ST"])
        self.assertTrue(all(result["restrictions"].values()))

    def test_no_default_or_substring_matches(self):
        result = parse_pbm_restrictions([None, 250, "PASTA QLIMIT STRENGTH"])
        self.assertIsNone(result["tier"])
        self.assertEqual(result["raw_codes_found"], [])
        self.assertFalse(any(result["restrictions"].values()))

    def test_tier_formats(self):
        for cell in ("T5", "tier 5", "Tier 5 (ACA)"):
            with self.subTest(cell=cell):
                self.assertEqual(parse_pbm_restrictions([cell])["tier"], "Tier 5")
        self.assertEqual(parse_pbm_restrictions(["drug", 5], 1)["tier"], "Tier 5")
        self.assertIsNone(parse_pbm_restrictions(["drug", "250 mg"], 1)["tier"])


class WriterTests(unittest.TestCase):
    def test_extraction_preserves_text_and_skips_invalid_tables(self):
        valid = [
            ["Drug Name", "Drug", "Requirements\n/ Limits"],
            [None, "Tier", None],
            ["drug", "1", "QL"],
            ["drug", "1", "QL"],
        ]
        malformed = [*valid, ["incomplete", "2"]]
        wrong_header = [
            ["Name", "Drug", "Requirements\n/ Limits"],
            [None, "Tier", None],
            ["not a drug listing", "1", "PA"],
        ]
        tables = [[], malformed, wrong_header, valid]
        page = MagicMock()
        page.extract_text.return_value = None
        page.extract_tables.return_value = tables
        pdf = MagicMock()
        pdf.pages = [page]
        with patch("src.okf_writer.pdfplumber.open") as open_pdf:
            open_pdf.return_value.__enter__.return_value = pdf
            with self.assertLogs(level="WARNING") as logs:
                chunks, drugs = _extract_pdf_data("formulary.pdf")
        self.assertEqual(len(logs.output), 2)
        expected_text = "--- Page 1 ---\n\n"
        for table in tables:
            for row in table:
                expected_text += " | ".join(str(cell or "").strip() for cell in row) + "\n"
        self.assertEqual(chunks, [(1, expected_text)])
        self.assertEqual(list(drugs), [("drug", "Tier 1", "QL")])
        info, pages = drugs[("drug", "Tier 1", "QL")]
        self.assertEqual(pages, [1])
        self.assertEqual(info["raw_codes_found"], ["QL"])

    def test_dynamic_nodes_pages_collisions_and_unknown_tier(self):
        table = [
            ["Drug Name", "Drug", "Requirements\n/ Limits"],
            [None, "Tier", None],
            ["ANTIVIRALS", None, None],
            [None, "", None],
            ["Drug-A", "5", "PA; QL; ACA"],
            ["Drug A", "2", "ST"],
            ["ST drug", "", ""],
        ]
        pdf = MagicMock()
        pdf.pages = [MagicMock() for _ in range(16)]
        for page in pdf.pages:
            page.extract_text.return_value = "Source text"
            page.extract_tables.return_value = [table]
        with patch("src.okf_writer.pdfplumber.open") as open_pdf:
            open_pdf.return_value.__enter__.return_value = pdf
            with tempfile.TemporaryDirectory() as output:
                with self.assertLogs(level="WARNING") as logs:
                    chunks = parse_pdf_and_generate_okf("formulary.pdf", output)
                self.assertTrue(any("Unknown tier" in line for line in logs.output))
                self.assertEqual(len(chunks), 15)
                pdf.pages[15].extract_tables.assert_not_called()
                nodes = {}
                for path in Path(output).glob("*.md"):
                    content = path.read_text(encoding="utf-8")
                    node = yaml.safe_load(content.split("---\n", 2)[1])
                    self.assertEqual(path.stem, node["id"])
                    nodes[node["id"]] = node
                self.assertEqual(len(nodes), 4)
                self.assertEqual(nodes["drug_drug_a"]["tier"], "Tier 5")
                self.assertEqual(nodes["drug_drug_a"]["raw_requirements"], "PA; QL; ACA")
                self.assertEqual(nodes["drug_drug_a"]["provenance"]["pages"], list(range(1, 16)))
                self.assertEqual(nodes["drug_drug_a_2"]["raw_codes_found"], ["ST"])
                self.assertIsNone(nodes["drug_st_drug"]["tier"])
                self.assertEqual(nodes["drug_st_drug"]["raw_codes_found"], [])
                links = nodes["rule_national_preferred_formulary"]["links"]["governing_policy"]
                self.assertEqual(set(links), set(nodes) - {"rule_national_preferred_formulary"})

    def test_no_recognized_drugs_is_an_error(self):
        pdf = MagicMock()
        page = MagicMock()
        page.extract_text.return_value = "No drug listing"
        page.extract_tables.return_value = [[["unrecognized"]]]
        pdf.pages = [page]
        with patch("src.okf_writer.pdfplumber.open") as open_pdf:
            open_pdf.return_value.__enter__.return_value = pdf
            with tempfile.TemporaryDirectory() as output:
                with self.assertLogs(level="WARNING"):
                    with self.assertRaisesRegex(ValueError, "No drug rows"):
                        parse_pdf_and_generate_okf("formulary.pdf", output)
                self.assertEqual(list(Path(output).iterdir()), [])

    def test_supplied_pdf_matches_source_rows(self):
        pdf_path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "MedMutual-2026-National-Preferred_National-Preferred-Plus-Prescription-Drug-Formulary.pdf"
        )
        if not pdf_path.is_file():
            self.skipTest("Local formulary PDF is not available")
        expected = {}
        with pdfplumber.open(pdf_path) as pdf:
            for number, page in enumerate(pdf.pages[:15], 1):
                for table in page.extract_tables():
                    for row in table[2:]:
                        if len(row) == 3 and row[0] and row[1] is not None:
                            name = " ".join(row[0].split())
                            requirements = " ".join((row[2] or "").split())
                            key = (name, f"Tier {row[1].strip()}", requirements)
                            expected.setdefault(key, set()).add(number)
        self.assertTrue(expected)
        with tempfile.TemporaryDirectory() as output:
            chunks = parse_pdf_and_generate_okf(str(pdf_path), output)
            self.assertEqual(len(chunks), 15)
            nodes = [
                yaml.safe_load(path.read_text(encoding="utf-8").split("---\n", 2)[1])
                for path in Path(output).glob("*.md")
            ]
            drugs = [node for node in nodes if node["type"] == "clinical_drug"]
            actual = {
                (node["title"], node["tier"], node["raw_requirements"]):
                set(node["provenance"]["pages"])
                for node in drugs
            }
            self.assertEqual(actual, expected)
            self.assertEqual(len(drugs), len(expected))
            for node in drugs:
                codes = [
                    code for code in ("PA", "QL", "ST")
                    if re.search(rf"\b{code}\b", node["raw_requirements"])
                ]
                self.assertEqual(node["raw_codes_found"], codes)
                for field, code in (
                    ("prior_authorization", "PA"),
                    ("quantity_limit", "QL"),
                    ("step_therapy", "ST"),
                ):
                    self.assertEqual(node["restrictions"][field], code in codes)
            formulary = next(node for node in nodes if node["type"] == "pbm_formulary_standard")
            self.assertEqual(
                set(formulary["links"]["governing_policy"]),
                {node["id"] for node in drugs},
            )


if __name__ == "__main__":
    unittest.main()
