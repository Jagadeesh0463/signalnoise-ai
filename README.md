# SignalNoise AI

Enterprise organisational intelligence platform that detects early warning signals hidden in meeting notes, incident logs, support tickets, and status reports — before they escalate into crises.

---

## What it does

Reads the documents your teams already produce and surfaces:
- **Delivery risks** — milestones slipping before they appear on dashboards
- **Team health signals** — burnout and capacity issues before attrition
- **Operational risks** — ticket patterns before they become incidents
- **Dependency blockers** — cross-team bottlenecks forming early

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.10+ |
| Privacy / PII removal | Presidio + spaCy |
| Embeddings | MiniLM-L6-v2 (sentence-transformers) |
| Vector store | ChromaDB |
| Signal detection | BERTopic |
| Knowledge graph | NetworkX |
| Memory | SQLite |
| LLM narration | Groq (demo) / Ollama (enterprise) |
| Dashboard | Streamlit |
| Tests | pytest |

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/your-username/signalnoise-ai.git
cd signalnoise-ai

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Download spaCy model (required for privacy shield)
python -m spacy download en_core_web_sm

# 5. Set up environment variables
cp .env.example .env
# Open .env and add your Groq API key (free at console.groq.com)

# 6. Run tests
pytest tests/test_quality_gate.py -v

# 7. Launch dashboard
streamlit run app/streamlit_app.py
```

---

## Pipeline

```
Upload (.txt / .docx / .pdf)
    → Quality Gate          — rejects bad documents
    → Privacy Shield        — removes PII, maps names to role codes
    → MiniLM Embeddings     — converts text to vectors
    → ChromaDB              — stores vectors
    → BERTopic              — detects signals (NOISE / WEAK / STRONG)
    → Evidence Validator    — corroborates across multiple documents
    → Risk Intelligence     — builds structured risk object
    → Groq Narration        — generates plain-English summary (last step only)
    → Streamlit Dashboard   — signal cards + confirm / dismiss
```

---

## Project Structure

```
signalnoise-ai/
├── src/
│   ├── models.py                  # shared dataclasses
│   ├── config.py                  # settings from .env
│   ├── exceptions.py              # custom error types
│   ├── ingestion/                 # quality gate + file loader
│   ├── privacy/                   # Presidio anonymizer
│   ├── signals/                   # embedder + BERTopic detector
│   ├── memory/                    # SQLite store + schema
│   ├── graph/                     # NetworkX knowledge graph
│   ├── evidence/                  # evidence validator
│   ├── risk/                      # risk intelligence
│   └── narration/                 # Groq narrator
├── app/
│   └── streamlit_app.py           # dashboard
├── tests/
│   ├── conftest.py                # shared fixtures
│   └── test_quality_gate.py       # 23 tests
├── data/
│   └── sample/                    # test documents go here
├── docs/                          # architecture and planning docs
├── .env.example                   # environment variable template
└── requirements.txt
```

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Key Design Rules

- Privacy shield runs **before** any embedding or LLM call — no raw names ever reach BERTopic or Groq
- Groq narrates structured risk objects only — it does **not** detect signals
- All signal evidence shown in the dashboard is anonymized
- Raw documents are deleted from disk immediately after anonymization

---

## Built by

Bhagya Thallapalem — FLM Learning AI Mastery Programme  
Frontlines Edutech Private Limited
