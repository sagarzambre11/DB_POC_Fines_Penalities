"""
frontend/helpers.py
-------------------
Utility functions shared across all frontend modules:
  - Session state initialisation
  - Pipeline log writer
  - Agent status badge HTML generator
  - Intent classifier (routes chat queries to correct agent)
  - DataFrame style maps for coverage and priority columns
  - Session state push helper for chat messages
"""
import time
import streamlit as st

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------

SESSION_DEFAULTS: dict = {
    "messages":       [],      # chat history: list of {role, content}
    "document_text":  None,    # raw text extracted from PDF/DOCX
    "extracted_data": None,    # structured JSON from Agent 1
    "inventory":      None,    # list[dict] GRC controls from Excel
    "rag_collection": None,    # ChromaDB collection (built by Agent 2)
    "comparison":     None,    # full pipeline result from Agent 3
    "pdf_filename":   None,
    "excel_filename": None,
    "pipeline_log":   [],      # list of HTML log line strings
    "a1":             "idle",  # Agent 1 status: idle|running|done|error
    "a2":             "idle",  # Agent 2 status
    "a3":             "idle",  # Agent 3 status
    "xl_bytes":       None,    # pre-built Excel report bytes
    "xl_name":        None,    # filename for the Excel report
}


def init_session() -> None:
    """Initialise all session state keys with their default values if not set."""
    for key, default in SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default


# ---------------------------------------------------------------------------
# Pipeline log
# ---------------------------------------------------------------------------

def log(msg: str, kind: str = "s") -> None:
    """
    Append a timestamped, colour-coded line to the pipeline log.

    kind codes:
      "e" → extraction (blue)
      "r" → retrieval  (green)
      "g" → gap        (orange)
      "s" → system     (grey, default)
    """
    css_map = {"e": "le", "r": "lr", "g": "lg", "s": "ls"}
    css = css_map.get(kind, "ls")
    ts  = time.strftime("%H:%M:%S")
    st.session_state.pipeline_log.append(
        f'<span class="{css}">[{ts}] {msg}</span>'
    )


def log_kind_from_msg(msg: str) -> str:
    """Infer log kind from message content."""
    ml = msg.lower()
    if "extraction" in msg or "extract" in ml:
        return "e"
    if "retrieval" in msg or "retriev" in ml or "hyde" in ml:
        return "r"
    if "gap" in ml or "gap" in msg or "screen" in ml:
        return "g"
    return "s"


# ---------------------------------------------------------------------------
# Agent badge HTML
# ---------------------------------------------------------------------------

def agent_badge(label: str, status: str) -> str:
    """
    Return an HTML badge string for the given agent status.

    status: "idle" | "running" | "done" | "error"
    """
    css_map  = {"idle": "b-idle", "running": "b-run", "done": "b-done", "error": "b-err"}
    icon_map = {"idle": "⚪", "running": "🔄", "done": "✅", "error": "❌"}
    css  = css_map.get(status, "b-idle")
    icon = icon_map.get(status, "⚪")
    return f'<span class="agent-badge {css}">{icon} {label}</span>'


# ---------------------------------------------------------------------------
# Intent classifier
# ---------------------------------------------------------------------------

def classify_intent(text: str) -> str:
    """
    Classify the user's chat message into one of these intent categories:
      summarise    → what happened / enforcement overview
      gap          → gap analysis / coverage / risk / stakeholder
      retrieve     → find/search specific controls or policies
      download     → export / download report
      inventory    → list/show GRC inventory
      general      → everything else
    """
    t = text.lower()

    if any(w in t for w in [
        "what happened", "describe", "summary", "summarise", "summarize",
        "overview", "explain", "enforcement", "what was", "what did",
        "tell me about", "case detail",
    ]):
        return "summarise"

    if any(w in t for w in [
        "gap", "sufficient", "cover", "coverage", "missing", "analyse",
        "analyze", "analysis", "risk", "assess", "stakeholder", "unaddressed",
        "compare", "shift", "finding",
    ]):
        return "gap"

    if any(w in t for w in [
        "which polic", "which control", "find control", "show control",
        "retrieve", "search", "lookup", "look up", "relevant control",
        "related control", "what control", "what polic",
    ]):
        return "retrieve"

    if any(w in t for w in ["download", "report", "excel", "export"]):
        return "download"

    if any(w in t for w in [
        "inventory", "show inventory", "list control", "how many control",
        "my control",
    ]):
        return "inventory"

    return "general"


# ---------------------------------------------------------------------------
# DataFrame style maps
# ---------------------------------------------------------------------------

def style_coverage(val: str) -> str:
    """Return inline CSS for a Controls Coverage cell."""
    return {
        "Covered":               "background:#d4edda;color:#155724;font-weight:bold",
        "Partially Covered":     "background:#fff3cd;color:#856404;font-weight:bold",
        "Potential Gap":         "background:#f8d7da;color:#721c24;font-weight:bold",
        "Insufficient Evidence": "background:#e2e3e5;color:#495057;font-weight:bold",
    }.get(val, "")


def style_priority(val: str) -> str:
    """Return inline CSS for a Priority cell."""
    return {
        "High":   "background:#f8d7da;color:#721c24;font-weight:bold",
        "Medium": "background:#fff3cd;color:#856404;font-weight:bold",
        "Low":    "background:#d4edda;color:#155724;font-weight:bold",
    }.get(val, "")


# ---------------------------------------------------------------------------
# Chat message push helper
# ---------------------------------------------------------------------------

def push_message(role: str, content: str) -> None:
    """Append a message to the chat history in session state."""
    st.session_state.messages.append({"role": role, "content": content})
