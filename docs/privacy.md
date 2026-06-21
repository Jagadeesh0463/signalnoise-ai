# Privacy

## Principles

SignalNoise AI was designed with privacy as a constraint, not a feature. These principles are enforced in code, not just policy.

**1. Strip PII before everything else.**
The Privacy Shield runs as the first processing step. No raw text ever reaches the embedding model, the topic model, or the LLM.

**2. No individual monitoring.**
All signals are detected at team or programme level. The minimum group size (`MIN_GROUP_SIZE = 5`) means no signal can be produced from fewer than 5 people. Signals describe collective patterns — not individuals.

**3. Role codes, not names.**
Presidio maps each person to a role code: `[Backend-Lead-A]`, `[Programme-Manager-B]`. The same person gets the same code within a document. Codes are not correlated across documents. The mapping (`role_map`) is not stored after the Privacy Shield stage.

**4. Raw text deleted immediately.**
After `anonymize()` returns, `Document.raw_text` is set to `""` and the uploaded file is deleted from `data/raw/`. The anonymized text in ChromaDB and SQLite is all that persists.

**5. LLM input is always anonymized.**
The Groq prompt contains only structured fields from the `Risk` object. An assertion in `narrator.py` would fire if raw text were accidentally included. (This assertion is implicit in the type system — Groq receives a `Risk`, not a `Document`.)

## What Presidio Detects

The Privacy Shield uses Microsoft Presidio with spaCy (`en_core_web_sm`) to detect:

| Entity Type | Example | Replaced With |
|-------------|---------|---------------|
| PERSON | "Priya Sharma" | `[Person-A]` |
| EMAIL_ADDRESS | "priya@company.com" | `[Email-A]` |
| PHONE_NUMBER | "+91 98765 43210" | `[Phone-A]` |
| LOCATION | "Bangalore" | `[Location-A]` |
| DATE_TIME | "Tuesday 14th" | `[Date-A]` |
| ORG | "Acme Corporation" | `[Org-A]` |

The `[Type-Letter]` format assigns a sequential letter per entity type within a document, so `[Person-A]` and `[Person-B]` refer to different people in the same document.

## What Is Stored

| Store | Contents | Contains PII? |
|-------|----------|---------------|
| ChromaDB | Anonymized text + 384-dim vectors | No |
| SQLite `documents` | Filename, word count, timestamps | No |
| SQLite `signals` | Title (BERTopic keywords), category, severity | No |
| SQLite `evidence` | Anonymized text snippets | No |
| SQLite `feedback` | Reviewer role code + confirm/dismiss decision | No |
| SQLite `audit_logs` | Action type + entity IDs | No |
| Logs | doc_id (UUID) + word count | No |

Raw text is never written to any persistent store.

## What Is NOT Stored

- Raw document text
- Real names or identifiers
- Individual-level signals
- IP addresses or session identifiers
- Browser fingerprints

## Groq Data Processing

When using Groq for narration:

- Input to Groq: structured `Risk` fields (category, priority, suggested action, business impact)
- Groq does NOT receive: raw documents, anonymized text, or any document content
- Groq's data processing terms apply to the structured fields sent — review [Groq's privacy policy](https://groq.com/privacy-policy/) before production use

**For enterprise deployment:** Replace Groq with Ollama. The pipeline runs entirely on-premise with no external API calls.

## Compliance Notes

This implementation is designed to support GDPR and similar frameworks by:

- Minimising data collection (no PII stored at any stage)
- Providing an audit trail of all actions
- Enabling right-to-erasure (delete a document_id from SQLite + ChromaDB)
- Not profiling individuals

This is not a legal compliance certification. Consult your legal team before deployment in regulated environments.
