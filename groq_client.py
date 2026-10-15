import os
from groq import Groq
from google import genai
from openai import OpenAI
from dotenv import load_dotenv

# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")


# ============================================================
# INITIALIZE CLIENTS
# ============================================================

# Groq
groq_client = Groq(api_key=GROQ_API_KEY)

# Gemini
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# OpenRouter
openrouter_client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)


# ============================================================
# MODELS
# ============================================================

GROQ_MODEL = "openai/gpt-oss-120b"

# Gemini model
GEMINI_MODEL = "gemini-2.5-flash"

# OpenRouter free model
OPENROUTER_MODEL = "openai/gpt-oss-120b:free"


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """You are the KoraLink Assistant, a helpful support chatbot for the KoraLink
platform (jobs, agents, employers, marketplace, wallet, payments, and related features).

Rules you must always follow:

1. The user's question may be short, vague, or just a keyword
   (e.g. "marketplace" instead of "what is the marketplace?").
   Use your own understanding of language and intent to figure out
   what they most likely mean, and match it to the most relevant
   piece of the CONTEXT below.

2. Any SPECIFIC fact about KoraLink itself — its features, fees,
   policies, how something works, numbers, steps, links, etc. —
   must come ONLY from the CONTEXT.
   Never invent or guess specific KoraLink facts that aren't in the context.

3. For everything else (understanding what the user means,
   being conversational, handling greetings/small talk,
   explaining general concepts like "what is a marketplace"
   in general terms before tying it back to KoraLink's context),
   you may use your own general knowledge and reasoning normally.

4. If the CONTEXT has genuinely nothing relevant to answer the
   specific KoraLink question being asked, reply with exactly:
   NOT_FOUND

5. Keep answers concise, friendly, and consistent in tone
   with the example FAQ answers.

6. Never mention "context", "documents", or that you are an AI/LLM.
   Just answer like a normal support agent would.
"""


# ============================================================
# BUILD CONTEXT
# ============================================================

def build_context(candidates):
    """
    candidates:
        list of tuples:
        (source_label, text, score, image)

    The image value is not sent to the LLM.
    """

    if not candidates:
        return "No relevant context found."

    lines = [
        "Relevant KoraLink information, ranked from most to least relevant:"
    ]

    for i, candidate in enumerate(candidates, 1):
        source = candidate[0]
        text = candidate[1]
        score = candidate[2]

        lines.append(
            f"{i}. [source: {source}] {text}"
        )

    return "\n".join(lines)


# ============================================================
# BUILD USER PROMPT
# ============================================================

def build_user_prompt(user_question, candidates):
    context = build_context(candidates)

    return f"""CONTEXT:
{context}

USER QUESTION:
{user_question}"""


# ============================================================
# GROQ
# ============================================================

def ask_groq(user_prompt):
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        temperature=0.2,
        max_tokens=300,
    )

    answer = response.choices[0].message.content

    if not answer:
        raise Exception("Groq returned an empty response")

    return answer.strip()


# ============================================================
# GEMINI
# ============================================================

def ask_gemini(user_prompt):
    full_prompt = f"""{SYSTEM_PROMPT}

{user_prompt}
"""

    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=full_prompt,
        config={
            "temperature": 0.2,
            "max_output_tokens": 300,
        },
    )

    answer = response.text

    if not answer:
        raise Exception("Gemini returned an empty response")

    return answer.strip()


# ============================================================
# OPENROUTER
# ============================================================

def ask_openrouter(user_prompt):
    response = openrouter_client.chat.completions.create(
        model=OPENROUTER_MODEL,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        temperature=0.2,
        max_tokens=300,
    )

    answer = response.choices[0].message.content

    if not answer:
        raise Exception("OpenRouter returned an empty response")

    return answer.strip()


def _complete_with_fallback(system_prompt, user_prompt, max_tokens=1200):
    errors = []
    try:
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0,
            max_tokens=max_tokens,
        )
        answer = response.choices[0].message.content
        if answer and answer.strip():
            return answer.strip()
        errors.append("Groq returned an empty response")
    except Exception as error:
        errors.append(f"Groq: {error}")

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"{system_prompt}\n\n{user_prompt}",
            config={"temperature": 0, "max_output_tokens": max_tokens},
        )
        if response.text and response.text.strip():
            return response.text.strip()
        errors.append("Gemini returned an empty response")
    except Exception as error:
        errors.append(f"Gemini: {error}")

    try:
        response = openrouter_client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0,
            max_tokens=max_tokens,
        )
        answer = response.choices[0].message.content
        if answer and answer.strip():
            return answer.strip()
        errors.append("OpenRouter returned an empty response")
    except Exception as error:
        errors.append(f"OpenRouter: {error}")

    raise RuntimeError("All configured LLM providers failed: " + " | ".join(errors))


def _parse_json_response(response):
    import json
    import re

    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def detect_language_and_translate_to_english(text):
    """Identify the customer's language and prepare English retrieval text."""
    system_prompt = (
        "Identify the language used in the customer message and translate it into English. "
        "Return only valid JSON with exactly two string keys: language and english. "
        "Use a readable language name for language, for example English or Kinyarwanda. "
        "If the message is already English, preserve it in english. Preserve intent, names, "
        "URLs, and requests to speak to a human. Do not answer the message."
    )
    response = _complete_with_fallback(system_prompt, text, max_tokens=500)
    try:
        data = _parse_json_response(response)
        language = str(data.get("language", "")).strip()
        english = str(data.get("english", "")).strip()
        if not language or not english:
            raise ValueError("Missing language or English text")
        return english, language
    except Exception as error:
        raise RuntimeError(f"Could not detect and translate the customer's language: {error}") from error


def translate_text(text, target_language):
    """Translate text through configured LLM providers, without Google Translate."""
    if not text or not text.strip():
        return text

    system_prompt = (
        f"Translate the provided text into {target_language}. Return only the translation. "
        "Preserve meaning, names, URLs, numbered steps, Markdown, and KoraLink icon tokens "
        "such as :wallet: exactly. Do not answer questions or add explanations."
    )
    return _complete_with_fallback(system_prompt, text, max_tokens=1200)


def translate_answer_and_images(answer, images, target_language, step_images=None):
    """Translate answer and image descriptions while leaving all image URLs intact."""
    import copy
    import json

    translated_images = copy.deepcopy(images or [])
    translated_steps = copy.deepcopy(step_images or {})
    slots = []

    def collect_image_records(value):
        if isinstance(value, dict):
            if "src" in value or "url" in value:
                slots.append(value)
            else:
                for nested in value.values():
                    collect_image_records(nested)
        elif isinstance(value, list):
            for nested in value:
                collect_image_records(nested)

    collect_image_records(translated_images)
    collect_image_records(translated_steps)
    if not slots:
        return translate_text(answer, target_language), translated_images, translated_steps

    bundle = {
        "answer": answer,
        "images": [{"alt": item.get("alt", ""), "caption": item.get("caption", "")} for item in slots],
    }
    system_prompt = (
        f"Translate all human-readable text values in the supplied JSON into {target_language}. "
        "Return only valid JSON with exactly the same structure and keys. Keep empty strings empty. "
        "Do not change image metadata other than alt and caption text. Preserve names, numbered "
        "steps, and icon tokens such as :wallet:. Do not add explanations."
    )
    response = _complete_with_fallback(system_prompt, json.dumps(bundle, ensure_ascii=False), max_tokens=1800)
    try:
        result = _parse_json_response(response)
        translated_answer = str(result["answer"])
        translated_slots = result["images"]
        if len(translated_slots) != len(slots):
            raise ValueError("Image metadata count changed")
        for original, translated in zip(slots, translated_slots):
            original["alt"] = str(translated.get("alt", original.get("alt", "")))
            original["caption"] = str(translated.get("caption", original.get("caption", "")))
        return translated_answer, translated_images, translated_steps
    except Exception as error:
        raise RuntimeError(f"Could not translate the answer and image descriptions: {error}") from error


# ============================================================
# MAIN LLM FUNCTION
# ============================================================

def get_llm_answer(user_question, candidates):
    """
    LLM fallback order:

        1. Groq
        2. Gemini
        3. OpenRouter

    Returns:
        Answer string
        or None if all providers fail / answer is NOT_FOUND
    """

    user_prompt = build_user_prompt(
        user_question,
        candidates
    )

    # --------------------------------------------------------
    # 1. GROQ
    # --------------------------------------------------------

    try:
        print("Trying Groq...")

        answer = ask_groq(user_prompt)

        if answer == "NOT_FOUND":
            return None

        print("Groq response successful.")

        return answer

    except Exception as e:
        print(f"Groq failed: {e}")


    # --------------------------------------------------------
    # 2. GEMINI
    # --------------------------------------------------------

    try:
        print("Trying Gemini...")

        answer = ask_gemini(user_prompt)

        if answer == "NOT_FOUND":
            return None

        print("Gemini response successful.")

        return answer

    except Exception as e:
        print(f"Gemini failed: {e}")


    # --------------------------------------------------------
    # 3. OPENROUTER
    # --------------------------------------------------------

    try:
        print("Trying OpenRouter...")

        answer = ask_openrouter(user_prompt)

        if answer == "NOT_FOUND":
            return None

        print("OpenRouter response successful.")

        return answer

    except Exception as e:
        print(f"OpenRouter failed: {e}")


    # --------------------------------------------------------
    # ALL PROVIDERS FAILED
    # --------------------------------------------------------

    print("All LLM providers failed.")

    return None