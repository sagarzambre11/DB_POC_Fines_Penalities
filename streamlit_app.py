"""
streamlit_app.py
----------------
Regulatory Enforcement Intelligence PoC — v4 (Agentic RAG)

AI-powered, regulator-agnostic gap analysis pipeline:
  Step 1 — Upload ANY enforcement document (FCA, DFS, SEC, MAS, etc.)
  Step 2 — Extract structured intelligence via Azure OpenAI
  Step 3 — Load GRC Inventory (default / Excel upload / controls document upload)
           + Build semantic vector index
  Step 4 — Run Controls Gap Analysis (Agentic RAG / Standard RAG / Full Scan)
  Step 5 — View shift-left signals, stakeholder alerts, and download report
"""

import time
import streamlit as st

from config import AzureOpenAIConfig, EmbeddingConfig, AppConfig
from app.parser import parse_document, get_document_preview
from app.extractor import extract_enforcement_data, get_extraction_summary
from app.inventory import (
    load_inventory,
    load_inventory_from_bytes,
    extract_controls_from_document,
    inventory_to_dataframe,
    get_inventory_summary,
)
from app.comparator import compare_findings_to_inventory, get_overall_assessment
from app.agents.orchestrator import run_agentic_pipeline
from app.reporter import (
    build_controls_gap_dataframe,
    build_stakeholder_signals_dataframe,
    build_unaddressed_findings_dataframe,
    generate_excel_report,
    get_report_filename,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Regulatory Enforcement Intelligence",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
.main-title  { font-size:2rem; font-weight:700; color:#1F4E79; margin-bottom:.2rem; }
.sub-title   { font-size:1rem; color:#555; margin-bottom:1.2rem; }
.step-header { background:#1F4E79; color:white; padding:.4rem .8rem;
               border-radius:6px; font-weight:600; font-size:1rem; margin-bottom:.5rem; }
.shift-left-box { background:#FFF3CD; border-left:5px solid #FFC107;
                  padding:.8rem 1rem; border-radius:4px; margin:.5rem 0; }
.signal-box { background:#F8D7DA; border-left:5px solid #DC3545;
              padding:.8rem 1rem; border-radius:4px; margin:.5rem 0; }
.rag-box    { background:#E8F4FD; border-left:5px solid #1F4E79;
              padding:.8rem 1rem; border-radius:4px; margin:.5rem 0; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------
for _key in [
    "document_text", "extracted_data", "inventory", "comparison",
    "uploaded_filename", "rag_collection", "rag_index_built",
    "inventory_source",    # "default" | "excel" | "document"
    "inventory_filename",  # display name of the current inventory source
]:
    if _key not in st.session_state:
        st.session_state[_key] = None

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## ⚙️ Configuration")

    missing_llm = AzureOpenAIConfig.validate()
    if missing_llm:
        st.error(
            "Missing Azure OpenAI config:\n\n" +
            "\n".join(f"- `{k}`" for k in missing_llm) +
            "\n\nUpdate your `.env` file."
        )
    else:
        st.success("✅ Azure OpenAI (LLM) connected")
        st.markdown(f"**LLM:** `{AzureOpenAIConfig.DEPLOYMENT}`")

    st.divider()
    st.markdown("## 🧠 Embedding Provider")
    missing_emb = EmbeddingConfig.validate()
    if missing_emb:
        st.warning(
            "Embedding config issue:\n\n" +
            "\n".join(f"- `{k}`" for k in missing_emb) +
            "\n\nRAG mode will fall back to full scan."
        )
    else:
        st.success(f"✅ {EmbeddingConfig.provider_display()}")
    st.caption(
        f"Set `EMBEDDING_PROVIDER=google` in `.env` to switch providers. "
        f"Currently: `{EmbeddingConfig.PROVIDER}`"
    )

    st.divider()
    st.markdown("## 📋 Pipeline")
    st.markdown("""
1. 📄 Upload Enforcement Document
2. 🔍 Extract Intelligence (LLM)
3. 📊 Load GRC Inventory + Semantic Index
4. 🤖 Run Controls Gap Analysis
5. 📥 View Results & Download
""")
    st.divider()
    st.markdown("**Version:** 4.0 — Agentic RAG")
    st.markdown(f"**LLM:** `{AzureOpenAIConfig.DEPLOYMENT}`")
    st.markdown(f"**Embeddings:** `{EmbeddingConfig.PROVIDER}`")

    st.divider()
    st.markdown("## 🔢 Token Usage")
    ext_usage = (st.session_state.get("extracted_data") or {}).get("_token_usage", {})
    cmp_usage = (st.session_state.get("comparison") or {}).get("_token_usage", {})
    rag_meta  = (st.session_state.get("comparison") or {}).get("_rag_metadata", {})

    if not ext_usage and not cmp_usage:
        st.caption("Token counts appear here after running the pipeline.")
    else:
        if ext_usage:
            st.markdown("**Step 2 — Extraction**")
            st.markdown(
                f"Input: `{ext_usage.get('prompt_tokens', 0):,}` | "
                f"Output: `{ext_usage.get('completion_tokens', 0):,}` | "
                f"Total: `{ext_usage.get('total_tokens', 0):,}`"
            )
        if cmp_usage:
            st.markdown("**Step 4 — Gap Analysis**")
            st.markdown(
                f"Input: `{cmp_usage.get('prompt_tokens', 0):,}` | "
                f"Output: `{cmp_usage.get('completion_tokens', 0):,}` | "
                f"Total: `{cmp_usage.get('total_tokens', 0):,}`"
            )
        if rag_meta:
            assessed  = rag_meta.get("controls_assessed", "?")
            total_inv = rag_meta.get("total_inventory", "?")
            reduction = rag_meta.get("reduction_pct", 0)
            st.markdown(
                f"**RAG:** `{assessed}` / `{total_inv}` controls "
                f"· `{reduction:.0f}%` reduction"
            )
        if ext_usage and cmp_usage:
            grand_total = (
                ext_usage.get("total_tokens", 0) + cmp_usage.get("total_tokens", 0)
            )
            st.markdown("---")
            st.markdown(f"**Grand Total: `{grand_total:,}` tokens**")

# ---------------------------------------------------------------------------
# Main title
# ---------------------------------------------------------------------------
st.markdown(
    '<div class="main-title">🏦 Regulatory Enforcement Intelligence</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="sub-title">Agentic RAG-powered controls gap analysis — '
    'enforcement documents mapped to your GRC inventory via self-correcting agents. '
    'Works for any regulator (FCA, DFS, SEC, MAS, FINRA...) and any compliance domain.</div>',
    unsafe_allow_html=True,
)
st.divider()


# ---------------------------------------------------------------------------
# Helper: token badge
# ---------------------------------------------------------------------------
def _render_token_badge(usage: dict, label: str = "") -> None:
    if not usage:
        return
    prefix = f"**{label}** — " if label else ""
    st.caption(
        f"🔢 {prefix}"
        f"Input: **{usage.get('prompt_tokens', 0):,}** · "
        f"Output: **{usage.get('completion_tokens', 0):,}** · "
        f"Total: **{usage.get('total_tokens', 0):,}** tokens"
    )


def _reset_index_and_comparison() -> None:
    """Reset downstream state when the inventory changes."""
    st.session_state.rag_collection = None
    st.session_state.rag_index_built = False
    st.session_state.comparison = None


# ---------------------------------------------------------------------------
# STEP 1 — Upload Enforcement Document
# ---------------------------------------------------------------------------
st.markdown(
    '<div class="step-header">Step 1 — Upload Enforcement Document (any regulator)</div>',
    unsafe_allow_html=True,
)

uploaded_file = st.file_uploader(
    "Upload a regulatory enforcement document — FCA Final Notice, DFS Consent Order, "
    "SEC Order, MAS Notice, FINRA Action, etc.",
    type=["docx", "pdf"],
    help="Supported formats: .docx and .pdf",
)

if uploaded_file is not None:
    if uploaded_file.name != st.session_state.uploaded_filename:
        st.session_state.extracted_data = None
        st.session_state.comparison = None
        st.session_state.uploaded_filename = uploaded_file.name
        with st.spinner(f"Parsing **{uploaded_file.name}**..."):
            try:
                file_bytes = uploaded_file.read()
                st.session_state.document_text = parse_document(file_bytes, uploaded_file.name)
                st.success(
                    f"✅ Document parsed — "
                    f"**{len(st.session_state.document_text):,}** characters extracted."
                )
            except ValueError as e:
                st.error(str(e))
                st.session_state.document_text = None

    if st.session_state.document_text:
        with st.expander("📄 Document Preview (first 1,000 characters)", expanded=False):
            st.text(get_document_preview(st.session_state.document_text, max_chars=1000))

st.divider()

# ---------------------------------------------------------------------------
# STEP 2 — Extract Intelligence
# ---------------------------------------------------------------------------
st.markdown(
    f'<div class="step-header">Step 2 — Extract Enforcement Intelligence '
    f'({AzureOpenAIConfig.DEPLOYMENT})</div>',
    unsafe_allow_html=True,
)

if st.session_state.document_text is None:
    st.info("⬆️ Upload a document in Step 1 to proceed.")
else:
    col1, _ = st.columns([1, 3])
    with col1:
        extract_btn = st.button(
            "🔍 Extract Intelligence", type="primary", use_container_width=True
        )

    if extract_btn:
        with st.spinner(f"{AzureOpenAIConfig.DEPLOYMENT} extracting enforcement intelligence..."):
            try:
                st.session_state.extracted_data = extract_enforcement_data(
                    st.session_state.document_text
                )
                st.session_state.comparison = None
                st.success("✅ Extraction complete.")
            except Exception as e:
                st.error(f"Extraction failed: {e}")
                st.session_state.extracted_data = None

    if st.session_state.extracted_data:
        _render_token_badge(
            st.session_state.extracted_data.get("_token_usage", {}),
            label="Step 2 token usage",
        )
        ed       = st.session_state.extracted_data
        reg      = ed.get("regulator", {})
        entity   = ed.get("regulated_entity", {})
        action   = ed.get("enforcement_action", {})
        domains  = ", ".join(ed.get("regulatory_domain", []))
        penalty  = action.get("penalty_amount")
        currency = action.get("penalty_currency", "")

        st.markdown("##### 🌍 Auto-Detected Enforcement Intelligence")
        r1c1, r1c2, r1c3, r1c4 = st.columns(4)
        r1c1.metric("Regulator",   reg.get("abbreviation") or reg.get("name", "N/A"))
        r1c2.metric("Jurisdiction", ed.get("jurisdiction", "N/A"))
        r1c3.metric("Entity",       entity.get("name", "N/A")[:30])
        r1c4.metric("Penalty",      f"{currency} {penalty:,}" if penalty else "N/A")

        r2c1, r2c2, r2c3, r2c4 = st.columns(4)
        r2c1.metric("Domain(s)",         domains[:40] if domains else "N/A")
        r2c2.metric("Notice Date",        action.get("notice_date", "N/A"))
        r2c3.metric("Misconduct Themes",  len(ed.get("misconduct_control_failure_themes", [])))
        r2c4.metric("Confidence",         get_extraction_summary(ed).get("Confidence Score", "N/A"))

        with st.expander("🔎 Full Extracted JSON", expanded=False):
            st.json(ed)

st.divider()

# ---------------------------------------------------------------------------
# STEP 3 — GRC Inventory + Semantic Index
# ---------------------------------------------------------------------------
st.markdown(
    '<div class="step-header">Step 3 — GRC Inventory + Semantic Index</div>',
    unsafe_allow_html=True,
)

# ── Inventory source selector ─────────────────────────────────────────────
inv_source = st.radio(
    "**GRC Inventory Source:**",
    options=[
        "📁 Default (docs/grc_inventory.xlsx)",
        "📊 Upload Excel Inventory (.xlsx)",
        "📄 Upload Controls Document (DOCX/PDF)",
    ],
    index=0,
    horizontal=True,
    help=(
        "Choose how to load the GRC control inventory:\n"
        "• Default — uses the bundled grc_inventory.xlsx\n"
        "• Excel — upload your own .xlsx inventory file\n"
        "• Controls Document — upload a DOCX/PDF and the LLM extracts controls from it"
    ),
)

if inv_source == "📁 Default (docs/grc_inventory.xlsx)":
    # Auto-load default from disk; reload if switching back from another source
    if st.session_state.inventory is None or st.session_state.inventory_source != "default":
        try:
            st.session_state.inventory = load_inventory()
            st.session_state.inventory_source = "default"
            st.session_state.inventory_filename = AppConfig.GRC_INVENTORY_PATH
            _reset_index_and_comparison()
        except Exception as e:
            st.error(f"Failed to load default GRC inventory: {e}")

elif inv_source == "📊 Upload Excel Inventory (.xlsx)":
    uploaded_inv = st.file_uploader(
        "Upload GRC Inventory (.xlsx)",
        type=["xlsx"],
        help=(
            f"Required sheet: '{AppConfig.GRC_SHEET_NAME}' (first sheet used if not found). "
            "Required columns: control_id, control_name, control_objective, "
            "control_description, control_type, frequency, trigger, process, "
            "regulatory_domain, owner, status."
        ),
        key="inv_excel_uploader",
    )
    if uploaded_inv is not None:
        if uploaded_inv.name != st.session_state.inventory_filename:
            with st.spinner(f"Loading inventory from **{uploaded_inv.name}**..."):
                try:
                    inv_bytes = uploaded_inv.read()
                    st.session_state.inventory = load_inventory_from_bytes(inv_bytes)
                    st.session_state.inventory_source = "excel"
                    st.session_state.inventory_filename = uploaded_inv.name
                    _reset_index_and_comparison()
                    st.success(
                        f"✅ Loaded **{len(st.session_state.inventory)}** controls "
                        f"from **{uploaded_inv.name}**. Rebuild the semantic index below."
                    )
                except (ValueError, RuntimeError) as e:
                    st.error(f"❌ Failed to load inventory: {e}")
                    st.session_state.inventory = None
                    st.session_state.inventory_filename = None

else:  # "📄 Upload Controls Document (DOCX/PDF)"
    st.markdown(
        "Upload a controls policy document (Word or PDF). "
        "The LLM will read it and extract all GRC controls into the standard inventory format."
    )
    uploaded_ctrl_doc = st.file_uploader(
        "Upload Controls Document (.docx or .pdf)",
        type=["docx", "pdf"],
        help=(
            "Examples: Controls Framework PDF, Policy Manual DOCX, Procedure Document. "
            "The LLM extracts control_id, name, objective, description, type, frequency, "
            "trigger, process, domain, owner and status from the document text."
        ),
        key="ctrl_doc_uploader",
    )
    if uploaded_ctrl_doc is not None:
        if uploaded_ctrl_doc.name != st.session_state.inventory_filename:
            _ctrl_status = st.empty()

            def _ctrl_progress(msg: str) -> None:
                _ctrl_status.info(msg)

            with st.spinner(f"Parsing and extracting controls from **{uploaded_ctrl_doc.name}**..."):
                try:
                    ctrl_bytes = uploaded_ctrl_doc.read()
                    ctrl_text  = parse_document(ctrl_bytes, uploaded_ctrl_doc.name)
                    _ctrl_status.info(
                        f"📄 Document parsed — {len(ctrl_text):,} characters. "
                        "Sending to LLM for controls extraction..."
                    )
                    st.session_state.inventory = extract_controls_from_document(
                        ctrl_text, progress_callback=_ctrl_progress
                    )
                    st.session_state.inventory_source   = "document"
                    st.session_state.inventory_filename = uploaded_ctrl_doc.name
                    _reset_index_and_comparison()
                    _ctrl_status.success(
                        f"✅ Extracted **{len(st.session_state.inventory)}** controls "
                        f"from **{uploaded_ctrl_doc.name}**. "
                        "Review the inventory below, then build the semantic index."
                    )
                except (ValueError, RuntimeError) as e:
                    _ctrl_status.error(f"❌ Controls extraction failed: {e}")
                    st.session_state.inventory = None
                    st.session_state.inventory_filename = None

# ── Inventory summary & preview ───────────────────────────────────────────
if st.session_state.inventory:
    inv_summary = get_inventory_summary(st.session_state.inventory)

    # Source badge
    src_icons = {"default": "📁", "excel": "📊", "document": "📄"}
    src_icon  = src_icons.get(st.session_state.inventory_source or "default", "📁")
    st.caption(f"{src_icon} Inventory: **{st.session_state.inventory_filename}**")

    ca, cb, cc = st.columns(3)
    ca.metric("Total Controls", inv_summary["Total Controls"])
    cb.metric("Domain(s)", ", ".join(inv_summary["Regulatory Domains"]))
    cc.metric(
        "Status",
        " | ".join(f"{k}: {v}" for k, v in inv_summary["Status Breakdown"].items()),
    )

    with st.expander("📊 GRC Inventory Preview", expanded=False):
        inv_df = inventory_to_dataframe(st.session_state.inventory)
        st.dataframe(inv_df, use_container_width=True, hide_index=True)

    st.divider()

    # ── Semantic Index ────────────────────────────────────────────────────────
    st.markdown("##### 🧠 Semantic Vector Index")
    st.markdown(
        "The semantic index embeds all GRC controls so the RAG pipeline can retrieve "
        "**only the most relevant controls** for each enforcement document."
    )

    # Check for a cached index
    if not st.session_state.rag_index_built:
        try:
            from app.vector_store import get_index_info
            info = get_index_info()
            if info:
                st.session_state.rag_index_built = True
                st.success(
                    f"✅ Semantic index loaded from cache — "
                    f"**{info['control_count']}** controls · "
                    f"Provider: `{info['embedding_model']}`"
                )
        except Exception:
            pass

    idx_col1, idx_col2 = st.columns([1, 3])
    with idx_col1:
        build_label = "🔄 Rebuild Index" if st.session_state.rag_index_built else "🧠 Build Semantic Index"
        build_btn   = st.button(build_label, use_container_width=True)

    with idx_col2:
        if st.session_state.rag_index_built:
            st.markdown(
                '<div class="rag-box">✅ <strong>Semantic index ready</strong> — '
                'RAG mode will select the most relevant controls via semantic search.</div>',
                unsafe_allow_html=True,
            )
        else:
            st.info(
                "Click **Build Semantic Index** to embed GRC controls. "
                "Required for RAG and Agentic modes. Cached to disk; only rebuilds when "
                "the inventory changes."
            )

    if build_btn and st.session_state.inventory:
        _idx_status = st.empty()
        try:
            from app.vector_store import get_or_build_control_index

            def _idx_progress(msg: str) -> None:
                _idx_status.info(msg)

            with st.spinner("Building semantic index..."):
                st.session_state.rag_collection = get_or_build_control_index(
                    st.session_state.inventory,
                    force_rebuild=True,
                    progress_callback=_idx_progress,
                )
            st.session_state.rag_index_built = True
            _idx_status.success(
                f"✅ Semantic index built — "
                f"**{len(st.session_state.inventory)}** controls indexed using "
                f"`{EmbeddingConfig.provider_display()}`."
            )
        except Exception as e:
            _idx_status.error(f"Failed to build semantic index: {e}")
            st.warning("Gap analysis will fall back to full inventory scan.")

st.divider()

# ---------------------------------------------------------------------------
# STEP 4 — Controls Gap Analysis
# ---------------------------------------------------------------------------
st.markdown(
    '<div class="step-header">Step 4 — Controls Gap Analysis (Agentic RAG / Standard RAG / Full Scan)</div>',
    unsafe_allow_html=True,
)

step4_ready = (
    st.session_state.extracted_data is not None
    and st.session_state.inventory is not None
)

if not step4_ready:
    st.info("⬆️ Complete Steps 1–3 before running the gap analysis.")
else:
    analysis_mode = st.radio(
        "**Analysis Mode:**",
        options=["🤖 Agentic RAG", "🧠 Standard RAG", "🔍 Full Scan"],
        index=0,
        horizontal=True,
        help=(
            "Agentic RAG: self-validating extraction + HyDE retrieval + reflection loop. "
            "Standard RAG: semantic search + direct LLM analysis. "
            "Full Scan: all controls sent to LLM."
        ),
    )

    if analysis_mode == "🤖 Agentic RAG":
        st.markdown(
            '<div class="rag-box">🤖 <strong>Agentic RAG mode</strong> — '
            '3 self-correcting agents: Extraction → Retrieval (HyDE) → Gap Analysis (reflection + deep dives).</div>',
            unsafe_allow_html=True,
        )
    elif analysis_mode == "🧠 Standard RAG":
        if st.session_state.rag_index_built:
            st.markdown(
                '<div class="rag-box">🧠 <strong>Standard RAG mode</strong> — '
                'Semantic search retrieves the most relevant controls before LLM analysis.</div>',
                unsafe_allow_html=True,
            )
        else:
            st.warning("⚠️ Semantic index not built. Build it in Step 3 for best results.")
    else:
        st.info("🔍 **Full Scan mode** — all controls sent to the LLM.")

    st.markdown(
        "**Controls Coverage** *(shift-left signal)* — Assesses whether your firm's Controls "
        "would have mandated the governance absent in the enforcement case."
    )

    col1, _ = st.columns([1, 3])
    with col1:
        analyse_btn = st.button("🤖 Run Gap Analysis", type="primary", use_container_width=True)

    if analyse_btn:
        _status_text  = st.empty()
        _progress_bar = st.progress(0)

        def _on_progress(message: str) -> None:
            _status_text.info(message)

        try:
            t0 = time.time()

            if analysis_mode == "🤖 Agentic RAG":
                st.session_state.comparison = run_agentic_pipeline(
                    document_text=st.session_state.document_text,
                    inventory=st.session_state.inventory,
                    rag_collection=st.session_state.rag_collection,
                    progress_callback=_on_progress,
                )
            else:
                use_rag = analysis_mode == "🧠 Standard RAG"
                st.session_state.comparison = compare_findings_to_inventory(
                    extracted_enforcement=st.session_state.extracted_data,
                    inventory=st.session_state.inventory,
                    progress_callback=_on_progress,
                    use_rag=use_rag,
                    rag_collection=st.session_state.rag_collection,
                )

            _progress_bar.progress(1.0)
            elapsed   = time.time() - t0
            rag_m     = st.session_state.comparison.get("_rag_metadata", {})
            assessed  = rag_m.get("controls_assessed", "?")
            total_inv = rag_m.get("total_inventory", "?")
            reduction = rag_m.get("reduction_pct", 0)
            _status_text.empty()

            if analysis_mode == "🤖 Agentic RAG":
                agent_meta   = st.session_state.comparison.get("_agent_metadata", {})
                gap_meta     = agent_meta.get("gap_analysis_agent", {})
                ret_meta     = agent_meta.get("retrieval_agent", {})
                hyde_count   = ret_meta.get("query_expansion", {}).get("hyde_queries_generated", 0)
                deep_dives   = gap_meta.get("deep_dives_performed", 0)
                contradicts  = gap_meta.get("contradictions_detected_and_resolved", 0)
                st.success(
                    f"✅ Agentic analysis complete in **{elapsed:.1f}s** — "
                    f"Controls: **{assessed}** of **{total_inv}** · "
                    f"HyDE: **{hyde_count}** · Deep dives: **{deep_dives}** · "
                    f"Contradictions resolved: **{contradicts}**"
                )
            else:
                mode_label = rag_m.get("mode", "unknown").replace("_", " ").title()
                st.success(
                    f"✅ Gap analysis complete in **{elapsed:.1f}s** — "
                    f"Mode: **{mode_label}** · "
                    f"Controls assessed: **{assessed}** of **{total_inv}** "
                    f"({reduction:.0f}% token reduction)"
                )

            _render_token_badge(
                st.session_state.comparison.get("_token_usage", {}),
                label="Step 4 token usage",
            )
        except Exception as e:
            _status_text.error(f"Gap analysis failed: {e}")
            st.session_state.comparison = None

st.divider()

# ---------------------------------------------------------------------------
# STEP 5 — Results & Download
# ---------------------------------------------------------------------------
st.markdown(
    '<div class="step-header">Step 5 — Results, Signals & Report</div>',
    unsafe_allow_html=True,
)

if st.session_state.comparison is None:
    st.info("⬆️ Run the gap analysis in Step 4 to see results here.")
else:
    comparison = st.session_state.comparison
    assessment = get_overall_assessment(comparison)
    rag_m      = comparison.get("_rag_metadata", {})

    headline = assessment.get("shift_left_headline", "")
    if headline:
        st.markdown(
            f'<div class="shift-left-box">⚡ <strong>Shift-Left Signal:</strong> {headline}</div>',
            unsafe_allow_html=True,
        )

    mode = rag_m.get("mode", "")

    # Analysis mode banner
    if mode == "agentic_rag":
        agent_meta  = comparison.get("_agent_metadata", {})
        gap_meta    = agent_meta.get("gap_analysis_agent", {})
        ret_meta    = agent_meta.get("retrieval_agent", {})
        hyde_count  = ret_meta.get("query_expansion", {}).get("hyde_queries_generated", 0)
        deep_dives  = gap_meta.get("deep_dives_performed", 0)
        contradicts = gap_meta.get("contradictions_detected_and_resolved", 0)
        flags       = gap_meta.get("reflection_flags_raised", 0)
        st.markdown(
            f'<div class="rag-box">🤖 <strong>Agentic RAG Analysis</strong> — '
            f'{rag_m.get("controls_assessed","?")} of {rag_m.get("total_inventory","?")} '
            f'controls · {rag_m.get("reduction_pct",0):.0f}% reduction · '
            f'HyDE: {hyde_count} · Reflection flags: {flags} · '
            f'Deep dives: {deep_dives} · Contradictions: {contradicts}</div>',
            unsafe_allow_html=True,
        )
        with st.expander("🔬 Agentic Pipeline Trace", expanded=False):
            ext_meta = agent_meta.get("extraction_agent", {})
            st.markdown("**Extraction Agent**")
            st.json({
                "iterations": ext_meta.get("iterations", 1),
                "refinements_applied": ext_meta.get("refinements_applied", []),
                "initial_confidence": ext_meta.get("initial_confidence"),
                "final_confidence": ext_meta.get("final_confidence"),
                "final_theme_count": ext_meta.get("final_theme_count"),
            })
            st.markdown("**Retrieval Agent**")
            st.json({
                "total_queries_run": ret_meta.get("query_expansion", {}).get("total_queries_run"),
                "hyde_queries_generated": hyde_count,
                "controls_filtered_out": ret_meta.get("quality_gate", {}).get("controls_filtered_out", 0),
                "domain_fallback": ret_meta.get("quality_gate", {}).get("domain_fallback_triggered"),
                "final_controls_selected": ret_meta.get("final_controls_count"),
            })
            st.markdown("**Gap Analysis Agent**")
            st.json({
                "quick_screen_count": gap_meta.get("quick_screen_count"),
                "reflection_flags_raised": flags,
                "deep_dives_performed": deep_dives,
                "deep_dive_control_ids": gap_meta.get("deep_dive_control_ids", []),
                "contradictions_resolved": contradicts,
            })
    elif mode == "rag":
        st.markdown(
            f'<div class="rag-box">🧠 <strong>Standard RAG Analysis</strong> — '
            f'{rag_m.get("controls_assessed","?")} of {rag_m.get("total_inventory","?")} '
            f'controls · {rag_m.get("reduction_pct",0):.0f}% reduction · '
            f'Semantic retrieval active</div>',
            unsafe_allow_html=True,
        )
    elif mode == "fallback_full_scan":
        st.warning(
            f"⚠️ RAG fallback: {rag_m.get('fallback_reason','unknown error')}. "
            "Full inventory scan was used."
        )

    # Overall Metrics
    st.markdown("### 📊 Overall Assessment")
    risk      = assessment.get("overall_risk_rating", "N/A")
    risk_icon = {"Low": "🟢", "Medium": "🟡", "High": "🟠", "Critical": "🔴"}.get(risk, "⚪")
    cl_s      = assessment.get("controls_layer_summary", {})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Assessed",        assessment.get("total_assessed", 0))
    c2.metric("Controls Gaps 🔴",      cl_s.get("potential_gap", 0))
    c3.metric("Partially Covered 🟡",  cl_s.get("partially_covered", 0))
    c4.metric(f"{risk_icon} Risk Rating", risk)

    exec_summary = assessment.get("executive_summary", "")
    if exec_summary:
        st.info(f"**Executive Summary:** {exec_summary}")

    # Results Tabs
    tab_controls, tab_signals, tab_unaddressed = st.tabs([
        "📋 Controls Gap Analysis",
        "🔔 Stakeholder Signals",
        "⚠️ Unaddressed Findings",
    ])

    with tab_controls:
        st.markdown("#### 📋 Controls Coverage — Gap Analysis")
        controls_df = build_controls_gap_dataframe(comparison)
        labels = ["Covered", "Partially Covered", "Potential Gap", "Insufficient Evidence"]
        sel = st.multiselect(
            "Filter by Controls Coverage:", options=labels, default=labels,
            key="filter_controls",
        )
        filtered = controls_df[controls_df["Controls Coverage"].isin(sel)]

        def _style_controls(val):
            m = {
                "Covered":               "background-color:#d4edda;color:#276221;font-weight:bold",
                "Partially Covered":     "background-color:#fff3cd;color:#9C5700;font-weight:bold",
                "Potential Gap":         "background-color:#f8d7da;color:#9C0006;font-weight:bold",
                "Insufficient Evidence": "background-color:#e2e3e5;color:#595959;font-weight:bold",
            }
            return m.get(val, "")

        st.dataframe(
            filtered.style.map(_style_controls, subset=["Controls Coverage"]),
            use_container_width=True, hide_index=True, height=400,
        )
        gap_items = filtered[filtered["Controls Coverage"] == "Potential Gap"]
        if not gap_items.empty:
            st.markdown("##### ⚡ Shift-Left Signals for Controls Gaps")
            for _, row in gap_items.iterrows():
                sig = row.get("Shift Left Signal", "")
                if sig:
                    st.markdown(
                        f'<div class="shift-left-box"><strong>{row["ID"]} — {row["Name"]}'
                        f'</strong><br>{sig}</div>',
                        unsafe_allow_html=True,
                    )

    with tab_signals:
        st.markdown("#### 🔔 Stakeholder Action Signals")
        signals_df = build_stakeholder_signals_dataframe(comparison)
        if signals_df.empty:
            st.success("No stakeholder signals — all controls are fully covered.")
        else:
            priorities = ["High", "Medium", "Low"]
            sel_pri = st.multiselect(
                "Filter by Priority:", options=priorities, default=priorities,
                key="filter_priority",
            )
            filtered_sig = signals_df[signals_df["Priority"].isin(sel_pri)]

            def _style_priority(val):
                m = {
                    "High":   "background-color:#f8d7da;color:#9C0006;font-weight:bold",
                    "Medium": "background-color:#fff3cd;color:#9C5700;font-weight:bold",
                    "Low":    "background-color:#d4edda;color:#276221;font-weight:bold",
                }
                return m.get(val, "")

            st.dataframe(
                filtered_sig.style.map(_style_priority, subset=["Priority"]),
                use_container_width=True, hide_index=True, height=400,
            )
            high_sig = filtered_sig[filtered_sig["Priority"] == "High"]
            if not high_sig.empty:
                st.markdown("##### 🔴 High Priority Actions")
                for _, row in high_sig.iterrows():
                    st.markdown(
                        f'<div class="signal-box"><strong>{row["Stakeholder"]}</strong> '
                        f'— {row["ID"]} {row["Name"]}<br>{row["Signal"]}</div>',
                        unsafe_allow_html=True,
                    )

    with tab_unaddressed:
        st.markdown("#### ⚠️ Unaddressed Enforcement Findings")
        st.caption(
            "Enforcement themes with **no matching control** in the inventory. "
            "New controls may be required."
        )
        unaddressed_df = build_unaddressed_findings_dataframe(comparison)
        if unaddressed_df.empty:
            st.success("All enforcement themes are addressed by at least one control.")
        else:
            st.warning(f"**{len(unaddressed_df)} enforcement theme(s)** have no matching control.")
            st.dataframe(unaddressed_df, use_container_width=True, hide_index=True)

    # Download Report
    st.divider()
    st.markdown("### 📥 Download Full Report")
    try:
        excel_bytes = generate_excel_report(
            comparison=comparison,
            extracted_enforcement=st.session_state.extracted_data,
            inventory=st.session_state.inventory,
        )
        filename = get_report_filename(st.session_state.extracted_data)
        st.download_button(
            label="📥 Download Excel Report (.xlsx)",
            data=excel_bytes,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
        st.caption(
            "Report contains 6 sheets: Summary, Controls Gap Analysis, "
            "Stakeholder Signals, Unaddressed Findings, Enforcement Data, GRC Inventory."
        )
    except Exception as e:
        st.error(f"Failed to generate Excel report: {e}")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.markdown(
    f"<div style='text-align:center;color:#aaa;font-size:.8rem;'>"
    f"Regulatory Enforcement Intelligence PoC v4 &nbsp;·&nbsp; "
    f"LLM: {AzureOpenAIConfig.DEPLOYMENT} &nbsp;·&nbsp; "
    f"Embeddings: {EmbeddingConfig.PROVIDER} &nbsp;·&nbsp; "
    f"FCA | DFS | SEC | MAS | FINRA &nbsp;·&nbsp; "
    f"For internal use only &nbsp;·&nbsp; Not legal advice"
    f"</div>",
    unsafe_allow_html=True,
)
