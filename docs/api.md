# API Reference

> **Note:** A REST API layer is planned for Sprint 3. This document describes the current Python module API.

## src.signals.detector

### `detect_signals(documents, embeddings, metadatas) → list[Signal]`

Run BERTopic on embedded documents and return classified signals.

**Parameters:**
- `documents` — `list[str]` — anonymized text strings from ChromaDB
- `embeddings` — `list[list[float]]` — 384-dim MiniLM vectors
- `metadatas` — `list[dict]` — metadata dicts containing `document_id`

**Returns:** `list[Signal]` — includes NOISE signals (filter with `signal.is_actionable()`)

**Raises:** `DetectionError` — if fewer than `MIN_DOCS_FOR_BERTOPIC` documents, or BERTopic fails

---

## src.signals.embedder

### `embed_documents(anon_docs) → list[list[float]]`

Embed a batch of AnonymizedDocuments and store in ChromaDB.

**Parameters:**
- `anon_docs` — `list[AnonymizedDocument]`

**Returns:** `list[list[float]]` — one 384-dim vector per document

**Raises:** `EmbeddingError`

### `get_all_embeddings() → tuple[list[str], list[list[float]], list[dict]]`

Retrieve all stored documents and embeddings from ChromaDB.

**Returns:** `(documents, embeddings, metadatas)`

---

## src.privacy.anonymizer

### `anonymize(document) → AnonymizedDocument`

Remove PII from a Document and return an AnonymizedDocument.

**Parameters:**
- `document` — `Document` with `raw_text` populated

**Returns:** `AnonymizedDocument` — PII replaced with role codes

**Side effects:** Sets `document.raw_text = ""` after anonymization

**Raises:** `PrivacyShieldError`

---

## src.evidence.validator

### `validate_signals(signals, anon_docs) → list[ValidationResult]`

Corroborate each signal across multiple documents.

**Parameters:**
- `signals` — `list[Signal]` — actionable (WEAK/STRONG) signals only
- `anon_docs` — `list[AnonymizedDocument]`

**Returns:** `list[ValidationResult]` — one per signal

---

## src.risk.intelligence

### `build_risks(validation_results) → list[Risk]`

Build Risk objects from passed validation results.

**Parameters:**
- `validation_results` — `list[ValidationResult]`

**Returns:** `list[Risk]` — `narration` field is empty (filled by narrator)

---

## src.narration.narrator

### `narrate_risks(risks, signal_titles) → list[Risk]`

Generate plain-English narration for each Risk via Groq. Falls back gracefully if Groq fails.

**Parameters:**
- `risks` — `list[Risk]`
- `signal_titles` — `dict[str, str]` — `{signal_id: title}`

**Returns:** Same list with `risk.narration` populated on each

---

## src.memory.store.MemoryStore

### `save_signal(signal) → None`
### `get_active_signals() → list[dict]`
### `save_evidence(evidence) → None`
### `get_evidence_for_signal(signal_id) → list[dict]`
### `save_feedback(feedback) → None`
### `get_audit_log(limit=50) → list[dict]`

---

## src.ingestion.quality_gate

### `check(text, filename="") → QualityResult`

Run all 6 quality rules on extracted text.

**Returns:** `QualityResult` with `.passed`, `.word_count`, `.rejection_reason`, `.warnings`

### `check_file_extension(filename) → QualityResult`

Lightweight extension-only check before text extraction.

---

## Data Models (`src.models`)

### `Document`
| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | UUID |
| `filename` | `str` | Original filename |
| `source_type` | `str` | `meeting_note \| incident_log \| ticket \| status_report` |
| `raw_text` | `str` | **Deleted after anonymization** |
| `word_count` | `int` | |
| `uploaded_at` | `datetime` | |
| `processed` | `bool` | True after anonymization |

### `AnonymizedDocument`
| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | UUID |
| `document_id` | `str` | Links to `Document.id` |
| `anonymized_text` | `str` | PII replaced with role codes |
| `role_map` | `dict[str, str]` | `{"John Smith": "Person-A"}` |
| `processed_at` | `datetime` | |

### `Signal`
| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | UUID |
| `title` | `str` | BERTopic top keywords |
| `category` | `str` | `delivery_risk \| team_health \| operational \| dependency` |
| `severity` | `str` | `NOISE \| WEAK \| STRONG` |
| `confidence_band` | `str` | `low \| medium \| high` |
| `trend` | `str` | `emerging \| stable \| fading` |
| `evidence` | `list[str]` | Anonymized text snippets |
| `source_document_ids` | `list[str]` | |
| `suggested_owner_role` | `str` | Role code, never a name |
| `status` | `str` | `active \| confirmed \| dismissed` |
