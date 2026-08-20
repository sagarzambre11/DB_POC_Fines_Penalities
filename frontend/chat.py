"""
frontend/chat.py
----------------
Chat interface UI component.

render_chat()
    Renders the full chat section including:
      - Welcome message (on first load)
      - Chat history replay
      - Chat input widget
      - Message routing via handle_chat_message()
      - Pipeline execution with live progress display
      - Download button injection for report requests
"""
import streamlit as st

from frontend.helpers import push_message
from frontend.pipeline import handle_chat_message, run_pipeline, build_gap_response


# Welcome message shown on first app load
_WELCOME = (
    "👋 Hello! I'm your **Regulatory Enforcement Intelligence** assistant.\n\n"
    "I'm powered by **three self-correcting agents**:\n"
    "- 📄 **Agent 1 — Extract Agent**: Parses enforcement documents and extracts "
    "structured intelligence (regulator, penalty, themes, root causes)\n"
    "- 🔍 **Agent 2 — Retrieval Agent**: Uses HyDE semantic search to find the "
    "most relevant GRC controls for the enforcement case\n"
    "- 📊 **Agent 3 — Gap Analysis Agent**: Quick-screens all controls, performs "
    "targeted deep-dives, and resolves contradictions\n\n"
    "**To get started:**\n"
    "1. 📄 Upload a **PDF** enforcement document in the sidebar\n"
    "2. 📊 Upload your **Excel** GRC inventory in the sidebar\n"
    "3. Ask me to **run the analysis** — or ask any question about the case!\n\n"
    "*Try: 'Run the gap analysis' · 'What happened?' · 'Which controls are relevant?' "
    "· 'Show stakeholder signals' · 'Download report'*"
)


def render_chat() -> None:
    """
    Render the complete chat interface.

    Handles:
    - First-load welcome message injection
    - Chat history rendering (all past messages)
    - User input capture via st.chat_input
    - Intent routing and agent triggering
    - Live pipeline progress display
    - Download button rendering for report requests
    """
    st.markdown("### 💬 Chat with the Agents")
    st.caption(
        "Ask questions about the enforcement case, request gap analysis, "
        "retrieve relevant controls, or download the report."
    )

    # Inject welcome message on first load
    if not st.session_state.messages:
        push_message("assistant", _WELCOME)

    # Render all past messages
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    prompt = st.chat_input(
        "Ask about the enforcement case, run the analysis, or request the report..."
    )
    if not prompt:
        return

    # Show user message immediately
    push_message("user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generate and display assistant response
    with st.chat_message("assistant"):
        _dispatch(prompt)


# ---------------------------------------------------------------------------
# Internal dispatcher
# ---------------------------------------------------------------------------

def _dispatch(prompt: str) -> None:
    """
    Route the user message and render the appropriate response in the chat bubble.

    Special return values from handle_chat_message:
      "__RUN_PIPELINE__" — run the full agentic pipeline, then show gap results
      "__DOWNLOAD__"     — render a download button for the Excel report
    """
    response = handle_chat_message(prompt)

    if response == "__RUN_PIPELINE__":
        _handle_pipeline_run()

    elif response == "__DOWNLOAD__":
        _handle_download()

    else:
        st.markdown(response)
        push_message("assistant", response)


def _handle_pipeline_run() -> None:
    """Execute the agentic pipeline with live progress display."""
    progress_ph = st.empty()

    with st.spinner(
        "🤖 Running agentic pipeline — Agent 1 → Agent 2 → Agent 3 "
        "(this typically takes 60–120 seconds)..."
    ):
        try:
            run_pipeline(progress_ph)
            progress_ph.empty()

            # Show gap analysis results in chat
            result_text = build_gap_response()
            st.markdown(result_text)
            push_message("assistant", result_text)

            # Offer download if Excel report is ready
            if st.session_state.xl_bytes:
                st.markdown("---")
                st.markdown("📥 **Your Excel report is ready:**")
                st.download_button(
                    label="📥 Download Excel Report (.xlsx)",
                    data=st.session_state.xl_bytes,
                    file_name=st.session_state.xl_name or "enforcement_report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="chat_dl_btn",
                )
                push_message(
                    "assistant",
                    "📥 Excel report generated — see download button above."
                )

            # Trigger rerun so results tabs appear
            st.rerun()

        except Exception as exc:
            error_msg = f"❌ Pipeline failed: {exc}"
            st.error(error_msg)
            push_message("assistant", error_msg)


def _handle_download() -> None:
    """Render a download button inside the chat bubble."""
    if st.session_state.xl_bytes:
        st.markdown("📥 **Your Excel report is ready to download:**")
        st.download_button(
            label="📥 Download Excel Report (.xlsx)",
            data=st.session_state.xl_bytes,
            file_name=st.session_state.xl_name or "enforcement_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="chat_dl_btn_2",
        )
        push_message("assistant", "📥 Excel report download button displayed above.")
    else:
        msg = "Report not ready yet — please run the gap analysis first."
        st.markdown(msg)
        push_message("assistant", msg)
