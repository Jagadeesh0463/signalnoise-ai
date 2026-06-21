# SignalNoise AI 📡

<div align="center">

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![CI](https://github.com/Jagadeesh0463/signalnoise-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/Jagadeesh0463/signalnoise-ai/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Jagadeesh0463/signalnoise-ai/actions/workflows/codeql.yml/badge.svg)](https://github.com/Jagadeesh0463/signalnoise-ai/actions/workflows/codeql.yml)
[![Code Style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](CHANGELOG.md)

**AI-powered platform for detecting early operational risks from organizational documents using NLP, BERTopic, and LLMs.**

[Quick Start](#quick-start) · [Architecture](#architecture) · [Documentation](docs/) · [Contributing](.github/CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

</div>

---

## What It Does

SignalNoise AI analyzes organizational documents — meeting notes, support tickets, incident reports, and status updates — to identify weak signals before they evolve into major business risks.

**Privacy-first by design.** PII is stripped before any model or API call. No individual is monitored — all signals are at team and program level.

---

## Features

| Feature | Description |
|---------|-------------|
| 🛡️ **Privacy Shield** | Presidio + spaCy removes all PII before any downstream call |
| 🔍 **Semantic Detection** | BERTopic clusters MiniLM embeddings to find emergent patterns |
| 📑 **Evidence Corroboration** | Signals promoted only when confirmed across multiple documents |
| ⚡ **Risk Intelligence** | Structured risk objects with priority, owner, and suggested action |
| 🤖 **LLM Risk Narration** | Groq or Ollama writes a 2-sentence executive summary from structured data only |
| 👍 **Feedback Loop** | Confirm/Dismiss on every signal card closes the learning loop |
| 📋 **Audit Trail** | Every action logged to SQLite for compliance |
| 📊 **Analytics Dashboard** | Interactive signal cards, confidence scores, charts, CSV export, and analyst review actions |
| 🐳 **Docker Ready** | Multi-stage Dockerfile with health check, non-root user |
| 🔁 **Offline Capable** | Replace Groq with Ollama for fully on-premise deployment |

---

## Architecture

```mermaid
flowchart TD
    A[📄 Upload .txt/.docx/.pdf] --> B[Quality Gate\n6 validation rules]
    B -->|FAIL| C[❌ Rejected with reason]
    B -->|PASS| D[🛡️ Privacy Shield\nPresidio + spaCy]
    D -->|PII removed| E[AnonymizedDocument\nrole codes only]
    E --> F[MiniLM-L6-v2\n384-dim embeddings]
    F --> G[(ChromaDB\nvector store)]
    G --> H[BERTopic\ntopic clustering]
    H --> I{Severity}
    I -->|NOISE| J[🔇 Logged, filtered]
    I -->|WEAK/STRONG| K[Evidence Validator\ncross-doc corroboration]
    K --> L[Risk Intelligence\nstructured risk object]
    L --> M[LLM Risk Narration\nGroq or Ollama]
    M --> N[(SQLite\nmemory store)]
    N --> O[📡 Streamlit Dashboard\nInteractive signal cards + analyst review]

    style D fill:#ff6b6b,color:#fff
    style E fill:#51cf66,color:#fff
    style J fill:#868e96,color:#fff
    style O fill:#339af0,color:#fff
```

**Key invariant:** PII is removed at the Privacy Shield (red). Everything downstream — embeddings, BERTopic, LLM, SQLite, dashboard — works exclusively on anonymized text with role codes.

---

## Technology Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Language | Python 3.10+ | Type hints, dataclasses, match statements |
| Privacy | Presidio + spaCy `en_core_web_sm` | Best-in-class PII detection, runs offline |
| Embeddings | MiniLM-L6-v2 (384-dim) | Fast on CPU, strong semantic quality, offline |
| Vector Store | ChromaDB | Self-hosted, persistent, Python-native |
| Topic Detection | BERTopic + HDBSCAN | Finds emergent patterns without labelled data |
| Memory | SQLite | Zero-config, sufficient for single-user MVP |
| LLM Narration | Groq / Ollama / Azure OpenAI / OpenAI | Configurable; Groq for demo, Ollama for on-premise |
| Dashboard | Streamlit | Rapid iteration, Python-native |
| Testing | pytest + pytest-cov | Standard, well-supported |
| CI | GitHub Actions | Matrix test across Python 3.10/3.11/3.12 |

---

## Quick Start

### macOS / Linux

```bash
git clone https://github.com/Jagadeesh0463/signalnoise-ai.git
cd signalnoise-ai
make install          # creates .venv, installs deps, downloads spaCy model
cp .env.example .env  # add your Groq API key
make run              # launches dashboard at http://localhost:8501
```

### Windows

```bash
git clone https://github.com/Jagadeesh0463/signalnoise-ai.git
cd signalnoise-ai
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
copy .env.example .env   # edit .env and add GROQ_API_KEY
streamlit run app/streamlit_app.py
```

### Docker

```bash
docker-compose up --build
```

Open [http://localhost:8501](http://localhost:8501) and upload the sample documents from `data/sample/`.

---

## Configuration

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `GROQ_API_KEY` | — | ✅ | Groq API key ([console.groq.com](https://console.groq.com)) |
| `GROQ_MODEL` | `llama3-8b-8192` | | LLM model for narration |
| `MIN_DOCS_FOR_BERTOPIC` | `10` | | Minimum docs before detection runs |
| `SPACY_MODEL` | `en_core_web_sm` | | spaCy model (`en_core_web_lg` for higher accuracy) |
| `CHROMA_DB_PATH` | `data/processed/chroma` | | ChromaDB persistence directory |
| `SQLITE_DB_PATH` | `data/processed/signalnoise.db` | | SQLite path |
| `LOG_LEVEL` | `INFO` | | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

See `.env.example` for the full list.

---

## Pipeline

```
1. Ingestion      — .txt / .docx / .pdf extraction with encoding detection
2. Quality Gate   — 6 rules: extension, empty, length, garbled, language
3. Privacy Shield — Presidio replaces PII with role codes ([Person-A], [Email-B], …)
4. Embeddings     — MiniLM-L6-v2 generates 384-dim vectors
5. Vector Store   — ChromaDB persists vectors for retrieval
6. Detection      — BERTopic clusters documents → NOISE / WEAK / STRONG
7. Validation     — Evidence corroborated across multiple documents
8. Risk Intel     — Signal → structured Risk object (priority, owner, action)
9. LLM Narration  — Groq or Ollama writes 2-sentence summary from structured fields only
10. Dashboard     — Streamlit renders signal cards, charts, audit log
```

---

## Example

**Input** (`data/sample/meeting_009.txt`)

```
Support Team Weekly — Ticket Volume Review
Ticket volume: 234 (up 40% from last week)
Resolution time: 3.2 days (SLA target: 1 day)
The support team has been working overtime for 10 consecutive days.
Team lead flagged burnout risk for the cohort deadline.
```

**Output**

```
🔴 Signal: platform stability, ticket volume  ·  📈 Emerging  ·  High confidence

Category:         Operational
Suggested owner:  SRE-Lead
Detected:         <timestamp>

"A platform stability issue following Tuesday's deployment has caused support
 ticket volume to spike 40% above baseline with SLA breaches. The SRE lead
 should initiate an incident response review before the delivery deadline."
```

---

## Testing

```bash
make test                              # all tests with coverage report
pytest tests/ -v                       # verbose output
pytest tests/test_quality_gate.py -v   # single file
```

Target: 90%+ coverage across 8 test files spanning every pipeline layer.

See [`docs/developer_guide.md`](docs/developer_guide.md) for full testing instructions.

---

## Privacy & Security

No personally identifiable information (PII) is stored in SQLite or ChromaDB. The LLM receives only structured risk fields — never document content.

See [`docs/privacy.md`](docs/privacy.md) and [`docs/security.md`](docs/security.md) for the full threat model and privacy policy.

---

## Roadmap

| Version | Focus |
|---------|-------|
| v1.1 | Evidence on cards · trend tracking · knowledge graph · weekly digest |
| v1.2 | FastAPI · RBAC · multi-language · Ollama integration |
| v2.0 | Async pipeline · structured logging · horizontal scaling |

See [`docs/roadmap.md`](docs/roadmap.md) for the full plan.

---

## Contributing

```bash
git checkout -b feat/your-feature
make install-dev   # installs dev tools + pre-commit hooks
make test && make lint
git commit -m "feat: describe your change"
git push origin feat/your-feature
# open a pull request
```

See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for full guidelines.

---

## License

MIT — see [LICENSE](LICENSE).

---

<div align="center">

Created and maintained by **S. Jagadeesh** — Senior Software Engineer · Bluetooth Software Engineer | AI Enthusiast

*If this project is useful to you, please ⭐ the repo.*

</div>
