"""
app/streamlit_app.py

SignalNoise AI — Streamlit Dashboard
Sprint 1 version: Upload → Process → Signal Cards → Confirm/Dismiss

Run:
    streamlit run app/streamlit_app.py
"""

import os
import sys
import uuid
from pathlib import Path

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("GROQ_API_KEY", "not-set")

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
    st.markdown("---")
    st.markdown("### Navigation")
    page = st.radio(
        "Go to",
        ["📤 Upload Documents", "📡 Signal Dashboard", "📋 Audit Log"],
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
    st.markdown("---")
    st.caption("SignalNoise AI · Sprint 1 · FLM Learning")


# ── Helper functions (must be defined before page routing) ───────────────────

def _render_signal_card(sig: dict, store: MemoryStore) -> None:
    """Render a single signal card with evidence and feedback buttons."""
    severity_color = {"STRONG": "🔴", "WEAK": "🟡", "NOISE": "⚪"}.get(sig["severity"], "⚪")
    trend_icon = {"emerging": "📈", "stable": "➡️", "fading": "📉"}.get(sig["trend"], "➡️")
    confidence_label = {"high": "High confidence", "medium": "Medium confidence", "low": "Low confidence"}.get(
        sig["confidence_band"], ""
    )

    with st.expander(
        f"{severity_color} **{sig['title']}** · {trend_icon} {sig['trend'].title()} · {confidence_label}",
        expanded=sig["severity"] == "STRONG",
    ):
        col1, col2 = st.columns([3, 1])

        with col1:
            st.markdown(f"**Category:** {sig['category'].replace('_', ' ').title()}")
            st.markdown(f"**Suggested owner:** `{sig['suggested_owner_role']}`")
            st.markdown(f"**Detected:** {sig['created_at'][:10]}")

            evidence = store.get_evidence_for_signal(sig["id"])
            if evidence:
                st.markdown("**Evidence:**")
                for ev in evidence[:3]:
                    st.markdown(f"> _{ev['snippet']}_")

        with col2:
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
    st.toast(f"{'✅ Confirmed' if decision == 'confirmed' else '❌ Dismissed'}", icon="📋")


# ── Page: Upload Documents ────────────────────────────────────────────────────

if page == "📤 Upload Documents":
    st.title("📤 Upload Documents")
    st.markdown(
        "Upload meeting notes, incident logs, status reports, or ticket exports. "
        "Supported formats: **.txt · .docx · .pdf**"
    )

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
                    text=f"Processing {uploaded_file.name}...",
                )

                # Save uploaded file to data/raw/ temporarily
                raw_path = config.RAW_DATA_DIR / f"{uuid.uuid4()}_{uploaded_file.name}"
                raw_path.write_bytes(uploaded_file.read())

                try:
                    # Step 1 — Load and quality check
                    doc = load_file(raw_path, source_type=source_type)
                    store.save_document(doc)

                    # Step 2 — Anonymize
                    anon_doc = anonymize(doc)
                    anon_docs.append(anon_doc)

                    # Step 3 — Add to knowledge graph
                    kg.add_document(anon_doc)

                    store.mark_document_processed(doc.id)

                except Exception as e:
                    failed.append((uploaded_file.name, str(e)))

                finally:
                    # Delete raw file from disk (privacy compliance)
                    if raw_path.exists():
                        raw_path.unlink()

            progress.empty()

            if anon_docs:
                st.session_state.anon_docs.extend(anon_docs)
                st.success(f"✅ {len(anon_docs)} document(s) processed and anonymized.")

            if failed:
                for name, reason in failed:
                    st.error(f"❌ **{name}** — {reason}")

            # Run signal detection if we have enough documents
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
                    f"Upload {needed} more to enable signal detection."
                )


# ── Page: Signal Dashboard ────────────────────────────────────────────────────

elif page == "📡 Signal Dashboard":
    st.title("📡 Signal Dashboard")

    store = get_store()
    anon_docs = st.session_state.anon_docs
    total_docs = len(anon_docs)

    # ── Run pipeline button
    col_btn, col_info = st.columns([2, 3])
    with col_btn:
        run_disabled = total_docs < config.MIN_DOCS_FOR_BERTOPIC
        if st.button(
            "🔍 Detect Signals",
            type="primary",
            disabled=run_disabled,
            help=f"Requires {config.MIN_DOCS_FOR_BERTOPIC} documents minimum.",
        ):
            _do_rerun = False   # set True on success — rerun happens OUTSIDE try/except

            with st.spinner("Running signal detection pipeline..."):
                try:
                    # Import here to avoid slow load on every page
                    from src.signals.embedder import embed_documents, get_all_embeddings
                    from src.signals.detector import detect_signals

                    # Embed all anonymized documents
                    embed_documents(anon_docs)

                    # Get embeddings from ChromaDB
                    documents, embeddings, metadatas = get_all_embeddings()

                    if not documents or len(documents) == 0:
                        st.error("No embeddings found. Please upload documents first.")
                    else:
                        # Detect signals
                        signals = detect_signals(documents, embeddings, metadatas)

                        # Split actionable vs noise
                        actionable_signals = [s for s in signals if s.is_actionable()]

                        if not actionable_signals:
                            # All signals are NOISE — save and show warning
                            for signal in signals:
                                store.save_signal(signal)
                            st.session_state.pipeline_ran = True
                            st.warning(
                                "⚠️ All signals were classified as NOISE. "
                                "Upload more varied documents to detect patterns."
                            )
                            _do_rerun = True
                        else:
                            # Validate evidence
                            validation_results = validate_signals(
                                actionable_signals,
                                anon_docs,
                            )

                            # Build risks
                            risks = build_risks(validation_results)

                            # Narrate
                            signal_titles = {s.id: s.title for s in signals}
                            narrate_risks(risks, signal_titles=signal_titles)

                            # Save to store
                            for signal in signals:
                                store.save_signal(signal)

                            # Update knowledge graph with signals
                            kg = get_kg()
                            for vr in validation_results:
                                if vr.passed and anon_docs:
                                    kg.add_signal(vr.signal, anon_docs[0])

                            st.session_state.pipeline_ran = True
                            st.success(
                                f"✅ Detection complete — "
                                f"{sum(1 for s in signals if s.is_actionable())} actionable signals found."
                            )
                            _do_rerun = True

                except Exception as e:
                    st.error(f"Pipeline error: {e}")

            # Rerun OUTSIDE try/except so RerunException propagates cleanly
            if _do_rerun:
                st.rerun()

    with col_info:
        if run_disabled:
            st.warning(
                f"⚠️ Need {config.MIN_DOCS_FOR_BERTOPIC - total_docs} more documents "
                f"(currently {total_docs}/{config.MIN_DOCS_FOR_BERTOPIC})."
            )

    st.markdown("---")

    # ── Signal cards
    active_signals = store.get_active_signals()
    actionable = [s for s in active_signals if s["severity"] in ("STRONG", "WEAK")]

    if not actionable:
        st.info(
            "No active signals yet. Upload documents and click **Detect Signals**."
        )
    else:
        strong_signals = [s for s in actionable if s["severity"] == "STRONG"]
        weak_signals = [s for s in actionable if s["severity"] == "WEAK"]

        if strong_signals:
            st.markdown("### 🔴 Strong Signals")
            for sig in strong_signals:
                _render_signal_card(sig, store)

        if weak_signals:
            st.markdown("### 🟡 Weak Signals")
            for sig in weak_signals:
                _render_signal_card(sig, store)


# ── Page: Audit Log ───────────────────────────────────────────────────────────

elif page == "📋 Audit Log":
    st.title("📋 Audit Log")
    st.markdown("Every system action logged for privacy compliance.")

    store = get_store()
    logs = store.get_audit_log(limit=100)

    if not logs:
        st.info("No audit entries yet.")
    else:
        import pandas as pd
        df = pd.DataFrame(logs)[["created_at", "action", "entity_type", "entity_id"]]
        df.columns = ["Timestamp", "Action", "Entity Type", "Entity ID"]
        df["Entity ID"] = df["Entity ID"].str[:8] + "..."
        st.dataframe(df, use_container_width=True, hide_index=True)
