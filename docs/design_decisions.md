# Design Decisions

Each decision records the choice, the alternatives considered, and the rationale.

---

## 1. Privacy-first pipeline order

**Decision:** PII removal runs before embeddings, ChromaDB storage, and LLM calls. The pipeline is physically ordered so that raw text can never reach a model.

**Alternatives considered:**
- Store raw text and anonymize on read — rejected because it stores PII at rest and creates a recovery risk
- Anonymize before LLM only — rejected because embeddings from named text can leak identity through vector similarity

**Rationale:** If PII reaches an embedding model, cosine similarity searches can re-identify individuals even without names. Removing PII before the first model call eliminates this attack surface entirely.

---

## 2. BERTopic over LLM-based classification

**Decision:** Signal detection uses BERTopic (topic modelling on pre-computed embeddings) rather than asking an LLM to classify documents.

**Alternatives considered:**
- GPT-4 zero-shot classification — rejected because it requires sending document text to an external API, requires PII to be in the input for context, and produces labels you defined rather than patterns that emerge from the data
- Fine-tuned classifier — rejected because it requires labelled training data we don't have

**Rationale:** BERTopic finds emergent patterns across documents without labelled training data. LLMs classify what you ask — BERTopic finds what you didn't know to ask for. The topic model also runs fully on CPU, offline, with no external calls.

---

## 3. LLM only for narration, not detection

**Decision:** Groq receives only structured `Risk` object fields. It never sees documents, raw text, or anonymized text. Its only job is: "Write 2 sentences for this structured data."

**Alternatives considered:**
- LLM for full pipeline — rejected because it creates a single point of failure, makes the system unauditable, and sends documents to an external API
- No LLM at all — considered valid; the fallback narration from structured fields works well enough for MVP

**Rationale:** The LLM role is narrowly scoped and auditable. Any failure falls back gracefully. The structured Risk fields provide enough context for a useful summary. Enterprise deployments can replace Groq with Ollama and run fully offline.

---

## 4. SQLite for persistence

**Decision:** SQLite for signals, evidence, feedback, and audit logs.

**Alternatives considered:**
- PostgreSQL — rejected for MVP because it requires a separate process, complicates Docker setup, and is overkill for single-user deployment
- In-memory only — rejected because signals are lost on restart

**Rationale:** SQLite is file-based, zero-config, and fast enough for hundreds of signals. The schema is designed for easy migration to PostgreSQL when scale demands it — table structure is the same, only the connection string changes.

---

## 5. ChromaDB for vector storage

**Decision:** ChromaDB as the persistent vector store.

**Alternatives considered:**
- FAISS — rejected because it requires manual serialization; ChromaDB handles persistence natively
- Pinecone / Weaviate — rejected because they require external API calls (privacy concern)
- Store embeddings in SQLite — rejected because BLOB storage is inefficient and SQLite has no built-in ANN search

**Rationale:** ChromaDB is self-hosted, Python-native, persistent by default, and integrates cleanly with the existing stack. For scale, migration to Weaviate or pgvector is straightforward.

---

## 6. MiniLM-L6-v2 for embeddings

**Decision:** `all-MiniLM-L6-v2` (384-dim) from sentence-transformers.

**Alternatives considered:**
- `text-embedding-ada-002` (OpenAI) — rejected because it sends text to an external API (privacy concern)
- `all-mpnet-base-v2` (768-dim) — considered; higher quality but 2x slower on CPU
- `all-MiniLM-L12-v2` — considered; marginal quality gain, slower

**Rationale:** MiniLM-L6-v2 is fast on CPU, produces strong semantic embeddings for short-to-medium texts (which meeting notes are), and runs fully offline. For enterprise deployment on GPU, swapping to a larger model is one line change.

---

## 7. NOISE / WEAK / STRONG classification

**Decision:** Three-tier severity system based on document count and risk keyword presence.

**Alternatives considered:**
- Continuous probability score — rejected because raw probabilities cause two problems: (a) users treat 0.73 as objective truth, (b) BERTopic probability outputs are unreliable on small datasets
- Binary (risk / no-risk) — rejected because WEAK signals provide value as early warnings even when not strong enough to act on

**Rationale:** The three-tier system matches how programme managers already think: "something to watch" (WEAK) vs "act now" (STRONG). The confidence_band (low/medium/high) provides additional nuance without exposing raw floats.

---

## 8. Minimum group size of 5

**Decision:** The `MIN_GROUP_SIZE` configuration prevents signals from being generated from fewer than 5 contributing documents (approximating 5 people).

**Rationale:** GDPR and similar frameworks require that analytics cannot be used to infer information about identifiable individuals. A minimum group size of 5 is a standard control in aggregate analytics to prevent re-identification.

---

## Code Style

- **PEP 8** — enforced by `flake8` and `black`
- **Type hints** — all functions, all parameters, all return types
- **Google-style docstrings** — Args / Returns / Raises
- **`logging` not `print()`** — structured log output with module name
- **Custom exceptions** — all raises use the `SignalNoiseError` hierarchy
- **Constants in config** — no magic numbers in business logic
- **Dataclasses for models** — no raw dicts between layers
