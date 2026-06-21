"""
src/narration/narrator.py

LLM Narrator — uses Groq to generate a plain-English executive summary
for each Risk object. This is the LAST step in the pipeline.

Pipeline position:
    Risk Intelligence → Narrator → Streamlit Dashboard

Design rules (non-negotiable):
    - Groq receives ONLY the structured Risk object fields — never raw text
    - All text sent to Groq is already anonymized (role codes, not names)
    - Groq is used for NARRATION only — never for signal detection or decisions
    - If Groq fails, the Risk is still returned with a fallback narration
    - Enterprise deployment replaces Groq with Ollama (same interface)

Usage:
    from src.narration.narrator import narrate_risk, narrate_risks
    risk = narrate_risk(risk)
    risks = narrate_risks(risk_list)
"""

import logging
import time

from groq import Groq

from src.config import config
from src.exceptions import NarrationError
from src.models import Risk

logger = logging.getLogger(__name__)

# ── Retry configuration ───────────────────────────────────────────────────────

_MAX_RETRIES = 2          # total attempts = 1 + _MAX_RETRIES
_RETRY_BASE_DELAY = 1.0   # seconds; doubles on each retry (exponential backoff)
_REQUEST_TIMEOUT = 10.0   # seconds per Groq request

# ── Groq client — loaded once ─────────────────────────────────────────────────
_client: Groq | None = None


def _get_client() -> Groq:
    """Initialise the Groq client once and reuse across calls."""
    global _client
    if _client is None:
        logger.info("Initialising Groq client (model: %s)", config.GROQ_MODEL)
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(risk: Risk, signal_title: str) -> str:
    """
    Build a structured prompt for Groq.

    All values come from the Risk object — no raw document text is included.
    The prompt is a template; user-controlled content is never interpolated
    into the instruction portion (prevents prompt injection).

    Args:
        risk:         Structured Risk object.
        signal_title: Title of the parent Signal.

    Returns:
        Complete prompt string for the Groq chat completion.
    """
    return (
        "You are a program risk analyst writing a brief executive summary.\n\n"
        "You have been given a structured risk object detected from anonymized "
        "organizational communications.\n"
        "Write a 2-sentence plain-English executive summary for a Program Manager.\n\n"
        "Rules:\n"
        "- Write exactly 2 sentences. No more, no less.\n"
        "- Use plain business language. No jargon.\n"
        "- Do not mention AI, machine learning, or detection systems.\n"
        "- Do not invent facts beyond what is provided below.\n"
        "- All role references use anonymized codes — keep them as-is.\n\n"
        "Risk data:\n"
        f"- Signal: {signal_title}\n"
        f"- Category: {risk.priority} priority {risk.suggested_owner_role} risk\n"
        f"- Business impact: {risk.business_impact}\n"
        f"- Root cause hypothesis: {risk.root_cause_hypothesis}\n"
        f"- Suggested action: {risk.suggested_action}\n"
        f"- Supporting evidence from {len(risk.supporting_document_ids)} document(s)\n\n"
        "Write the 2-sentence summary now:"
    )


# ── Fallback narration ────────────────────────────────────────────────────────

def _fallback_narration(risk: Risk) -> str:
    """
    Produce a readable summary from structured Risk fields when Groq is unavailable.
    Never raises — always returns a non-empty string.

    Args:
        risk: A Risk object with all fields populated.

    Returns:
        A plain-English summary built from structured fields.
    """
    return (
        f"{risk.business_impact} "
        f"Suggested action: {risk.suggested_action}"
    )


# ── Public API ────────────────────────────────────────────────────────────────

def narrate_risk(risk: Risk, signal_title: str = "Signal detected") -> Risk:
    """
    Generate a plain-English executive narration for a Risk object.

    Attempts to call Groq with exponential backoff retry. If all retries
    fail, a structured fallback narration is used. The pipeline never stops
    because of a narration failure.

    Args:
        risk:         A Risk object from Risk Intelligence (narration is empty).
        signal_title: The title of the parent Signal — used in the prompt.

    Returns:
        The same Risk object with narration populated (mutated in place).
    """
    if risk.narration:
        logger.info("Risk %s already has narration — skipping.", risk.id[:8])
        return risk

    prompt = _build_prompt(risk, signal_title)
    last_error: Exception | None = None

    for attempt in range(1 + _MAX_RETRIES):
        try:
            if attempt > 0:
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.info(
                    "Retrying Groq for risk=%s (attempt %d/%d, delay=%.1fs)...",
                    risk.id[:8],
                    attempt + 1,
                    1 + _MAX_RETRIES,
                    delay,
                )
                time.sleep(delay)

            client = _get_client()

            logger.info(
                "Calling Groq for risk=%s (model=%s, attempt=%d)...",
                risk.id[:8],
                config.GROQ_MODEL,
                attempt + 1,
            )

            response = client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a concise program risk analyst. "
                            "You write exactly 2 sentences. You never invent facts."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,    # low temperature = consistent, factual output
                max_tokens=150,     # 2 sentences needs no more than 150 tokens
                timeout=_REQUEST_TIMEOUT,
            )

            narration = response.choices[0].message.content.strip()

            if not narration:
                raise NarrationError("Groq returned an empty response.")

            risk.narration = narration
            logger.info(
                "Narration complete for risk=%s — %d chars (attempt %d).",
                risk.id[:8],
                len(narration),
                attempt + 1,
            )
            return risk

        except NarrationError:
            # Empty response — no point retrying
            logger.warning(
                "Groq returned empty response for risk=%s — using fallback.",
                risk.id[:8],
            )
            break

        except Exception as exc:
            last_error = exc
            # Rate limit or server error — retry
            logger.warning(
                "Groq call failed for risk=%s (attempt %d/%d): %s",
                risk.id[:8],
                attempt + 1,
                1 + _MAX_RETRIES,
                exc,
            )

    # All retries exhausted — use fallback
    logger.warning(
        "All Groq retries failed for risk=%s — using fallback narration. Last error: %s",
        risk.id[:8],
        last_error,
    )
    risk.narration = _fallback_narration(risk)
    return risk


def narrate_risks(
    risks: list[Risk],
    signal_titles: dict[str, str] | None = None,
) -> list[Risk]:
    """
    Narrate a list of Risk objects.

    Continues even if individual narrations fail — fallback is used per risk.
    Already-narrated risks are skipped.

    Args:
        risks:         List of Risk objects from Risk Intelligence.
        signal_titles: Optional dict mapping signal_id → signal title.
                       A generic title is used if not provided.

    Returns:
        The same list of Risk objects with narration populated on each.
    """
    if not risks:
        logger.warning("narrate_risks called with empty list.")
        return risks

    signal_titles = signal_titles or {}

    for risk in risks:
        title = signal_titles.get(risk.signal_id, "Organizational risk signal detected")
        narrate_risk(risk, signal_title=title)

    narrated = sum(1 for r in risks if r.narration)
    logger.info(
        "Narration complete — %d/%d risks narrated.",
        narrated,
        len(risks),
    )
    return risks
