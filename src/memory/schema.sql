-- SignalNoise AI — SQLite Schema
-- Initialized automatically by src/memory/store.py on first run.
-- Never run this file manually.

-- ── Documents ─────────────────────────────────────────────────────────────────
-- Tracks every uploaded file. Raw text is never stored here.
-- After anonymization, the 'deleted' flag is set to 1.

CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    source_type TEXT NOT NULL,       -- meeting_note | incident_log | ticket | status_report
    word_count  INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL,       -- ISO 8601 datetime
    processed   INTEGER DEFAULT 0,   -- 0 = pending, 1 = complete
    deleted     INTEGER DEFAULT 0    -- 1 = raw text has been deleted (privacy)
);

-- ── Signals ───────────────────────────────────────────────────────────────────
-- One row per detected signal cluster from BERTopic.

CREATE TABLE IF NOT EXISTS signals (
    id                   TEXT PRIMARY KEY,
    title                TEXT NOT NULL,
    category             TEXT NOT NULL,   -- delivery_risk | team_health | operational | dependency
    severity             TEXT NOT NULL,   -- NOISE | WEAK | STRONG
    confidence_band      TEXT NOT NULL,   -- low | medium | high
    trend                TEXT NOT NULL,   -- emerging | stable | fading
    suggested_owner_role TEXT,
    status               TEXT DEFAULT 'active',  -- active | confirmed | dismissed
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

-- ── Signal History ────────────────────────────────────────────────────────────
-- Snapshot of each signal over time — this is the organisational memory.
-- Every time signals are re-run, a new snapshot is written.
-- This is what enables "this signal has been growing for 3 weeks."

CREATE TABLE IF NOT EXISTS signal_history (
    id              TEXT PRIMARY KEY,
    signal_id       TEXT NOT NULL,
    severity        TEXT NOT NULL,
    confidence_band TEXT NOT NULL,
    trend           TEXT NOT NULL,
    snapshot_at     TEXT NOT NULL,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

-- ── Evidence ──────────────────────────────────────────────────────────────────
-- Anonymized text snippets that support each signal.
-- source_count >= 2 is required for a signal to reach STRONG.

CREATE TABLE IF NOT EXISTS evidence (
    id               TEXT PRIMARY KEY,
    signal_id        TEXT NOT NULL,
    document_id      TEXT NOT NULL,
    snippet          TEXT NOT NULL,    -- anonymized text fragment shown on signal card
    relevance_score  REAL NOT NULL,    -- 0.0–1.0, internal only
    source_count     INTEGER DEFAULT 1,
    FOREIGN KEY (signal_id)   REFERENCES signals(id),
    FOREIGN KEY (document_id) REFERENCES documents(id)
);

-- ── Feedback ──────────────────────────────────────────────────────────────────
-- Human confirm / dismiss decisions — closes the learning loop.

CREATE TABLE IF NOT EXISTS feedback (
    id            TEXT PRIMARY KEY,
    signal_id     TEXT NOT NULL,
    reviewer_role TEXT NOT NULL,       -- Programme-Manager | Director | SRE-Lead
    decision      TEXT NOT NULL,       -- confirmed | dismissed
    comment       TEXT,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

-- ── Audit Logs ────────────────────────────────────────────────────────────────
-- Every system action logged for privacy compliance and debugging.
-- Never log raw text or PII here — only IDs and action names.

CREATE TABLE IF NOT EXISTS audit_logs (
    id          TEXT PRIMARY KEY,
    action      TEXT NOT NULL,         -- document_uploaded | signal_detected | pii_removed | feedback_given
    entity_type TEXT NOT NULL,         -- document | signal | feedback
    entity_id   TEXT NOT NULL,
    detail      TEXT,                  -- JSON string for extra context
    created_at  TEXT NOT NULL
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
-- Speed up the most common queries.

CREATE INDEX IF NOT EXISTS idx_signals_status
    ON signals(status);

CREATE INDEX IF NOT EXISTS idx_signals_severity
    ON signals(severity);

CREATE INDEX IF NOT EXISTS idx_signal_history_signal_id
    ON signal_history(signal_id);

CREATE INDEX IF NOT EXISTS idx_evidence_signal_id
    ON evidence(signal_id);

CREATE INDEX IF NOT EXISTS idx_feedback_signal_id
    ON feedback(signal_id);

CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_id
    ON audit_logs(entity_id);
