# Troubleshooting

## Common Issues

### "Need X more documents (currently Y/10)"

**Cause:** BERTopic requires a minimum number of documents for reliable clustering.

**Fix:** Upload more documents. The default minimum is 10 (set by `MIN_DOCS_FOR_BERTOPIC` in `.env`). For testing, you can lower this to 2 — but signal quality will be poor.

```bash
# In .env:
MIN_DOCS_FOR_BERTOPIC=2
```

---

### "Invalid API Key" from Groq

**Cause:** The `GROQ_API_KEY` in `.env` is missing, expired, or incorrect.

**Fix:**
1. Go to [console.groq.com](https://console.groq.com) → API Keys
2. Generate a new key
3. Update `.env`: `GROQ_API_KEY=gsk_...`
4. Restart Streamlit

**Note:** The pipeline works without a valid Groq key — it uses fallback narration from structured Risk fields.

---

### Dashboard shows old signals with "persona" / "datea" in titles

**Cause:** Stale signals from a previous buggy run are in SQLite. The keywords are junk tokens from Presidio role codes that weren't cleaned before BERTopic.

**Fix:**
```bash
# Stop Streamlit (Ctrl+C), then:
rm -rf data/processed/chroma
rm -f data/processed/signalnoise.db
# Restart Streamlit and re-upload documents
```

---

### ChromaDB accumulation (sidebar shows more signals than expected)

**Cause:** Each Streamlit restart re-uploads documents with new UUIDs, creating duplicate ChromaDB entries.

**Fix:** Clear ChromaDB before a clean run:
```bash
rm -rf data/processed/chroma
```

---

### "BERTopic clustering failed"

**Cause:** Usually insufficient document variety for BERTopic to find distinct clusters.

**Fix:**
- Upload more varied documents (different topics, departments, time periods)
- Lower `MIN_TOPIC_SIZE` in `.env` (default: 2)
- Check that documents passed the quality gate (they should show in the upload success message)

---

### spaCy model not found

**Error:** `OSError: [E050] Can't find model 'en_core_web_sm'`

**Fix:**
```bash
python -m spacy download en_core_web_sm
```

---

### "ModuleNotFoundError: No module named 'src'"

**Cause:** Running from the wrong directory or without the venv activated.

**Fix:**
```bash
cd /path/to/signalnoise-ai
source .venv/bin/activate
streamlit run app/streamlit_app.py
```

---

### Streamlit reloading on every file change

**Cause:** Streamlit's file watcher is enabled.

**Fix:** Already handled by `.streamlit/config.toml`:
```toml
[server]
fileWatcherType = "none"
```

If this file is missing, create it manually.

---

### Tests failing with "ConfigurationError: Required environment variable 'GROQ_API_KEY' is missing"

**Cause:** Tests need GROQ_API_KEY set before importing `src.*`.

**Fix:** `conftest.py` sets this automatically:
```python
os.environ.setdefault("GROQ_API_KEY", "test-key-conftest")
```

If you're running individual test files without `conftest.py`, set the env var manually:
```bash
GROQ_API_KEY=test pytest tests/test_quality_gate.py
```

---

### Docker container exits immediately

**Cause:** Missing `.env` file or `GROQ_API_KEY` not set.

**Fix:**
```bash
# Verify .env exists and has GROQ_API_KEY set
cat .env | grep GROQ_API_KEY

# Run with explicit env
docker run -p 8501:8501 -e GROQ_API_KEY=gsk_... signalnoise-ai
```

---

## Performance Issues

### Embedding is slow on first run

**Expected.** The MiniLM model (~80MB) downloads on first run. Subsequent runs use the cached model.

### Signal detection is slow with many documents

BERTopic is O(n log n) for HDBSCAN clustering. For 10–100 documents it should complete in under 10 seconds on CPU.

If slow:
- Ensure `batch_size=32` is set in `embedder.py` (it is by default)
- Consider running on a machine with more RAM (HDBSCAN is memory-intensive above 1000 documents)

---

## Getting Help

1. Check this troubleshooting guide
2. Check [GitHub Issues](https://github.com/Jagadeesh0463/signalnoise-ai/issues)
3. Open a new issue with: Python version, OS, error message, and relevant log output
