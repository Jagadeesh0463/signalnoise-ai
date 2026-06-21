"""
app/streamlit_app.py

SignalNoise AI — Streamlit Dashboard
Sprint 1: Upload → Process → Signal Cards → Confirm/Dismiss

Run:
    streamlit run app/streamlit_app.py
"""

import io
import os
import sys
import uuid
from pathlib import Path

# Ensure src/ is importable when running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("GROQ_API_KEY", "not-set")

import pandas as pd
import streamlit as st

from src.config import config
from src.evidence.validator import validate_signals
from src.graph.knowledge_graph import KnowledgeGraph
from src.ingestion.loader import load_file
from src.memory.store import MemoryStore
from src.models import Feedback, Signal
from src.narration.narrator import narrate_risks
from src.privacy.anonymizer import anonymize
from src.risk.intelligence import build_risks

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="SignalNoise AI",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    .metric-card {
        background: #1e1e2e;
        border-radius: 8px;
        padding: 16px;
        border-left: 4px solid;
    }
    .stExpander > div:first-child {
        font-size: 1.05rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Session state ─────────────────────────────────────────────────────────────

if "store" not in st.session_state:
    st.session_state.store = MemoryStore()

if "kg" not in st.session_state:
    st.session_state.kg = KnowledgeGraph()

if "anon_docs" not in st.session_state:
    st.session_state.anon_docs = []

if "pipeline_ran" not in st.session_state:
    st.session_state.pipeline_ran = False


def get_store() -> MemoryStore:
    return st.session_state.store


def get_kg() -> KnowledgeGraph:
    return st.session_state.kg


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 📡 SignalNoise AI")
    st.caption("v1.0.0 · github.com/Jagadeesh0463")
    st.markdown("---")

    page = st.radio(
        "Navigation",
        ["📤 Upload Documents", "📡 Signal Dashboard", "📊 Analytics", "📋 Audit Log"],
        label_visibility="collapsed",
    )

    st.markdown("---")

    store = get_store()
    active = store.get_active_signals()
    strong = [s for s in active if s["severity"] == "STRONG"]
    weak = [s for s in active if s["severity"] == "WEAK"]

    st.markdown("### Programme Health")
    col1, col2 = st.columns(2)
    col1.metric("🔴 Strong", len(strong))
    col2.metric("🟡 Weak", len(weak))

    docs_uploaded = len(st.session_state.anon_docs)
    if docs_uploaded > 0:
        st.metric("📄 Documents", docs_uploaded)

    st.markdown("---")

    # Quick reset option
    if st.button("🗑️ Reset Data", help="Clear ChromaDB and SQLite — use before a fresh demo run"):
        import shutil
        chroma_path = config.CHROMA_DB_PATH
        db_path = config.SQLITE_DB_PATH
        if chroma_path.exists():
            shutil.rmtree(chroma_path)
        if db_path.exists():
            db_path.unlink()
        st.session_state.anon_docs = []
        st.session_state.store = MemoryStore()
        st.session_state.pipeline_ran = False
        st.success("✅ Data reset complete.")
        st.rerun()


# ── Helper: render signal card ────────────────────────────────────────────────

def _confidence_display(sig: dict) -> str:
    """Return the computed confidence percentage, or estimate from band."""
    score = sig.get("confidence_score")
    if score:
        return f"{score}%"
    # Fallback for signals saved before confidence engine
    band = sig.get("confidence_band", "low")
    return {"high": "85%", "medium": "70%", "low": "55%"}.get(band, "55%")


def _render_signal_card(sig: dict, store: MemoryStore) -> None:
    """Render a full enterprise signal card with evidence, narration, and feedback."""
    severity_icon = {"STRONG": "🔴", "WEAK": "🟡", "NOISE": "⚪"}.get(sig["severity"], "⚪")
    trend_icon = {"emerging": "📈", "stable": "➡️", "fading": "📉"}.get(sig["trend"], "➡️")
    confidence_pct = _confidence_display(sig)

    with st.expander(
        f"{severity_icon} **{sig['title']}**  ·  {confidence_pct} confidence  ·  {trend_icon} {sig['trend'].title()}",
        expanded=(sig["severity"] == "STRONG"),
    ):
        col_detail, col_action = st.columns([3, 1])

        with col_detail:
            # ── Metadata row ──────────────────────────────────────────────────
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Category", sig["category"].replace("_", " ").title())
            m2.metric("Severity", sig["severity"].title())
            m3.metric("Confidence", confidence_pct)
            m4.metric("Detected", sig["created_at"][:10])

            st.markdown(f"**Suggested owner:** `{sig['suggested_owner_role']}`")

            # ── Executive Summary ─────────────────────────────────────────────
            narration = sig.get("narration")
            if narration:
                st.markdown("**Executive Summary**")
                st.info(narration)

            # ── Evidence ──────────────────────────────────────────────────────
            evidence = store.get_evidence_for_signal(sig["id"])
            if evidence:
                doc_ids = {ev["document_id"] for ev in evidence}
                st.markdown(
                    f"**Evidence** — {len(doc_ids)} document(s) · {len(evidence)} mention(s)"
                )
                for ev in evidence[:5]:
                    snippet = ev["snippet"].strip()
                    if snippet:
                        st.markdown(f"> _{snippet}_")
            else:
                # Fallback: show signal's own embedded evidence snippets
                fallback = [e for e in (sig.get("evidence") or []) if e]
                if not fallback:
                    # Try parsing from Signal object stored in DB
                    pass
                st.caption("📎 Evidence will appear after re-running detection.")

            # ── Explainability ────────────────────────────────────────────────
            with st.expander("🔍 Why was this signal detected?", expanded=False):
                st.markdown(
                    f"- **Signal category:** {sig['category'].replace('_', ' ').title()}\n"
                    f"- **Severity rule:** {'4+ documents with 2+ risk keywords' if sig['severity'] == 'STRONG' else '2–3 documents with risk keywords'}\n"
                    f"- **Confidence:** {confidence_pct} (based on document coverage, evidence quality, keyword density)\n"
                    f"- **Trend:** {sig['trend'].title()} — first detected {sig['created_at'][:10]}"
                )

        with col_action:
            st.markdown("**Review this signal:**")

            # ── Recommended Action ────────────────────────────────────────────
            action_map = {
                "critical": "🚨 Escalate today",
                "high":     "⚠️ Act this week",
                "medium":   "📋 Plan next sprint",
                "low":      "📝 Log and monitor",
            }
            # Derive priority from severity/confidence
            score = sig.get("confidence_score") or 70
            if sig["severity"] == "STRONG" and score >= 85:
                priority_hint = "critical"
            elif sig["severity"] == "STRONG":
                priority_hint = "high"
            elif score >= 70:
                priority_hint = "medium"
            else:
                priority_hint = "low"
            st.info(action_map[priority_hint])

            reviewer_role = st.selectbox(
                "Your role",
                ["Program-Manager", "Engineering-Manager", "Platform-Lead",
                 "HR-Business-Partner", "Engineering-Lead", "SRE-Lead", "Director"],
                key=f"role_{sig['id']}",
                label_visibility="collapsed",
            )
            if st.button("✅ Confirm", key=f"confirm_{sig['id']}", use_container_width=True):
                _save_feedback(sig["id"], reviewer_role, "confirmed", store)
                st.rerun()
            if st.button("❌ Dismiss", key=f"dismiss_{sig['id']}", use_container_width=True):
                _save_feedback(sig["id"], reviewer_role, "dismissed", store)
                st.rerun()


def _save_feedback(signal_id: str, reviewer_role: str, decision: str, store: MemoryStore) -> None:
    import datetime as dt

    fb = Feedback(
        id=str(uuid.uuid4()),
        signal_id=signal_id,
        reviewer_role=reviewer_role,
        decision=decision,
        created_at=dt.datetime.utcnow(),
    )
    store.save_feedback(fb)
    icon = "✅" if decision == "confirmed" else "❌"
    st.toast(f"{icon} {decision.title()}", icon="📋")


# ── Page: Upload Documents ────────────────────────────────────────────────────

if page == "📤 Upload Documents":
    st.title("📤 Upload Documents")
    st.markdown(
        "Upload meeting notes, incident logs, status reports, or ticket exports. "
        "Supported: **.txt · .docx · .pdf**"
    )

    col_type, col_spacer = st.columns([2, 3])
    with col_type:
        source_type = st.selectbox(
            "Document type",
            ["meeting_note", "incident_log", "status_report", "ticket"],
            format_func=lambda x: x.replace("_", " ").title(),
        )

    uploaded_files = st.file_uploader(
        "Choose files",
        type=["txt", "docx", "pdf"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        st.markdown(f"**{len(uploaded_files)} file(s) selected**")

        if st.button("🚀 Process Documents", type="primary"):
            store = get_store()
            kg = get_kg()
            anon_docs = []
            failed = []

            progress = st.progress(0, text="Starting...")

            for i, uploaded_file in enumerate(uploaded_files):
                progress.progress(
                    (i + 1) / len(uploaded_files),
                    text=f"Processing {uploaded_file.name}…",
                )

                raw_path = config.RAW_DATA_DIR / f"{uuid.uuid4()}_{uploaded_file.name}"
                raw_path.write_bytes(uploaded_file.read())

                try:
                    doc = load_file(raw_path, source_type=source_type)
                    store.save_document(doc)

                    anon_doc = anonymize(doc)
                    anon_docs.append(anon_doc)

                    kg.add_document(anon_doc)
                    store.mark_document_processed(doc.id)

                except Exception as e:
                    failed.append((uploaded_file.name, str(e)))

                finally:
                    if raw_path.exists():
                        raw_path.unlink()

            progress.empty()

            if anon_docs:
                st.session_state.anon_docs.extend(anon_docs)
                st.success(f"✅ {len(anon_docs)} document(s) processed and anonymized.")

            if failed:
                for name, reason in failed:
                    st.error(f"❌ **{name}** — {reason}")

            total_docs = len(st.session_state.anon_docs)
            if total_docs >= config.MIN_DOCS_FOR_BERTOPIC:
                st.info(
                    f"📡 {total_docs} documents ready. "
                    "Go to **Signal Dashboard** to detect signals."
                )
            else:
                needed = config.MIN_DOCS_FOR_BERTOPIC - total_docs
                st.warning(
                    f"⚠️ {total_docs}/{config.MIN_DOCS_FOR_BERTOPIC} documents uploaded. "
                    f"Need {needed} more to enable signal detection."
                )


# ── Page: Signal Dashboard ────────────────────────────────────────────────────

elif page == "📡 Signal Dashboard":
    st.title("📡 Signal Dashboard")

    store = get_store()
    anon_docs = st.session_state.anon_docs
    total_docs = len(anon_docs)

    # ── Filter bar ──────────────────────────────────────────────────────────────
    col_filter1, col_filter2, col_btn, col_export = st.columns([2, 2, 1, 1])

    with col_filter1:
        category_filter = st.selectbox(
            "Category",
            ["All", "Delivery Risk", "Team Health", "Attrition", "Bus Factor",
             "Technical Debt", "Operational", "Dependency"],
            label_visibility="visible",
        )

    with col_filter2:
        severity_filter = st.selectbox(
            "Severity",
            ["All", "Strong", "Weak"],
            label_visibility="visible",
        )

    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        run_disabled = total_docs < config.MIN_DOCS_FOR_BERTOPIC
        detect_clicked = st.button(
            "🔍 Detect Signals",
            type="primary",
            disabled=run_disabled,
            help=f"Requires {config.MIN_DOCS_FOR_BERTOPIC} documents minimum.",
            use_container_width=True,
        )

    # ── Run pipeline ────────────────────────────────────────────────────────────
    if detect_clicked:
        _do_rerun = False

        with st.spinner("Running signal detection pipeline…"):
            try:
                from src.signals.aggregator import aggregate_signals
                from src.signals.confidence import compute_confidence
                from src.signals.detector import detect_signals
                from src.signals.embedder import embed_documents, get_all_embeddings

                embed_documents(anon_docs)
                documents, embeddings, metadatas = get_all_embeddings()

                if not documents or len(documents) == 0:
                    st.error("No embeddings found. Please upload documents first.")
                else:
                    raw_signals = detect_signals(documents, embeddings, metadatas)

                    # Aggregate: merge semantically equivalent signals by category
                    signals = aggregate_signals(raw_signals)

                    if not signals:
                        st.session_state.pipeline_ran = True
                        st.warning(
                            "⚠️ All signals were classified as NOISE. "
                            "Upload more varied documents to detect patterns."
                        )
                        _do_rerun = True
                    else:
                        # Validate evidence for every actionable signal
                        validation_results = validate_signals(signals, anon_docs)

                        # ── Save evidence to SQLite (THE critical fix) ──────────
                        for vr in validation_results:
                            if vr.passed:
                                for ev in vr.evidence_list:
                                    try:
                                        store.save_evidence(ev)
                                    except Exception:
                                        pass  # already exists — upsert handles it

                        # Build evidence lookup for confidence engine
                        evidence_by_signal: dict[str, list] = {
                            vr.signal.id: vr.evidence_list
                            for vr in validation_results if vr.passed
                        }

                        # Build risks from validated signals
                        risks = build_risks(validation_results)

                        # Compute confidence scores and store in session
                        confidence_map: dict[str, int] = {}
                        for sig in signals:
                            ev_list = evidence_by_signal.get(sig.id, [])
                            score, _ = compute_confidence(sig, ev_list, total_docs=total_docs)
                            confidence_map[sig.id] = score

                        # Narrate with category-specific prompts
                        signal_titles = {s.id: s.title for s in signals}
                        signal_categories = {s.id: s.category for s in signals}
                        narrate_risks(
                            risks,
                            signal_titles=signal_titles,
                            signal_categories=signal_categories,
                        )

                        # Build narration lookup
                        narration_map = {r.signal_id: r.narration for r in risks if r.narration}

                        # Save signals with narration and computed confidence %
                        for signal in signals:
                            store.save_signal(
                                signal,
                                narration=narration_map.get(signal.id),
                                confidence_score=confidence_map.get(signal.id),
                            )

                        # Update knowledge graph
                        kg = get_kg()
                        for vr in validation_results:
                            if vr.passed and anon_docs:
                                kg.add_signal(vr.signal, anon_docs[0])

                        st.session_state.pipeline_ran = True
                        st.session_state.confidence_map = confidence_map
                        actionable_count = len(signals)
                        st.success(f"✅ Detection complete — {actionable_count} actionable signals found.")
                        _do_rerun = True

            except Exception as e:
                st.error(f"Pipeline error: {e}")

        if _do_rerun:
            st.rerun()

    if run_disabled:
        st.warning(
            f"⚠️ Need {config.MIN_DOCS_FOR_BERTOPIC - total_docs} more documents "
            f"(currently {total_docs}/{config.MIN_DOCS_FOR_BERTOPIC})."
        )

    st.markdown("---")

    # ── Signal cards ────────────────────────────────────────────────────────────
    active_signals = store.get_active_signals()
    actionable = [s for s in active_signals if s["severity"] in ("STRONG", "WEAK")]

    # Apply filters
    if category_filter != "All":
        cat_key = category_filter.lower().replace(" ", "_")
        actionable = [s for s in actionable if s["category"] == cat_key]

    if severity_filter != "All":
        actionable = [s for s in actionable if s["severity"] == severity_filter.upper()]

    # Export button
    with col_export:
        st.markdown("<br>", unsafe_allow_html=True)
        if actionable:
            df_export = pd.DataFrame(
                [
                    {
                        "Title": s["title"],
                        "Category": s["category"],
                        "Severity": s["severity"],
                        "Confidence": s["confidence_band"],
                        "Trend": s["trend"],
                        "Owner": s["suggested_owner_role"],
                        "Detected": s["created_at"][:10],
                        "Status": s["status"],
                    }
                    for s in actionable
                ]
            )
            csv_bytes = df_export.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ Export CSV",
                data=csv_bytes,
                file_name="signalnoise_signals.csv",
                mime="text/csv",
                use_container_width=True,
            )

    if not actionable:
        st.info("No active signals yet. Upload documents and click **Detect Signals**.")
    else:
        strong_signals = [s for s in actionable if s["severity"] == "STRONG"]
        weak_signals = [s for s in actionable if s["severity"] == "WEAK"]

        if strong_signals:
            st.markdown(f"### 🔴 Strong Signals ({len(strong_signals)})")
            for sig in strong_signals:
                _render_signal_card(sig, store)

        if weak_signals:
            st.markdown(f"### 🟡 Weak Signals ({len(weak_signals)})")
            for sig in weak_signals:
                _render_signal_card(sig, store)


# ── Page: Analytics ───────────────────────────────────────────────────────────

elif page == "📊 Analytics":
    st.title("📊 Analytics")

    store = get_store()
    all_signals = store.get_active_signals()

    if not all_signals:
        st.info("No signals detected yet. Upload documents and run detection first.")
    else:
        df = pd.DataFrame(all_signals)

        # ── Programme Health Score ────────────────────────────────────────────────
        total = len(df)
        strong = len(df[df["severity"] == "STRONG"])
        weak = len(df[df["severity"] == "WEAK"])
        confirmed = len(df[df["status"] == "confirmed"])
        dismissed = len(df[df["status"] == "dismissed"])
        avg_confidence = (
            int(df["confidence_score"].dropna().mean())
            if "confidence_score" in df.columns and df["confidence_score"].notna().any()
            else None
        )
        # Score: 100 − (strong*15 + weak*5), min 0
        health_score = max(0, 100 - strong * 15 - weak * 5)
        health_label = (
            "🟢 Healthy" if health_score >= 80
            else "🟡 At Risk" if health_score >= 50
            else "🔴 Critical"
        )

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Programme Health", f"{health_score}/100", health_label)
        col2.metric("🔴 Strong", strong)
        col3.metric("🟡 Weak", weak)
        col4.metric("✅ Confirmed", confirmed)
        col5.metric("Avg Confidence", f"{avg_confidence}%" if avg_confidence else "—")

        st.markdown("---")

        # ── Charts row 1 ─────────────────────────────────────────────────────────
        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            st.markdown("#### Signals by Category")
            cat_counts = df["category"].value_counts().reset_index()
            cat_counts.columns = ["Category", "Count"]
            cat_counts["Category"] = cat_counts["Category"].str.replace("_", " ").str.title()
            st.bar_chart(cat_counts.set_index("Category"))

        with chart_col2:
            st.markdown("#### Confidence Distribution")
            if "confidence_score" in df.columns and df["confidence_score"].notna().any():
                conf_df = df[["title", "confidence_score"]].dropna().copy()
                conf_df["title"] = conf_df["title"].str[:30]
                conf_df = conf_df.sort_values("confidence_score", ascending=False)
                st.bar_chart(conf_df.set_index("title")["confidence_score"])
            else:
                sev_counts = df["severity"].value_counts().reset_index()
                sev_counts.columns = ["Severity", "Count"]
                st.bar_chart(sev_counts.set_index("Severity"))

        # ── Charts row 2 ─────────────────────────────────────────────────────────
        chart_col3, chart_col4 = st.columns(2)

        with chart_col3:
            st.markdown("#### Top Risk Owners")
            owner_counts = df["suggested_owner_role"].value_counts().reset_index()
            owner_counts.columns = ["Owner", "Signals"]
            st.bar_chart(owner_counts.set_index("Owner"))

        with chart_col4:
            st.markdown("#### Signal Status Breakdown")
            status_counts = df["status"].value_counts().reset_index()
            status_counts.columns = ["Status", "Count"]
            st.bar_chart(status_counts.set_index("Status"))

        st.markdown("---")

        # ── Signal table ─────────────────────────────────────────────────────────
        st.markdown("#### All Signals")
        display_cols = ["title", "category", "severity", "confidence_score",
                        "trend", "suggested_owner_role", "status", "created_at"]
        available_cols = [c for c in display_cols if c in df.columns]
        display_df = df[available_cols].copy()
        col_labels = {
            "title": "Signal", "category": "Category", "severity": "Severity",
            "confidence_score": "Confidence %", "trend": "Trend",
            "suggested_owner_role": "Owner", "status": "Status", "created_at": "Detected",
        }
        display_df.rename(columns=col_labels, inplace=True)
        if "Detected" in display_df.columns:
            display_df["Detected"] = display_df["Detected"].str[:10]
        if "Confidence %" in display_df.columns:
            display_df["Confidence %"] = display_df["Confidence %"].apply(
                lambda x: f"{int(x)}%" if pd.notna(x) else "—"
            )
        st.dataframe(display_df, use_container_width=True, hide_index=True)


# ── Page: Audit Log ───────────────────────────────────────────────────────────

elif page == "📋 Audit Log":
    st.title("📋 Audit Log")
    st.markdown("Every system action logged for privacy compliance.")

    store = get_store()
    logs = store.get_audit_log(limit=100)

    if not logs:
        st.info("No audit entries yet.")
    else:
        df = pd.DataFrame(logs)
        if all(c in df.columns for c in ["created_at", "action", "entity_type", "entity_id"]):
            display_df = df[["created_at", "action", "entity_type", "entity_id", "detail"]].copy()
            display_df.columns = ["Timestamp", "Action", "Entity Type", "Entity ID", "Detail"]
            display_df["Entity ID"] = display_df["Entity ID"].str[:8] + "…"
            display_df["Timestamp"] = display_df["Timestamp"].str[:19]
            display_df["Detail"] = display_df["Detail"].fillna("—")
            st.dataframe(display_df, use_container_width=True, hide_index=True)

            # Summary counts
            action_counts = df["action"].value_counts()
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Documents Uploaded", int(action_counts.get("document_uploaded", 0)))
            col_b.metric("Signals Detected", int(action_counts.get("signal_detected", 0)))
            col_c.metric("Feedback Given", int(action_counts.get("feedback_given", 0)))

            csv_bytes = display_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ Export Audit Log",
                data=csv_bytes,
                file_name="signalnoise_audit_log.csv",
                mime="text/csv",
            )
