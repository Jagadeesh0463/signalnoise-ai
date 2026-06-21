# Data Flow

## End-to-End Sequence

```
User uploads file
        │
        ▼
loader.py: extract text
        │
        ▼
quality_gate.py: 6 checks
        │  FAIL → error shown in UI, stop
        │  PASS ↓
        ▼
anonymizer.py: PII → role codes
        │  raw_text deleted from Document
        │  file deleted from data/raw/
        ▼
AnonymizedDocument
        │
        ├──► store.save_document(doc)        → SQLite documents table
        │
        ▼
embedder.embed_document(anon_doc)
        │  MiniLM-L6-v2 → 384-dim vector
        │
        ▼
ChromaDB.upsert(
    id=document_id,
    embedding=vector,
    document=anonymized_text,
    metadata={document_id, processed_at}
)
        │
        ▼ (when user clicks "Detect Signals")
        │
embedder.get_all_embeddings()
        │  returns (documents, embeddings, metadatas)
        │
        ▼
detector.detect_signals(documents, embeddings, metadatas)
        │  role codes stripped before BERTopic
        │  BERTopic.fit_transform(clean_docs, embeddings_array)
        │  each topic → Signal(severity=NOISE|WEAK|STRONG)
        │
        ▼
signals = [Signal, Signal, ...]
        │
        ├── NOISE signals → store.save_signal() → logged only
        │
        ▼
actionable_signals = [WEAK, STRONG signals only]
        │
        ▼
validator.validate_signals(actionable_signals, anon_docs)
        │  for each signal: count corroborating documents
        │  WEAK signals with 4+ docs → promoted to STRONG
        │  returns [ValidationResult, ...]
        │
        ▼
intelligence.build_risks(validation_results)
        │  each passed ValidationResult → Risk object
        │  priority = f(severity, confidence_band)
        │  business_impact, action, root_cause from templates
        │
        ▼
risks = [Risk, Risk, ...]
        │
        ▼
narrator.narrate_risks(risks, signal_titles)
        │  for each risk: call Groq with structured fields
        │  Groq returns 2-sentence narration
        │  if Groq fails: fallback narration from fields
        │
        ▼
store.save_signal(signal) for each signal
        │
        ▼
Streamlit re-renders signal cards from store.get_active_signals()
```

## State Across Sessions

| State | Where Stored | Persists? |
|-------|-------------|-----------|
| Processed documents | `st.session_state.anon_docs` | Session only |
| Signals | SQLite `signals` table | ✅ Yes |
| Signal history | SQLite `signal_history` table | ✅ Yes |
| Evidence | SQLite `evidence` table | ✅ Yes |
| Feedback | SQLite `feedback` table | ✅ Yes |
| Audit log | SQLite `audit_logs` table | ✅ Yes |
| Vectors | ChromaDB on disk | ✅ Yes |
| Knowledge graph | In-memory NetworkX | Session only |

## Key Data Transforms

### Document → AnonymizedDocument

```python
Document(
    raw_text="Priya raised that the team is blocked...",
    filename="meeting_001.txt",
    source_type="meeting_note",
)
    ↓  anonymize()
AnonymizedDocument(
    anonymized_text="[Person-A] raised that the team is blocked...",
    role_map={"Priya Sharma": "Person-A"},
    document_id="abc123",
)
# Document.raw_text is now ""
# File is deleted from data/raw/
```

### AnonymizedDocument → Signal

```python
# BERTopic clusters documents into topics
# Topic 0 has keywords: ["sprint", "blocker", "vendor"]
# 5 documents in this topic → STRONG severity

Signal(
    title="Signal: sprint, blocker, vendor",
    category="dependency",
    severity="STRONG",
    confidence_band="medium",
    evidence=["[Person-A] confirmed vendor API contract delayed..."],
    source_document_ids=["abc123", "def456", ...],
)
```

### Signal → Risk

```python
Signal(severity="STRONG", confidence_band="medium", category="dependency")
    ↓  build_risk()
Risk(
    priority="high",
    business_impact="Dependency bottleneck forming — escalate to remove blocker this sprint.",
    suggested_action="Owner to contact dependency team lead and set a resolution deadline.",
    root_cause_hypothesis="Likely causes: external vendor delay, cross-team coordination gap...",
    narration="",   # filled by narrator.py
)
```

### Risk → Narrated Risk

```python
Risk(
    business_impact="Dependency bottleneck forming...",
    suggested_action="Owner to contact dependency team lead...",
)
    ↓  Groq prompt (structured fields only, no raw text)
Risk(
    narration="A critical external dependency on the vendor API contract has been "
              "blocking sprint delivery for two consecutive sprints. The programme "
              "manager should escalate to the vendor relationship owner today.",
)
```
