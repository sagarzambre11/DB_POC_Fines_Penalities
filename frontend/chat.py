"""
frontend/chat.py
----------------
Chat interface UI component — message-first pattern.

All responses are saved to session_state.messages FIRST, then st.rerun()
is called so the history replay loop renders every message cleanly as a
proper chat bubble. This avoids interrupted renders from st.rerun() inside
a live st.chat_message() block.

render_chat()
    1. Inject welcome message on first load
    2. Replay full chat history from session state (each message in its own bubble)
    3. Capture new user input via st.chat_input
    4. Route input → generate response → push to session state → st.rerun()
"""
import streamlit as st

from frontend.helpers import push_message
from frontend.pipeline import handle_chat_message, run_pipeline, build_gap_response

# ── Special sentinel values stored in message history ─────────────────────────
_SENTINEL_DOWNLOAD = "__SHOW_DOWNLOAD__"

# Welcome message shown once on first app load
_WELCOME = (
    "👋 Hello! I'm your **Regulatory Enforcement Intelligence** assistant.\n\n"
    "I'm powered by **three self-correcting agents** via LangGraph:\n"
    "- 📄 **Agent 1 — Extract**: Parses enforcement documents and extracts "
    "structured intelligence (regulator, penalty, themes, root causes)\n"
    "- 🔍 **Agent 2 — Retrieve**: HyDE-augmented semantic search over your GRC controls\n"
    "- 📊 **Agent 3 — Gap Analysis**: Quick-screens controls with deep-dives and "
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
    This ensures every message is displayed correctly as a chat bubble
    without interrupted renders.
    """
    st.markdown("### 💬 Chat with the Agents")
    st.caption(
        "Ask anything about the enforcement case — "
        "the agents will extract, retrieve, and analyse on your behalf."
    )

    # ── Inject welcome on first load ──────────────────────────────────────────
    if not st.session_state.messages:
        push_message("assistant", _WELCOME)

    # ── Replay full message history ───────────────────────────────────────────
    for msg in st.session_state.messages:
        _render_message(msg["role"], msg["content"])

    # ── Show pipeline progress bar if running ─────────────────────────────────
    # (placeholder rendered between history and input; filled during pipeline run)
    progress_ph = st.empty()

    # ── Capture new user input ────────────────────────────────────────────────
    prompt = st.chat_input(
        "Ask about the case, run the analysis, request the report..."
    )
    if not prompt:
        return

    # Save and display user message immediately
    push_message("user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    # ── Route and respond ─────────────────────────────────────────────────────
    response = handle_chat_message(prompt)

    if response == "__RUN_PIPELINE__":
        _run_and_respond(progress_ph)

    elif response == "__DOWNLOAD__":
        push_message("assistant", _SENTINEL_DOWNLOAD)
        st.rerun()

    else:
        # Standard text response — push and rerun to show in history
        push_message("assistant", response)
        st.rerun()


# ---------------------------------------------------------------------------
# Message renderer
# ---------------------------------------------------------------------------

def _render_message(role: str, content: str) -> None:
    """
    Render a single chat message.

    Handles special sentinel values:
      __SHOW_DOWNLOAD__ → renders the Excel download button inside the bubble
    """
    with st.chat_message(role):
        if content == _SENTINEL_DOWNLOAD:
            if st.session_state.xl_bytes:
                st.markdown("📥 **Your Excel report is ready:**")
                st.download_button(
                    label="📥 Download Excel Report (.xlsx)",
                    data=st.session_state.xl_bytes,
                    file_name=st.session_state.xl_name or "enforcement_report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"dl_btn_{st.session_state.messages.index({'role': role, 'content': content})}",
                )
            else:
                st.markdown("Report not ready yet — please run the analysis first.")
        else:
            st.markdown(content)


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def _run_and_respond(progress_ph) -> None:
    """
    Run the LangGraph agentic pipeline, push result to chat history, rerun.

    Shows live status in `progress_ph` during execution.
    After completion, saves the gap analysis response and (optionally)
    a download-ready message to session state, then calls st.rerun() so
    the history replay loop shows everything cleanly.
    """
    with st.spinner(
        "🤖 Running LangGraph pipeline — "
        "Agent 1 → Agent 2 → Agent 3 (60–120 seconds)..."
    ):
        try:
            run_pipeline(progress_ph)
            progress_ph.empty()

            # Push gap analysis results as a chat message
            result_text = build_gap_response()
            push_message("assistant", result_text)

            # Offer download button if Excel report was generated
            if st.session_state.xl_bytes:
                push_message("assistant", _SENTINEL_DOWNLOAD)

        except Exception as exc:
            push_message("assistant", f"❌ Pipeline failed: {exc}\n\nCheck the pipeline log in the sidebar.")

    # Always rerun so the history loop renders everything
    st.rerun()
