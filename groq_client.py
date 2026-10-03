import os
from groq import Groq
from dotenv import load_dotenv

# Automatically look for a .env file in the same folder and load its variables
load_dotenv()

# Initialize Groq using your environment variable safely
# (This keeps your credentials secure and hidden from public GitHub commits!)
api_key = os.environ.get("GROQ_API_KEY")
client = Groq(api_key=api_key)

# Switched to the 8B-instant model to optimize and bypass heavy token limit caps
MODEL = "openai/gpt-oss-120b"

SYSTEM_PROMPT = """You are the KoraLink Assistant, a helpful support chatbot for the KoraLink \
platform (jobs, agents, employers, marketplace, wallet, payments, and related features).

Rules you must always follow:
1. The user's question may be short, vague, or just a keyword (e.g. "marketplace" instead of \
"what is the marketplace?"). Use your own understanding of language and intent to figure out \
what they most likely mean, and match it to the most relevant piece of the CONTEXT below.
2. Any SPECIFIC fact about KoraLink itself — its features, fees, policies, how something \
works, numbers, steps, links, etc. — must come ONLY from the CONTEXT. Never invent or guess \
specific KoraLink facts that aren't in the context.
3. For everything else (understanding what the user means, being conversational, handling \
greetings/small talk, explaining general concepts like "what is a marketplace" in general \
terms before tying it back to KoraLink's context), you may use your own general knowledge and \
reasoning normally.
4. If the CONTEXT has genuinely nothing relevant to answer the specific KoraLink question \
being asked, reply with exactly this single token and nothing else: NOT_FOUND
5. Keep answers concise, friendly, and consistent in tone with the example FAQ answers.
6. Never mention "context", "documents", or that you are an AI/LLM. Just answer like a normal \
support agent would.
"""

def build_context(candidates):
    """
    candidates: a list of (source_label, text, score, image) tuples,
    already pooled and ranked across every source (FAQ, website, PDF, ...).
    Presenting them ranked - and labeled by source - lets the LLM see at
    a glance which piece of evidence is strongest and where it came from.
    The image slot isn't sent to the LLM (it can't render one), it's only
    used by the fast-path in scap.py.
    """
    if not candidates:
        return "No relevant context found."

    lines = ["Relevant KoraLink information, ranked from most to least relevant:"]
    for i, candidate in enumerate(candidates, 1):
        source, text, score = candidate[0], candidate[1], candidate[2]
        lines.append(f"{i}. [source: {source}] {text}")
    return "\n".join(lines)


def get_llm_answer(user_question, candidates):
    """
    candidates: ranked list of (source_label, text, score) tuples pooled
    from all retrieval sources (FAQ, website scrape, PDF, ...).

    Returns a grounded answer string, or None if the LLM couldn't find
    anything relevant (so the caller can fall back to the default message)
    or if the API call fails for any reason.
    """
    context = build_context(candidates)
    user_prompt = f"CONTEXT:\n{context}\n\nUSER QUESTION: {user_question}"

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=300,
        )
        answer = response.choices[0].message.content.strip()

        if not answer or answer == "NOT_FOUND":
            return None
        return answer

    except Exception as e:
        print("Groq API error:", e)
        return None