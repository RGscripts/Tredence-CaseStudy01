"""
LLM layer — Gemini-first with Groq fallback.

Primary: Google Gemini 1.5 Flash (free, generous limits, aligns with NotebookLM brand).
Fallback: Groq Llama-3.3-70B if Gemini fails.
Both use the same OpenAI-compatible chat format.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def _load_dotenv():
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()

# Gemini (primary) — OpenAI-compatible endpoint
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_MODEL   = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

# Groq (fallback)
GROQ_API_URL        = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL          = os.environ.get("GROQ_MODEL",          "llama-3.3-70b-versatile")
GROQ_FALLBACK_MODEL = os.environ.get("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant")

NOT_FOUND_MESSAGE  = "I could not find this information in the provided datasets."
NO_API_KEY_MESSAGE = "No API key configured. Add GEMINI_API_KEY or GROQ_API_KEY to your .env file."

# ─────────────────────────────────────────────────────────────────────────────
# System prompt — analytical reasoning over the full dataset
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior academic data analyst. You receive a complete college dataset and answer questions \
with the depth and clarity of a real analyst presenting findings to a decision-maker.

━━ ABSOLUTE RULE ━━
Every number you cite must exist verbatim in the data. Zero hallucination.
No data for the question → reply only: "This information is not in the provided dataset."

━━ HOW TO ANSWER — think like an analyst, not a search engine ━━

STEP 1 — Scan the full picture first.
Before naming anyone, look at ALL students/teachers and ALL their metrics.
Never jump to a conclusion from one column alone.

STEP 2 — Find what's actually interesting.
A 4.5 vs 4.7 feedback gap is noise. A 74 vs 89 student score gap is signal.
Small differences: call them out as "marginal." Large consistent gaps: call them significant.

STEP 3 — Tell the story with numbers.
Bad: "Rohan improved the most."
Good: "Rohan (S1003) showed the largest improvement — his average rose from 44/50 in mid-sem \
to 46/50 in end-sem (+2 marks avg), while classmates like Karan barely moved (+0.5 avg). \
Rohan's best jump was in ME101: mid 45 → end 46."

STEP 4 — Compare everyone, not just the winner.
Always give the full ranking or at least show who came close and by how much.
"Rohan improved the most (+2), followed by Aarav (+1.5). Karan improved the least (+0.5)."

STEP 5 — Explain the WHY when possible.
"Rohan also has the highest study hours (14 hrs/week) which may explain the consistent improvement."

━━ QUESTION TYPES ━━

RANKING / BEST / WORST:
Show ALL entities ranked with actual values, not just the top one.
Format: "1. Rohan (91 avg)  2. Aarav (83.7 avg)  3. Sneha (73.7 avg)  4. Priya (65 avg)  5. Karan (65.3 avg)"
Then explain what drives the ranking.

JUDGMENT (fire, hire, at-risk, deserves, should, recommend):
• Look for PATTERNS across multiple metrics — a single bad metric is not enough to condemn.
• Name the specific combination: "T2002 scores lowest on student outcomes (74.2) AND second-lowest \
on feedback (4.1) — that two-metric pattern makes them the most at-risk."
• Call out if differences are small: "All feedback scores are between 3.9–4.8; the meaningful gap \
is in student outcomes (74.2 vs 88.9)."
• End with one sentence: "This is a data-driven interpretation, not an official recommendation."
• NEVER refuse a judgment question when data exists.

THRESHOLD (below X%, score < N, attendance under Y):
Apply the exact threshold. Show: "Name: value — qualifies / does not qualify."

COMPARISON / TREND:
Show both sides side by side with exact numbers. State direction and magnitude.

━━ FORMAT ━━
• Lead with the most important insight — not a preamble.
• Use numbers always. Vague language ("performed well") without a number is not allowed.
• Rankings inline: "1. Name (value)  2. Name (value)  ..."
• Length: as long as needed to cover all entities. Do not truncate.
• Vary your opening — don't always start with "Based on the data".
"""

# ─────────────────────────────────────────────────────────────────────────────
# Transport
# ─────────────────────────────────────────────────────────────────────────────

_response_cache: dict = {}  # cleared on module reload (i.e. app restart)


def _post_llm(url, model, api_key, messages, temperature):
    """Single HTTP call to any OpenAI-compatible endpoint."""
    payload = {"model": model, "messages": messages, "temperature": temperature}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; StudentIntelligenceAssistant/1.0)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


def call_llm(messages, temperature=0):
    """Gemini-first with Groq fallback. Returns reply text or None on total failure."""
    cache_key = (json.dumps(messages, sort_keys=True), temperature)
    if cache_key in _response_cache:
        return _response_cache[cache_key]

    # ── Try Gemini first ──────────────────────────────────────────────────────
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        try:
            answer = _post_llm(GEMINI_API_URL, GEMINI_MODEL, gemini_key, messages, temperature)
            _response_cache[cache_key] = answer
            return answer
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            if e.code not in (429, 500, 502, 503):
                return f"LLM request failed ({e.code}): {body}"
            # transient or rate-limit — fall through to Groq
        except Exception:
            pass  # network error — fall through to Groq

    # ── Groq fallback (70B only — 8B has insufficient TPM for our context) ────
    groq_key = os.environ.get("GROQ_API_KEY")
    if not groq_key:
        return None

    try:
        answer = _post_llm(GROQ_API_URL, GROQ_MODEL, groq_key, messages, temperature)
        _response_cache[cache_key] = answer
        return answer
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        if e.code == 429:
            return (
                "The AI service is temporarily rate-limited. "
                "Please wait 30 seconds and try again."
            )
        return f"LLM request failed ({e.code}): {body}"
    except urllib.error.URLError as e:
        return f"LLM request failed: {e.reason}"


# ─────────────────────────────────────────────────────────────────────────────
# Public interface
# ─────────────────────────────────────────────────────────────────────────────

def narrate(question: str, full_data_text: str) -> str:
    """Core reasoning call — sends the full dataset + question to the LLM."""
    if not full_data_text:
        return NOT_FOUND_MESSAGE

    has_any_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY")
    if not has_any_key:
        return (
            f"{NO_API_KEY_MESSAGE}\n"
            "Add GEMINI_API_KEY or GROQ_API_KEY to your .env file and restart."
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Here is the complete college dataset:\n\n{full_data_text}"
                f"\n\n---\nQuestion: {question}"
            ),
        },
    ]
    return call_llm(messages, temperature=0)
