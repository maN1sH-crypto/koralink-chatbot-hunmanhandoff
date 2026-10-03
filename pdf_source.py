import os
import numpy as np

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

import bot_work as bot


PDF_PATH = os.environ.get("PDF_PATH", "data/koralink.pdf")

pdf_chunks = []
pdf_embeddings = None


def _extract_pdf_text(path):
    if PdfReader is None:
        print("pypdf is not installed - run: pip install pypdf")
        return ""

    if not os.path.exists(path):
        print(
            f"[pdf_source] No PDF found at '{path}' - PDF source will be skipped. "
            f"Set the PDF_PATH env var if your file lives elsewhere."
        )
        return ""

    reader = PdfReader(path)
    text_parts = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        text_parts.append(page_text)
    return " ".join(text_parts)


def _split_text(text, size=300):
    words = text.split()
    chunks = []
    for i in range(0, len(words), size):
        chunk = " ".join(words[i:i + size])
        chunks.append(chunk)
    return chunks


def _load_pdf():
    """(Re)loads and embeds the PDF at PDF_PATH. Safe to call even if the
    file is missing or pypdf isn't installed - it just leaves pdf_chunks
    empty, and top_pdf_chunks() will quietly return nothing for every query."""
    global pdf_chunks, pdf_embeddings

    text = _extract_pdf_text(PDF_PATH)
    if not text.strip():
        pdf_chunks = []
        pdf_embeddings = None
        return

    pdf_chunks = _split_text(text)
    pdf_embeddings = bot.embedding_model.encode(pdf_chunks, convert_to_numpy=True)
    print(f"[pdf_source] Loaded {len(pdf_chunks)} chunks from PDF: {PDF_PATH}")


# Load once at import time, same pattern as the website scrape in scrapping.py
_load_pdf()


def _cosine_sim(query_embedding, corpus_embeddings):
    return np.dot(corpus_embeddings, query_embedding) / (
        np.linalg.norm(corpus_embeddings, axis=1) * np.linalg.norm(query_embedding) + 1e-10
    )


def top_pdf_chunks(query, top_k=3, min_score=0.2):
    """
    Returns up to top_k (chunk_text, score) tuples from the PDF that are
    above min_score, sorted by relevance. Returns [] if no PDF was loaded
    (missing file, missing dependency, or nothing scored above min_score).
    """
    if pdf_embeddings is None or len(pdf_chunks) == 0:
        return []

    query_embedding = bot.embedding_model.encode(query, convert_to_numpy=True)
    similarities = _cosine_sim(query_embedding, pdf_embeddings)
    top_indices = np.argsort(similarities)[::-1][:top_k]

    return [
        (pdf_chunks[i], float(similarities[i]))
        for i in top_indices
        if similarities[i] >= min_score
    ]


def reload_pdf(new_path=None):
    """Call this if you swap in a new/updated PDF file while the app is running."""
    global PDF_PATH
    if new_path:
        PDF_PATH = new_path
    _load_pdf()
