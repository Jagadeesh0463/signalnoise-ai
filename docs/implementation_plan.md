# SignalNoise AI — Implementation Plan
**Version:** 2.0 | **Status:** Approved for Build  
**Author:** Bhagya Thallapalem | FLM Learning AI Training Program

---

## 1. Folder Structure (Final)

Two additions from the original plan: `src/models.py` and `src/config.py`.  
Every module imports from these two files. Without them, every module defines its own types and settings — which causes drift.

```
signalnoise-ai/
│
├── requirements.txt
├── .env                          ← API keys (never commit)
├── .env.example                  ← Safe template to commit
│
├── src/
│   ├── models.py                 ← NEW: all shared dataclasses (Document, Signal, Risk...)
│   ├── config.py                 ← NEW: all settings loaded from .env
│   │
│   ├── ingestion/
│   │   ├── quality_gate.py       ✅ BUILT
│   │   └── loader.py             ← extracts text from .txt / .docx / .pdf
│   │
│   ├── privacy/
│   │   └── anonymizer.py         ← Presidio PII removal + role mapping
│   │
│   ├── signals/
│   │   ├── embedder.py           ← MiniLM → ChromaDB
│   │   └── detector.py           ← BERTopic NOISE / WEAK / STRONG
│   │
│   ├── memory/
│   │   ├── store.py              ← SQLite read/write
│   │   └── schema.sql            ← table definitions (run once on init)
│   │
│   ├── graph/
│   │   └── knowledge_graph.py    ← NetworkX: roles, teams, signal links
│   │
│   ├── evidence/
│   │   └── validator.py          ← multi-source corroboration
│   │
│   ├── risk/
│   │   └── intelligence.py       ← builds Risk object from ValidatedSignal
│   │
│   └── narration/
│       └── narrator.py           ← Groq API, last step only
│
├── app/
│   └── streamlit_app.py          ← dashboard + upload + feedback UI
│
├── data/
│   ├── raw/                      ← uploaded files (deleted after processing)
│   ├── processed/                ← anonymized signal data only
│   └── sample/                   ← 20 synthetic test documents
│
├── tests/
│   ├── test_quality_gate.py      ✅ BUILT (23 tests)
│   ├── test_loader.py
│   ├── test_anonymizer.py
│   ├── test_embedder.py
│   ├── test_detector.py
│   ├── test_validator.py
│   ├── test_intelligence.py
│   └── test_narrator.py
│
└── docs/
    ├── implementation_plan.md    ← this file
    └── (existing 6 documents)
```

**What changed from ChatGPT's proposal:**
- Removed `config/` folder → single `src/config.py` (no folder needed)
- Removed `models/` folder → single `src/models.py` (all models fit in one file)
- Removed `utils/` folder → add only if shared utilities emerge during build
- Removed `database/` folder → `src/memory/` covers this with `store.py` + `schema.sql`
- Kept everything else as-is

---

## 2. Domain Models

All models live in `src/models.py`. Every other module imports from here.  
Using Python `dataclasses` — no external dependency, clean, fast.

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class Document:
    id: str                          # UUID generated at upload
    filename: str                    # original filename
    source_type: str                 # meeting_note | incident_log | ticket | status_report
    raw_text: str                    # DELETED after anonymization
    word_count: int
    uploaded_at: datetime
    processed: bool = False

@dataclass
class AnonymizedDocument:
    id: str
    document_id: str                 # links back to Document.id
    anonymized_text: str             # PII replaced with role codes
    role_map: dict                   # {"John Smith": "Backend-Lead-A"}
    processed_at: datetime

@dataclass
class Signal:
    id: str
    title: str                       # "Repeated deployment failures in Backend team"
    category: str                    # delivery_risk | team_health | operational | dependency
    severity: str                    # NOISE | WEAK | STRONG
    confidence_band: str             # low | medium | high  (NOT a number — see PRD)
    trend: str                       # emerging | stable | fading
    evidence: list[str]              # anonymized text snippets, min 2 for STRONG
    source_document_ids: list[str]   # which documents this came from
    suggested_owner_role: str        # "Programme-Manager" | "SRE-Lead" etc.
    related_teams: list[str]         # ["Backend-Team", "Platform-Team"]
    related_projects: list[str]
    status: str                      # active | confirmed | dismissed
    created_at: datetime
    updated_at: datetime

@dataclass
class Evidence:
    id: str
    signal_id: str
    document_id: str
    snippet: str                     # anonymized text fragment
    relevance_score: float           # 0.0–1.0, internal only, not shown to users
    source_count: int                # how many docs corroborate this evidence

@dataclass
class Risk:
    id: str
    signal_id: str
    business_impact: str             # "Delivery milestone at risk Q3"
    confidence_band: str             # low | medium | high
    priority: str                    # critical | high | medium | low
    suggested_owner_role: str
    suggested_action: str            # "Schedule 1:1 with Backend-Lead-A this week"
    root_cause_hypothesis: str       # "Resource constraint + dependency bottleneck"
    supporting_document_ids: list[str]
    narration: str                   # Groq-generated executive summary (last step)
    created_at: datetime

@dataclass
class Feedback:
    id: str
    signal_id: str
    reviewer_role: str               # "Programme-Manager" | "Director" | "SRE-Lead"
    decision: str                    # confirmed | dismissed
    comment: Optional[str]
    created_at: datetime
```

**Why these models and not others:**
- `Document` and `AnonymizedDocument` are separate because raw text is deleted after anonymization — they cannot be the same object
- `Signal` holds `confidence_band` as a string (low/medium/high), never a float — uncalibrated scores mislead users (PRD §8)
- `Evidence` is separate from `Signal` so evidence can be queried independently and updated as new documents arrive
- `Risk` is a downstream output of `Signal` — not the same thing. A signal is a pattern; a risk is a business consequence with an owner and action attached
- `Feedback` is the human loop — it closes the learning cycle

---

## 3. SQLite Database Schema

File: `src/memory/schema.sql`  
Initialized once by `src/memory/store.py` on first run.

```sql
-- Track every uploaded document (metadata only after processing)
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    source_type TEXT NOT NULL,
    word_count  INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL,
    processed   INTEGER DEFAULT 0,   -- 0=pending, 1=complete
    deleted     INTEGER DEFAULT 0    -- 1=raw text has been deleted
);

-- One row per detected signal
CREATE TABLE IF NOT EXISTS signals (
    id                   TEXT PRIMARY KEY,
    title                TEXT NOT NULL,
    category             TEXT NOT NULL,
    severity             TEXT NOT NULL,      -- NOISE | WEAK | STRONG
    confidence_band      TEXT NOT NULL,      -- low | medium | high
    trend                TEXT NOT NULL,      -- emerging | stable | fading
    suggested_owner_role TEXT,
    status               TEXT DEFAULT 'active',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

-- Organizational memory — snapshot of each signal over time
-- This is what enables "signal has been growing for 3 weeks"
CREATE TABLE IF NOT EXISTS signal_history (
    id              TEXT PRIMARY KEY,
    signal_id       TEXT NOT NULL,
    severity        TEXT NOT NULL,
    confidence_band TEXT NOT NULL,
    trend           TEXT NOT NULL,
    snapshot_at     TEXT NOT NULL,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

-- Which documents support which signals
CREATE TABLE IF NOT EXISTS evidence (
    id               TEXT PRIMARY KEY,
    signal_id        TEXT NOT NULL,
    document_id      TEXT NOT NULL,
    snippet          TEXT NOT NULL,      -- anonymized
    relevance_score  REAL NOT NULL,
    source_count     INTEGER DEFAULT 1,
    FOREIGN KEY (signal_id)   REFERENCES signals(id),
    FOREIGN KEY (document_id) REFERENCES documents(id)
);

-- Human feedback — confirm or dismiss each signal
CREATE TABLE IF NOT EXISTS feedback (
    id            TEXT PRIMARY KEY,
    signal_id     TEXT NOT NULL,
    reviewer_role TEXT NOT NULL,
    decision      TEXT NOT NULL,         -- confirmed | dismissed
    comment       TEXT,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

-- Every system action logged (privacy compliance + debugging)
CREATE TABLE IF NOT EXISTS audit_logs (
    id          TEXT PRIMARY KEY,
    action      TEXT NOT NULL,           -- document_uploaded | signal_detected | pii_removed | feedback_given
    entity_type TEXT NOT NULL,           -- document | signal | feedback
    entity_id   TEXT NOT NULL,
    detail      TEXT,                    -- JSON blob for extra context
    created_at  TEXT NOT NULL
);
```

**Key design decisions:**
- All timestamps stored as ISO 8601 TEXT — SQLite has no native datetime type
- `signal_history` is the organizational memory engine — without it, there is no trend data
- `audit_logs` covers every action — required for enterprise privacy compliance
- `evidence` is a separate table so signals can gain new evidence as more documents arrive

---

## 4. REST API Design

> **MVP note:** FastAPI is introduced in Sprint 2. In Sprint 1, Streamlit calls Python functions directly. These API definitions are the contract the functions must satisfy — so Sprint 2 wraps them in FastAPI without rewriting logic.

### POST /api/documents/upload
```
Purpose:    Upload a document for processing
Request:    multipart/form-data
            - file: binary (max 10MB)
            - source_type: string (meeting_note | incident_log | ticket | status_report)
Response:   202 { document_id, filename, word_count, status: "queued" }
Errors:     400 Bad Request — quality gate failed (body includes rejection reason)
            415 Unsupported Media Type — file type not .txt/.docx/.pdf
```

### GET /api/signals
```
Purpose:    List all active signals (dashboard main view)
Request:    query params: severity (optional), status (optional, default: active)
Response:   200 [{ signal_id, title, severity, confidence_band, trend, created_at }]
```

### GET /api/signals/{signal_id}
```
Purpose:    Full signal detail including evidence
Response:   200 Signal object + list of Evidence objects
Errors:     404 Signal not found
```

### POST /api/signals/{signal_id}/feedback
```
Purpose:    Human confirms or dismisses a signal
Request:    { reviewer_role, decision: "confirmed"|"dismissed", comment? }
Response:   201 { feedback_id, signal_id, decision }
Errors:     400 Invalid decision value
            404 Signal not found
```

### GET /api/signals/{signal_id}/history
```
Purpose:    Signal trend over time (organizational memory)
Response:   200 [{ severity, confidence_band, trend, snapshot_at }]
```

### GET /api/digest/weekly
```
Purpose:    Top 3 signals for weekly digest (Slack/email)
Response:   200 { top_signals: [...], generated_at, programme_context }
```

---

## 5. Module Interfaces

The contract between every module. Input and output types must match exactly.

```
┌─────────────────────────────────────────────────────────────────┐
│ INTERFACE                  INPUT              OUTPUT             │
├─────────────────────────────────────────────────────────────────┤
│ Loader → QualityGate       file bytes,        QualityResult      │
│                            filename                              │
├─────────────────────────────────────────────────────────────────┤
│ QualityGate → Loader       QualityResult      raw text (str)     │
│ (on pass only)                                                   │
├─────────────────────────────────────────────────────────────────┤
│ Loader → Anonymizer        Document           AnonymizedDocument │
│                            (with raw_text)                       │
├─────────────────────────────────────────────────────────────────┤
│ Anonymizer → Embedder      AnonymizedDocument list[float]        │
│                            .anonymized_text   (384-dim vector)   │
├─────────────────────────────────────────────────────────────────┤
│ Embedder → ChromaDB        (doc_id, vector,   stored; returns    │
│                            metadata)          doc_id             │
├─────────────────────────────────────────────────────────────────┤
│ ChromaDB + Embedder        document           list[Signal]       │
│ → Detector                 collection         (NOISE/WEAK/STRONG)│
├─────────────────────────────────────────────────────────────────┤
│ Detector → Validator       list[Signal]       list[Signal]       │
│                            (WEAK + STRONG     with Evidence      │
│                            only; NOISE        attached           │
│                            dropped here)                         │
├─────────────────────────────────────────────────────────────────┤
│ Validator → Risk           Signal +           Risk               │
│                            list[Evidence]                        │
├─────────────────────────────────────────────────────────────────┤
│ Risk → Narrator            Risk               Risk               │
│                            (structured)       (+ narration str)  │
├─────────────────────────────────────────────────────────────────┤
│ Narrator → Dashboard       list[Risk]         Streamlit renders  │
│                                               signal cards       │
└─────────────────────────────────────────────────────────────────┘
```

**Critical rule enforced by interfaces:**  
NOISE signals are dropped at the Detector → Validator boundary. They are logged to SQLite but never reach the Risk or Narration layers. This keeps the dashboard clean.

---

## 6. Signal Object Schema — Field Rationale

| Field | Type | Why it exists |
|---|---|---|
| `id` | UUID string | Stable reference across all tables |
| `title` | string | Human-readable summary for the signal card |
| `category` | enum | delivery_risk / team_health / operational / dependency — drives who receives the signal |
| `severity` | enum | NOISE / WEAK / STRONG — the core BERTopic classification output |
| `confidence_band` | enum | low / medium / high — shown to users instead of a raw float (PRD §8: uncalibrated scores mislead) |
| `trend` | enum | emerging / stable / fading — requires signal_history table; this is the organizational memory output |
| `evidence` | list[str] | Anonymized snippets — every signal card must show its sources (PRD §8, explainability) |
| `source_document_ids` | list[str] | Traceability — user can ask "where did this come from?" |
| `suggested_owner_role` | string | Role code (not name) of who should act — Privacy Shield ensures no PII here |
| `related_teams` | list[str] | Enables cross-team risk detection in Sprint 2 |
| `related_projects` | list[str] | Links signal to delivery context |
| `status` | enum | active / confirmed / dismissed — driven by human feedback loop |
| `created_at` | datetime | Enables lead-time metric: "how many days before escalation?" |
| `updated_at` | datetime | Changes when feedback is received or new evidence arrives |

---

## 7. Risk Object — Field Rationale

| Field | Type | Why it exists |
|---|---|---|
| `id` | UUID string | Stable reference |
| `signal_id` | string | Every Risk traces back to exactly one Signal |
| `business_impact` | string | Groq narrates this in plain English — "Q3 delivery milestone at risk" |
| `confidence_band` | enum | Inherited from Signal, shown on risk card |
| `priority` | enum | critical / high / medium / low — Programme Manager acts on this |
| `suggested_owner_role` | string | Who should own the resolution (role code, never a name) |
| `suggested_action` | string | One concrete action: "Schedule sync between Backend-Lead-A and Platform-Lead-B" |
| `root_cause_hypothesis` | string | LLM-generated hypothesis based on structured evidence |
| `supporting_document_ids` | list[str] | Traceability back to source documents |
| `narration` | string | Full Groq-generated executive summary paragraph |
| `created_at` | datetime | Audit trail |

---

## 8. Evaluation Metrics

### Technical Metrics (measured in testing)

| Metric | Target | How measured |
|---|---|---|
| Signal Precision | > 60% MVP, > 75% v1.0 | Confirmed signals ÷ total signals surfaced |
| Signal Recall | > 65% v1.0 | Signals with prior detection ÷ total escalations |
| False Positive Rate | < 40% MVP | Dismissed signals ÷ total signals surfaced |
| Pipeline Latency | < 10 min for 20 docs | Timed end-to-end test per sprint |
| Test Coverage | > 80% | pytest-cov report |

### Business Metrics (measured in pilot)

| Metric | Target | How measured |
|---|---|---|
| Lead Time Before Escalation | > 7 days MVP, > 14 days v1.0 | Signal created_at vs actual escalation date (backtest) |
| Signal Acceptance Rate | > 50% | Confirmed ÷ (confirmed + dismissed) |
| Actionability Rate | > 45% | Signals that led to a PMO action |
| Executive Satisfaction | > 4.0 / 5.0 | User survey after pilot |
| Surprise Escalation Reduction | Measurable decrease | Compared against pre-SignalNoise baseline |

---

## 9. Implementation Roadmap

### Sprint 1 — Data Foundation (current)
**Goal:** Upload 20 documents → privacy shield → signal detected → signal card visible

| # | File | What it does | Tests |
|---|---|---|---|
| ✅ | `src/ingestion/quality_gate.py` | Rejects bad inputs | 23 tests passing |
| ⬜ | `src/models.py` | All shared dataclasses | import test |
| ⬜ | `src/config.py` | Settings + API keys from .env | config load test |
| ⬜ | `src/ingestion/loader.py` | Text extraction from .txt/.docx/.pdf | 3 format tests |
| ⬜ | `src/privacy/anonymizer.py` | Presidio PII removal + role mapping | PII removal test |
| ⬜ | `src/signals/embedder.py` | MiniLM vectors → ChromaDB | embedding shape test |
| ⬜ | `src/signals/detector.py` | BERTopic NOISE/WEAK/STRONG | classification test |
| ⬜ | `src/memory/store.py` + `schema.sql` | SQLite init + CRUD | insert/read test |
| ⬜ | `app/streamlit_app.py` (v1) | Upload + signal cards only | manual demo |

**Sprint 1 acceptance criteria:**
- Upload a `.docx` meeting note containing planted risk language
- Signal classified as WEAK or STRONG appears in Streamlit
- Signal card shows: title, severity, evidence snippets (anonymized), suggested owner role
- No PII visible anywhere in the UI

---

### Sprint 2 — Intelligence Layer
**Goal:** Signals have trends, evidence is corroborated, knowledge graph is built

| # | File | What it does |
|---|---|---|
| ⬜ | `src/memory/store.py` (update) | signal_history writes + reads |
| ⬜ | `src/graph/knowledge_graph.py` | NetworkX: roles, teams, signals |
| ⬜ | `src/evidence/validator.py` | Multi-source corroboration + confidence band |
| ⬜ | `app/streamlit_app.py` (v2) | Add trend arrows, evidence count, history tab |

**Sprint 2 acceptance criteria:**
- Upload 3 weeks of documents; signal_history shows trend over time
- Signal card shows trend direction (emerging / stable / fading)
- Evidence requires corroboration from ≥ 2 documents to reach STRONG

---

### Sprint 3 — Risk Intelligence + Narration
**Goal:** Structured risk objects generated, Groq narrates them

| # | File | What it does |
|---|---|---|
| ⬜ | `src/risk/intelligence.py` | Builds Risk from ValidatedSignal |
| ⬜ | `src/narration/narrator.py` | Groq generates executive narration |
| ⬜ | `app/streamlit_app.py` (v3) | Risk cards with narration, confirm/dismiss UI |
| ⬜ | `src/memory/store.py` (update) | Write feedback to SQLite |

**Sprint 3 acceptance criteria:**
- Groq produces a 2-sentence executive summary per risk
- Programme Manager can confirm or dismiss each signal card
- Feedback is stored in SQLite

---

### Sprint 4 — Production Polish
**Goal:** Full end-to-end demo ready for enterprise pilot

| # | File | What it does |
|---|---|---|
| ⬜ | Weekly digest generator | Top 3 signals as plain text (Slack/email) |
| ⬜ | `src/memory/store.py` (update) | Audit log writes for every action |
| ⬜ | End-to-end test suite | 20 documents → signals → feedback in one pytest run |
| ⬜ | `app/streamlit_app.py` (v4) | Timeline tab, digest preview, programme selector |

**Sprint 4 acceptance criteria:**
- End-to-end pipeline test passes with 20 sample documents
- Weekly digest shows correct top 3 signals
- Audit log contains every document upload, signal detection, and feedback event
- Zero PII visible in any output

---

## 10. Architecture Audit

### Implementation blockers (MVP only)

| Blocker | Fix |
|---|---|
| No `src/models.py` | Build first — every other module imports from it |
| No `src/config.py` | Build second — Groq API key and ChromaDB path must be centralized |
| No SQLite schema init | `store.py` must create tables on first run — not a separate migration tool |
| spaCy model not downloaded | `anonymizer.py` requires `python -m spacy download en_core_web_lg` — must be in setup instructions |
| No sample documents | Need 20 synthetic test documents with planted signals before BERTopic can be tested |

### What is NOT a blocker
- FastAPI (Sprint 2 — Streamlit function calls are sufficient for Sprint 1)
- Knowledge graph (Sprint 2)
- Groq narration (Sprint 3 — pipeline works without it until then)
- RBAC / audit log completeness (Sprint 4)
- PDF export, live connectors (Post-launch)

---

## Go / No-Go Decision

**GO.**

> Architecture Approved for Implementation.

Build order for Sprint 1:
1. `src/models.py`
2. `src/config.py`
3. `src/ingestion/loader.py`
4. `src/privacy/anonymizer.py`
5. `src/signals/embedder.py`
6. `src/signals/detector.py`
7. `src/memory/store.py` + `schema.sql`
8. `app/streamlit_app.py` (Sprint 1 version)
