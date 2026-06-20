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

from groq import Groq

from src.config import config
from src.exceptions import NarrationError
from src.models import Risk

logger = logging.getLogger(__name__)

# ── Groq client — loaded once ─────────────────────────────────────────────────
_client: Groq | None = None


def _get_client() -> Groq:
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
    """
    return f"""You are a programme risk analyst writing a brief executive summary.

You have been given a structured risk object detected from anonymised organisational communications.
Write a 2-sentence plain-English executive summary for a Programme Manager.

Rules:
- Write exactly 2 sentences. No more, no less.
- Use plain business language. No jargon.
- Do not mention AI, machine learning, or detection systems.
- Do not invent facts beyond what is provided below.
- All role references use anonymised codes — keep them as-is.

Risk data:
- Signal: {signal_title}
- Category: {risk.priority} priority {risk.suggested_owner_role} risk
- Business impact: {risk.business_impact}
- Root cause hypothesis: {risk.root_cause_hypothesis}
- Suggested action: {risk.suggested_action}
- Supporting evidence from {len(risk.supporting_document_ids)} document(s)

Write the 2-sentence summary now:"""


# ── Fallback narration ────────────────────────────────────────────────────────

def _fallback_narration(risk: Risk) -> str:
    """
    Used when Groq is unavailable or fails.
    Produces a readable summary from structured fields — no LLM needed.
    """
    return (
        f"{risk.business_impact} "
        f"Suggested action: {risk.suggested_action}"
    )


# ── Public API ────────────────────────────────────────────────────────────────

def narrate_risk(risk: Risk, signal_title: str = "Signal detected") -> Risk:
    """
    Generate a plain-English executive narration for a Risk object.
    Populates risk.narration in place and returns the same Risk object.

    If Groq fails for any reason, a fallback narration is used — the
    pipeline never stops because of a narration failure.

    Args:
        risk:         A Risk object from Risk Intelligence (narration is empty).
        signal_title: The title of the parent Signal — used in the prompt.

    Returns:
        The same Risk object with narration populated.
    """
    if risk.narration:
        logger.info("Risk %s already has narration — skipping.", risk.id[:8])
        return risk

    try:
        client = _get_client()
        prompt = _build_prompt(risk, signal_title)

        logger.info(
            "Calling Groq for risk=%s (model=%s)...",
            risk.id[:8],
            config.GROQ_MODEL,
        )

        response = client.chat.completions.create(
            model=config.GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a concise programme risk analyst. "
                        "You write exactly 2 sentences. You never invent facts."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,        # low temperature = consistent, factual output
            max_tokens=150,         # 2 sentences needs no more than 150 tokens
        )

        narration = response.choices[0].message.content.strip()

        # Basic sanity check — must be non-empty
        if not narration:
            raise NarrationError("Groq returned an empty response.")

        risk.narration = narration
        logger.info(
            "Narration complete for risk=%s — %d chars.",
            risk.id[:8],
            len(narration),
        )

    except NarrationError:
        raise
    except Exception as exc:
        logger.warning(
            "Groq call failed for risk=%s (%s) — using fallback narration.",
            risk.id[:8],
            exc,
        )
        risk.narration = _fallback_narration(risk)

    return risk


def narrate_risks(risks: list[Risk], signal_titles: dict[str, str] | None = None) -> list[Risk]:
    """
    Narrate a list of Risk objects.
    Continues even if individual narrations fail — fallback is used per risk.

    Args:
        risks:         List of Risk objects from Risk Intelligence.
        signal_titles: Optional dict mapping signal_id → signal title.
                       If not provided, a generic title is used.

    Returns:
        The same list of Risk objects with narration populated on each.
    """
    if not risks:
        logger.warning("narrate_risks called with empty list.")
        return risks

    signal_titles = signal_titles or {}

    for risk in risks:
        title = signal_titles.get(risk.signal_id, "Organisational risk signal detected")
        narrate_risk(risk, signal_title=title)

    narrated = sum(1 for r in risks if r.narration)
    logger.info(
        "Narration complete — %d/%d risks narrated.",
        narrated,
        len(risks),
    )
    return risks
