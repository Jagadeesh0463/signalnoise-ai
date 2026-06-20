"""
src/privacy/anonymizer.py

Privacy Shield — removes PII and maps real names to role codes.
Uses Microsoft Presidio for PII detection and anonymization.

Pipeline position:
    Loader → Anonymizer → Embedder

Design rules (non-negotiable):
    - Runs BEFORE any embedding, BERTopic, or Groq call
    - Never logs raw_text — only doc_id and word count
    - Role codes replace names: "John Smith" → "[Backend-Lead-A]"
    - raw_text is cleared from Document after anonymization

Usage:
    from src.privacy.anonymizer import anonymize
    anon_doc = anonymize(document)
"""

import logging
import re
from datetime import datetime
from string import ascii_uppercase

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from src.config import config
from src.exceptions import PrivacyShieldError
from src.models import AnonymizedDocument, Document

logger = logging.getLogger(__name__)

# ── PII entity types Presidio will detect and remove ─────────────────────────
ENTITIES_TO_ANONYMIZE = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "URL",
    "IP_ADDRESS",
    "LOCATION",
    "DATE_TIME",
    "NRP",               # Nationality, Religion, Political group
    "MEDICAL_LICENSE",
    "IBAN_CODE",
    "CREDIT_CARD",
]

# ── Module-level engine instances (loaded once, reused per call) ──────────────
_analyzer: AnalyzerEngine | None = None
_anonymizer: AnonymizerEngine | None = None
_role_counter: dict[str, int] = {}   # tracks how many roles assigned per type


def _get_engines() -> tuple[AnalyzerEngine, AnonymizerEngine]:
    """Load Presidio engines once and reuse. Thread-safe for single-user MVP."""
    global _analyzer, _anonymizer
    if _analyzer is None:
        logger.info("Loading Presidio engines with model=%s (first call only)...", config.SPACY_MODEL)
        nlp_configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": config.SPACY_MODEL}],
        }
        provider = NlpEngineProvider(nlp_configuration=nlp_configuration)
        nlp_engine = provider.create_engine()
        _analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
        _anonymizer = AnonymizerEngine()
        logger.info("Presidio engines loaded with %s.", config.SPACY_MODEL)
    return _analyzer, _anonymizer


# ── Role mapping ──────────────────────────────────────────────────────────────

def _entity_type_to_role_prefix(entity_type: str) -> str:
    """Map a Presidio entity type to a readable role prefix."""
    mapping = {
        "PERSON":          "Person",
        "EMAIL_ADDRESS":   "Email",
        "PHONE_NUMBER":    "Phone",
        "URL":             "URL",
        "IP_ADDRESS":      "IP",
        "LOCATION":        "Location",
        "DATE_TIME":       "Date",
        "NRP":             "Group",
        "MEDICAL_LICENSE": "License",
        "IBAN_CODE":       "Account",
        "CREDIT_CARD":     "Card",
    }
    return mapping.get(entity_type, "Entity")


def _assign_role_code(original: str, entity_type: str, role_map: dict[str, str]) -> str:
    """
    Return a stable role code for a detected PII value.
    Same name always gets the same role code within one document.

    Example:
        "John Smith"  → "[Person-A]"
        "Jane Doe"    → "[Person-B]"
        "John Smith"  → "[Person-A]"  (same code, second occurrence)
    """
    if original in role_map:
        return role_map[original]

    prefix = _entity_type_to_role_prefix(entity_type)
    count = sum(1 for k in role_map.values() if k.startswith(f"[{prefix}-"))
    suffix = ascii_uppercase[count] if count < 26 else str(count)
    role_code = f"[{prefix}-{suffix}]"
    role_map[original] = role_code
    return role_code


# ── Public API ────────────────────────────────────────────────────────────────

def anonymize(document: Document) -> AnonymizedDocument:
    """
    Remove PII from a Document and return an AnonymizedDocument.

    Steps:
        1. Detect all PII entities using Presidio Analyzer
        2. Build a role_map: original → role code
        3. Replace each PII span with its role code
        4. Clear raw_text from the original Document (privacy compliance)

    Args:
        document: A Document with raw_text populated.

    Returns:
        AnonymizedDocument with anonymized_text and role_map.

    Raises:
        PrivacyShieldError: If Presidio fails or document has no raw_text.
    """
    if not document.raw_text:
        raise PrivacyShieldError(
            f"Document '{document.id[:8]}' has no raw_text. "
            "Was it already anonymized?"
        )

    analyzer, anonymizer = _get_engines()
    role_map: dict[str, str] = {}

    logger.info(
        "Anonymizing doc_id=%s (%d words)",
        document.id[:8],
        document.word_count,
    )

    try:
        # Step 1 — detect PII
        results = analyzer.analyze(
            text=document.raw_text,
            entities=ENTITIES_TO_ANONYMIZE,
            language="en",
        )

        if not results:
            logger.info(
                "No PII detected in doc_id=%s — text passes through unchanged.",
                document.id[:8],
            )
            anonymized_text = document.raw_text

        else:
            logger.info(
                "Detected %d PII entity/entities in doc_id=%s.",
                len(results),
                document.id[:8],
            )

            # Step 2 — build role_map from detected spans
            for result in results:
                original_span = document.raw_text[result.start:result.end]
                _assign_role_code(original_span, result.entity_type, role_map)

            # Step 3 — replace PII spans with role codes using Presidio Anonymizer
            operators = {
                entity: OperatorConfig(
                    "replace",
                    {"new_value": role_map.get(
                        document.raw_text[
                            next(r.start for r in results if r.entity_type == entity):
                            next(r.end for r in results if r.entity_type == entity)
                        ],
                        f"[{_entity_type_to_role_prefix(entity)}-X]"
                    )}
                )
                for entity in {r.entity_type for r in results}
            }

            anonymized_result = anonymizer.anonymize(
                text=document.raw_text,
                analyzer_results=results,
                operators=operators,
            )
            anonymized_text = anonymized_result.text

    except PrivacyShieldError:
        raise
    except Exception as exc:
        raise PrivacyShieldError(
            f"Presidio failed on doc_id={document.id[:8]}: {exc}"
        ) from exc

    # Step 4 — clear raw_text from Document (privacy compliance)
    document.clear_raw_text()

    anon_doc = AnonymizedDocument(
        id=_new_id(),
        document_id=document.id,
        anonymized_text=anonymized_text,
        role_map=role_map,
        processed_at=datetime.utcnow(),
    )

    logger.info(
        "Anonymized doc_id=%s — %d PII entities replaced, role_map size=%d.",
        document.id[:8],
        len(role_map),
        len(role_map),
    )

    return anon_doc


def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())
