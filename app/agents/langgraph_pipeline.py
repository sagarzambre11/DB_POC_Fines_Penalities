"""
app/agents/langgraph_pipeline.py
---------------------------------
LangGraph-based agentic pipeline for Regulatory Enforcement Intelligence v4.

Wraps the three self-correcting agents as a LangGraph StateGraph:

  State
  ├── document_text      (str)        — raw text from PDF/DOCX
  ├── inventory          (list[dict]) — GRC controls from Excel
  ├── rag_collection     (object)     — ChromaDB collection (optional pre-built)
  ├── extracted_data     (dict)       — Agent 1 output: structured enforcement JSON
  ├── condensed          (dict)       — condensed enforcement for downstream agents
  ├── selected_controls  (list[dict]) — Agent 2 output: semantically retrieved controls
  ├── gap_analysis       (list[dict]) — Agent 3 output: per-control gap results
  ├── overall_assessment (dict)       — Agent 3 output: summary + risk rating
  ├── unaddressed        (list[dict]) — Agent 3 output: unaddressed enforcement themes
  ├── token_usage        (dict)       — combined token usage across all agents
  ├── rag_metadata       (dict)       — RAG mode, controls assessed, reduction %
  ├── agent_metadata     (dict)       — per-agent trace data
  ├── progress_callback  (callable)   — optional UI progress callback
  └── error              (str|None)   — set if a node fails

Graph topology:
  [START] → extract_node → retrieve_node → gap_analysis_node → [END]

Each node corresponds to one self-correcting agent from orchestrator.py:
  extract_node       → _run_extraction_agent  (Agent 1)
  retrieve_node      → _run_retrieval_agent   (Agent 2)
  gap_analysis_node  → _run_gap_analysis_agent + _generate_summary (Agent 3)

Public API:
  build_graph()           → compiled LangGraph app
  run_langgraph_pipeline(...) → dict (same schema as orchestrator.run_agentic_pipeline)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, END

from config import AzureOpenAIConfig, AppConfig
from app.extractor import _build_client, _sum_usage
from app.comparator import _condense_enforcement_for_comparison
from app.agents.orchestrator import (
    _run_extraction_agent,
    _run_retrieval_agent,
    _run_gap_analysis_agent,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline State
# ---------------------------------------------------------------------------

class PipelineState(TypedDict, total=False):
    """
    Shared state passed between LangGraph nodes.

    Fields are populated progressively as each agent node runs.
    All fields are optional at graph entry — only document_text,
    inventory, and optionally rag_collection are required inputs.
    """
    # ── Inputs ─────────────────────────────────────────────────────────────
    document_text:     str
    inventory:         List[Dict[str, Any]]
    rag_collection:    Optional[Any]
    progress_callback: Optional[Callable[[str], None]]

    # ── Agent 1 — Extraction outputs ───────────────────────────────────────
    extracted_data:    Optional[Dict[str, Any]]
    condensed:         Optional[Dict[str, Any]]

    # ── Agent 2 — Retrieval outputs ─────────────────────────────────────────
    selected_controls: Optional[List[Dict[str, Any]]]

    # ── Agent 3 — Gap Analysis outputs ──────────────────────────────────────
    gap_analysis:      Optional[List[Dict[str, Any]]]
    overall_assessment: Optional[Dict[str, Any]]
    unaddressed:       Optional[List[Dict[str, Any]]]

    # ── Metadata ────────────────────────────────────────────────────────────
    token_usage:       Optional[Dict[str, int]]
    rag_metadata:      Optional[Dict[str, Any]]
    agent_metadata:    Optional[Dict[str, Any]]
    error:             Optional[str]


# ---------------------------------------------------------------------------
# Node 1 — Extraction Agent
# ---------------------------------------------------------------------------

def extract_node(state: PipelineState) -> PipelineState:
    """
    LangGraph node: Agent 1 — Extraction Agent.

    Reads:  state["document_text"], state["progress_callback"]
    Writes: state["extracted_data"], state["condensed"],
            state["token_usage"], state["agent_metadata"]
    """
    cb = state.get("progress_callback")
    if cb:
        cb("📄 Intelligence Extractor: Starting extraction...")

    try:
        missing = AzureOpenAIConfig.validate()
        if missing:
            raise RuntimeError(
                f"Missing Azure OpenAI config: {', '.join(missing)}"
            )

        client = _build_client()
        extracted, ext_meta, ext_usage = _run_extraction_agent(
            client,
            state["document_text"],
            progress_callback=cb,
        )

        condensed = _condense_enforcement_for_comparison(extracted)

        return {
            **state,
            "extracted_data": extracted,
            "condensed":       condensed,
            "token_usage":     ext_usage,
            "agent_metadata":  {"extraction_agent": ext_meta},
            "error":           None,
        }

    except Exception as exc:
        logger.error("extract_node failed: %s", exc)
        if cb:
            cb(f"❌ Intelligence Extractor error: {exc}")
        return {**state, "error": str(exc)}


# ---------------------------------------------------------------------------
# Node 2 — Retrieval Agent
# ---------------------------------------------------------------------------

def retrieve_node(state: PipelineState) -> PipelineState:
    """
    LangGraph node: Agent 2 — Retrieval Agent (HyDE-augmented).

    Reads:  state["condensed"], state["inventory"],
            state["rag_collection"], state["progress_callback"]
    Writes: state["selected_controls"], state["rag_metadata"],
            state["rag_collection"] (updated if built),
            updates state["token_usage"], state["agent_metadata"]
    """
    if state.get("error"):
        return state  # skip if upstream node failed

    cb = state.get("progress_callback")
    if cb:
        cb("🔍 Semantic Retrieval Agent: Starting retrieval...")

    try:
        client = _build_client()
        selected, ret_meta, ret_usage = _run_retrieval_agent(
            client,
            state["condensed"],
            state["inventory"],
            rag_collection=state.get("rag_collection"),
            progress_callback=cb,
        )

        total_inventory = len(state["inventory"])
        controls_assessed = ret_meta.get("final_controls_count", len(selected))
        reduction_pct = (1 - controls_assessed / max(total_inventory, 1)) * 100

        rag_metadata = {
            "mode":               "agentic_rag",
            "total_inventory":    total_inventory,
            "controls_assessed":  controls_assessed,
            "reduction_pct":      round(reduction_pct, 1),
        }

        combined_usage = _sum_usage(state.get("token_usage") or {}, ret_usage)
        agent_meta = {
            **(state.get("agent_metadata") or {}),
            "retrieval_agent": ret_meta,
        }

        return {
            **state,
            "selected_controls": selected,
            "rag_metadata":      rag_metadata,
            "token_usage":       combined_usage,
            "agent_metadata":    agent_meta,
            "error":             None,
        }

    except Exception as exc:
        logger.error("retrieve_node failed: %s", exc)
        if cb:
            cb(f"❌ Semantic Retrieval Agent error: {exc} — falling back to full inventory")
        # Graceful fallback: use full inventory
        total = len(state["inventory"])
        return {
            **state,
            "selected_controls": state["inventory"],
            "rag_metadata": {
                "mode": "fallback_full_scan",
                "total_inventory": total,
                "controls_assessed": total,
                "reduction_pct": 0,
                "fallback_reason": str(exc),
            },
            "error": None,  # allow pipeline to continue
        }


# ---------------------------------------------------------------------------
# Node 3 — Gap Analysis Agent
# ---------------------------------------------------------------------------

def gap_analysis_node(state: PipelineState) -> PipelineState:
    """
    LangGraph node: Agent 3 — Gap Analysis Agent.

    Reads:  state["condensed"], state["selected_controls"],
            state["progress_callback"]
    Writes: state["gap_analysis"], state["overall_assessment"],
            state["unaddressed"], updates state["token_usage"],
            state["agent_metadata"]
    """
    if state.get("error"):
        return state  # skip if upstream node failed

    cb = state.get("progress_callback")
    if cb:
        cb("📊 Compliance Gap Analyser: Starting gap analysis...")

    try:
        client = _build_client()
        final_gap, summary, gap_meta, gap_usage = _run_gap_analysis_agent(
            client,
            state["condensed"],
            state["selected_controls"],
            progress_callback=cb,
        )

        combined_usage = _sum_usage(state.get("token_usage") or {}, gap_usage)
        agent_meta = {
            **(state.get("agent_metadata") or {}),
            "gap_analysis_agent": gap_meta,
        }

        return {
            **state,
            "gap_analysis":       final_gap,
            "overall_assessment": summary.get("overall_assessment", {}),
            "unaddressed":        summary.get("unaddressed_findings", []),
            "token_usage":        combined_usage,
            "agent_metadata":     agent_meta,
            "error":              None,
        }

    except Exception as exc:
        logger.error("gap_analysis_node failed: %s", exc)
        if cb:
            cb(f"❌ Compliance Gap Analyser error: {exc}")
        return {**state, "error": str(exc)}


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph():
    """
    Build and compile the LangGraph StateGraph for the agentic pipeline.

    Topology:
        START → extract_node → retrieve_node → gap_analysis_node → END

    Returns:
        A compiled LangGraph application (CompiledGraph) ready to invoke.
    """
    graph = StateGraph(PipelineState)

    # Register agent nodes
    graph.add_node("extract",      extract_node)
    graph.add_node("retrieve",     retrieve_node)
    graph.add_node("gap_analysis", gap_analysis_node)

    # Wire sequential edges
    graph.set_entry_point("extract")
    graph.add_edge("extract",      "retrieve")
    graph.add_edge("retrieve",     "gap_analysis")
    graph.add_edge("gap_analysis", END)

    return graph.compile()


# Singleton compiled graph (built once, reused across calls)
_compiled_graph = None


def _get_graph():
    """Return the singleton compiled LangGraph app, building it on first call."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_langgraph_pipeline(
    document_text: str,
    inventory: list[dict],
    rag_collection=None,
    progress_callback=None,
) -> dict:
    """
    Run the full three-agent pipeline via LangGraph StateGraph.

    This is a drop-in replacement for orchestrator.run_agentic_pipeline().
    The same three agents run in the same order (Extract → Retrieve → Gap Analysis),
    but they are wired and executed via LangGraph's StateGraph runtime, which
    provides:
      - Explicit state passing between nodes
      - Built-in error isolation per node
      - Graph visualisation compatibility (graph.get_graph().draw_mermaid())
      - Future extensibility (conditional edges, human-in-the-loop, etc.)

    Args:
        document_text:     Plain text of the enforcement document.
        inventory:         GRC controls list from inventory.load_inventory().
        rag_collection:    Pre-built ChromaDB collection (optional).
        progress_callback: Optional callable(message: str) for UI updates.

    Returns:
        dict with keys matching orchestrator.run_agentic_pipeline() output:
          gap_analysis, overall_assessment, unaddressed_findings,
          _token_usage, _rag_metadata, _agent_metadata

    Raises:
        RuntimeError: If Azure OpenAI configuration is missing.
        RuntimeError: If the pipeline fails and error propagation is enabled.
    """
    missing = AzureOpenAIConfig.validate()
    if missing:
        raise RuntimeError(
            f"Missing Azure OpenAI configuration: {', '.join(missing)}. "
            "Please update your .env file."
        )

    graph = _get_graph()

    initial_state: PipelineState = {
        "document_text":     document_text,
        "inventory":         inventory,
        "rag_collection":    rag_collection,
        "progress_callback": progress_callback,
        "token_usage":       {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "agent_metadata":    {},
        "error":             None,
    }

    if progress_callback:
        progress_callback("🚀 LangGraph pipeline starting: Intelligence Extractor → Semantic Retrieval Agent → Compliance Gap Analyser")

    # Invoke the compiled graph — runs all three nodes sequentially
    final_state: PipelineState = graph.invoke(initial_state)

    # Surface any error from node execution
    if final_state.get("error"):
        raise RuntimeError(f"LangGraph pipeline error: {final_state['error']}")

    # Map final state back to the standard output schema
    return {
        "gap_analysis":        final_state.get("gap_analysis", []),
        "overall_assessment":  final_state.get("overall_assessment", {}),
        "unaddressed_findings": final_state.get("unaddressed", []),
        "_token_usage":        final_state.get("token_usage", {}),
        "_rag_metadata":       final_state.get("rag_metadata", {}),
        "_agent_metadata":     final_state.get("agent_metadata", {}),
    }
