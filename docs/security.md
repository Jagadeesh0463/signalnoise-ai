# Security

## Threat Model

SignalNoise AI processes internal organizational communications. The primary threats are:

1. **PII leakage** — real names or identifiers reaching external APIs
2. **Secret exposure** — API keys committed to version control
3. **Prompt injection** — malicious document content hijacking LLM behavior
4. **Path traversal** — uploaded files escaping the intended directory
5. **Dependency vulnerabilities** — third-party packages with known CVEs

## Controls

### PII Leakage

**Control:** Privacy Shield (Presidio) runs before every downstream operation. The anonymization layer is the first processing step — not an optional add-on.

**Verification:** The `AnonymizedDocument` type is enforced at every layer boundary. The Embedder, Detector, and Narrator accept only `AnonymizedDocument`, never `Document`.

**Logging:** Raw text is never logged. Log statements use `doc_id[:8]` and `word_count` only.

**Deletion:** `Document.raw_text` is set to `""` immediately after anonymization completes. The `clear_raw_text()` method is called in `loader.py` and the file is deleted from `data/raw/` after processing.

### Secret Exposure

**Control:** `.env` is listed in `.gitignore`. The `.env.example` contains only placeholder values.

**Verification:** A pre-commit hook (in `.pre-commit-config.yaml`) runs `detect-secrets` before every commit to catch accidentally added keys.

**Rotation:** If a key is accidentally committed, rotate it immediately at the provider before addressing the git history.

### Prompt Injection

**Control:** Groq never receives raw document text. It receives only structured fields from the `Risk` dataclass — `business_impact`, `suggested_action`, `priority`, and `confidence_band`. These are templated strings produced by `intelligence.py`, not user input.

**The prompt is:** "Write a 2-sentence summary for this structured risk object." The LLM cannot be redirected by document content.

### Path Traversal

**Control:** Uploaded files are saved using `uuid4()` as the filename prefix, not the original filename. Files are saved to `config.RAW_DATA_DIR` only.

```python
raw_path = config.RAW_DATA_DIR / f"{uuid.uuid4()}_{uploaded_file.name}"
```

The original filename is stored in `Document.filename` for display — it is never used as a filesystem path after the initial save.

### Dependency Vulnerabilities

**Control:** Dependencies are listed with minimum versions in `requirements.txt`. Dependabot is configured (`.github/dependabot.yml`) to open PRs for version updates weekly.

**Recommended:** Run `pip audit` before production deployment:

```bash
pip install pip-audit
pip-audit
```

## Security Checklist

Before deploying to production, verify:

- [ ] `.env` is not committed (check `git log -- .env`)
- [ ] Groq API key is scoped to minimum required permissions
- [ ] `LOG_LEVEL` is set to `WARNING` or higher (never `DEBUG` in production)
- [ ] `data/raw/` is empty after processing (raw files deleted)
- [ ] Streamlit is behind authentication (reverse proxy or Streamlit Cloud auth)
- [ ] ChromaDB and SQLite are not accessible from the public internet
- [ ] `pip-audit` shows no high-severity vulnerabilities

## Reporting Vulnerabilities

See [SECURITY.md](../.github/SECURITY.md) for the disclosure policy.
