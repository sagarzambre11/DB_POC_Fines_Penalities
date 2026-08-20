"""
frontend/sidebar.py
-------------------
Sidebar UI component for the Regulatory Enforcement Intelligence app.

render_sidebar()
    Renders the complete sidebar including:
      - File upload widgets (PDF enforcement doc + Excel GRC inventory)
      - Agent status badges (Agent 1, 2, 3)
      - Pipeline log terminal
      - Configuration status (LLM + Embeddings)
      - Token usage summary (post-analysis)
      - Reset button
"""
import streamlit as st

from config import AzureOpenAIConfig, EmbeddingConfig
from app.parser import parse_document
from app.inventory import load_inventory_from_bytes, get_inventory_summary
from frontend.helpers import agent_badge, log, push_message


def render_sidebar() -> None:
    """Render the full sidebar. Call once per app rerun."""
    with st.sidebar:
        # ── Branding ──────────────────────────────────────────────────────────
        st.markdown("## 🏦 Enforcement Intelligence")
        st.caption("v4 · Three Self-Correcting Agents · Agentic RAG")
        st.divider()

        # ── File Upload ───────────────────────────────────────────────────────
        st.markdown("### 📎 Upload Files")

        _render_pdf_upload()
        st.markdown("")
        _render_excel_upload()

        st.divider()

        # ── Agent Status ──────────────────────────────────────────────────────
        st.markdown("### 🤖 Agent Status")
        st.markdown(
            agent_badge("📄 Intelligence Extractor", st.session_state.a1) + "<br>" +
            agent_badge("🔍 Semantic Retrieval Agent", st.session_state.a2) + "<br>" +
            agent_badge("📊 Compliance Gap Analyser", st.session_state.a3),
            unsafe_allow_html=True,
        )
        st.caption(
            "Intelligence Extractor: parses & extracts enforcement data · "
            "Semantic Retrieval Agent: HyDE semantic search · "
            "Compliance Gap Analyser: quick-screen + deep-dive"
        )
        st.divider()

        # ── Pipeline Log ──────────────────────────────────────────────────────
        _render_pipeline_log()

        # ── Config Status ─────────────────────────────────────────────────────
        st.markdown("### ⚙️ Configuration")

        missing_llm = AzureOpenAIConfig.validate()
        if missing_llm:
            st.error(
                "Missing Azure OpenAI config:\n" +
                "\n".join(f"- `{k}`" for k in missing_llm) +
                "\n\nUpdate your `.env` file."
            )
        else:
            st.success(f"✅ LLM: `{AzureOpenAIConfig.DEPLOYMENT}`")

        missing_emb = EmbeddingConfig.validate()
        if missing_emb:
            st.warning("Embedding config issue — RAG may fall back to full scan.")
        else:
            st.success(f"✅ Embeddings: `{EmbeddingConfig.PROVIDER}` · `{EmbeddingConfig.AZURE_DEPLOYMENT if EmbeddingConfig.PROVIDER == 'azure' else EmbeddingConfig.GOOGLE_MODEL}`")

        st.divider()

        # ── Token Usage (post-analysis) ───────────────────────────────────────
        _render_token_usage()

        # ── Reset ─────────────────────────────────────────────────────────────
        if st.button("🔄 Reset Everything", use_container_width=True, key="reset_btn"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _render_pdf_upload() -> None:
    """Render the PDF/DOCX file uploader and handle parsing."""
    pdf_file = st.file_uploader(
        "📄 Enforcement Document (PDF / DOCX)",
        type=["pdf", "docx"],
        key="pdf_upload",
        help="Upload any regulatory enforcement document: FCA Final Notice, DFS Consent Order, SEC Order, etc.",
    )

    if pdf_file:
        if pdf_file.name != st.session_state.pdf_filename:
            with st.spinner(f"Parsing {pdf_file.name}..."):
                try:
                    raw_bytes = pdf_file.read()
                    text = parse_document(raw_bytes, pdf_file.name)
                    st.session_state.document_text  = text
                    st.session_state.pdf_filename   = pdf_file.name
                    # Reset downstream state on new file
                    st.session_state.extracted_data = None
                    st.session_state.comparison     = None
                    st.session_state.a1 = st.session_state.a2 = st.session_state.a3 = "idle"
                    log(
                        f"PDF parsed: {pdf_file.name} "
                        f"({len(text):,} characters extracted)", "e"
                    )
                    push_message(
                        "assistant",
                        f"📄 **{pdf_file.name}** uploaded and parsed — "
                        f"**{len(text):,}** characters extracted.\n\n"
                        f"Now upload your Excel GRC inventory (if not already done), "
                        f"then ask me to **run the analysis**.",
                    )
                except Exception as exc:
                    st.error(f"Parse error: {exc}")

    if st.session_state.pdf_filename:
        st.markdown(
            f'<span style="color:#28a745;font-size:.82rem;font-weight:600;">'
            f'✅ {st.session_state.pdf_filename}</span>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("No document uploaded yet.")


def _render_excel_upload() -> None:
    """Render the Excel GRC inventory uploader and handle loading."""
    xls_file = st.file_uploader(
        "📊 GRC Inventory (Excel .xlsx)",
        type=["xlsx"],
        key="xls_upload",
        help="Upload your GRC controls inventory. Must have a sheet named 'grc_control_inv1' with the required columns.",
    )

    if xls_file:
        if xls_file.name != st.session_state.excel_filename:
            with st.spinner(f"Loading inventory from {xls_file.name}..."):
                try:
                    inv = load_inventory_from_bytes(xls_file.read())
                    st.session_state.inventory      = inv
                    st.session_state.excel_filename  = xls_file.name
                    # Reset vector store and analysis on new file
                    st.session_state.rag_collection = None
                    st.session_state.comparison     = None
                    s = get_inventory_summary(inv)
                    log(
                        f"Excel loaded: {xls_file.name} "
                        f"({s['Total Controls']} controls, domains: "
                        f"{', '.join(s['Regulatory Domains'])})", "r"
                    )
                    push_message(
                        "assistant",
                        f"📊 **{xls_file.name}** loaded — "
                        f"**{s['Total Controls']}** controls across "
                        f"domain(s): *{', '.join(s['Regulatory Domains'])}*\n\n"
                        f"Both files are ready. Ask me to **run the gap analysis** "
                        f"or ask any question!",
                    )
                except Exception as exc:
                    st.error(f"Inventory load error: {exc}")

    if st.session_state.excel_filename:
        inv_count = len(st.session_state.inventory) if st.session_state.inventory else "?"
        st.markdown(
            f'<span style="color:#28a745;font-size:.82rem;font-weight:600;">'
            f'✅ {st.session_state.excel_filename} ({inv_count} controls)</span>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("No inventory uploaded yet.")


def _render_pipeline_log() -> None:
    """Render the pipeline log terminal if there are log entries."""
    if not st.session_state.pipeline_log:
        return

    st.markdown("### 🖥️ Pipeline Log")
    log_html = "<br>".join(st.session_state.pipeline_log[-40:])
    st.markdown(f'<div class="plog">{log_html}</div>', unsafe_allow_html=True)

    if st.button("Clear log", key="clear_log_btn", use_container_width=True):
        st.session_state.pipeline_log = []
        st.rerun()

    st.divider()


def _render_token_usage() -> None:
    """Render token usage summary after a successful analysis run."""
    cmp = st.session_state.comparison
    if not cmp:
        return

    st.markdown("### 🔢 Token Usage")
    usage = cmp.get("_token_usage", {})
    rag   = cmp.get("_rag_metadata", {})
    am    = cmp.get("_agent_metadata", {})

    st.markdown(
        f"**Total:** `{usage.get('total_tokens', 0):,}` tokens  \n"
        f"Input: `{usage.get('prompt_tokens', 0):,}` · "
        f"Output: `{usage.get('completion_tokens', 0):,}`"
    )
    st.markdown(
        f"**RAG:** `{rag.get('controls_assessed', '?')}` / "
        f"`{rag.get('total_inventory', '?')}` controls · "
        f"`{rag.get('reduction_pct', 0):.0f}%` token reduction"
    )

    ext_a = am.get("extraction_agent", {})
    ret_a = am.get("retrieval_agent", {})
    gap_a = am.get("gap_analysis_agent", {})

    with st.expander("Agent details", expanded=False):
        if ext_a:
            st.markdown(
                f"**📄 Intelligence Extractor:** {ext_a.get('final_theme_count', '?')} themes · "
                f"conf {ext_a.get('final_confidence', 0):.2f} · "
                f"{ext_a.get('iterations', 1)} iteration(s)"
            )
        if ret_a:
            qe = ret_a.get("query_expansion", {})
            st.markdown(
                f"**🔍 Semantic Retrieval Agent:** {qe.get('hyde_queries_generated', 0)} HyDE queries · "
                f"{ret_a.get('final_controls_count', '?')} controls selected"
            )
        if gap_a:
            st.markdown(
                f"**📊 Compliance Gap Analyser:** {gap_a.get('quick_screen_count', 0)} screened · "
                f"{gap_a.get('deep_dives_performed', 0)} deep dives · "
                f"{gap_a.get('contradictions_detected_and_resolved', 0)} resolved"
            )

    st.divider()
