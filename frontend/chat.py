"""
frontend/chat.py
----------------
Chat interface UI component — message-first pattern.

All responses are saved to session_state.messages FIRST, then st.rerun()
is called so the history replay loop renders every message cleanly as a
proper chat bubble. This avoids interrupted renders from st.rerun() inside
a live st.chat_message() block.

Special sentinels stored in message history:
  __SHOW_RESULTS__  → renders the full results section (tabs + metrics) inline
  __SHOW_DOWNLOAD__ → renders the Excel download button inline

render_chat()
    1. Inject welcome message on first load
    2. Replay full chat history from session state (each message in its own bubble)
    3. Capture new user input via st.chat_input
    4. Route input → generate response → push to session state → st.rerun()
"""
import streamlit as st

from frontend.helpers import push_message
from frontend.pipeline import handle_chat_message, run_pipeline, build_gap_response

# ── Sentinel constants ────────────────────────────────────────────────────────
_SENTINEL_RESULTS  = "__SHOW_RESULTS__"
_SENTINEL_DOWNLOAD = "__SHOW_DOWNLOAD__"

# ── Welcome message ───────────────────────────────────────────────────────────
_WELCOME = (
    "👋 Hello! I'm your **Regulatory Enforcement Intelligence** assistant.\n\n"
    "I'm powered by **three self-correcting agents** via LangGraph:\n"
    "- 📄 **Intelligence Extractor**: Parses enforcement documents and extracts "
    "structured intelligence (regulator, penalty, themes, root causes)\n"
    "- 🔍 **Semantic Retrieval Agent**: HyDE-augmented semantic search over your GRC controls\n"
    "- 📊 **Compliance Gap Analyser**: Quick-screens controls with deep-dives and "
    "contradiction resolution\n\n"
    "**To get started:**\n"
    "1. 📄 Upload a **PDF** enforcement document in the sidebar\n"
    "2. 📊 Upload your **Excel** GRC inventory in the sidebar\n"
    "3. Ask me anything!\n\n"
    "*Try: 'Run the gap analysis' · 'What happened in this case?' · "
    "'Which controls are relevant?' · 'Show stakeholder signals' · 'Download report'*"
)


def render_chat() -> None:
    """
    Render the complete chat interface.

    Pattern: save-to-state → rerun → replay from state.
    All results, summaries, and download buttons appear inside chat bubbles.
    """
    st.markdown("### 💬 Chat with the Agents")
    st.caption(
        "Ask anything about the enforcement case — "
        "all results appear here in the chat."
    )

    # Inject welcome on first load
    if not st.session_state.messages:
        push_message("assistant", _WELCOME)

    # Replay full message history — every message in its own bubble
    for i, msg in enumerate(st.session_state.messages):
        _render_message(msg["role"], msg["content"], index=i)

    # Progress placeholder (filled during pipeline run)
    progress_ph = st.empty()

    # Capture new user input
    prompt = st.chat_input(
        "Ask about the case, run the analysis, request the report..."
    )
    if not prompt:
        return

    # Save and show user message immediately
    push_message("user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    # Route and respond
    response = handle_chat_message(prompt)

    if response == "__RUN_PIPELINE__":
        _run_and_respond(progress_ph)

    elif response == "__DOWNLOAD__":
        push_message("assistant", _SENTINEL_DOWNLOAD)
        st.rerun()

    else:
        push_message("assistant", response)
        st.rerun()


# ---------------------------------------------------------------------------
# Message renderer
# ---------------------------------------------------------------------------

def _render_message(role: str, content: str, index: int = 0) -> None:
    """
    Render a single chat message inside a chat bubble.

    Handles sentinels:
      __SHOW_RESULTS__  → full results tabs + metrics inside the bubble
      __SHOW_DOWNLOAD__ → Excel download button inside the bubble
      (anything else)   → plain markdown
    """
    with st.chat_message(role):
        if content == _SENTINEL_RESULTS:
            _render_results_inline()
        elif content == _SENTINEL_DOWNLOAD:
            _render_download_inline(key_suffix=str(index))
        else:
            st.markdown(content)


# ---------------------------------------------------------------------------
# Inline results renderer (inside a chat bubble)
# ---------------------------------------------------------------------------

def _render_results_inline() -> None:
    """
    Render the gap analysis results section inside a chat message bubble.
    Includes: metrics, shift-left banner, and three result tabs.
    """
    from app.comparator import get_overall_assessment
    from app.reporter import (
        build_controls_gap_dataframe,
        build_stakeholder_signals_dataframe,
        build_unaddressed_findings_dataframe,
    )
    from frontend.helpers import style_coverage, style_priority

    cmp = st.session_state.comparison
    if not cmp:
        st.markdown("*No results available yet.*")
        return

    assessment = get_overall_assessment(cmp)
    cl   = assessment.get("controls_layer_summary", {})
    rag  = cmp.get("_rag_metadata", {})
    risk = assessment.get("overall_risk_rating", "N/A")
    ri   = {"Low": "🟢", "Medium": "🟡", "High": "🟠", "Critical": "🔴"}.get(risk, "⚪")

    # Shift-left banner
    headline = assessment.get("shift_left_headline", "")
    if headline:
        st.markdown(
            f'<div class="banner-yellow">⚡ <strong>Shift-Left Signal:</strong> {headline}</div>',
            unsafe_allow_html=True,
        )

    # RAG mode banner
    mode_label = rag.get("mode", "unknown").replace("_", " ").title()
    st.markdown(
        f'<div class="banner-blue">🧠 <strong>{mode_label}</strong> — '
        f'{rag.get("controls_assessed","?")} of {rag.get("total_inventory","?")} '
        f'controls assessed · {rag.get("reduction_pct",0):.0f}% token reduction</div>',
        unsafe_allow_html=True,
    )

    # Key metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Risk Rating",         f"{ri} {risk}")
    c2.metric("🔴 Potential Gaps",   cl.get("potential_gap", 0))
    c3.metric("🟡 Partial Coverage", cl.get("partially_covered", 0))
    c4.metric("✅ Covered",           cl.get("covered", 0))

    exec_sum = assessment.get("executive_summary", "")
    if exec_sum:
        st.info(f"**Executive Summary:** {exec_sum}")

    # Result tabs
    tab_gap, tab_signals, tab_unaddressed = st.tabs([
        "📋 Controls Gap Analysis",
        "🔔 Stakeholder Signals",
        "⚠️ Unaddressed Findings",
    ])

    with tab_gap:
        df = build_controls_gap_dataframe(cmp)
        if df.empty:
            st.info("No gap analysis data available.")
        else:
            labels = ["Covered", "Partially Covered", "Potential Gap", "Insufficient Evidence"]
            sel = st.multiselect("Filter:", options=labels, default=labels, key="chat_filter_gap")
            fdf = df[df["Controls Coverage"].isin(sel)]
            if not fdf.empty:
                st.dataframe(
                    fdf.style.map(style_coverage, subset=["Controls Coverage"]),
                    width="stretch", hide_index=True, height=320,
                )
                # Shift-left signals for gaps
                gaps = fdf[fdf["Controls Coverage"] == "Potential Gap"]
                for _, row in gaps.iterrows():
                    sig = row.get("Shift Left Signal", "")
                    if sig:
                        st.markdown(
                            f'<div class="banner-yellow"><strong>{row["ID"]} — {row["Name"]}'
                            f'</strong><br>{sig}</div>',
                            unsafe_allow_html=True,
                        )
            else:
                st.info("No results match the selected filters.")

    with tab_signals:
        sdf = build_stakeholder_signals_dataframe(cmp)
        if sdf.empty:
            st.success("No stakeholder signals — all controls are covered.")
        else:
            pris = ["High", "Medium", "Low"]
            sp = st.multiselect("Filter by priority:", options=pris, default=pris, key="chat_filter_sig")
            fsdf = sdf[sdf["Priority"].isin(sp)]
            if not fsdf.empty:
                st.dataframe(
                    fsdf.style.map(style_priority, subset=["Priority"]),
                    width="stretch", hide_index=True, height=320,
                )
                for _, row in fsdf[fsdf["Priority"] == "High"].iterrows():
                    st.markdown(
                        f'<div class="banner-red"><strong>{row["Stakeholder"]}</strong> — '
                        f'`{row["ID"]}` {row["Name"]}<br>{row["Signal"]}</div>',
                        unsafe_allow_html=True,
                    )

    with tab_unaddressed:
        udf = build_unaddressed_findings_dataframe(cmp)
        if udf.empty:
            st.success("All enforcement themes are addressed by at least one control.")
        else:
            st.warning(f"**{len(udf)} theme(s)** have no matching control.")
            st.dataframe(udf, width="stretch", hide_index=True)


def _render_download_inline(key_suffix: str = "") -> None:
    """Render Excel download button inside a chat bubble."""
    if st.session_state.xl_bytes:
        st.markdown("📥 **Your Excel report is ready:**")
        st.download_button(
            label="📥 Download Excel Report (.xlsx)",
            data=st.session_state.xl_bytes,
            file_name=st.session_state.xl_name or "enforcement_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"dl_btn_{key_suffix}",
        )
    else:
        st.markdown("Report not ready yet — please run the analysis first.")


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def _run_and_respond(progress_ph) -> None:
    """
    Run the LangGraph agentic pipeline and push results into the chat history.

    After completion:
    - Gap analysis summary text → pushed as assistant message
    - __SHOW_RESULTS__ sentinel → results tabs rendered inline in chat
    - __SHOW_DOWNLOAD__ sentinel → download button rendered inline in chat
    Then st.rerun() so everything displays cleanly from history.
    """
    with st.spinner(
        "🤖 Running LangGraph pipeline — "
        "Intelligence Extractor → Semantic Retrieval Agent → Compliance Gap Analyser "
        "(60–120 seconds)..."
    ):
        try:
            run_pipeline(progress_ph)
            progress_ph.empty()

            # Push text summary
            result_text = build_gap_response()
            push_message("assistant", result_text)

            # Push results tables sentinel (shows tabs inline in chat)
            push_message("assistant", _SENTINEL_RESULTS)

            # Push download sentinel if Excel is ready
            if st.session_state.xl_bytes:
                push_message("assistant", _SENTINEL_DOWNLOAD)

        except Exception as exc:
            push_message(
                "assistant",
                f"❌ Pipeline failed: {exc}\n\nCheck the pipeline log in the sidebar.",
            )

    st.rerun()
