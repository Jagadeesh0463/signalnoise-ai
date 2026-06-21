# Roadmap

## v1.0 — Core Pipeline (Released ✅)

- [x] Data ingestion: `.txt`, `.docx`, `.pdf` support
- [x] Quality gate: 6 validation rules
- [x] Privacy Shield: Presidio PII removal with role codes
- [x] MiniLM embeddings + ChromaDB vector store
- [x] BERTopic signal detection (NOISE / WEAK / STRONG)
- [x] Evidence corroboration across documents
- [x] Risk Intelligence with structured templates
- [x] LLM narration (Groq) with fallback and retry
- [x] Streamlit dashboard with signal cards
- [x] Confirm / Dismiss feedback loop
- [x] SQLite audit trail
- [x] 10 sample documents
- [x] Docker, CI/CD, CodeQL, pre-commit, Makefile

---

## v1.1 — Intelligence & Connectors

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

**Jira / Confluence connectors**
- Pull ticket summaries and Confluence pages as document sources

---

## v1.2 — API & Enterprise Readiness

**FastAPI layer**
- REST API wrapping the signal pipeline
- `/upload`, `/signals`, `/feedback` endpoints
- OpenAPI documentation

**Role-based access control**
- Program Manager sees all signals
- Team Lead sees signals for their team only
- Director sees aggregated program view

**Multi-language support**
- Replace English-only quality gate with `langdetect`
- Add multilingual sentence-transformers model option

**Custom risk taxonomy**
- Admin UI to define custom signal categories
- Custom RISK_KEYWORDS per organization

**LLM provider flexibility**
- Ollama (on-premise, `LLM_PROVIDER=ollama`)
- Azure OpenAI (data-sovereign cloud)
- OpenAI GPT-4o

---

## v2.0 — Scale & Observability

**Async pipeline**
- Background task queue (Celery or asyncio)
- Progress indicators in UI during long-running detection

**Structured logging**
- JSON log format for log aggregation (Datadog, Splunk)
- Request tracing with correlation IDs

**Monitoring**
- Prometheus metrics: documents processed, signals detected, LLM latency
- Grafana dashboard template

**Horizontal scaling**
- ChromaDB dedicated service
- SQLite → PostgreSQL
- Stateless Streamlit with shared storage

**Testing**
- Increase coverage to 95%+
- Integration tests with real BERTopic runs
- End-to-end test with sample documents

---

## Long-term Vision

- Real-time signal detection (streaming documents)
- Integration with HR systems for team structure context
- Anonymized benchmarking across similar organizations
- Mobile app for Program Manager alerts
- Custom LLM fine-tuned on program risk vocabulary
