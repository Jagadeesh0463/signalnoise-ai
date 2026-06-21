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

_CATEGORY_FOCUS: dict[str, str] = {
    "dependency":     "Focus on: which APIs or vendors are blocked, how long they have been unresolved, and escalation urgency.",
    "delivery_risk":  "Focus on: missed milestones, sprint velocity decline, carry-forward work, and timeline impact.",
    "operational":    "Focus on: incidents, outages, deployment failures, and reliability risk.",
    "team_health":    "Focus on: overtime patterns, morale signals, workload allocation, and burnout indicators.",
    "attrition":      "Focus on: retention risk, resignation signals, staffing impact on delivery, and urgency of action.",
    "bus_factor":     "Focus on: which roles hold critical knowledge, single-point-of-failure risk, and documentation gaps.",
    "technical_debt": "Focus on: test coverage gaps, bugs escaping to production, QA capacity, and quality degradation trend.",
}


def _build_prompt(risk: Risk, signal_title: str, category: str = "") -> str:
    """
    Build a category-specific prompt for Groq.

    All values come from the Risk object — no raw document text is included.
    The prompt is a template; user-controlled content is never interpolated
    into the instruction portion (prevents prompt injection).

    Args:
        risk:         Structured Risk object.
        signal_title: Title of the parent Signal.
        category:     Signal category for focus instructions.

    Returns:
        Complete prompt string for the Groq chat completion.
    """
    focus_hint = _CATEGORY_FOCUS.get(category, "Focus on the business impact and urgency of action.")

    return (
        "You are a program risk analyst writing a concise executive summary.\n\n"
        "Write exactly 2 sentences for a Program Manager reading a risk dashboard.\n\n"
        "Rules:\n"
        "- First sentence: describe the specific risk and its organizational impact.\n"
        "- Second sentence: state the recommended action with urgency.\n"
        f"- {focus_hint}\n"
        "- Reference specific patterns where possible (e.g. 'three consecutive sprints', "
        "'unresolved for five weeks', 'two team members at risk').\n"
        "- Use plain business language. No jargon, no AI/ML references.\n"
        "- Do not invent facts not present in the data below.\n"
        "- Role codes are anonymized — use them as-is.\n\n"
        "Risk data:\n"
        f"  Signal: {signal_title}\n"
        f"  Category: {category or 'general'}\n"
        f"  Priority: {risk.priority}\n"
        f"  Owner: {risk.suggested_owner_role}\n"
        f"  Business impact: {risk.business_impact}\n"
        f"  Root cause: {risk.root_cause_hypothesis}\n"
        f"  Suggested action: {risk.suggested_action}\n"
        f"  Evidence from {len(risk.supporting_document_ids)} document(s)\n\n"
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

def narrate_risk(risk: Risk, signal_title: str = "Signal detected", category: str = "") -> Risk:
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

    prompt = _build_prompt(risk, signal_title, category=category)
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
    signal_categories: dict[str, str] | None = None,
) -> list[Risk]:
    """
    Narrate a list of Risk objects with category-specific prompts.

    Continues even if individual narrations fail — fallback is used per risk.
    Already-narrated risks are skipped.

    Args:
        risks:              List of Risk objects from Risk Intelligence.
        signal_titles:      Optional dict mapping signal_id → signal title.
        signal_categories:  Optional dict mapping signal_id → category string.

    Returns:
        The same list of Risk objects with narration populated on each.
    """
    if not risks:
        logger.warning("narrate_risks called with empty list.")
        return risks

    signal_titles = signal_titles or {}
    signal_categories = signal_categories or {}

    for risk in risks:
        title = signal_titles.get(risk.signal_id, "Organizational risk signal detected")
        category = signal_categories.get(risk.signal_id, "")
        narrate_risk(risk, signal_title=title, category=category)

    narrated = sum(1 for r in risks if r.narration)
    logger.info(
        "Narration complete — %d/%d risks narrated.",
        narrated,
        len(risks),
    )
    return risks
