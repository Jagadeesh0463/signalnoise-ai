"""
src/signals/detector.py

Hybrid Signal Detector — sentence-level contextual scanning + BERTopic discovery.

Primary engine: Contextual Scanner
    Analyses each document sentence-by-sentence for seven risk categories.
    Cross-document corroboration: STRONG if 4+ documents, WEAK if 2–3.
    Evidence is the actual matching sentences — every signal is evidence-backed
    from creation, with no dependency on a separate validation pass.

Secondary engine: BERTopic
    Runs on all documents to catch novel or emergent risk patterns not covered
    by the contextual pattern set. Fills any risk categories that the contextual
    scanner did not detect. Falls back gracefully if the corpus is too small.

Corroboration rules:
    STRONG  — risk pattern found in >= 4 distinct documents
    WEAK    — risk pattern found in 2–3 distinct documents
    NOISE   — risk pattern found in only 1 document (not promoted)

Design rules:
    - Input is always anonymized text — no PII reaches this module
    - A signal is only created if it has evidence (matching sentences)
    - Contextual signals take priority over BERTopic for the same category
    - NOISE signals from BERTopic are logged but never passed downstream

Usage:
    from src.signals.detector import detect_signals
    signals = detect_signals(documents, embeddings, metadatas)
"""

import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime

import numpy as np
from bertopic import BERTopic
from sklearn.feature_extraction.text import CountVectorizer

from src.config import config
from src.exceptions import DetectionError
from src.models import Signal

logger = logging.getLogger(__name__)

# ── Role-code cleanup (BERTopic only) ─────────────────────────────────────────
# Presidio replaces PII with codes like [Person-A], [Date-B], [Location-C].
# Strip them before BERTopic so they don't pollute topic keywords.
# The contextual scanner intentionally keeps them — they do not interfere with
# the regex patterns which target contextual phrases, not proper nouns.

_ROLE_CODE_RE = re.compile(r'\[[A-Za-z]+-[A-Z0-9]+\]')


def _clean_for_topic_model(text: str) -> str:
    return _ROLE_CODE_RE.sub(' ', text)


# ── Sentence splitter ─────────────────────────────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    """
    Split meeting-note text into candidate sentences for pattern matching.

    Meeting notes mix two structures:
        1. Multi-sentence paragraphs: "Priya noted X. Ravi raised Y."
        2. Bullet-point lines:        "- Risk: single point of failure on Dev."

    We handle both by splitting on newlines first, then on sentence boundaries.
    Fragments shorter than 15 characters are discarded.
    """
    sentences: list[str] = []
    for line in text.split('\n'):
        # Strip leading bullet markers and whitespace
        line = line.strip().lstrip('-*•').strip()
        if len(line) < 15:
            continue
        # Split on sentence-ending punctuation followed by whitespace
        parts = re.split(r'(?<=[.!?])\s+', line)
        for part in parts:
            part = part.strip()
            if len(part) >= 15:
                sentences.append(part)
    return sentences


# ── Contextual sentence-level patterns ───────────────────────────────────────
# Each entry maps a risk category to a list of regex patterns.
# A sentence that matches ANY pattern in a category's list constitutes one
# piece of evidence for that category in that document.
#
# Patterns are written to match anonymized text — role codes like [Person-A]
# are already stripped from the matched text by the time it reaches these regexes,
# because the patterns focus on contextual phrases, not named entities.

_SENTENCE_PATTERNS: dict[str, list[str]] = {

    # ── Team Health / Burnout ─────────────────────────────────────────────────
    "team_health": [
        r"burnout|burn.?out|burned\s+out|burnt\s+out",
        r"working\s+(weekends?|evenings?|overtime|nights?|long\s+hours)",
        r"(overwhelmed|overloaded|exhausted|stretched\s+thin)",
        r"morale\s+(is\s+)?(low|dropping|poor|suffering|concern)",
        r"(capacity|allocation|bandwidth)\s+(issue|concern|over|stretched|at\s+1[0-9][0-9]%)",
        r"at\s+(1[0-9][0-9]|[0-9]{3})\s*%\s+(allocation|capacity)",
        r"team\s+(is\s+)?(under\s+pressure|struggling|frustrated|demoralised|demoralized|visibly\s+tired)",
        r"overtime\s+(for\s+)?\d+\s+(consecutive\s+)?(days?|weeks?|months?)",
        r"(signs\s+of|showing)\s+(burnout|fatigue|exhaustion)",
        r"team\s+needs\s+support",
        r"(overall\s+mood|team\s+sentiment)\s*:\s*(low|poor|negative|amber|bad)",
        r"no\s+(slack|buffer)\s+(in\s+the\s+team|available|left)",
        r"(support\s+(agents?|staff|team))\s+(working|on)\s+overtime",
        r"(demoralised|demoralized|disengaged|frustrated)\s+(from|by|about)",
    ],

    # ── Delivery Risk ─────────────────────────────────────────────────────────
    "delivery_risk": [
        r"(deadline|milestone)\s+(at\s+risk|missed|slipped?|pushed|delayed|behind)",
        r"(sprint|velocity)\s+(missed|behind|declined?|drop(ped)?|below|target|not\s+hit)",
        r"(not\s+on\s+track|behind\s+schedule|running\s+(late|behind))",
        r"carry[\s-]?forward|carryover|rolled?\s+over",
        r"(slipped?|pushed?\s+back|deferred?)\s+\d+\s+weeks?",
        r"(at\s+risk\s+of\s+missing|risk\s+of\s+delay)",
        r"commitment[s]?\s+(at\s+risk|missed|broken|slipping)",
        r"below\s+\d+%\s+(velocity|capacity|completion)",
        r"(third|second|fourth|consecutive)\s+(sprint|week)\s+(in\s+a\s+row|below|miss)",
        r"Q[0-9]\s+(milestone|launch|target|delivery)\s+(at\s+risk|slipping|miss)",
        r"(overall\s+status|programme\s+status)\s*:\s*(amber|red|at\s+risk)",
        r"(launch|release|delivery)\s+(date\s+)?(slips?|pushed|delayed|at\s+risk)",
        r"sprint\s+\d+\s+(carry|carry-forward|incomplete|unfinished)",
        r"carrying\s+forward\s+\d+\s+(stories|items|tickets)",
        r"velocity[:\s]+\d+\s+(points?\s+delivered\s+vs\s+\d+\s+committed|below|target)",
    ],

    # ── Attrition / Retention ─────────────────────────────────────────────────
    "attrition": [
        r"(leaving|resigned|quit|quitting|stepping\s+down|moving\s+on)",
        r"(looking\s+for|exploring|interviewing|considering)\s+(other|new|another|external|outside)\s+(opportunities?|role|job|position)",
        r"(retention|turnover)\s+(risk|concern|issue|rate)",
        r"(backfill|replacement|hire\s+to\s+replace|headcount\s+gap)",
        r"(transfer|transferring)\s+(to\s+)?(another|other|different)\s+team",
        r"(requested?|considering|explored?)\s+(a\s+)?transfer",
        r"may\s+consider\s+leaving|considering\s+leaving",
        r"looking\s+(elsewhere|externally|at\s+external\s+opportunities)",
        r"(attrition\s+risk|resignation\s+risk|departure\s+risk)",
        r"(reduced\s+hours|part.time\s+request|request\s+(for\s+)?reduced)",
        r"(started|actively)\s+looking\s+(at\s+)?(external|other)\s+(opportunities|roles?|options)",
        r"(two|2|three|3|multiple)\s+(members?|engineers?|team\s+members?)\s+(may|might|could)\s+(consider\s+)?leaving",
        r"(one|two|three|a)\s+(senior\s+)?(developer|engineer|member)\s+.{0,30}(transfer|leaving|resignation)",
        r"attrition\s+(risk|signal)\s*[:(]?\s*(high|critical|medium)",
    ],

    # ── Bus Factor / Knowledge Concentration ──────────────────────────────────
    "bus_factor": [
        r"(only|sole|single)\s+(person|engineer|developer|one|resource)\s+(who\s+)?(knows?|understands?|owns?|has\s+knowledge|can\s+support)",
        r"(knowledge\s+silo|knowledge\s+concentration|single\s+point\s+of\s+failure)",
        r"(undocumented|not\s+documented|lacks?\s+documentation|poorly\s+documented)",
        r"(bus\s+factor)\s+(is\s+)?(1|one|critical|high|risk)",
        r"if\s+(he|she|they|.{0,20})\s+(leaves?|left|is\s+gone|quits?|departs?|is\s+(sick|unavailable))",
        r"(no\s+(one|body|backup)\s+else|nobody\s+else)\s+(who|that|knows?|can|understands?)",
        r"(critical|institutional)\s+knowledge\s+(concentrated|held\s+by|only\s+with|at\s+risk)",
        r"serious\s+trouble\s+if",
        r"(only\s+\w+\s+who|sole\s+person)\s+(understands?|knows?|can)",
        r"knowledge\s+transfer\s+(session|needed|required|not\s+prioritised|pending)",
        r"(three|3|four|4|five|5)\s+sprints?\s+(now|in\s+a\s+row).{0,50}(only|sole)\s+(person|one)",
    ],

    # ── Dependency Blockers ───────────────────────────────────────────────────
    "dependency": [
        r"(blocked|blocking)\s+(by|on|waiting\s+for|due\s+to)",
        r"(api|service|system|platform|endpoint)\s+(is\s+)?(down|unavailable|not\s+responding|failing|broken|overdue|delayed)",
        r"(waiting\s+for|pending|waiting\s+on)\s+(api|vendor|team|external|approval|integration|response|documentation)",
        r"(vendor|supplier|third.party)\s+(delay|issue|not\s+responding|unresponsive|escalat)",
        r"(dependency|integration|blocker)\s+(unresolved|pending|outstanding|blocked|at\s+risk|flag)",
        r"(no\s+response|unanswered|unresolved)\s+(from|by)\s+(vendor|team|external|account\s+manager)",
        r"escalat(ed|ion)\s+(on|for|to).{0,40}(vendor|api|dependency|blocker)",
        r"\d+\s+weeks?\s+(unresolved|overdue|delayed|without\s+response|without\s+a\s+fix|blocked)",
        r"(hard|critical|blocking)\s+dependency\s+(for|on|is)",
        r"(api\s+contract|data\s+processing\s+agreement|legal\s+approval|api\s+documentation)\s+(not\s+arrived|pending|delayed|overdue|incomplete)",
        r"cannot\s+(complete|proceed|deliver|launch)\s+without\s+(the\s+)?(api|vendor|approval|integration|response)",
        r"(auth|authentication|student\s+records?|payment|lms|assessment)\s+(api|service|system).{0,30}(blocked|blocker|delayed|unresolved|waiting)",
        r"(has\s+)?(been\s+)?blocked\s+(on\s+this\s+for|for)\s+\d+\s+(working\s+)?(days?|weeks?)",
    ],

    # ── Technical Debt / Engineering Quality ──────────────────────────────────
    "technical_debt": [
        r"(test\s+coverage|code\s+coverage)\s+(gap|low|insufficient|poor|missing|below\s+\d+%|at\s+\d+%)",
        r"(technical\s+debt|tech\s+debt)",
        r"(legacy\s+(code|system|architecture|format|data))",
        r"(bugs?|defects?)\s+(in\s+)?(production|escaping|slipping\s+through|missed|to\s+production)",
        r"(qa|testing|test)\s+(capacity|bottleneck|backlog|gap|bandwidth|squeezed|not\s+enough)",
        r"(flaky|unstable|broken)\s+tests?",
        r"shipping\s+(stories?|features?|work)\s+without\s+tests?",
        r"(building|accumulating|building\s+up)\s+technical\s+debt",
        r"(no\s+staging|testing\s+in\s+production|directly\s+in\s+production|all\s+testing.{0,20}production)",
        r"rework.{0,30}(mid.sprint|requirements\s+changed|scope\s+changed)",
        r"bugs?\s+slip(ping)?\s+(to|through\s+to|into)\s+production",
        r"(automated\s+test\s+coverage|test\s+suite)\s+(below|at|missing|lacking|none|under)\s+\d+%",
        r"coverage\s+(is\s+)?below\s+\d+%",
        r"(edge\s+cases?|regressions?)\s+(every\s+week|discovered|found\s+in\s+production)",
    ],

    # ── Operational / Production Stability ────────────────────────────────────
    "operational": [
        r"(production\s+(incident|outage|failure|issue|bug|down))",
        r"(deployment|pipeline|deploy)\s+(failed|broken|down|issue|problem|incident|broke)",
        r"(data\s+(sync|pipeline|feed|batch)\s+(job)?)\s+(failed|broken|down|silent|issue|stale|not\s+run)",
        r"(rollback|hotfix|emergency\s+fix|emergency\s+deploy)",
        r"(monitoring|alerting|observability|alerts?)\s+(not|broken|missing|gaps?|suppressed|disabled|never\s+re.enabled)",
        r"(system|service|platform|lms)\s+(unstable|down|degraded|unavailable|outage|full\s+outage)",
        r"(went\s+undetected|silent\s+failure|unmonitored|no\s+alert|undetected\s+for)",
        r"(learners?|users?|customers?)\s+(affected|impacted|unable\s+to\s+access|cannot\s+access)",
        r"\d+\s+(hours?|days?)\s+(outage|down|undetected|unresolved|offline|of\s+downtime)",
        r"(suppressed|disabled|not\s+re.enabled)\s+(monitoring|alerts?|alarm)",
        r"SLA\s+(breach|missed|target\s+not\s+met|target\s*:)",
        r"(unannounced|bypassed|without\s+(approval|a\s+rollback|change\s+management))\s+(change|migration|deploy|schema)",
        r"(staging\s+environment|test\s+environment)\s+(down|unavailable|lacks?|no\s+proper|does\s+not\s+exist)",
        r"(third|3rd|fourth|4th|fifth|5th)\s+(deployment|incident|outage)\s+(in|this)",
        r"(nightly\s+batch|batch\s+job)\s+(failed|down|silent|stale|not\s+run)",
    ],
}

# ── Classification thresholds ─────────────────────────────────────────────────

STRONG_MIN_DOCS = 4
WEAK_MIN_DOCS = 2

# ── Category metadata ─────────────────────────────────────────────────────────

_CATEGORY_TITLES: dict[str, str] = {
    "team_health":    "Team Burnout and Capacity Risk",
    "delivery_risk":  "Delivery Milestone Risk — Repeated Velocity Decline",
    "attrition":      "Staff Attrition Risk — Multiple Engineers",
    "bus_factor":     "Knowledge Concentration Risk — Single Points of Failure",
    "dependency":     "External Dependency Blockers — Multiple Unresolved",
    "technical_debt": "Engineering Quality Risk — Test Coverage and Production Bugs",
    "operational":    "Production Stability Risk — Incidents and Monitoring Gaps",
}

_CATEGORY_OWNERS: dict[str, str] = {
    "delivery_risk":  "Program-Manager",
    "team_health":    "Engineering-Manager",
    "attrition":      "HR-Business-Partner",
    "bus_factor":     "Engineering-Manager",
    "technical_debt": "Engineering-Lead",
    "operational":    "SRE-Lead",
    "dependency":     "Platform-Lead",
}

# ── Public API ────────────────────────────────────────────────────────────────


def detect_signals(
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> list[Signal]:
    """
    Detect organizational risk signals using a hybrid two-engine approach.

    Engine 1 (primary): Contextual sentence-level scanner.
        Analyses every sentence in every document against 7 risk category
        pattern sets. Corroborates findings across documents: a category must
        appear in >= 2 documents to produce a signal. Evidence is the matching
        sentences themselves — so every signal produced here has evidence.

    Engine 2 (secondary): BERTopic unsupervised clustering.
        Runs after the contextual scan and fills any categories not yet detected.
        Falls back gracefully if BERTopic fails on a small corpus.

    Args:
        documents:  List of anonymized text strings (from ChromaDB).
        embeddings: Corresponding 384-dim vectors.
        metadatas:  Metadata dicts from ChromaDB (contains document_id).

    Returns:
        List of Signal objects. Includes NOISE signals (severity="NOISE") so
        they can be logged — filter with signal.is_actionable() downstream.

    Raises:
        DetectionError: If both engines fail or document count is too low.
    """
    if len(documents) < config.MIN_DOCS_FOR_BERTOPIC:
        raise DetectionError(
            f"Only {len(documents)} documents available. "
            f"Minimum required: {config.MIN_DOCS_FOR_BERTOPIC}. "
            "Upload more documents and try again."
        )

    logger.info("Starting hybrid detection on %d documents.", len(documents))

    # ── Engine 1: contextual scanner ─────────────────────────────────────────
    contextual_signals = _contextual_detect(documents, metadatas)
    detected_categories = {s.category for s in contextual_signals if s.severity != "NOISE"}

    logger.info(
        "Contextual scanner: %d actionable signals — categories: %s",
        len([s for s in contextual_signals if s.severity != "NOISE"]),
        sorted(detected_categories),
    )

    # ── Engine 2: BERTopic (fills gaps) ──────────────────────────────────────
    bertopic_signals: list[Signal] = []
    try:
        bertopic_signals = _bertopic_detect(documents, embeddings, metadatas)
    except Exception as exc:
        logger.warning("BERTopic engine skipped: %s", exc)

    # Merge: contextual takes priority; BERTopic fills uncovered categories
    gap_signals = [
        s for s in bertopic_signals
        if s.severity != "NOISE" and s.category not in detected_categories
    ]
    if gap_signals:
        logger.info(
            "BERTopic filled %d gap category/categories: %s",
            len(gap_signals),
            [s.category for s in gap_signals],
        )

    all_signals = contextual_signals + gap_signals

    actionable = [s for s in all_signals if s.severity != "NOISE"]
    logger.info(
        "Detection complete — %d total signals, %d actionable.",
        len(all_signals),
        len(actionable),
    )

    return all_signals


# ── Engine 1: Contextual scanner ──────────────────────────────────────────────

def _contextual_detect(
    documents: list[str],
    metadatas: list[dict],
) -> list[Signal]:
    """
    Sentence-level contextual risk scanner.

    For each document:
        1. Split into sentences.
        2. Match each sentence against all 7 category pattern sets.
        3. Record matching sentences as evidence for that category + document.

    After scanning all documents:
        4. Group findings by category.
        5. Count distinct source documents per category.
        6. Create one Signal per category that meets the corroboration threshold.

    Returns:
        List of Signal objects with evidence embedded. NOISE results (only 1
        document matched) are excluded — we only return WEAK and STRONG signals.
    """
    # findings[category] = list of {doc_id, evidence: [sentences]}
    findings: dict[str, list[dict]] = defaultdict(list)

    for doc_idx, doc_text in enumerate(documents):
        doc_id = (
            metadatas[doc_idx].get("document_id", f"doc-{doc_idx}")
            if doc_idx < len(metadatas) else f"doc-{doc_idx}"
        )
        sentences = _split_sentences(doc_text)

        # Per-document: collect matching sentences per category
        doc_hits: dict[str, list[str]] = defaultdict(list)

        for sentence in sentences:
            sent_lower = sentence.lower()
            for category, patterns in _SENTENCE_PATTERNS.items():
                # Stop at 4 snippets per category per document — enough for evidence
                if len(doc_hits[category]) >= 4:
                    continue
                for pattern in patterns:
                    if re.search(pattern, sent_lower):
                        doc_hits[category].append(sentence.strip())
                        break  # one match per sentence is sufficient

        for category, matched_sentences in doc_hits.items():
            if matched_sentences:
                findings[category].append({
                    "doc_id": doc_id,
                    "evidence": matched_sentences[:3],  # cap per-doc snippets
                })

        if doc_hits:
            logger.debug(
                "Doc %s: matched categories %s",
                doc_id[:8],
                sorted(doc_hits.keys()),
            )

    # Build one signal per category where enough documents corroborate
    signals: list[Signal] = []

    for category, doc_findings in findings.items():
        unique_doc_ids = list({f["doc_id"] for f in doc_findings})
        doc_count = len(unique_doc_ids)

        if doc_count < WEAK_MIN_DOCS:
            logger.info(
                "Contextual: '%s' found in only %d document — below threshold, skipped.",
                category, doc_count,
            )
            continue

        severity = "STRONG" if doc_count >= STRONG_MIN_DOCS else "WEAK"
        confidence_band = (
            "high"   if doc_count >= 6 else
            "medium" if severity == "STRONG" else
            "low"
        )

        # Collect and deduplicate evidence across all documents
        all_evidence: list[str] = []
        seen_keys: set[str] = set()
        for f in doc_findings:
            for snippet in f["evidence"]:
                key = snippet.strip().lower()[:60]
                if key not in seen_keys and len(snippet.strip()) >= 20:
                    seen_keys.add(key)
                    all_evidence.append(snippet.strip())

        if not all_evidence:
            logger.info("Contextual: '%s' has no valid evidence snippets — skipped.", category)
            continue

        title = _CATEGORY_TITLES.get(category, "Organizational Risk Signal")

        signal = Signal(
            id=str(uuid.uuid4()),
            title=title,
            category=category,
            severity=severity,
            confidence_band=confidence_band,
            trend="emerging",
            evidence=all_evidence[:8],              # cap at 8 snippets
            source_document_ids=unique_doc_ids,
            suggested_owner_role=_CATEGORY_OWNERS.get(category, "Program-Manager"),
            related_teams=[],
            related_projects=[],
            status="active",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        signals.append(signal)

        logger.info(
            "Contextual: '%s' [%s] — %d documents, %d evidence snippets",
            title, severity, doc_count, len(all_evidence),
        )

    return signals


# ── Engine 2: BERTopic (gap-fill) ─────────────────────────────────────────────

def _bertopic_detect(
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> list[Signal]:
    """
    BERTopic unsupervised clustering — used to fill risk categories not
    covered by the contextual scanner.

    Raises DetectionError if clustering fails, which the caller handles
    by logging a warning and continuing without BERTopic signals.
    """
    clean_docs = [_clean_for_topic_model(doc) for doc in documents]
    embeddings_array = np.array(embeddings)

    try:
        vectorizer = CountVectorizer(
            stop_words="english",
            min_df=1,
            ngram_range=(1, 2),
        )
        topic_model = BERTopic(
            vectorizer_model=vectorizer,
            min_topic_size=config.MIN_TOPIC_SIZE,
            nr_topics=None,
            calculate_probabilities=False,
            verbose=False,
        )
        topics, probs = topic_model.fit_transform(clean_docs, embeddings_array)
        topic_info = topic_model.get_topic_info()
        logger.info("BERTopic: %d topics (including noise topic -1).", len(topic_info))
    except Exception as exc:
        raise DetectionError(f"BERTopic clustering failed: {exc}") from exc

    # Group documents by topic
    topic_docs: dict[int, list[dict]] = {}
    for idx, topic_id in enumerate(topics):
        topic_id = int(topic_id)
        if topic_id not in topic_docs:
            topic_docs[topic_id] = []
        prob_val = 0.0
        if probs is not None:
            try:
                p = probs[idx]
                prob_val = float(p) if np.ndim(p) == 0 else float(np.max(p))
            except Exception:
                prob_val = 0.0
        topic_docs[topic_id].append({
            "text": documents[idx],
            "metadata": metadatas[idx] if idx < len(metadatas) else {},
            "prob": prob_val,
        })

    signals: list[Signal] = []
    for topic_id, doc_group in topic_docs.items():
        signal = _build_bertopic_signal(topic_id, doc_group, topic_model)
        signals.append(signal)

    return signals


def _build_bertopic_signal(
    topic_id: int,
    doc_group: list[dict],
    topic_model: BERTopic,
) -> Signal:
    """Build a Signal from one BERTopic topic."""
    doc_count = len(doc_group)

    top_words: list[str] = []
    if topic_id != -1:
        try:
            topic_words = topic_model.get_topic(topic_id)
            top_words = [word for word, _ in topic_words[:10]] if topic_words else []
        except Exception:
            top_words = []

    severity = _classify_severity(topic_id, doc_count, top_words)
    confidence_band = "high" if doc_count >= 6 else ("medium" if severity == "STRONG" else "low")
    category = _infer_category(top_words)
    title = _CATEGORY_TITLES.get(category, "Organizational Risk Signal")

    # Evidence: top-probability document snippets
    sorted_docs = sorted(doc_group, key=lambda d: d["prob"], reverse=True)
    evidence = [d["text"][:200].strip() for d in sorted_docs[:3]]

    source_doc_ids = [d["metadata"].get("document_id", "unknown") for d in doc_group]

    logger.info(
        "BERTopic topic %d → '%s' [%s] — %d documents, top words: %s",
        topic_id, title, severity, doc_count, top_words[:5],
    )

    return Signal(
        id=str(uuid.uuid4()),
        title=title,
        category=category,
        severity=severity,
        confidence_band=confidence_band,
        trend="emerging",
        evidence=evidence,
        source_document_ids=source_doc_ids,
        suggested_owner_role=_CATEGORY_OWNERS.get(category, "Program-Manager"),
        related_teams=[],
        related_projects=[],
        status="active",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


# ── BERTopic helpers ──────────────────────────────────────────────────────────

def _classify_severity(topic_id: int, doc_count: int, top_words: list[str]) -> str:
    if topic_id == -1 or doc_count < WEAK_MIN_DOCS:
        return "NOISE"
    words_lower = {w.lower() for w in top_words}
    risk_hits = words_lower & _BERTOPIC_RISK_KEYWORDS
    if doc_count >= STRONG_MIN_DOCS and len(risk_hits) >= 2:
        return "STRONG"
    return "WEAK"


def _infer_category(top_words: list[str]) -> str:
    words = {w.lower() for w in top_words}
    if words & {"transfer", "resignation", "leaving", "quit", "backfill", "retention"}:
        return "attrition"
    if words & {"sole", "single", "undocumented", "silo", "understands", "bus"}:
        return "bus_factor"
    if words & {"debt", "coverage", "qa", "quality", "rework", "legacy", "flaky"}:
        return "technical_debt"
    if words & {"burnout", "overtime", "weekend", "exhausted", "morale", "overloaded"}:
        return "team_health"
    if words & {"incident", "outage", "failure", "alert", "rollback", "degraded"}:
        return "operational"
    if words & {"blocked", "blocking", "dependency", "vendor", "api", "waiting"}:
        return "dependency"
    return "delivery_risk"


_BERTOPIC_RISK_KEYWORDS = {
    "delayed", "blocked", "overdue", "slipped", "missed", "critical",
    "escalation", "blocker", "dependency", "deadline", "burnout", "attrition",
    "leaving", "morale", "exhausted", "overloaded", "sole", "single", "debt",
    "coverage", "qa", "incident", "outage", "failure", "waiting", "unresolved",
}
