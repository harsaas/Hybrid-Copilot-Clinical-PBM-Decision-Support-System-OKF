import logging
import os
import re
from collections.abc import Sequence
from datetime import date
from typing import TypedDict

import requests
import yaml
import pdfplumber


class Restrictions(TypedDict):
    prior_authorization: bool
    quantity_limit: bool
    step_therapy: bool


class PbmRestrictions(TypedDict):
    tier: str | None
    restrictions: Restrictions
    raw_codes_found: list[str]


DrugListings = dict[tuple[str, str | None, str], tuple[PbmRestrictions, list[int]]]


def parse_pbm_restrictions(
    row_cells: Sequence[str | int | None],
    tier_column_index: int | None = None,
) -> PbmRestrictions:
    """Extract explicit tiers and PA/QL/ST tokens; never assume a missing tier."""
    cells = [str(cell).strip() if cell is not None else "" for cell in row_cells]
    row_text = " ".join(cells).upper()
    codes = [code for code in ("PA", "QL", "ST") if re.search(rf"\b{code}\b", row_text)]
    tier = None
    if tier_column_index is not None:
        tier_cell = cells[tier_column_index]
        if re.fullmatch(r"[1-9]\d*", tier_cell):
            tier = f"Tier {tier_cell}"
    if tier is None:
        for cell in cells:
            match = re.fullmatch(r"(?:TIER\s+|T)([1-9]\d*)(?:\s*\([^)]*\))?", cell, re.I)
            if match:
                tier = f"Tier {match.group(1)}"
                break
    return {
        "tier": tier,
        "restrictions": {
            "prior_authorization": "PA" in codes,
            "quantity_limit": "QL" in codes,
            "step_therapy": "ST" in codes,
        },
        "raw_codes_found": codes,
    }


def download_real_pdf(url: str, output_path: str):
    """Downloads live enterprise PBM PDF if not cached locally."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if not os.path.exists(output_path):
        print(f"Downloading live enterprise PBM PDF from: {url}")
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print("Download successful.")
        else:
            raise Exception(f"Failed to download PDF. Status: {response.status_code}")
    else:
        print(f"Using cached PDF: {output_path}")


def _extract_pdf_data(pdf_path: str) -> tuple[list[tuple[int, str]], DrugListings]:
    """Read page text and collect drugs from the first 15 pages."""
    extracted_chunks: list[tuple[int, str]] = []
    drugs: DrugListings = {}

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages[:15], start=1):
            page_text = page.extract_text() or ""
            table_lines = []

            for table in page.extract_tables():
                for row in table:
                    table_lines.append(" | ".join(str(cell or "").strip() for cell in row) + "\n")
                if not table:
                    continue
                if any(len(row) != 3 for row in table):
                    logging.warning("Skipping unrecognized table on PDF page %s", page_number)
                    continue

                header = []
                for column in range(3):
                    text = " ".join(str(row[column] or "") for row in table[:2])
                    header.append(text.strip().lower())
                if (
                    header[0] != "drug name"
                    or "tier" not in header[1]
                    or "requirements" not in header[2]
                ):
                    logging.warning("Skipping unrecognized table on PDF page %s", page_number)
                    continue

                for name_cell, tier_cell, requirements_cell in table[2:]:
                    if not name_cell or (tier_cell is None and requirements_cell is None):
                        continue
                    name = " ".join(name_cell.split())
                    requirements = " ".join((requirements_cell or "").split())
                    # Scan requirements, not the drug name, for restriction codes.
                    info = parse_pbm_restrictions([tier_cell, requirements], tier_column_index=0)
                    if info["tier"] is None:
                        logging.warning("Unknown tier for %r on PDF page %s", name, page_number)

                    key = (name, info["tier"], requirements)
                    if key not in drugs:
                        drugs[key] = (info, [])
                    pages = drugs[key][1]
                    if page_number not in pages:
                        pages.append(page_number)

            table_text = "".join(table_lines)
            combined = f"--- Page {page_number} ---\n{page_text}\n{table_text}"
            extracted_chunks.append((page_number, combined))

    return extracted_chunks, drugs


def _write_okf_node(
    output_dir: str, node_id: str, metadata: dict[str, object], body: str
) -> None:
    with open(os.path.join(output_dir, f"{node_id}.md"), "w", encoding="utf-8") as f:
        f.write(f"---\n{yaml.safe_dump(metadata, sort_keys=False)}---\n{body}")


def _write_drug_nodes(
    drugs: DrugListings, output_dir: str, source: str, parsed_date: str
) -> list[str]:
    node_ids: list[str] = []
    used_ids: set[str] = set()
    for (name, _, raw_requirements), (info, pages) in drugs.items():
        base_id = "drug_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:120]
        node_id = base_id
        suffix = 2
        while node_id in used_ids:
            node_id = f"{base_id}_{suffix}"
            suffix += 1
        used_ids.add(node_id)
        node_ids.append(node_id)
        metadata: dict[str, object] = {
            "id": node_id,
            "type": "clinical_drug",
            "title": name,
            "provenance": {"source": source, "pages": pages, "parsed_date": parsed_date},
            **info,
            "raw_requirements": raw_requirements,
            "links": {"governing_policy": ["rule_national_preferred_formulary"]},
        }
        body = (
            f"# {name}\n\n"
            f"Tier: {info['tier'] or 'Unknown (not extracted)'}.\n\n"
            f"Source requirements/limits: {raw_requirements or 'No codes listed in the source row'}.\n\n"
            "Restriction flags indicate codes detected in the source row, not independently "
            "verified clinical or coverage advice. Consult the plan for applicability.\n"
        )
        _write_okf_node(output_dir, node_id, metadata, body)
    return node_ids


def parse_pdf_and_generate_okf(pdf_path: str, output_dir: str):
    """Read the first 15 pages, write drug and formulary nodes, and return page text."""
    print(f"[{pdf_path}] Parsing enterprise tables and guidelines...")
    extracted_chunks, drugs = _extract_pdf_data(pdf_path)
    if not drugs:
        raise ValueError(f"No drug rows found in recognized tables in the first 15 pages of {pdf_path}")

    os.makedirs(output_dir, exist_ok=True)
    source = os.path.basename(pdf_path)
    parsed_date = date.today().isoformat()
    node_ids = _write_drug_nodes(drugs, output_dir, source, parsed_date)

    formulary_id = "rule_national_preferred_formulary"
    metadata: dict[str, object] = {
        "id": formulary_id,
        "type": "pbm_formulary_standard",
        "title": "Parsed Formulary Drug Listings",
        "provenance": {
            "source": source,
            "pages": [page_num for page_num, _ in extracted_chunks],
            "parsed_date": parsed_date,
        },
        "links": {"governing_policy": node_ids},
    }
    body = (
        "# Formulary Listings\n"
        "Drug nodes are extracted from recognized tables in the first 15 PDF pages only. "
        "PA, QL, and ST flags reflect the requirements column of each source row. "
        "Missing tiers are unknown; no dose limits or clinical contraindications are inferred.\n"
    )
    _write_okf_node(output_dir, formulary_id, metadata, body)

    print(f"Generated {len(drugs)} drug nodes and 1 formulary node in: {output_dir}")
    return extracted_chunks