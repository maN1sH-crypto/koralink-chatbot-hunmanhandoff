from bs4 import BeautifulSoup
import re
import requests
import numpy as np
import bot_work as bot  
import groq_client
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --------------------------------------------------
# web scraping
def scrape_page(url, verify_ssl=False):
    response = requests.get(url, verify=verify_ssl)
    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    return text


# split long texts
def split_text(text, size=300):
    words = text.split()
    chunks = []
    for i in range(0, len(words), size):
        chunk = " ".join(words[i:i + size])
        chunks.append(chunk)
    return chunks

website_text = scrape_page("https://koralink.org/en")
website_chunks = split_text(website_text)

# test_hf uses encode_texts() instead of bot.embedding_model.encode()
website_embeddings = bot.encode_texts(website_chunks)


def _cosine_sim(query_embedding, corpus_embeddings):
    return np.dot(corpus_embeddings, query_embedding) / (
        np.linalg.norm(corpus_embeddings, axis=1) * np.linalg.norm(query_embedding) + 1e-10
    )


def top_website_chunks(query, top_k=3, min_score=0.2):
    """Returns up to top_k (chunk_text, score) tuples from the scraped website."""
    # Flatten query embedding to 1D vector (dim,) for dot product compatibility
    query_embedding = bot.encode_texts([query])[0]
    similarities = _cosine_sim(query_embedding, website_embeddings)
    top_indices = np.argsort(similarities)[::-1][:top_k]

    return [
        (website_chunks[i], float(similarities[i]))
        for i in top_indices
        if similarities[i] >= min_score
    ]


def search_website(query):
    """Kept for backward compatibility - single best chunk, text only."""
    chunks = top_website_chunks(query, top_k=1, min_score=0.0)
    return chunks[0][0] if chunks else ""


# High-confidence bar: if the FAQ match is this good, skip the LLM entirely
# (fast + free). Anything below this pools every source together instead.
FAQ_HIGH_CONFIDENCE = 0.55

# How many of the best candidates (across ALL sources combined) get sent
# to the LLM as context.
MAX_CANDIDATES_FOR_LLM = 6

# When the top FAQ candidates are within this margin of each other, prefer
# the one with actual numbered steps over a purely informational one.
STEP_PREFERENCE_MARGIN = 0.08

_STEP_LINE_REGEX = re.compile(r"^\s*\d{1,2}[\.\)]\s+", re.M)


def _has_steps(answer):
    return len(_STEP_LINE_REGEX.findall(answer)) >= 2


def _prefer_step_answers(faq_candidates):
    """
    faq_candidates: list of (question, answer, score, images, step_images),
    already sorted by score descending.
    """
    if not faq_candidates or _has_steps(faq_candidates[0][1]):
        return faq_candidates

    top_score = faq_candidates[0][2]
    close_enough = [c for c in faq_candidates if top_score - c[2] <= STEP_PREFERENCE_MARGIN]
    step_candidates = [c for c in close_enough if _has_steps(c[1])]
    if not step_candidates:
        return faq_candidates

    best_step_candidate = max(step_candidates, key=lambda c: c[2])
    rest = [c for c in faq_candidates if c is not best_step_candidate]
    return [best_step_candidate] + rest


def retrieve_all_candidates(user_message):
    """
    Gathers candidates from every source - FAQ, scraped website,
    and PDF - each tagged with its source and similarity score.
    """
    candidates = []

    # test_hf.py provides top_faq_candidates(...) with the exact same return signature
    faq_candidates = bot.top_faq_candidates(user_message, top_k=5, min_score=0.25)
    faq_candidates = _prefer_step_answers(faq_candidates)
    for question, answer, score, images, step_images in faq_candidates:
        candidates.append(("FAQ", answer, score, images, step_images))

    website_candidates = top_website_chunks(user_message, top_k=3, min_score=0.2)
    for chunk, score in website_candidates:
        candidates.append(("Website", chunk, score, [], {}))

    candidates.sort(key=lambda c: c[2], reverse=True)
    return candidates, faq_candidates


# ----------------------------------------------------------------
# final answer retrieval method
def answer_finder(user_message):
    """
    Returns {"answer": str, "images": list, "step_images": dict}.
    """
    ranked_candidates, faq_candidates = retrieve_all_candidates(user_message)

    # Fast path: a strong direct FAQ match, no need to call the LLM.
    if faq_candidates and faq_candidates[0][2] >= FAQ_HIGH_CONFIDENCE:
        _question, answer, _score, images, step_images = faq_candidates[0]
        return {"answer": answer, "images": images, "step_images": step_images}

    top_candidates = ranked_candidates[:MAX_CANDIDATES_FOR_LLM]

    llm_answer = groq_client.get_llm_answer(user_message, top_candidates)
    if llm_answer:
        return {"answer": llm_answer, "images": [], "step_images": {}}

    # Uses FALLBACK_MESSAGE defined in test_hf.py
    return {"answer": bot.FALLBACK_MESSAGE, "images": [], "step_images": {}}
