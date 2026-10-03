import os
import re
import hashlib
import numpy as np
from dotenv import load_dotenv
from pymongo import MongoClient
from huggingface_hub import InferenceClient

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MONGO_URI = os.getenv("MONGO_URI")
DATABASE_NAME = os.getenv("DATABASE_NAME", "koralink")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "knowledge")
HF_TOKEN = os.getenv("HF_TOKEN")

EMBEDDINGS_FILE = "data/question_embeddings.npy"
EMBEDDINGS_HASH_FILE = "data/question_embeddings.npy.hash"

TIER1_EXACT_MATCH_SCORE = 0.99
TIER2_PHRASE_MATCH_SCORE = 0.95
TIER3_ALL_WORDS_MATCH_SCORE = 0.93
TIER4_SINGLE_WORD_MATCH_SCORE = 0.90
KEYWORD_CONTAINS_MAX_WORDS = 8
# ============================================================
# VALIDATE ENVIRONMENT VARIABLES
# ============================================================
if not MONGO_URI:
    raise RuntimeError("MONGO_URI is missing in your .env file.")

if not HF_TOKEN:
    raise RuntimeError("HF_TOKEN is missing in your .env file.")
# ============================================================
# HUGGING FACE EMBEDDING CLIENT
# ============================================================
hf_client = InferenceClient(
    provider="hf-inference",
    api_key=HF_TOKEN
)
def encode_texts(texts):
    """
    Generate normalized embeddings remotely through Hugging Face.

    Input:
        texts: string or list of strings

    Output:
        NumPy array of shape:
        - (1, embedding_size) for one text
        - (number_of_texts, embedding_size) for many texts
    """

    if isinstance(texts, str):
        texts = [texts]

    embeddings = []

    for text in texts:
        try:
            vector = hf_client.feature_extraction(
                text,
                model=MODEL_NAME
            )

            vector = np.asarray(vector, dtype=np.float32)

            # Some services can potentially return nested arrays.
            # For Sentence Transformer embeddings, we need one flat vector.
            if vector.ndim > 1:
                vector = vector.mean(axis=0)

            norm = np.linalg.norm(vector)

            if norm > 0:
                vector = vector / norm

            embeddings.append(vector)

        except Exception as error:
            raise RuntimeError(
                f"Could not create Hugging Face embedding: {error}"
            ) from error

    return np.asarray(embeddings, dtype=np.float32)


# ============================================================
# DATABASE CONNECTION
# ============================================================

client = MongoClient(MONGO_URI)
db = client[DATABASE_NAME]
collection = db[COLLECTION_NAME]


# ============================================================
# LOAD FAQ DATA FROM MONGODB
# ============================================================

qa_pairs = list(
    collection.find({
        "$or": [
            {"active": True},
            {"active": "true"}
        ]
    })
)

# If no FAQ entries have active=True, use all entries.
if not qa_pairs:
    qa_pairs = list(collection.find({}))

if not qa_pairs:
    raise RuntimeError(
        f"Database collection '{COLLECTION_NAME}' is empty or does not exist."
    )

questions = [str(item.get("question", "")).strip() for item in qa_pairs]
answers = [str(item.get("answer", "")).strip() for item in qa_pairs]


# ============================================================
# FAQ METADATA NORMALIZATION
# ============================================================

def normalize_images(item):
    """
    Supports:
    - images: [...]
    - image: {...}

    Always returns a list.
    """
    multiple_images = item.get("images")

    if multiple_images:
        return multiple_images

    single_image = item.get("image")

    if single_image:
        return [single_image]

    return []


def normalize_step_images(item):
    """Return images assigned to specific answer steps."""
    return item.get("step_images", {}) or {}


def normalize_keywords(item):
    """Return clean lowercase keyword aliases."""
    return [
        keyword.strip().lower()
        for keyword in item.get("keywords", [])
        if isinstance(keyword, str) and keyword.strip()
    ]


images = [normalize_images(item) for item in qa_pairs]
step_images = [normalize_step_images(item) for item in qa_pairs]
keywords = [normalize_keywords(item) for item in qa_pairs]


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(text):
    """Normalize text for direct and keyword matching."""
    text = str(text).lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


normalized_questions = [
    normalize_text(question)
    for question in questions
]

normalized_keywords = [
    [
        normalize_text(keyword)
        for keyword in keyword_list
        if keyword
    ]
    for keyword_list in keywords
]


# ============================================================
# EMBEDDING INPUTS
# ============================================================

embedding_inputs = [
    question + (" " + " ".join(keyword_list) if keyword_list else "")
    for question, keyword_list in zip(questions, keywords)
]


# ============================================================
# FAQ EMBEDDING CACHE
# ============================================================

def embedding_inputs_hash():
    """
    Makes a hash from questions + keywords.

    If the MongoDB FAQ data changes, the hash changes and
    the local embeddings cache will be regenerated.
    """
    joined_text = "\n".join(embedding_inputs)
    return hashlib.sha256(
        joined_text.encode("utf-8")
    ).hexdigest()


def load_or_create_embeddings():
    """
    Load locally saved FAQ embeddings if still valid.

    Otherwise:
    1. Call Hugging Face to create FAQ embeddings.
    2. Save the embeddings locally.
    3. Save the content hash.
    """
    current_hash = embedding_inputs_hash()

    if (
        os.path.exists(EMBEDDINGS_FILE)
        and os.path.exists(EMBEDDINGS_HASH_FILE)
    ):
        try:
            with open(
                EMBEDDINGS_HASH_FILE,
                "r",
                encoding="utf-8"
            ) as file:
                cached_hash = file.read().strip()

            if cached_hash == current_hash:
                embeddings = np.load(
                    EMBEDDINGS_FILE,
                    mmap_mode="r"
                )

                if embeddings.shape[0] == len(embedding_inputs):
                    print(
                        f"Loaded cached FAQ embeddings: {embeddings.shape}"
                    )
                    return embeddings

            print("FAQ content changed. Rebuilding embeddings.")

        except Exception as error:
            print(f"Could not load embeddings cache: {error}")

    print(
        f"Creating Hugging Face embeddings for "
        f"{len(embedding_inputs)} FAQ entries..."
    )

    embeddings = encode_texts(embedding_inputs)

    os.makedirs(
        os.path.dirname(EMBEDDINGS_FILE),
        exist_ok=True
    )

    np.save(EMBEDDINGS_FILE, embeddings)

    with open(
        EMBEDDINGS_HASH_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        file.write(current_hash)

    print(f"Saved FAQ embeddings to: {EMBEDDINGS_FILE}")

    return embeddings


question_embeddings = load_or_create_embeddings()


# ============================================================
# FALLBACK RESPONSE
# ============================================================

FALLBACK_MESSAGE = (
    "I'm sorry, I couldn't find information about that. "
    "Please check the spelling and try again. "
    "I'm designed to answer questions related to the KoraLink platform. "
    "You can ask me about jobs, agents, employers, the marketplace, "
    "wallet, payments, and other KoraLink features."
)


# ============================================================
# COSINE SIMILARITY
# ============================================================

def cosine_scores(query_embedding):
    """
    All embeddings are L2-normalized.

    Therefore, dot product = cosine similarity.
    """
    return np.dot(question_embeddings, query_embedding)


# ============================================================
# FAQ SEARCH
# ============================================================

def top_faq_candidates(
    user_question,
    top_k=5,
    min_score=0.85
):
    """
    Return the top matching FAQ candidates.

    Result format:
    [
        (
            question,
            answer,
            score,
            images,
            step_images
        )
    ]
    """

    if not user_question:
        return []

    normalized_query = normalize_text(user_question)

    if not normalized_query:
        return []

    query_words = normalized_query.split()
    query_word_count = len(query_words)
    query_word_set = set(query_words)

    # --------------------------------------------------------
    # 1. SEMANTIC MATCHING THROUGH HUGGING FACE
    # --------------------------------------------------------

    query_embedding = encode_texts([user_question])[0]
    scores = cosine_scores(query_embedding)

    # --------------------------------------------------------
    # 2. KEYWORD / EXACT MATCHING
    # --------------------------------------------------------

    keyword_scores = {}

    for index in range(len(questions)):

        # Exact question or exact keyword alias match.
        if (
            normalized_query == normalized_questions[index]
            or normalized_query in normalized_keywords[index]
        ):
            keyword_scores[index] = TIER1_EXACT_MATCH_SCORE
            continue

        # Do not use broad keyword logic on long questions.
        if query_word_count > KEYWORD_CONTAINS_MAX_WORDS:
            continue

        best_keyword_score = None

        for keyword in normalized_keywords[index]:

            if not keyword:
                continue

            keyword_words = keyword.split()

            # Multi-word exact phrase.
            if len(keyword_words) >= 2:
                phrase_pattern = r"\b" + re.escape(keyword) + r"\b"

                if re.search(phrase_pattern, normalized_query):
                    best_keyword_score = max(
                        best_keyword_score or 0,
                        TIER2_PHRASE_MATCH_SCORE
                    )
                    continue

            # All words of a multi-word keyword occur in question.
            if len(keyword_words) >= 2:
                if all(word in query_word_set for word in keyword_words):
                    best_keyword_score = max(
                        best_keyword_score or 0,
                        TIER3_ALL_WORDS_MATCH_SCORE
                    )

            # Single-word keyword.
            if len(keyword_words) == 1:
                word_pattern = r"\b" + re.escape(keyword) + r"\b"

                if re.search(word_pattern, normalized_query):
                    best_keyword_score = max(
                        best_keyword_score or 0,
                        TIER4_SINGLE_WORD_MATCH_SCORE
                    )

        if best_keyword_score is not None:
            keyword_scores[index] = best_keyword_score

    # --------------------------------------------------------
    # 3. COMBINE SEMANTIC + KEYWORD SCORES
    # --------------------------------------------------------

    for index, keyword_score in keyword_scores.items():
        scores[index] = max(scores[index], keyword_score)

    # --------------------------------------------------------
    # 4. RETURN BEST MATCHES
    # --------------------------------------------------------

    top_indices = np.argsort(scores)[::-1][:top_k]

    candidates = [
        (
            questions[index],
            answers[index],
            float(scores[index]),
            images[index],
            step_images[index]
        )
        for index in top_indices
        if scores[index] >= min_score
    ]

    return candidates


# ============================================================
# MAIN CHATBOT FUNCTION
# ============================================================

def answer_user_question(user_question, threshold=0.45):
    """
    Return the best FAQ answer or a fallback message.
    """

    candidates = top_faq_candidates(
        user_question=user_question,
        top_k=1,
        min_score=0.0
    )

    if not candidates:
        return FALLBACK_MESSAGE

    question, answer, score, matched_images, matched_step_images = candidates[0]

    print(f"Best FAQ: {question}")
    print(f"Best Score: {score:.3f}")

    if score < threshold:
        return FALLBACK_MESSAGE

    return answer


# ============================================================
# TEST LOCALLY
# ============================================================

if __name__ == "__main__":
    test_question = "how to join koralink"

    print(f"\nQuestion: {test_question}")
    print(f"Answer: {answer_user_question(test_question)}")