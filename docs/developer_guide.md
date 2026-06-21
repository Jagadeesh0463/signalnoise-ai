# Developer Guide

## Local Setup

```bash
git clone https://github.com/Jagadeesh0463/signalnoise-ai.git
cd signalnoise-ai

# Full dev install (includes black, isort, flake8, mypy, pre-commit)
make install-dev

# Copy and configure environment
cp .env.example .env
# Edit .env — add GROQ_API_KEY, optionally set MIN_DOCS_FOR_BERTOPIC=2 for testing

# Run the dashboard
make run

# Run tests
make test

# Lint
make lint

# Format
make format
```

## Repository Layout

```
src/
├── __version__.py          # Single source of truth for version
├── config.py               # All settings — import config, not os.environ
├── models.py               # All dataclasses — never define models in modules
├── exceptions.py           # All custom exceptions — never raise bare Exception
├── ingestion/
│   ├── loader.py           # File → Document (quality gate + text extraction)
│   └── quality_gate.py     # 6 rules, returns QualityResult — never raises
├── privacy/
│   └── anonymizer.py       # Document → AnonymizedDocument (Presidio)
├── signals/
│   ├── embedder.py         # AnonymizedDocument → ChromaDB vector
│   └── detector.py         # ChromaDB vectors → [Signal]
├── evidence/
│   └── validator.py        # [Signal] → [ValidationResult]
├── risk/
│   └── intelligence.py     # ValidationResult → Risk
├── narration/
│   └── narrator.py         # Risk → Risk (narration populated via Groq)
├── memory/
│   ├── store.py            # All SQLite read/write
│   └── schema.sql          # Table definitions + indexes
└── graph/
    └── knowledge_graph.py  # NetworkX in-memory graph (Sprint 2)
```

## Architecture Rules

These rules are enforced by code review. Violations will block a PR.

**1. Single-direction data flow.**
Data moves: Ingestion → Privacy → Signal → Risk → Narration → Memory → Dashboard.
No layer imports from a layer above it.

**2. All models in `src/models.py`.**
Never define a dataclass or TypedDict inside an individual module.
Import from `src.models` everywhere.

**3. All exceptions from `src/exceptions.py`.**
Never `raise Exception(...)` or `raise ValueError(...)`.
Use the correct subclass of `SignalNoiseError`.

**4. All configuration from `src/config.py`.**
Never call `os.environ.get(...)` outside of `config.py`.
Import `from src.config import config` and use attributes.

**5. Never log raw text.**
Log `doc_id[:8]` and `word_count`. The raw text of any document is PII-adjacent.

**6. Privacy Shield runs first.**
Any function that receives document content must receive `AnonymizedDocument`,
not `Document`. Type hints enforce this at development time.

## Adding a New Pipeline Stage

Say you want to add a `Classifier` stage between Evidence Validator and Risk Intelligence.

**Step 1 — Add exception type**

```python
# src/exceptions.py
class ClassificationError(SignalNoiseError):
    """Raised when the classifier fails."""
    pass
```

**Step 2 — Add output model if needed**

```python
# src/models.py
@dataclass
class ClassificationResult:
    signal_id: str
    label: str          # e.g. "people_risk" | "technical_risk"
    confidence: float   # 0.0–1.0, internal only
    id: str = field(default_factory=_new_id)
```

**Step 3 — Write the module**

```python
# src/classification/classifier.py
from src.exceptions import ClassificationError
from src.models import ClassificationResult, Signal

def classify(signal: Signal) -> ClassificationResult:
    """..."""
    ...
```

**Step 4 — Wire into `streamlit_app.py`**

Import and call between `validate_signals` and `build_risks`.

**Step 5 — Write tests**

```python
# tests/test_classifier.py
class TestClassify:
    def test_people_signals_classified_correctly(self, ...):
        ...
```

## Adding a New Document Source Type

1. Add to `VALID_SOURCE_TYPES` in `src/ingestion/loader.py`
2. Add to the `source_type` selectbox in `app/streamlit_app.py`
3. Add a corresponding template string in `src/risk/intelligence.py` if the category needs custom messaging

## Adding a New Risk Category

1. Add the category name to `IMPACT_TEMPLATES`, `ACTION_TEMPLATES`, `ROOT_CAUSE_TEMPLATES` in `src/risk/intelligence.py`
2. Add detection words to `_infer_category()` in `src/signals/detector.py`
3. Add risk keywords to `RISK_KEYWORDS` in `src/signals/detector.py`
4. Update `owner_map` in `_build_signal()` to assign the right owner role

## Running a Single Test File

```bash
pytest tests/test_quality_gate.py -v
pytest tests/test_memory_store.py -v -k "test_save"   # filter by name
pytest tests/ --lf                                     # re-run last failed
```

## Debugging the Pipeline

Set `LOG_LEVEL=DEBUG` in `.env` for verbose output from every stage.

```bash
LOG_LEVEL=DEBUG streamlit run app/streamlit_app.py
```

To debug BERTopic specifically, temporarily add `verbose=True` to `BERTopic(...)` in `detector.py`.

## Pre-Commit Hooks

After `make install-dev`, pre-commit hooks run automatically on `git commit`.
They check:
- Trailing whitespace
- Large files (>1MB)
- Detect secrets (API keys)
- black formatting
- isort import order
- flake8 linting

To run hooks manually:

```bash
pre-commit run --all-files
```

## Type Checking

```bash
mypy src/ --ignore-missing-imports
```

mypy is configured in `pyproject.toml`. The project uses Python 3.10+ type hints throughout (`list[str]`, `dict[str, str]`, `X | Y`, etc.).

## Release Process

1. Update `CHANGELOG.md` — add a new `[x.y.z]` section
2. Update `src/__version__.py` — bump `__version__`
3. Commit: `git commit -m "chore: release v1.1.0"`
4. Tag: `git tag v1.1.0 && git push origin v1.1.0`
5. GitHub Actions `release.yml` creates the GitHub Release automatically

## Common Pitfalls

**BERTopic crashes with `TypeError: The truth value of an array is ambiguous`**
Set `nr_topics=None` (not `"auto"`) in `_build_topic_model()`. The `"auto"` setting triggers an internal numpy comparison that fails on small datasets.

**`st.rerun()` caught by `except Exception`**
Streamlit's `RerunException` inherits from `Exception`. Always set a `_do_rerun = True` flag and call `st.rerun()` outside the try/except block.

**Signal titles contain "persona" or "datea"**
Presidio role codes (`[Person-A]`, `[Date-B]`) create junk tokens when BERTopic's CountVectorizer tokenises them. The `_clean_for_topic_model()` function in `detector.py` strips them before topic modelling.

**ChromaDB accumulates entries across restarts**
Each run upserts by `document_id`. If you reset Streamlit session state but keep ChromaDB, re-uploads create new UUIDs and new entries. Run `make clean-data` before a fresh demo.
