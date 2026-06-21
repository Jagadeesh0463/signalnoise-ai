# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned
- Evidence snippets displayed on signal cards
- Signal trend tracking (emerging → stable → fading)
- Full NetworkX knowledge graph queries
- Weekly digest email
- Jira / Confluence connector

---

## [1.0.0] — 2026-06-20

### Added
- Full end-to-end pipeline: Upload → Quality Gate → Privacy Shield → Embeddings → BERTopic → Evidence Validator → Risk Intelligence → Groq Narration → Streamlit Dashboard
- `src/ingestion/loader.py` — `.txt`, `.docx`, `.pdf` extraction with encoding detection
- `src/ingestion/quality_gate.py` — 6 sequential validation rules (extension, empty, length, garbled, language)
- `src/privacy/anonymizer.py` — Microsoft Presidio + spaCy PII removal with role codes (`[Person-A]`, `[Email-B]`, etc.)
- `src/signals/embedder.py` — MiniLM-L6-v2 (384-dim) embeddings with ChromaDB persistent storage
- `src/signals/detector.py` — BERTopic topic modelling with NOISE/WEAK/STRONG classification and risk keyword matching
- `src/evidence/validator.py` — Cross-document evidence corroboration; promotes/demotes signal severity
- `src/risk/intelligence.py` — Structured Risk object with priority, owner, action, and root cause templates
- `src/narration/narrator.py` — Groq narration (llama3-8b-8192) with structured fallback
- `src/memory/store.py` — SQLite store with signals, evidence, feedback, audit log
- `src/graph/knowledge_graph.py` — NetworkX signal relationship graph (Sprint 2 queries)
- `app/streamlit_app.py` — Signal Dashboard with Upload, Signal cards, Analytics, Audit Log pages
- `data/sample/` — 10 realistic meeting notes covering burnout, vendor blockers, incidents, delivery risk
- Role code cleanup in detector (`[Person-A]` stripped before BERTopic to prevent junk tokens)
- `_do_rerun` flag pattern to prevent `st.rerun()` being caught by `except Exception`
- Analytics page with bar charts (by category, by severity), signal table, CSV export
- Category and severity filtering on Signal Dashboard
- Reset Data button in sidebar

### Fixed
- BERTopic `nr_topics="auto"` ValueError on small datasets — changed to `nr_topics=None`
- NumPy 2.x scalar conversion error (`float(multi_element_array)`) — added `np.ndim()` check
- `st.rerun()` caught by bare `except Exception` — moved outside try/except block
- `validate_signals([])` called with empty actionable list — guarded with if/else
- "persona"/"datea" junk tokens in signal titles — role codes stripped before topic modelling

### Security
- Raw text never logged — only `doc_id[:8]` and `word_count`
- Raw files deleted from `data/raw/` immediately after anonymization
- `.env` excluded from git via `.gitignore`
- Groq receives only structured `Risk` fields — no document text

### Infrastructure
- `.gitignore` — covers `.env`, `data/raw/`, `data/processed/`, `.venv/`, `*.db`
- `.env.example` — placeholder values, never real keys
- `.streamlit/config.toml` — `fileWatcherType = "none"` to prevent unnecessary reloads
- `README.md` — professional badges, architecture, install guide, FAQ
- `docs/` — 10 documentation files
- `.github/` — CI workflow, PR template, issue templates, SECURITY.md, CONTRIBUTING.md, Dependabot
- `Makefile` — `install`, `run`, `test`, `lint`, `format`, `clean`, `clean-data`
- `pyproject.toml` — black, isort, mypy, pytest, coverage config
- `.pre-commit-config.yaml` — trailing whitespace, detect-secrets, black, isort, flake8
- `.editorconfig`
- `Dockerfile` — multi-stage build, non-root user, health check
- `docker-compose.yml` — volume-mounted data persistence
- `LICENSE` — MIT

---

[Unreleased]: https://github.com/Jagadeesh0463/signalnoise-ai/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Jagadeesh0463/signalnoise-ai/releases/tag/v1.0.0
