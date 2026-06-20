# SignalNoise AI — Final Implementation Readiness Review
**Version:** 1.0 | **Reviewer role:** Principal Software Engineer / Enterprise Architect  
**Date:** 2026-06-18 | **Scope:** MVP only

---

## 1. Folder Structure

**Verdict: Two critical files missing. Everything else is correct.**

| Issue | Severity | Fix |
|---|---|---|
| `.gitignore` missing | ❌ BLOCKING | Groq API key in `.env` will be committed to GitHub without it |
| `README.md` missing | ⚠ | Portfolio project with no README is not presentable |
| `tests/conftest.py` missing | ⚠ | Shared fixtures for temp files and sample docs go here |
| `data/sample/` is empty | ❌ BLOCKING | BERTopic cannot run without documents; needed before Sprint 1 ends |
| `src/memory/schema.sql` missing | ⚠ | Designed, not yet created |

No folders to merge. No files to split. No files to rename.  
Structure is clean — two missing files are the only problem.

---

## 2. Code Quality

### quality_gate.py (only built file — reviewed)

| Issue | Severity | Fix |
|---|---|---|
| `MIN_WORD_COUNT`, `MAX_WORD_COUNT`, `MAX_SINGLE_TOKEN_RATIO` are module-level constants | ⚠ | Move to `config.py` so they are configurable without editing source |
| `_ENGLISH_MARKERS` is a large hardcoded set | ℹ acceptable | Fine for MVP — do not over-engineer |
| No logging calls | ⚠ | Add `logging.info` on reject decisions so operators can debug silently failing uploads |

### Modules not yet built — design-level observations

| Risk | Affected modules | Prevention |
|---|---|---|
| `loader.py` writes uploaded files to `data/raw/` using the original filename | `loader.py` | Sanitize filename before disk write — never trust the upload name directly |
| `anonymizer.py` processes raw text that contains PII | `anonymizer.py` | Never log `raw_text` — only log doc ID and word count |
| `narrator.py` sends text to Groq | `narrator.py` | Send only anonymized text — add an assertion that raw text is not in the payload |
| `embedder.py` and `detector.py` both process the same documents | both | Pass `AnonymizedDocument` object between them — do not re-read from disk |
| No shared exception type | all modules | Add `SignalNoiseError` base class in `src/exceptions.py` |

**Circular dependency risk: none** — the pipeline is strictly linear. Each module only imports from `src/models.py` and `src/config.py`. No back-references.

---

## 3. Python Best Practices

### Add to the project — these are not optional for production-quality code

**A. Centralized logging setup in `src/config.py`**
```python
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
```
Every module then does `logger = logging.getLogger(__name__)` — not `print()`.

**B. Custom exception hierarchy in `src/exceptions.py`**
```python
class SignalNoiseError(Exception): pass
class QualityGateError(SignalNoiseError): pass
class LoaderError(SignalNoiseError): pass
class PrivacyShieldError(SignalNoiseError): pass
class EmbeddingError(SignalNoiseError): pass
class DetectionError(SignalNoiseError): pass
```
Currently the pipeline returns result objects on failure (which is correct for quality_gate). Other modules should raise typed exceptions so callers can handle them precisely.

**C. Type hints — enforce consistently**
- All function signatures must have type hints
- All dataclass fields must have types (already planned ✅)
- Return type annotations required on every public function

**D. `config.py` must load from `.env` at import time**
```python
from dotenv import load_dotenv
load_dotenv()

GROQ_API_KEY: str = os.environ["GROQ_API_KEY"]       # raise if missing
CHROMA_DB_PATH: str = os.getenv("CHROMA_DB_PATH", "data/processed/chroma")
MIN_WORD_COUNT: int = int(os.getenv("MIN_WORD_COUNT", "50"))
```
Never use `os.environ.get()` for required secrets — use `os.environ["KEY"]` so it fails loudly at startup, not silently at runtime.

---

## 4. Security Review

| Risk | Severity | Fix |
|---|---|---|
| No `.gitignore` — `.env` will be committed | ❌ BLOCKING | Create `.gitignore` before first `git add` |
| Uploaded filename used directly for disk I/O | ❌ BLOCKING | Sanitize: generate a UUID filename, store original name in metadata only |
| Malicious PDF (zip bomb, embedded JS) | ⚠ | Set `pdfplumber` page limit (e.g., max 200 pages) and file size cap (10MB in quality gate) |
| Raw text logged before anonymization | ⚠ | Log only: doc_id, word_count, filename. Never raw_text. |
| Groq receives text — verify it is anonymized | ⚠ | Add assertion in `narrator.py`: anonymized_text must pass a Presidio scan before sending |
| ChromaDB stored at a predictable path | ℹ | Path from config, not hardcoded — done ✅ (planned) |
| spaCy model loaded at import time | ℹ | Load once in `anonymizer.py` module scope — not per-call. Already the correct pattern. |

**Path traversal fix (one line):**
```python
from pathlib import Path
safe_filename = Path(upload.filename).name  # strips any directory components
save_path = RAW_DATA_DIR / f"{uuid4()}_{safe_filename}"
```

---

## 5. Performance Review

| Component | MVP Scale | Risk | Fix |
|---|---|---|---|
| MiniLM model load | First run only | ~80MB download, 3–5s load | Load once at app startup, not per document |
| BERTopic on 20 docs | Tiny dataset | HDBSCAN needs ≥ 10 docs to cluster | Ensure sample dataset has ≥ 15 documents |
| ChromaDB queries | Local, in-process | No risk at MVP scale | No action needed |
| SQLite concurrent writes | Streamlit is single-user for MVP | No risk | No action needed |
| Streamlit blocking on pipeline | UX freeze during processing | Use `st.spinner()` wrapping the pipeline call | Add `st.spinner("Analysing documents...")` |
| Presidio on long documents | ~1–3s per document | Acceptable for MVP batch | No action needed; revisit at 100+ docs |

**One rule for Sprint 1:** Load MiniLM and spaCy models once at startup. Never inside a loop.

---

## 6. Test Strategy

### What is in place
- `tests/test_quality_gate.py` — 23 unit tests ✅

### What is missing

**`tests/conftest.py` — shared fixtures (create before writing more tests)**
```python
# fixtures needed:
# - tmp_txt_file(content) → Path
# - tmp_docx_file(content) → Path  
# - tmp_pdf_file(content) → Path
# - sample_english_text(n_words) → str
# - mock_groq_client() → Mock
```

**Unit tests needed per module:**

| Module | Key tests |
|---|---|
| `loader.py` | .txt loads correctly; .docx loads correctly; .pdf loads correctly; empty file rejected; corrupt PDF doesn't crash |
| `anonymizer.py` | "John Smith" → role code; email removed; phone removed; no PII in output; role_map populated |
| `embedder.py` | output is list[float] of length 384; identical texts produce similar vectors; ChromaDB stores and retrieves |
| `detector.py` | NOISE/WEAK/STRONG returned for each doc; NOISE is not empty string; min 15 docs for test |
| `validator.py` | single-source signal stays WEAK; two-source signal can be STRONG; rejected evidence logged |
| `intelligence.py` | Risk has all required fields; priority maps correctly from severity |
| `narrator.py` | Groq call is mocked in tests; narration is a non-empty string; raw PII not in Groq payload |

**Integration test (Sprint 1 end gate):**
```
load 5 sample .txt docs → quality gate → anonymizer → embedder → detector
assert: at least 1 WEAK or STRONG signal returned
assert: no PII strings appear in signal evidence
```

**Edge cases that must be tested:**
- Zero-byte file upload
- PDF with no text (image-only scan)
- `.docx` with only a table, no paragraphs
- Document with names but no risk language (should be NOISE)
- Document in German (should be rejected by quality gate) ✅ already tested

**Mocking rule:** Groq API is always mocked in tests. Never make a real API call in `pytest`.

---

## 7. Documentation

| Document | Status | Priority |
|---|---|---|
| `README.md` | ❌ missing | High — first thing anyone sees on GitHub |
| `SETUP.md` or setup section in README | ❌ missing | High — spaCy model download is a hidden step that breaks onboarding |
| `.env.example` | ❌ missing | High — developers need to know what env vars are required |
| `docs/implementation_plan.md` | ✅ written | — |
| `docs/readiness_review.md` | ✅ this file | — |
| Architecture sequence diagram | ⚠ optional | Add as Mermaid diagram in README once Sprint 1 is complete |
| ER diagram for SQLite schema | ⚠ optional | Add after `schema.sql` is built |

**`README.md` must contain (minimum):**
1. One-sentence product description
2. Architecture diagram (even ASCII is fine)
3. Setup commands: clone → venv → pip install → spacy download → pytest
4. How to run: `streamlit run app/streamlit_app.py`
5. How to upload a document and see a signal

---

## 8. Developer Experience

**Can a new developer clone this repo and contribute in 30 minutes?**

Currently: **No.**

| Blocker | Fix |
|---|---|
| No README — no idea what the project does | Write `README.md` |
| `python -m spacy download en_core_web_lg` is not documented anywhere | Add to README setup steps |
| No `.env.example` — developer doesn't know what env vars to set | Create `.env.example` |
| No `conftest.py` — adding a test requires understanding fixture patterns | Create with shared fixtures |
| sample documents don't exist — can't run end-to-end without them | Create 20 synthetic `.txt` docs |

**After these 5 fixes:** A developer can clone, run setup commands from README, run `pytest`, and see 23 tests pass within 15 minutes.

---

## 9. GitHub Readiness

| File | Status | Action |
|---|---|---|
| `README.md` | ❌ missing | Create — required for portfolio |
| `.gitignore` | ❌ missing | Create — required before first commit |
| `.env.example` | ❌ missing | Create — required for onboarding |
| `LICENSE` | ⚠ optional | Add MIT licence — standard for portfolio open-source |
| `CONTRIBUTING.md` | skip | Unnecessary for MVP portfolio project |
| `CHANGELOG.md` | skip | Premature for v0.1 |
| `CODE_OF_CONDUCT.md` | skip | Not needed for single-developer portfolio |
| Issue templates | skip | Not needed for MVP |

**Minimum viable GitHub repo requires:** README + .gitignore + .env.example. Nothing else is blocking.

---

## 10. Final Readiness Checklist

| Area | Status | Note |
|---|---|---|
| Folder Structure | ⚠ | Missing `.gitignore`, `README.md`, `conftest.py` |
| Configuration | ⚠ | `config.py` designed, not built; quality_gate constants must move here |
| Models | ⚠ | `models.py` designed, not built |
| Database | ⚠ | `schema.sql` and `store.py` designed, not built |
| APIs | ⚠ | Defined, not built (Sprint 2 — acceptable) |
| Documentation | ❌ | README and .env.example are missing |
| Testing | ⚠ | 23 unit tests ✅; conftest.py and integration tests missing |
| Sample Data | ❌ | 20 test documents do not exist yet |
| Dashboard | ❌ | Not built (Sprint 1 deliverable) |
| Security | ❌ | .gitignore missing — API key exposure risk |

---

## Final Answers

### 1. Is this project ready for implementation?
**Yes — with 3 blockers resolved first (see below).**

### 2. Top 10 Implementation Improvements

1. Create `.gitignore` before any `git add` — API key exposure is a real risk
2. Add `src/exceptions.py` with `SignalNoiseError` hierarchy — typed errors across all modules
3. Move quality gate constants (`MIN_WORD_COUNT` etc.) into `config.py`
4. Add centralized logging setup in `config.py` — replace all `print()` with `logging`
5. Sanitize uploaded filenames — UUID prefix before writing to `data/raw/`
6. Assert anonymized text before sending to Groq — one-line guard in `narrator.py`
7. Load MiniLM and spaCy once at startup — not inside processing loops
8. Cap PDF pages in pdfplumber — `max_pages=200` prevents zip bomb freeze
9. Use `os.environ["KEY"]` not `os.getenv("KEY")` for required secrets — fail loudly
10. Wrap Streamlit pipeline call in `st.spinner()` — prevents UI appearing frozen

### 3. Top 5 Documentation Improvements

1. Write `README.md` — setup steps, run command, how to see a signal (portfolio critical)
2. Create `.env.example` — list every env var with a placeholder value
3. Add spaCy download command explicitly in setup (`python -m spacy download en_core_web_lg`)
4. Add Mermaid sequence diagram to README after Sprint 1 (shows pipeline in one image)
5. Add ER diagram for SQLite schema after `schema.sql` is built

### 4. Top 5 Testing Improvements

1. Create `tests/conftest.py` with shared fixtures before writing more tests
2. Write integration test: 5 docs → quality gate → anonymizer → embedder → detector
3. Mock Groq client in all tests — never make real API calls in `pytest`
4. Add edge case: zero-byte file, image-only PDF, `.docx` with tables only
5. Create 20 synthetic sample documents with planted signals for end-to-end testing

### 5. Sprint 1 Blockers

| # | Blocker | Why it blocks |
|---|---|---|
| 1 | `.gitignore` missing | First `git add .` commits `.env` and exposes Groq API key |
| 2 | Sample documents missing | BERTopic cannot cluster; `detector.py` cannot be tested |
| 3 | `models.py` not built | Every module after `loader.py` imports `Document`, `Signal` etc. — nothing compiles without it |

No other blockers. Everything else is a quality improvement, not a blocker.

---

**Implementation Plan Approved. Proceed to Development.**
