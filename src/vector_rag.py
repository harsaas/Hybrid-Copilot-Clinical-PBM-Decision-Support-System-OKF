import hashlib
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.vectorstores import VectorStoreRetriever
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore


def initialize_vector_retriever(
    chunks: list[tuple[int, str]], source: str = "formulary_pdf"
) -> VectorStoreRetriever:
    """Store all supplied page text in Pinecone and return a top-two retriever."""
    if not source.strip():
        raise ValueError("A nonempty source identifier is required")
    if not chunks:
        raise ValueError("No PDF page chunks supplied")

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    required = ("OPENAI_API_KEY", "PINECONE_API_KEY", "INDEX_NAME")
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    docs = []
    for page_num, text in chunks:
        if isinstance(page_num, bool) or not isinstance(page_num, int) or page_num < 1:
            raise ValueError(f"Invalid PDF page number: {page_num!r}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"PDF page {page_num} has no usable text")
        page_docs = splitter.create_documents(
            texts=[text], metadatas=[{"source": source, "page": page_num}]
        )
        docs.extend(page_docs)

    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    print(f"Created {len(docs)} vector chunks from {len(chunks)} pages (500 characters, 50 overlap).")
    namespace = hashlib.sha256(source.encode("utf-8")).hexdigest()
    store = PineconeVectorStore(
        index_name=os.environ["INDEX_NAME"],
        pinecone_api_key=os.environ["PINECONE_API_KEY"],
        embedding=embeddings,
        namespace=namespace,
    )
    store.add_documents(docs, async_req=False)
    print(f"Stored {len(docs)} chunks in Pinecone for source: {source}")
    return store.as_retriever(search_kwargs={"k": 2})