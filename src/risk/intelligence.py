"""
src/risk/intelligence.py

Risk Intelligence — builds a structured Risk object from a validated signal.
This is the last purely structured step before Groq narration.

Pipeline position:
    Evidence Validator → Risk Intelligence → LLM Narrator

What it does:
    - Maps signal category + severity to business impact statement
    - Assigns priority (critical / high / medium / low)
    - Suggests a concrete action for the owner
    - Forms a root cause hypothesis from signal keywords
    - Produces a complete Risk object ready for Groq to narrate

Design rules:
    - No LLM calls here — structured logic only
    - All text is anonymized before reaching this module
    - narration field is left empty — Groq fills it in narrator.py

Usage:
    from src.risk.intelligence import build_risk
    risk = build_risk(validation_result)
"""

import logging
import uuid
from datetime import datetime

from src.evidence.validator import ValidationResult
from src.exceptions import RiskIntelligenceError
from src.models import Risk, Signal

logger = logging.getLogger(__name__)


# ── Priority mapping ──────────────────────────────────────────────────────────
# severity + confidence_band → priority

PRIORITY_MAP: dict[tuple[str, str], str] = {
    ("STRONG", "high"):   "critical",
    ("STRONG", "medium"): "high",
    ("STRONG", "low"):    "high",
    ("WEAK",   "high"):   "medium",
    ("WEAK",   "medium"): "medium",
    ("WEAK",   "low"):    "low",
}


# ── Business impact templates ─────────────────────────────────────────────────

IMPACT_TEMPLATES: dict[str, dict[str, str]] = {
    "delivery_risk": {
        "critical": "Programme delivery milestone at critical risk — escalation required this week.",
        "high":     "Delivery milestone at risk — intervention needed before next sprint.",
        "medium":   "Delivery timeline showing early warning signs — monitor closely.",
        "low":      "Minor delivery friction detected — log and review next sprint.",
    },
    "team_health": {
        "critical": "Team capacity critically low — risk of burnout and attrition is imminent.",
        "high":     "Team health signals deteriorating — people risk requires director attention.",
        "medium":   "Team health showing stress signals — proactive support recommended.",
        "low":      "Early team health signal — check in with team lead this week.",
    },
    "attrition": {
        "critical": "Multiple team members showing attrition signals — immediate retention action required.",
        "high":     "Attrition risk detected across the team — HR and management review needed this week.",
        "medium":   "Early attrition signals observed — manager 1:1s and retention check recommended.",
        "low":      "Low-level attrition signal — monitor and include in next people review.",
    },
    "bus_factor": {
        "critical": "Critical knowledge concentrated in one person — programme is at single-point-of-failure risk.",
        "high":     "Knowledge silos detected — loss of a key individual would severely impact delivery.",
        "medium":   "Knowledge concentration risk emerging — documentation and knowledge sharing needed.",
        "low":      "Early knowledge silo signal — encourage documentation in next sprint.",
    },
    "technical_debt": {
        "critical": "Engineering quality critically degraded — test coverage gaps and bugs threaten the release.",
        "high":     "Technical debt accumulation is impacting delivery speed and software quality.",
        "medium":   "Engineering quality signals present — test coverage and QA process review recommended.",
        "low":      "Low-level quality signal — add to technical backlog for next planning cycle.",
    },
    "operational": {
        "critical": "Operational stability at risk — potential incident in progress or imminent.",
        "high":     "Operational signals suggest reliability risk — SRE review required.",
        "medium":   "Operational pattern warrants monitoring — review ticket volume trend.",
        "low":      "Low-level operational noise — log for pattern tracking.",
    },
    "dependency": {
        "critical": "Critical external dependency blocking programme — immediate owner action required.",
        "high":     "Dependency bottleneck forming — escalate to remove blocker this sprint.",
        "medium":   "Dependency risk emerging — identify owner and set resolution deadline.",
        "low":      "Early dependency signal — track and review next sprint.",
    },
}


# ── Action templates ──────────────────────────────────────────────────────────

ACTION_TEMPLATES: dict[str, dict[str, str]] = {
    "delivery_risk": {
        "critical": "Convene emergency programme review. Identify which milestone is at risk and assign a recovery owner today.",
        "high":     "Schedule a focused delivery review with the programme manager and team leads before end of week.",
        "medium":   "Add delivery risk to the agenda for the next programme standup. Assign a tracking owner.",
        "low":      "Log the signal and review in the next sprint retrospective.",
    },
    "team_health": {
        "critical": "Director to hold 1:1 with team leads immediately. Consider resource rebalancing or timeline relief.",
        "high":     "Programme manager to schedule a team health check-in this week.",
        "medium":   "Team lead to run a brief pulse check with the team. Report findings to programme manager.",
        "low":      "Monitor team communications over the next sprint for escalation.",
    },
    "attrition": {
        "critical": "HR Business Partner and Engineering Manager to hold immediate retention conversations. Escalate to Director if two or more members are at risk.",
        "high":     "Engineering Manager to run 1:1 retention check-ins this week. Identify root causes and relief options.",
        "medium":   "Manager to check in with flagged team members. Review workload and growth opportunities.",
        "low":      "Include attrition signal in next people review. Monitor for escalation.",
    },
    "bus_factor": {
        "critical": "Immediately identify critical knowledge held by one person. Initiate knowledge transfer sessions and document runbooks this sprint.",
        "high":     "Engineering Manager to assign documentation pairing. Schedule knowledge transfer before next sprint.",
        "medium":   "Team lead to run a knowledge mapping session. Identify undocumented systems or processes.",
        "low":      "Add knowledge sharing to sprint goals. Encourage peer documentation review.",
    },
    "technical_debt": {
        "critical": "Engineering Lead to halt new feature work until critical test coverage gaps are resolved. Run QA review immediately.",
        "high":     "Schedule a dedicated tech debt sprint. Engineering Lead to define coverage targets and assign debt owners.",
        "medium":   "Include tech debt items in next sprint planning. Engineering Lead to set minimum test coverage threshold.",
        "low":      "Log tech debt signal. Add to backlog and review in next planning cycle.",
    },
    "operational": {
        "critical": "SRE lead to initiate incident response protocol. Page on-call if not already active.",
        "high":     "SRE lead to review incident logs and ticket volume. Prepare runbook update.",
        "medium":   "Operations lead to review ticket patterns. Set alert threshold for next week.",
        "low":      "Log operational signal. Include in next SRE weekly review.",
    },
    "dependency": {
        "critical": "Programme manager to escalate blocking dependency to director today. Identify workaround or timeline impact.",
        "high":     "Owner to contact dependency team lead and set a resolution deadline before end of sprint.",
        "medium":   "Assign a dependency owner. Schedule a sync between affected teams this week.",
        "low":      "Log dependency risk. Add to programme risk register.",
    },
}


# ── Root cause templates ──────────────────────────────────────────────────────

ROOT_CAUSE_TEMPLATES: dict[str, str] = {
    "delivery_risk":  "Likely causes: resource constraint, scope creep, unresolved technical blocker, or dependency on another team.",
    "team_health":    "Likely causes: sustained overload, unclear priorities, lack of support, or team structure misalignment.",
    "attrition":      "Likely causes: sustained overwork, lack of career growth, team conflict, compensation concerns, or unclear expectations.",
    "bus_factor":     "Likely causes: insufficient documentation, lack of pair programming, knowledge hoarding, or rapid team scaling without onboarding.",
    "technical_debt": "Likely causes: delivery pressure squeezing QA, lack of test coverage standards, accumulated deferred refactoring, or insufficient code review.",
    "operational":    "Likely causes: increased system load, unresolved technical debt, insufficient monitoring, or deployment instability.",
    "dependency":     "Likely causes: external vendor delay, cross-team coordination gap, or missing ownership of the dependency.",
}


# ── Public API ────────────────────────────────────────────────────────────────

def build_risk(validation_result: ValidationResult) -> Risk:
    """
    Build a Risk object from a validated signal.

    Args:
        validation_result: Output from the Evidence Validator (must have passed=True).

    Returns:
        A Risk object with all fields populated except narration (Groq fills that).

    Raises:
        RiskIntelligenceError: If the validation result failed or signal is NOISE.
    """
    if validation_result.failed:
        raise RiskIntelligenceError(
            f"Cannot build Risk from a failed validation result: {validation_result.reason}"
        )

    signal = validation_result.signal

    if signal.severity == "NOISE":
        raise RiskIntelligenceError(
            f"Signal {signal.id[:8]} is NOISE — Risk Intelligence does not process NOISE signals."
        )

    priority = _get_priority(signal)
    business_impact = _get_business_impact(signal, priority)
    suggested_action = _get_suggested_action(signal, priority)
    root_cause = _get_root_cause(signal)
    supporting_doc_ids = list({ev.document_id for ev in validation_result.evidence_list})

    risk = Risk(
        id=str(uuid.uuid4()),
        signal_id=signal.id,
        business_impact=business_impact,
        confidence_band=signal.confidence_band,
        priority=priority,
        suggested_owner_role=signal.suggested_owner_role,
        suggested_action=suggested_action,
        root_cause_hypothesis=root_cause,
        supporting_document_ids=supporting_doc_ids,
        narration="",   # Groq fills this in narrator.py
        created_at=datetime.utcnow(),
    )

    logger.info(
        "Built Risk: id=%s signal=%s priority=%s category=%s",
        risk.id[:8],
        signal.id[:8],
        risk.priority,
        signal.category,
    )

    return risk


def build_risks(validation_results: list[ValidationResult]) -> list[Risk]:
    """
    Build Risk objects for all passed validation results.
    Skips failed results silently — they are already logged by the Validator.

    Args:
        validation_results: List of ValidationResult objects.

    Returns:
        List of Risk objects, one per passed validation result.
    """
    risks: list[Risk] = []

    for result in validation_results:
        if result.failed:
            continue
        try:
            risk = build_risk(result)
            risks.append(risk)
        except RiskIntelligenceError as exc:
            logger.warning("Skipped risk build: %s", exc)

    logger.info(
        "Risk Intelligence complete — %d risks built from %d validation results.",
        len(risks),
        len(validation_results),
    )
    return risks


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_priority(signal: Signal) -> str:
    key = (signal.severity, signal.confidence_band)
    return PRIORITY_MAP.get(key, "low")


def _get_business_impact(signal: Signal, priority: str) -> str:
    category_map = IMPACT_TEMPLATES.get(signal.category, IMPACT_TEMPLATES["delivery_risk"])
    return category_map.get(priority, category_map["low"])


def _get_suggested_action(signal: Signal, priority: str) -> str:
    category_map = ACTION_TEMPLATES.get(signal.category, ACTION_TEMPLATES["delivery_risk"])
    return category_map.get(priority, category_map["low"])


def _get_root_cause(signal: Signal) -> str:
    return ROOT_CAUSE_TEMPLATES.get(signal.category, ROOT_CAUSE_TEMPLATES["delivery_risk"])
