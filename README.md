# Hybrid OKF Formulary Explorer

A research demo that parses a prescription drug formulary PDF into per-drug
Markdown files, loads their links into NetworkX, and optionally combines Pinecone
retrieval with an OpenAI answer. A React dashboard lets you inspect the actual
local PDF snippets, drug records, and graph connections.

> Not a clinical decision system. Extracted listings and AI answers require
> qualified review. A detected code is source evidence, not an independently
> verified coverage rule, contraindication, or treatment recommendation.

## Two Ways to Use the App

| Mode | What it does | External services |
|---|---|---|
| React dashboard | Inspect existing local Markdown, PDF chunks, graph links, and JSON source records | None |
| Python pipeline | Download/cache PDF, write/read Markdown, embed text, store/search Pinecone, generate an answer | PDF host, OpenAI, Pinecone |

Both use **only the first 15 PDF pages**, not the entire formulary. The supplied
PDF has 236 pages; drugs beyond the parsed section cannot be confirmed.

## Setup

Run commands from the project root in PowerShell.

- Python 3.10+ and a virtual environment.
- Node.js 18+ and npm for the React frontend; Node.js 24 was used for the demo.
- OpenAI/Pinecone credentials are needed only for the live Python pipeline.

If you do not already have a project environment:

```powershell
python -m venv .venv
```

For the local dashboards and PDF processing, install the focused dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install pdfplumber==0.11.5 python-frontmatter==1.1.0 pyyaml==6.0.2 networkx==3.4.2 requests==2.32.3 langchain-text-splitters
```

For the live pipeline, also install:

```powershell
.\.venv\Scripts\python.exe -m pip install python-dotenv langchain-openai langchain-pinecone "pinecone>=6,<8"
```

The existing [requirements.txt](requirements.txt) also contains broader AI/demo
dependencies that are not all needed for the React explorer.

## React Dashboard Quick Start

With the generated files already available:

```powershell
npm install
npm run build
.\.venv\Scripts\python.exe -m src.dashboard_api
```

Open **http://127.0.0.1:8000**. Stop the server with **Ctrl+C**.

After the initial install/build, start the demo with just:

```powershell
.\.venv\Scripts\python.exe -m src.dashboard_api
```

Rebuild with `npm run build` after changing frontend files.

### What the Dashboard Shows

- KPI cards computed from local files, rather than preset counts.
- Searchable drug listings, defaulting to **fluconazole oral tablet 150 mg**.
- Side-by-side PDF text chunks and Markdown metadata.
- Detected PA, QL, and ST flags, tier, raw requirements, and source provenance.
- An interactive graph neighborhood showing the selected drug's actual links.
- Downloadable Markdown and a plain JSON source record.
- A provenance trace explaining where the displayed data came from.

The layout follows the supplied React design, but does not reuse its mock
medical scenarios, similarity scores, clinical safety protocols, or FHIR claims.
The JSON export is **not a FHIR resource or clinical compliance audit**.

The dashboard is read-only. **Refresh local data** reloads files; it does not
download the PDF, regenerate Markdown, embed text, search Pinecone, or call an LLM.
Chunk previews match source/page metadata and prefer complete drug-title matches;
they are not semantic search results. The displayed chunk count is not a live
Pinecone vector count.

### Which Dashboard Files Are Needed?

| File | React demo requirement | Purpose |
|---|---|---|
| [src/app.jsx](src/app.jsx) | Required | Dashboard components and interactions |
| [src/dashboard.css](src/dashboard.css) | Required | Dark theme, cards, layout, and responsive styling |
| [src/frontend.jsx](src/frontend.jsx) | Required | React entry point |
| [src/dashboard_api.py](src/dashboard_api.py) | Required | Reads local data and serves the built app/API |
| [index.html](index.html), [package.json](package.json), [vite.config.js](vite.config.js) | Required | Frontend entry, dependencies, and build/development configuration |

The Python server binds to localhost and serves the built `dist/` directory plus
its read-only API. Credentials and `.env` are not included in the API response.
Do not copy secrets into frontend files, `dist/`, or `VITE_*` variables.
This server is for local demonstration, not production deployment.

### Frontend Development

Keep the Python API server running in one terminal:

```powershell
.\.venv\Scripts\python.exe -m src.dashboard_api
```

In another terminal:

```powershell
npm run dev
```

Open the localhost URL printed by Vite. Its `/api` requests are proxied to Python
on port 8000. `npm run preview` alone does not provide the API.

## Generate Local PDF and Markdown Data Without AI Calls

The React dashboard expects:

- `data/real_clinical_formulary.pdf`
- `docs/okf/*.md`

If these are missing, download and parse the PDF using the existing writer:

```powershell
@'
from src.main import REAL_PDF_URL, LOCAL_PDF_PATH, OKF_DIR
from src.okf_writer import download_real_pdf, parse_pdf_and_generate_okf

download_real_pdf(REAL_PDF_URL, LOCAL_PDF_PATH)
chunks = parse_pdf_and_generate_okf(LOCAL_PDF_PATH, OKF_DIR)
print(f"Extracted {len(chunks)} PDF pages")
'@ | .\.venv\Scripts\python.exe -
```

This contacts the public PDF host if no cached copy exists. It does not create
embeddings or contact OpenAI/Pinecone. Refresh the dashboard afterward.

The writer recognizes three-column Drug Name / Drug Tier / Requirements tables.
It writes one node per distinct listing plus a formulary node. Identical repeated
listings share a node with all source page numbers; different formulations,
tiers, or requirements remain separate. Filename collisions receive suffixes.

Numeric tiers, including Tier 5, come from the dedicated tier column. Missing
tiers are YAML `null` and logged rather than defaulted to Tier 1. PA, QL, and ST
are detected as exact tokens in the requirements cell; other codes remain in
`raw_requirements`. A false flag means the code was not detected, **not** that the
plan guarantees unrestricted coverage.

The parser returns `(PDF page number, extracted text)` pairs including flattened
table rows. Unrecognized tables are logged and skipped; no recognized drug rows
raises an error. It does not infer dose limits, FDA claims, or contraindications.
Page numbers are physical PDF pages, which may differ from printed page labels.

The writer does not delete old files. Use a clean, separate output directory
when switching sources to avoid mixing listings. The download function reuses an
existing cached file; subsequent runs do not automatically refresh that PDF.

## Live Python Pipeline

### Configure `.env`

Create or update the project-root `.env` with your own credentials:

```dotenv
OPENAI_API_KEY=your-openai-key
PINECONE_API_KEY=your-pinecone-key
INDEX_NAME=your-existing-index
```

Do not commit, display, or share these values. `load_dotenv` does not overwrite
variables already set in the process environment.

The existing Pinecone index must support **1536-dimensional dense vectors**
for `text-embedding-3-small`; cosine similarity was used in the tested setup.
The application does not create the index.

### Run All Five Stages

```powershell
$env:LANGSMITH_TRACING = "false"
$env:LANGCHAIN_TRACING_V2 = "false"
.\.venv\Scripts\python.exe -m src.main
```

The tracing variables disable optional LangSmith uploads for this process,
without modifying `.env`. Enable tracing only when deliberately configured.

The console shows:

1. **Download/cache:** retain the PDF at `data/real_clinical_formulary.pdf`.
2. **Write:** parse the first 15 pages and generate `docs/okf/*.md`.
3. **Read:** load Markdown IDs, content, provenance, and links into NetworkX.
4. **Vectorize:** split pages into blocks of at most 500 characters with a
   50-character target overlap, embed with OpenAI, and store in Pinecone.
5. **Retrieve/answer:** retrieve the top two passages, match graph nodes, and
   send the combined context to `gpt-4o-mini`.

The current query in [src/main.py](src/main.py) is:

> What tier and requirements are listed for fluconazole oral tablet 150 mg?

This targets an available Markdown listing on PDF page 9: **Tier 1 with a QL
code**. No numeric quantity limit is inferred from that code.

**Live runs transmit document text to OpenAI and Pinecone and may incur charges.**
Use only data you are authorized to send. Running the pipeline does not launch
the React dashboard; start its server separately.

### Vector Storage and Graph Matching

[src/vector_rag.py](src/vector_rag.py) stores every supplied page chunk, not
unparsed PDF pages or the generated drug Markdown files. Long rows and paragraphs
may cross chunk boundaries. Metadata preserves `source` and `page`.

Each source uses a SHA-256-derived Pinecone namespace. Vector IDs are generated
automatically, so **repeated ingestion can create duplicates**, including for
unchanged text. Old vectors are not removed automatically.

[src/hybrid_agent.py](src/hybrid_agent.py) checks every retrieved document.
It supports explicit `okf_node_link` metadata; otherwise a drug match requires:

- The vector source equals the writer's source PDF basename.
- The retrieved page occurs in the node's provenance.
- The complete drug title occurs in the snippet, ignoring case and normalizing
  whitespace.

The entry point supplies the matching PDF basename. A split or partial drug
title may not match; the agent does not guess from the page alone. Matched nodes
are included once, with outgoing graph links. Missing graph context is explicitly
identified in the prompt.

The graph reader currently retains title, type, provenance, content, and link
edges, not the structured restriction fields. The dashboards therefore read
restriction metadata directly from Markdown. `parsed_date` means extraction
date, not clinical verification.

## Tests and Validation

Build the React frontend:

```powershell
npm run build
```

Run the Python tests after installing the local PDF and live-pipeline dependencies:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Focused examples:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_dashboard_api.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_hybrid_agent.py -v
```

Automated tests mock external APIs. Some integration tests use the supplied local
PDF or generated files and skip when those files are absent. They do not prove
live service availability, answer quality, or clinical correctness.

A previous live run verified download, Markdown generation, Pinecone persistence,
retrieval, graph matching, and an OpenAI answer. For the tested PDF, the first
15 pages yielded **171 drug files + 1 formulary file**, **172 graph nodes**,
**342 directed edges**, and **92 text/vector chunks**. These are observed results,
not fixed application constants.

## Troubleshooting

| Symptom | Action |
|---|---|
| Dashboard says frontend is not built | Run `npm install` and `npm run build`, then reload. |
| Browser cannot load local data | Start `python -m src.dashboard_api`; check its terminal for errors. |
| Empty drug list or missing PDF previews | Generate the expected local data using the command above. |
| Frontend changes do not appear | Rebuild, or use `npm run dev` with the Python API server running. |
| Missing API key/index configuration | Check the project-root `.env` and any pre-existing process variables. |
| Pinecone dimension error | Use an existing index compatible with 1536-dimensional embeddings. |
| No graph context | Check source basename, page provenance, and complete-title matching. |
| LangSmith authentication warnings | Disable tracing as shown above, or deliberately configure its credentials. |
| Duplicate search results after reruns | Re-ingestion uses automatic vector IDs and can add duplicate records. |
| A drug is not available | It may be outside the first 15 pages; absence here is not a coverage decision. |
