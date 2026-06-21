"""
src/memory/store.py

Organizational Memory Store — all SQLite read/write operations.
Initializes the database schema on first run automatically.

Pipeline position:
    Detector → Store (save signals)
    Validator → Store (save evidence)
    Dashboard → Store (read signals, save feedback)

Design rules:
    - Never store raw text or PII — only anonymized content and IDs
    - Every write is logged to audit_logs
    - All timestamps are ISO 8601 UTC strings

Usage:
    from src.memory.store import MemoryStore
    store = MemoryStore()
    store.save_signal(signal)
    signals = store.get_active_signals()
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from src.config import config
from src.exceptions import MemoryStoreError
from src.models import Document, Evidence, Feedback, Signal

logger = logging.getLogger(__name__)

# Path to schema file — relative to this file's location
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class MemoryStore:
    """
    SQLite-backed store for all SignalNoise AI persistent data.
    One instance is shared across the application.

    Creates the database and all tables on first instantiation.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or config.SQLITE_DB_PATH
        self._init_db()

    # ── Initialisation ────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create database file and run schema if tables don't exist yet."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        if not SCHEMA_PATH.exists():
            raise MemoryStoreError(f"Schema file not found: {SCHEMA_PATH}")

        with self._connect() as conn:
            schema_sql = SCHEMA_PATH.read_text()
            conn.executescript(schema_sql)
            # ── Column migrations (safe to run on every startup) ──────────────
            # ALTER TABLE IF NOT EXISTS is not supported in SQLite < 3.37,
            # so we catch the error if the column already exists.
            for migration_sql, migration_name in [
                ("ALTER TABLE signals ADD COLUMN narration TEXT", "narration"),
                ("ALTER TABLE signals ADD COLUMN confidence_score INTEGER", "confidence_score"),
            ]:
                try:
                    conn.execute(migration_sql)
                    logger.info("Migration: added %s column to signals table.", migration_name)
                except Exception:
                    pass  # Column already exists — no action needed

        logger.info("MemoryStore initialized at: %s", self.db_path)

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection with foreign key enforcement enabled."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row       # access columns by name
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ── Documents ─────────────────────────────────────────────────────────────

    def save_document(self, document: Document) -> None:
        """Save document metadata. Never call this with raw_text populated."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO documents
                        (id, filename, source_type, word_count, uploaded_at, processed, deleted)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document.id,
                        document.filename,
                        document.source_type,
                        document.word_count,
                        document.uploaded_at.isoformat(),
                        int(document.processed),
                        1 if not document.raw_text else 0,
                    ),
                )
                self._audit(conn, "document_uploaded", "document", document.id)
            logger.info("Saved document: %s (%s)", document.id[:8], document.filename)
        except Exception as exc:
            raise MemoryStoreError(f"Failed to save document {document.id[:8]}: {exc}") from exc

    def get_document(self, document_id: str) -> dict | None:
        """Retrieve document metadata by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        return dict(row) if row else None

    def mark_document_processed(self, document_id: str) -> None:
        """Mark a document as fully processed and raw text deleted."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE documents SET processed = 1, deleted = 1 WHERE id = ?",
                (document_id,),
            )
            self._audit(conn, "pii_removed", "document", document_id)

    # ── Signals ───────────────────────────────────────────────────────────────

    def save_signal(
        self,
        signal: Signal,
        narration: str | None = None,
        confidence_score: int | None = None,
    ) -> None:
        """Save a detected signal. Also writes a signal_history snapshot.

        Args:
            signal:           The Signal object to persist.
            narration:        Optional Groq/LLM executive summary for this signal.
            confidence_score: Optional computed confidence percentage (50–97).
        """
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO signals
                        (id, title, category, severity, confidence_band, trend,
                         suggested_owner_role, status, narration, confidence_score,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal.id,
                        signal.title,
                        signal.category,
                        signal.severity,
                        signal.confidence_band,
                        signal.trend,
                        signal.suggested_owner_role,
                        signal.status,
                        narration,
                        confidence_score,
                        signal.created_at.isoformat(),
                        signal.updated_at.isoformat(),
                    ),
                )
                # Write history snapshot for trend tracking
                conn.execute(
                    """
                    INSERT INTO signal_history
                        (id, signal_id, severity, confidence_band, trend, snapshot_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        signal.id,
                        signal.severity,
                        signal.confidence_band,
                        signal.trend,
                        datetime.utcnow().isoformat(),
                    ),
                )
                self._audit(conn, "signal_detected", "signal", signal.id)

            logger.info(
                "Saved signal: %s [%s] '%s'",
                signal.id[:8],
                signal.severity,
                signal.title[:40],
            )
        except Exception as exc:
            raise MemoryStoreError(f"Failed to save signal {signal.id[:8]}: {exc}") from exc

    def get_active_signals(self) -> list[dict]:
        """Return all signals with status='active', newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM signals
                WHERE status = 'active'
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_signal(self, signal_id: str) -> dict | None:
        """Return a single signal by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM signals WHERE id = ?", (signal_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_signal_history(self, signal_id: str) -> list[dict]:
        """Return all history snapshots for a signal, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM signal_history
                WHERE signal_id = ?
                ORDER BY snapshot_at ASC
                """,
                (signal_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ── Evidence ──────────────────────────────────────────────────────────────

    def save_evidence(self, evidence: Evidence) -> None:
        """Save an evidence snippet supporting a signal."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO evidence
                        (id, signal_id, document_id, snippet, relevance_score, source_count)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evidence.id,
                        evidence.signal_id,
                        evidence.document_id,
                        evidence.snippet,
                        evidence.relevance_score,
                        evidence.source_count,
                    ),
                )
        except Exception as exc:
            raise MemoryStoreError(f"Failed to save evidence {evidence.id[:8]}: {exc}") from exc

    def get_evidence_for_signal(self, signal_id: str) -> list[dict]:
        """Return all evidence for a signal, highest relevance first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM evidence
                WHERE signal_id = ?
                ORDER BY relevance_score DESC, source_count DESC
                """,
                (signal_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_document_map(self) -> dict[str, str]:
        """Return {document_id: filename} for all documents.
        Used by the signal card renderer to label evidence by source file."""
        with self._connect() as conn:
            rows = conn.execute("SELECT id, filename FROM documents").fetchall()
        return {row["id"]: row["filename"] for row in rows}

    # ── Feedback ──────────────────────────────────────────────────────────────

    def save_feedback(self, feedback: Feedback) -> None:
        """Save a confirm/dismiss decision and update the signal status."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO feedback
                        (id, signal_id, reviewer_role, decision, comment, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        feedback.id,
                        feedback.signal_id,
                        feedback.reviewer_role,
                        feedback.decision,
                        feedback.comment,
                        feedback.created_at.isoformat(),
                    ),
                )
                # Update signal status to match the feedback decision
                conn.execute(
                    "UPDATE signals SET status = ?, updated_at = ? WHERE id = ?",
                    (
                        feedback.decision,   # "confirmed" or "dismissed"
                        datetime.utcnow().isoformat(),
                        feedback.signal_id,
                    ),
                )
                self._audit(conn, "feedback_given", "feedback", feedback.id,
                            {"signal_id": feedback.signal_id, "decision": feedback.decision})

            logger.info(
                "Feedback saved: signal=%s decision=%s by %s",
                feedback.signal_id[:8],
                feedback.decision,
                feedback.reviewer_role,
            )
        except Exception as exc:
            raise MemoryStoreError(f"Failed to save feedback: {exc}") from exc

    def get_feedback_for_signal(self, signal_id: str) -> list[dict]:
        """Return all feedback for a signal."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM feedback WHERE signal_id = ? ORDER BY created_at DESC",
                (signal_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ── Weekly Digest ─────────────────────────────────────────────────────────

    def get_top_signals_for_digest(self, limit: int = 3) -> list[dict]:
        """
        Return top signals for the weekly digest.
        Priority: STRONG first, then WEAK. Newest first within each group.
        Only active (not confirmed/dismissed) signals.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM signals
                WHERE status = 'active'
                  AND severity IN ('STRONG', 'WEAK')
                ORDER BY
                    CASE severity WHEN 'STRONG' THEN 0 ELSE 1 END,
                    created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ── Audit ─────────────────────────────────────────────────────────────────

    def _audit(
        self,
        conn: sqlite3.Connection,
        action: str,
        entity_type: str,
        entity_id: str,
        detail: dict | None = None,
    ) -> None:
        """Write an audit log entry. Called inside existing transactions."""
        conn.execute(
            """
            INSERT INTO audit_logs (id, action, entity_type, entity_id, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                action,
                entity_type,
                entity_id,
                json.dumps(detail) if detail else None,
                datetime.utcnow().isoformat(),
            ),
        )

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        """Return the most recent audit log entries."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
