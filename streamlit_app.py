"""
streamlit_app.py
----------------
Regulatory Enforcement Intelligence PoC — v4 (Agentic RAG + Chat UI)

Entry point for the Streamlit application.
All UI logic is in the frontend/ package:

  frontend/styles.py   — Global CSS
  frontend/helpers.py  — Session state, logging, intent detection, style maps
  frontend/pipeline.py — Agentic pipeline runner + chat response builders
  frontend/sidebar.py  — File upload, agent status, pipeline log, config
  frontend/results.py  — Results tabs + download button
  frontend/chat.py     — Chat interface (history, input, routing)

Three self-correcting agents (app/agents/orchestrator.py):
  Agent 1 — Extraction Agent  : PDF → structured enforcement JSON
  Agent 2 — Retrieval Agent   : HyDE-augmented semantic search over GRC inventory
  Agent 3 — Gap Analysis Agent: Quick-screen + deep-dive + reflection

Run with:
  python -m streamlit run streamlit_app.py
"""
import streamlit as st

# ── Page configuration (must be first Streamlit call) ────────────────────────
st.set_page_config(
    page_title="Regulatory Enforcement Intelligence",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Frontend modules ──────────────────────────────────────────────────────────
from frontend.styles  import inject_css
from frontend.helpers import init_session
from frontend.sidebar import render_sidebar
from frontend.chat    import render_chat
from config import AzureOpenAIConfig, EmbeddingConfig

# ── Initialise ────────────────────────────────────────────────────────────────
inject_css()
init_session()

# ── Sidebar ───────────────────────────────────────────────────────────────────
render_sidebar()

# ── Main area header ──────────────────────────────────────────────────────────
st.markdown(
    '<div class="app-title">🏦 Regulatory Enforcement Intelligence</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="app-sub">'
    'Agentic RAG · Three self-correcting agents · '
    'Upload PDF + Excel in the sidebar, then ask any question in the chat below'
    '</div>',
    unsafe_allow_html=True,
)

# ── Chat interface (results shown inline inside chat) ────────────────────────
render_chat()

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.markdown(
    f"<div style='text-align:center;color:#aaa;font-size:.75rem;'>"
    f"🏦 Regulatory Enforcement Intelligence v4 &nbsp;·&nbsp; "
    f"LLM: {AzureOpenAIConfig.DEPLOYMENT} &nbsp;·&nbsp; "
    f"Embeddings: {EmbeddingConfig.PROVIDER} &nbsp;·&nbsp; "
    f"Agentic RAG · Extract · Retrieve (HyDE) · Gap Analysis &nbsp;·&nbsp; "
    f"Internal use only · Not legal advice"
    f"</div>",
    unsafe_allow_html=True,
)
