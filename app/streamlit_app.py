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

def _render_signal_card(sig: dict, store: MemoryStore) -> None:
    """Render a single signal card with evidence, narration, and feedback buttons."""
    severity_icon = {"STRONG": "🔴", "WEAK": "🟡", "NOISE": "⚪"}.get(sig["severity"], "⚪")
    trend_icon = {"emerging": "📈", "stable": "➡️", "fading": "📉"}.get(sig["trend"], "➡️")
    confidence_label = {
        "high": "High confidence",
        "medium": "Medium confidence",
        "low": "Low confidence",
    }.get(sig["confidence_band"], "")

    with st.expander(
        f"{severity_icon} **{sig['title']}**  ·  {trend_icon} {sig['trend'].title()}  ·  {confidence_label}",
        expanded=(sig["severity"] == "STRONG"),
    ):
        col_detail, col_action = st.columns([3, 1])

        with col_detail:
            cat_display = sig["category"].replace("_", " ").title()
            st.markdown(f"**Category:** {cat_display}")
            st.markdown(f"**Suggested owner:** `{sig['suggested_owner_role']}`")
            st.markdown(f"**Detected:** {sig['created_at'][:10]}")

            # Evidence snippets from store
            evidence = store.get_evidence_for_signal(sig["id"])
            if evidence:
                st.markdown("**Evidence:**")
                for ev in evidence[:3]:
                    st.markdown(f"> _{ev['snippet']}_")

        with col_action:
            st.markdown("**Your feedback:**")
            reviewer_role = st.selectbox(
                "Your role",
                ["Programme-Manager", "Director", "SRE-Lead"],
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
            ["All", "Delivery Risk", "Team Health", "Operational", "Dependency"],
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
                from src.signals.detector import detect_signals
                from src.signals.embedder import embed_documents, get_all_embeddings

                embed_documents(anon_docs)
                documents, embeddings, metadatas = get_all_embeddings()

                if not documents or len(documents) == 0:
                    st.error("No embeddings found. Please upload documents first.")
                else:
                    signals = detect_signals(documents, embeddings, metadatas)
                    actionable_signals = [s for s in signals if s.is_actionable()]

                    if not actionable_signals:
                        for signal in signals:
                            store.save_signal(signal)
                        st.session_state.pipeline_ran = True
                        st.warning(
                            "⚠️ All signals were classified as NOISE. "
                            "Upload more varied documents to detect patterns."
                        )
                        _do_rerun = True
                    else:
                        validation_results = validate_signals(actionable_signals, anon_docs)
                        risks = build_risks(validation_results)
                        signal_titles = {s.id: s.title for s in signals}
                        narrate_risks(risks, signal_titles=signal_titles)

                        for signal in signals:
                            store.save_signal(signal)

                        kg = get_kg()
                        for vr in validation_results:
                            if vr.passed and anon_docs:
                                kg.add_signal(vr.signal, anon_docs[0])

                        st.session_state.pipeline_ran = True
                        actionable_count = sum(1 for s in signals if s.is_actionable())
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

        # ── Summary metrics ──────────────────────────────────────────────────────
        col1, col2, col3, col4 = st.columns(4)
        total = len(df)
        strong = len(df[df["severity"] == "STRONG"])
        weak = len(df[df["severity"] == "WEAK"])
        confirmed = len(df[df["status"] == "confirmed"])

        col1.metric("Total Signals", total)
        col2.metric("🔴 Strong", strong)
        col3.metric("🟡 Weak", weak)
        col4.metric("✅ Confirmed", confirmed)

        st.markdown("---")

        # ── Charts ───────────────────────────────────────────────────────────────
        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            st.markdown("#### Signals by Category")
            if "category" in df.columns:
                cat_counts = df["category"].value_counts().reset_index()
                cat_counts.columns = ["Category", "Count"]
                cat_counts["Category"] = cat_counts["Category"].str.replace("_", " ").str.title()
                st.bar_chart(cat_counts.set_index("Category"))

        with chart_col2:
            st.markdown("#### Signals by Severity")
            if "severity" in df.columns:
                sev_counts = df["severity"].value_counts().reset_index()
                sev_counts.columns = ["Severity", "Count"]
                st.bar_chart(sev_counts.set_index("Severity"))

        st.markdown("---")

        # ── Signal table ─────────────────────────────────────────────────────────
        st.markdown("#### All Signals")
        display_cols = ["title", "category", "severity", "confidence_band", "trend", "status", "created_at"]
        available_cols = [c for c in display_cols if c in df.columns]
        display_df = df[available_cols].copy()
        display_df.columns = [c.replace("_", " ").title() for c in display_df.columns]
        if "Created At" in display_df.columns:
            display_df["Created At"] = display_df["Created At"].str[:10]
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
            display_df = df[["created_at", "action", "entity_type", "entity_id"]].copy()
            display_df.columns = ["Timestamp", "Action", "Entity Type", "Entity ID"]
            display_df["Entity ID"] = display_df["Entity ID"].str[:8] + "…"
            display_df["Timestamp"] = display_df["Timestamp"].str[:19]
            st.dataframe(display_df, use_container_width=True, hide_index=True)

            # Export audit log
            csv_bytes = display_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ Export Audit Log",
                data=csv_bytes,
                file_name="signalnoise_audit_log.csv",
                mime="text/csv",
            )
