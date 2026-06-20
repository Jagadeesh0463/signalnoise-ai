"""
src/models.py

Shared data models for SignalNoise AI.
Every module imports from here — never define models inside individual modules.

These are plain Python dataclasses — no external dependency required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import uuid4


def _new_id() -> str:
    """Generate a new unique ID."""
    return str(uuid4())


# ── Stage 1: Ingestion ────────────────────────────────────────────────────────

@dataclass
class Document:
    """
    Represents a file uploaded by the user before any processing.

    raw_text is deleted (set to "") after anonymization completes.
    Never pass a Document with raw_text populated to any model or API.
    """
    filename: str
    source_type: str        # meeting_note | incident_log | ticket | status_report
    raw_text: str           # DELETED after anonymizer runs — never log this field
    word_count: int
    uploaded_at: datetime = field(default_factory=datetime.utcnow)
    processed: bool = False
    id: str = field(default_factory=_new_id)

    def clear_raw_text(self) -> None:
        """Delete raw text after anonymization. Call this — do not access raw_text after."""
        self.raw_text = ""
        self.processed = True


# ── Stage 2: Privacy ──────────────────────────────────────────────────────────

@dataclass
class AnonymizedDocument:
    """
    Output of the Privacy Shield.
    PII has been removed. Role codes replace real names.
    Safe to pass to embeddings, BERTopic, and Groq.
    """
    document_id: str                    # links back to Document.id
    anonymized_text: str                # PII replaced: "John" → "[Backend-Lead-A]"
    role_map: dict[str, str]            # {"John Smith": "Backend-Lead-A"}
    processed_at: datetime = field(default_factory=datetime.utcnow)
    id: str = field(default_factory=_new_id)


# ── Stage 3: Signal Detection ─────────────────────────────────────────────────

@dataclass
class Signal:
    """
    A detected pattern in organisational communications.

    severity:         NOISE | WEAK | STRONG
    confidence_band:  low | medium | high  (never a raw float — PRD §8)
    trend:            emerging | stable | fading  (from signal_history table)
    status:           active | confirmed | dismissed  (driven by human feedback)
    """
    title: str                          # "Repeated deployment failures in Backend team"
    category: str                       # delivery_risk | team_health | operational | dependency
    severity: str                       # NOISE | WEAK | STRONG
    confidence_band: str                # low | medium | high
    trend: str                          # emerging | stable | fading
    evidence: list[str]                 # anonymized text snippets — min 2 for STRONG
    source_document_ids: list[str]      # which documents this came from
    suggested_owner_role: str           # "Programme-Manager" — role code, never a name
    related_teams: list[str]            # ["Backend-Team", "Platform-Team"]
    related_projects: list[str]
    status: str = "active"             # active | confirmed | dismissed
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    id: str = field(default_factory=_new_id)

    def is_actionable(self) -> bool:
        """Only WEAK and STRONG signals are shown to users. NOISE is dropped."""
        return self.severity in ("WEAK", "STRONG")


# ── Stage 4: Evidence ─────────────────────────────────────────────────────────

@dataclass
class Evidence:
    """
    A specific piece of text that supports a Signal.
    Multiple Evidence objects corroborate a single Signal.
    source_count >= 2 is required for a signal to reach STRONG severity.
    """
    signal_id: str
    document_id: str
    snippet: str                        # anonymized text fragment shown on signal card
    relevance_score: float              # 0.0–1.0, internal only — never shown to users
    source_count: int = 1              # how many documents contain this evidence
    id: str = field(default_factory=_new_id)


# ── Stage 5: Risk ─────────────────────────────────────────────────────────────

@dataclass
class Risk:
    """
    Business consequence derived from a validated Signal.
    This is what the Programme Manager acts on.

    narration is populated last — by Groq. Everything else is structured data.
    """
    signal_id: str
    business_impact: str                # "Q3 delivery milestone at risk"
    confidence_band: str                # low | medium | high — inherited from Signal
    priority: str                       # critical | high | medium | low
    suggested_owner_role: str           # role code of who should act
    suggested_action: str              # "Schedule sync between Backend-Lead-A and Platform-Lead-B"
    root_cause_hypothesis: str         # "Resource constraint + dependency bottleneck"
    supporting_document_ids: list[str]
    narration: str = ""                # Groq-generated executive summary — populated last
    created_at: datetime = field(default_factory=datetime.utcnow)
    id: str = field(default_factory=_new_id)


# ── Stage 6: Human Feedback ───────────────────────────────────────────────────

@dataclass
class Feedback:
    """
    Human confirm / dismiss decision on a Signal.
    Stored in SQLite. Drives the learning loop.

    decision: confirmed | dismissed
    """
    signal_id: str
    reviewer_role: str                  # "Programme-Manager" | "Director" | "SRE-Lead"
    decision: str                       # confirmed | dismissed
    comment: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    id: str = field(default_factory=_new_id)
