import os
from pathlib import Path

from dotenv import load_dotenv

OKF_DIR = "docs/okf"
DATA_DIR = "data"
REAL_PDF_URL = "https://www.medmutual.com/-/media/MedMutual/Files/IndividualsFamilies/2026/FEHB/MedMutual-2026-National-Preferred_National-Preferred-Plus-Prescription-Drug-Formulary.pdf"
LOCAL_PDF_PATH = os.path.join(DATA_DIR, "real_clinical_formulary.pdf")

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise RuntimeError("OPENAI_API_KEY is missing from the environment and project .env file")

    from src.okf_writer import download_real_pdf, parse_pdf_and_generate_okf
    from src.okf_reader import load_okf_graph
    from src.vector_rag import initialize_vector_retriever
    from src.hybrid_agent import HybridOKFAgent

    print("=== Starting Modular Hybrid OKF PBM Copilot Pipeline ===")
    
    print("\n[1/5] Downloading PDF (or using the cached copy)...")
    download_real_pdf(REAL_PDF_URL, LOCAL_PDF_PATH)
    print(f"PDF saved: {LOCAL_PDF_PATH} ({os.path.getsize(LOCAL_PDF_PATH):,} bytes)")
    
    print(f"\n[2/5] Parsing the first 15 pages and writing Markdown to {OKF_DIR}...")
    chunks = parse_pdf_and_generate_okf(LOCAL_PDF_PATH, OKF_DIR)
    print(f"Extracted {len(chunks)} pages, {sum(len(text) for _, text in chunks):,} characters.")
    
    print("\n[3/5] Reading Markdown files into the OKF graph...")
    okf_graph = load_okf_graph(OKF_DIR)
    
    print("\n[4/5] Splitting page text, creating OpenAI embeddings, and storing in Pinecone...")
    retriever = initialize_vector_retriever(chunks, source=os.path.basename(LOCAL_PDF_PATH))
    
    print("\n[5/5] Running vector retrieval and the hybrid agent...")
    agent = HybridOKFAgent(retriever, okf_graph)
    query = "What tier and requirements are listed for fluconazole oral tablet 150 mg?"
    print(f"Query: {query}")
    print("Scope: first 15 PDF pages only; a drug outside this scope cannot be confirmed.")
    
    result = agent.run(query)
    print("\n================ FINAL HYBRID AGENT RESPONSE ================")
    print(result)