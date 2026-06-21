# Contributing to SignalNoise AI

Thank you for considering a contribution. This guide covers everything you need to get started.

## Development Setup

```bash
git clone https://github.com/Jagadeesh0463/signalnoise-ai.git
cd signalnoise-ai
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install black isort flake8 mypy pre-commit
python -m spacy download en_core_web_sm
pre-commit install
cp .env.example .env
```

## Workflow

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Make your changes
4. Run `make test && make lint`
5. Commit with a clear message: `git commit -m "feat: add weekly digest email"`
6. Push and open a pull request against `main`

## Commit Message Format

```
<type>: <short description>

Types: feat | fix | docs | test | refactor | chore
```

Examples:
- `feat: add Jira connector for ticket ingestion`
- `fix: handle empty ChromaDB collection gracefully`
- `docs: add deployment guide for Streamlit Cloud`
- `test: add anonymizer edge case for mixed-language names`

## Code Standards

All code must:
- Pass `black` formatting (`make format`)
- Pass `isort` import ordering
- Pass `flake8` linting (max line length 100)
- Pass `mypy` type checking
- Include type hints on all functions
- Use Google-style docstrings on public functions
- Use `logging` not `print()`
- Raise from the `SignalNoiseError` hierarchy, not bare `Exception`

## Testing Requirements

All PRs must:
- Include tests for new functionality
- Not reduce overall test coverage below 85%
- Pass the full test suite: `pytest tests/ -v`

For new pipeline stages, add tests in the matching `tests/test_<module>.py` file.

## Privacy Rules (Non-Negotiable)

Any PR that violates these will be closed without merge:

- **No PII in tests or sample data.** Use fictional names (not real people).
- **No raw text in logs.** Log `doc_id[:8]` and word count only.
- **No new external API calls with document content.** All external calls must receive anonymized data.
- **No reverse mapping of role codes.** Role codes are one-way.

## Architecture Rules

- Do not skip pipeline layers. Ingestion → Privacy → Signal → Risk → Narration.
- New modules must import from `src.models` — not define their own data structures.
- All configuration goes through `src.config.config` — not `os.environ` directly.
- All exceptions must be subclasses of `SignalNoiseError`.

## Reviewing PRs

All PRs are reviewed against:
1. Does it pass CI?
2. Does it follow the privacy rules?
3. Does it follow the architecture rules?
4. Is it tested?
5. Is it documented (docstrings + relevant docs/ update)?

## Questions?

Open a [GitHub Discussion](https://github.com/Jagadeesh0463/signalnoise-ai/discussions) or open an issue.
