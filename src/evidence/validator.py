"""
src/evidence/validator.py

Evidence Validator — corroborates signals across multiple source documents.
Promotes or demotes signal severity based on evidence strength.

Pipeline position:
    Detector → Validator → Risk Intelligence

Corroboration rules:
    - A signal needs evidence from >= 2 different documents to be STRONG
    - A signal with evidence from only 1 document stays WEAK
    - A signal with no matching evidence snippets is downgraded to NOISE
    - Confidence band is recalculated after validation

Design rules:
    - Only anonymized text is processed here — no PII
    - NOISE signals are filtered out — never passed to Risk Intelligence
    - Every validation decision is logged

Usage:
    from src.evidence.validator import validate_signals
    validated = validate_signals(signals, anon_docs)
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from src.exceptions import ValidationError
from src.models import AnonymizedDocument, Evidence, Signal

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────

MIN_SOURCES_FOR_STRONG = 2      # minimum distinct documents to confirm STRONG
MIN_SNIPPET_LENGTH = 20         # evidence snippet must be at least 20 chars
MAX_SNIPPETS_PER_SIGNAL = 5     # cap evidence shown on signal card


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    signal: Signal
    evidence_list: list[Evidence]
    passed: bool
    reason: str = ""

    @property
    def failed(self) -> bool:
        return not self.passed


# ── Public API ────────────────────────────────────────────────────────────────

def validate_signals(
    signals: list[Signal],
    anon_docs: list[AnonymizedDocument],
) -> list[ValidationResult]:
    """
    Validate each signal against the full set of anonymized documents.

    For each WEAK or STRONG signal:
        1. Find text snippets across all documents that match the signal's keywords
        2. Count how many distinct documents contain supporting evidence
        3. Promote to STRONG if >= MIN_SOURCES_FOR_STRONG documents found
        4. Downgrade to NOISE if no evidence found across any document

    NOISE signals from the Detector are passed through with failed=True
    so they can be logged — they are never passed to Risk Intelligence.

    Args:
        signals:   List of Signal objects from the Detector.
        anon_docs: All AnonymizedDocuments processed in this run.

    Returns:
        List of ValidationResult objects. Filter with result.passed to get
        only signals that should proceed to Risk Intelligence.
    """
    if not signals:
        raise ValidationError("No signals provided for validation.")

    if not anon_docs:
        raise ValidationError("No documents provided for evidence search.")

    results: list[ValidationResult] = []

    for signal in signals:
        result = _validate_one(signal, anon_docs)
        results.append(result)

        if result.passed:
            logger.info(
                "VALIDATED signal=%s [%s] — %d evidence snippets from %d documents.",
                signal.id[:8],
                signal.severity,
                len(result.evidence_list),
                len({e.document_id for e in result.evidence_list}),
            )
        else:
            logger.info(
                "REJECTED signal=%s [%s] — %s",
                signal.id[:8],
                signal.severity,
                result.reason,
            )

    passed = sum(1 for r in results if r.passed)
    logger.info(
        "Validation complete — %d/%d signals passed.",
        passed,
        len(results),
    )
    return results


# ── Internal helpers ──────────────────────────────────────────────────────────

def _validate_one(
    signal: Signal,
    anon_docs: list[AnonymizedDocument],
) -> ValidationResult:
    """Validate a single signal against all documents."""

    # NOISE signals from Detector are immediately rejected
    if signal.severity == "NOISE":
        return ValidationResult(
            signal=signal,
            evidence_list=[],
            passed=False,
            reason="Signal classified as NOISE by Detector — not actionable.",
        )

    # Extract keywords from signal title and existing evidence snippets
    keywords = _extract_keywords(signal)

    if not keywords:
        return ValidationResult(
            signal=signal,
            evidence_list=[],
            passed=False,
            reason="No keywords extracted from signal — cannot search for evidence.",
        )

    # Search all documents for matching snippets
    evidence_list: list[Evidence] = []
    source_doc_ids: set[str] = set()

    for anon_doc in anon_docs:
        snippets = _find_snippets(anon_doc.anonymized_text, keywords)
        for snippet in snippets:
            ev = Evidence(
                id=str(uuid.uuid4()),
                signal_id=signal.id,
                document_id=anon_doc.document_id,
                snippet=snippet,
                relevance_score=_score_snippet(snippet, keywords),
                source_count=1,
            )
            evidence_list.append(ev)
            source_doc_ids.add(anon_doc.document_id)

    # No evidence found anywhere — downgrade to NOISE
    if not evidence_list:
        signal.severity = "NOISE"
        signal.confidence_band = "low"
        signal.updated_at = datetime.utcnow()
        return ValidationResult(
            signal=signal,
            evidence_list=[],
            passed=False,
            reason="No supporting evidence found across any document.",
        )

    # Cap evidence list and sort by relevance
    evidence_list.sort(key=lambda e: e.relevance_score, reverse=True)
    evidence_list = evidence_list[:MAX_SNIPPETS_PER_SIGNAL]

    # Update source_count on each evidence item
    for ev in evidence_list:
        ev.source_count = len(source_doc_ids)

    # Promote or demote severity based on source count
    source_count = len(source_doc_ids)
    original_severity = signal.severity

    if source_count >= MIN_SOURCES_FOR_STRONG:
        signal.severity = "STRONG"
        signal.confidence_band = "high" if source_count >= 4 else "medium"
    else:
        signal.severity = "WEAK"
        signal.confidence_band = "low"

    if signal.severity != original_severity:
        logger.info(
            "Signal=%s severity changed: %s → %s (%d sources)",
            signal.id[:8],
            original_severity,
            signal.severity,
            source_count,
        )

    # Update signal evidence snippets with validated ones
    signal.evidence = [ev.snippet for ev in evidence_list]
    signal.source_document_ids = list(source_doc_ids)
    signal.updated_at = datetime.utcnow()

    return ValidationResult(
        signal=signal,
        evidence_list=evidence_list,
        passed=True,
    )


def _extract_keywords(signal: Signal) -> list[str]:
    """
    Extract search keywords from the signal title and existing evidence.
    Returns lowercase words of length >= 4 (skip short stopwords).
    """
    text = signal.title + " " + " ".join(signal.evidence)
    words = text.lower().split()
    # Keep meaningful words only — skip short words and role codes
    keywords = [
        w.strip(".,;:[]()") for w in words
        if len(w) >= 4 and not w.startswith("[")
    ]
    return list(set(keywords))


def _find_snippets(text: str, keywords: list[str]) -> list[str]:
    """
    Find sentences in text that contain at least one keyword.
    Returns anonymized snippets of MIN_SNIPPET_LENGTH or longer.
    """
    sentences = [s.strip() for s in text.replace("\n", ". ").split(".") if s.strip()]
    snippets: list[str] = []

    for sentence in sentences:
        sentence_lower = sentence.lower()
        if any(kw in sentence_lower for kw in keywords):
            if len(sentence) >= MIN_SNIPPET_LENGTH:
                snippets.append(sentence[:200])   # cap at 200 chars

    return snippets


def _score_snippet(snippet: str, keywords: list[str]) -> float:
    """
    Score a snippet by how many keywords it contains.
    Returns a value between 0.0 and 1.0.
    Internal use only — never shown to users.
    """
    snippet_lower = snippet.lower()
    hits = sum(1 for kw in keywords if kw in snippet_lower)
    return min(hits / max(len(keywords), 1), 1.0)
