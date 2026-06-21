# Architecture

## Overview

SignalNoise AI is a layered pipeline architecture. Each layer has one responsibility and communicates with adjacent layers only through well-defined data models. No layer skips another.

```
┌─────────────────────────────────────────────────────────────┐
│                     Presentation Layer                       │
│                  app/streamlit_app.py                        │
└────────────────────────────┬────────────────────────────────┘
                             │ reads / writes
┌────────────────────────────▼────────────────────────────────┐
│                      Memory Layer                            │
│              src/memory/store.py (SQLite)                    │
│              src/graph/knowledge_graph.py (NetworkX)         │
└────────────────────────────┬────────────────────────────────┘
                             │
       ┌─────────────────────┼────────────────────────┐
       │                     │                         │
┌──────▼───────┐  ┌──────────▼──────────┐  ┌─────────▼──────┐
│  Ingestion   │  │  Signal Intelligence │  │    Narration   │
│  Layer       │  │  Layer               │  │    Layer       │
│  loader.py   │  │  embedder.py         │  │  narrator.py   │
│  quality_    │  │  detector.py         │  │  (Groq / LLM)  │
│  gate.py     │  │  validator.py        │  └────────────────┘
└──────┬───────┘  │  intelligence.py     │
       │          └──────────────────────┘
┌──────▼───────┐
│  Privacy     │
│  Layer       │
│  anonymizer  │
│  .py         │
└──────────────┘
```

## Layer Responsibilities

### Ingestion Layer (`src/ingestion/`)

Accepts uploaded files, extracts text, and runs the quality gate.

- `loader.py` — dispatches to the right extractor based on file extension (`.txt`, `.docx`, `.pdf`)
- `quality_gate.py` — six sequential rules that must all pass before the document proceeds

**Output:** `Document` dataclass with `raw_text` populated.

### Privacy Layer (`src/privacy/`)

Removes all PII before any downstream processing. This is the most critical security boundary in the system.

- `anonymizer.py` — runs Microsoft Presidio with spaCy NLP to detect and replace PII entities
- Replaces names, emails, phone numbers, locations with role codes: `[Person-A]`, `[Email-B]`, etc.
- Deletes `raw_text` after anonymization — the original text cannot be recovered downstream

**Output:** `AnonymizedDocument` dataclass. Raw text is gone.

### Signal Intelligence Layer (`src/signals/`, `src/evidence/`, `src/risk/`)

Three sub-layers operating on anonymized text only:

1. **Embedder** — converts anonymized text to 384-dim vectors using MiniLM-L6-v2, stores in ChromaDB
2. **Detector** — runs BERTopic on stored vectors to find topic clusters; classifies each as NOISE / WEAK / STRONG
3. **Validator** — corroborates each signal across multiple documents; requires evidence from at least 2 sources for STRONG
4. **Risk Intelligence** — translates a validated Signal into a structured Risk with priority, owner, and action

**Output:** `Risk` objects with all fields populated except `narration`.

### Narration Layer (`src/narration/`)

The only layer that uses an external LLM. Receives structured Risk objects (never raw documents) and produces a 2-sentence plain-English executive summary.

- If Groq fails, a fallback narration is generated from Risk fields — the pipeline never stops
- Enterprise deployments replace Groq with Ollama (same interface, same code)

**Output:** `Risk.narration` populated.

### Memory Layer (`src/memory/`, `src/graph/`)

Persistence layer for all structured data.

- `store.py` — SQLite with tables for documents, signals, signal_history, evidence, feedback, audit_logs
- `knowledge_graph.py` — NetworkX graph of signal relationships for trend detection (Sprint 2)

### Presentation Layer (`app/`)

Streamlit dashboard. Reads from `MemoryStore` and calls the pipeline on user action.

## Data Flow Between Layers

See [data_flow.md](data_flow.md) for the full sequence diagram.

## Key Design Principles

**Single-direction data flow.** Data moves forward through the pipeline. No layer calls a layer above it.

**Immutable data models.** `dataclass` instances are passed between layers, never dictionaries. This catches type errors at development time.

**No cross-layer imports.** The Privacy layer does not import from Signal Intelligence. The Narration layer does not import from Ingestion. Violations break the architecture.

**Fail loudly at startup, gracefully at runtime.** Missing environment variables raise `ConfigurationError` at import time. Individual narration failures use fallback — the pipeline continues.

## Dependency Graph

```
config.py          ← imported by all layers
exceptions.py      ← imported by all layers
models.py          ← imported by all layers

quality_gate.py    ← no internal imports
loader.py          ← quality_gate
anonymizer.py      ← models, config
embedder.py        ← models, config, exceptions
detector.py        ← models, config, exceptions
validator.py       ← models, exceptions
intelligence.py    ← models, exceptions, validator
narrator.py        ← models, config, exceptions
store.py           ← models, config, exceptions
knowledge_graph.py ← models
```
