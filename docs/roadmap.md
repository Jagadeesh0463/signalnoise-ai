# Roadmap

## Sprint 1 — Core Pipeline (Complete ✅)

- [x] Data ingestion: `.txt`, `.docx`, `.pdf` support
- [x] Quality gate: 6 validation rules
- [x] Privacy Shield: Presidio PII removal with role codes
- [x] MiniLM embeddings + ChromaDB vector store
- [x] BERTopic signal detection (NOISE / WEAK / STRONG)
- [x] Evidence corroboration across documents
- [x] Risk Intelligence with structured templates
- [x] Groq narration with fallback
- [x] Streamlit dashboard with signal cards
- [x] Confirm / Dismiss feedback loop
- [x] SQLite audit trail
- [x] 10 sample documents

---

## Sprint 2 — Intelligence & Connectors

**Evidence display on signal cards**
- Wire `store.save_evidence()` into the pipeline
- Show anonymized evidence snippets on each signal card

**Signal trend tracking**
- Read `signal_history` table to compute emerging / stable / fading
- Add trend sparkline to signal cards

**Knowledge graph**
- Complete NetworkX integration with team and project nodes
- Show related signals and team connections in the dashboard

**Weekly digest**
- Email digest of top 3 signals every Monday
- `src/digest/digest.py` skeleton already in place

**Jira connector**
- Pull Jira ticket summaries for signal corroboration
- Map ticket status to signal category

**Confluence connector**
- Index Confluence pages as document sources

---

## Sprint 3 — API & Enterprise Readiness

**FastAPI layer**
- REST API wrapping the signal pipeline
- `/upload`, `/signals`, `/feedback` endpoints
- OpenAPI documentation

**Role-based access control**
- Programme Manager sees all signals
- Team Lead sees signals for their team only
- Director sees aggregated programme view

**Multi-language support**
- Replace English-only quality gate with `langdetect`
- Add multilingual spaCy model option
- Add multilingual sentence-transformers model option

**Custom risk taxonomy**
- Admin UI to define custom signal categories
- Custom RISK_KEYWORDS per organization

**Ollama integration**
- Drop-in replacement for Groq
- Configuration via `LLM_PROVIDER=ollama` in `.env`
- Default model: `llama3`

---

## Sprint 4 — Scale & Observability

**Async pipeline**
- Background task queue (Celery or asyncio) for document processing
- Progress indicators in UI during long-running detection

**Structured logging**
- JSON log format for log aggregation (Datadog, Splunk, etc.)
- Request tracing with correlation IDs

**Monitoring**
- Prometheus metrics: documents processed, signals detected, Groq latency
- Grafana dashboard template

**Horizontal scaling**
- Move ChromaDB to a dedicated service
- Move SQLite to PostgreSQL
- Stateless Streamlit app with shared storage

**Automated testing**
- Increase test coverage to 95%+
- Integration tests with real BERTopic runs
- End-to-end test with sample documents

---

## Long-term Vision

- Real-time signal detection (streaming documents)
- Integration with HR systems for team structure context
- Anonymized benchmarking across similar organizations
- Mobile app for Program Manager alerts
- Custom LLM fine-tuned on programme risk vocabulary
