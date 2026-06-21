# Future Work

Items that are out of scope for Sprint 1 but worth tracking for future contributors.

## Technical Debt

**`store.save_evidence()` not called in pipeline**
The `Evidence` model and `save_evidence()` method are implemented in `store.py`. The signal detection pipeline does not yet call them, so evidence snippets do not appear on signal cards. Sprint 2 item.

**Knowledge graph partially implemented**
`knowledge_graph.py` adds documents and signals but the graph is not queried for related signal detection or trend inference. Sprint 2 item.

**`MIN_DOCS_FOR_BERTOPIC=2` in test .env**
The `.env.example` correctly sets this to 10. Users testing with 2 documents will get poor BERTopic results. Add a UI warning when the count is below 10 but above the configured minimum.

**BERTopic topic titles are raw keywords**
Signal titles like "Signal: team, sprint, issue" are not human-readable. Sprint 2 could use a lightweight LLM call to generate a descriptive title from the top keywords — separate from the risk narration.

## Enhancements

**Feedback learning loop**
`Feedback` records are stored in SQLite but not yet used to improve future signal classification. A simple approach: if a signal category is consistently dismissed, downgrade its confidence. A more sophisticated approach: fine-tune the RISK_KEYWORDS list from confirmed signals.

**Document deduplication**
The same document uploaded twice creates two ChromaDB entries. Add a content hash check before embedding.

**Signal deduplication**
If signal detection is run twice without clearing ChromaDB, similar signals may be created. Add duplicate detection based on topic similarity.

**Async document processing**
Document processing (quality gate + anonymization + embedding) runs synchronously in the Streamlit upload handler. For large batches, this blocks the UI. A background task queue (Celery, asyncio, or a simple thread pool) would improve UX significantly.

**Streaming narration**
Groq supports streaming. Displaying the narration word-by-word in the dashboard would improve perceived performance.

**Export and reporting**
- Export signal cards to PDF
- Export evidence to CSV for programme review meetings
- Weekly email digest (skeleton in `src/digest/`)

## Architecture Evolution

**FastAPI layer**
Adding a REST API between the pipeline and the dashboard would allow:
- Multiple frontends (mobile app, Slack bot)
- Programmatic signal querying
- Webhook integration with Jira / PagerDuty

**PostgreSQL migration**
SQLite is appropriate for single-user deployment. For multi-user enterprise use, migrate to PostgreSQL. The schema is already normalised and the migration is a connection string change plus a `pg_dump`-style migration script.

**Distributed ChromaDB**
ChromaDB supports a server mode. For multi-instance deployments, switch from `PersistentClient` to `HttpClient` pointing at a shared ChromaDB server.

**Plugin architecture**
A connector plugin system would allow organizations to add document sources (Confluence, SharePoint, Google Drive) without modifying core pipeline code.
