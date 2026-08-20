"""
app/retriever.py
----------------
Semantic retrieval layer for the RAG pipeline.

Given a set of enforcement themes and root causes extracted from an enforcement
document, this module finds the most semantically relevant GRC controls from the
vector index — without keyword matching, without assessing every control.

This is the core of the Phase 2 RAG approach:

  Phase 1:  ALL N controls → batch into groups → LLM assesses each group
  Phase 2:  Enforcement themes → embed → semantic search → TOP K controls only
            → LLM assesses only the K most relevant controls

For a 500-control inventory and 9 enforcement themes, Phase 2 typically reduces
the LLM input from 500 controls to 8–15 controls — a 97%+ reduction in tokens
with better precision (LLM attention focused on relevant controls only).
"""

from __future__ import annotations

import logging

from config import AppConfig
from app.vector_store import get_or_build_control_index, query_controls

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def retrieve_relevant_controls(
    themes: list[str],
    root_causes: list[dict],
    inventory: list[dict],
    top_k: int = None,
    max_controls: int = None,
    collection=None,
) -> list[dict]:
    """
    Retrieve the most semantically relevant GRC controls for the enforcement findings.

    For each enforcement theme and root cause finding, runs a separate vector
    similarity search. Results are deduplicated across queries and ranked by
    best (lowest) distance score, then capped at max_controls.

    Args:
        themes:       List of misconduct/control failure theme strings from extraction.
        root_causes:  List of root cause dicts (each with a "finding" key) from extraction.
        inventory:    Full GRC inventory list (used to build/retrieve the vector index).
        top_k:        Controls to retrieve per individual query. Defaults to
                      AppConfig.RETRIEVAL_TOP_K.
        max_controls: Maximum unique controls returned after deduplication. Defaults to
                      AppConfig.MAX_RETRIEVED_CONTROLS.
        collection:   Pre-built ChromaDB collection (optional). If None, the collection
                      is loaded or built automatically via get_or_build_control_index().

    Returns:
        List of control dicts (same format as inventory.load_inventory()) containing
        only the most relevant controls, ordered by semantic relevance (best first).

    Raises:
        RuntimeError: If the vector index cannot be built or queried.
    """
    top_k = top_k or AppConfig.RETRIEVAL_TOP_K
    max_controls = max_controls or AppConfig.MAX_RETRIEVED_CONTROLS

    # ── Load or reuse vector index ────────────────────────────────────────────
    if collection is None:
        collection = get_or_build_control_index(inventory)

    # ── Build query list ──────────────────────────────────────────────────────
    # Include both themes and root cause findings as separate queries to maximise
    # recall. Different phrasing of the same issue often matches different controls.
    queries: list[str] = []

    for theme in themes:
        if theme and theme.strip():
            queries.append(theme.strip())

    for rc in root_causes:
        finding = rc.get("finding", "").strip()
        if finding:
            queries.append(finding)

    if not queries:
        logger.warning(
            "No themes or root causes provided — returning full inventory as fallback."
        )
        return inventory[:max_controls]

    logger.info(
        "Retrieving controls for %d queries (themes + root causes), top_k=%d per query.",
        len(queries),
        top_k,
    )

    # ── Search across all queries, track best distance per control ────────────
    # control_id → best (lowest) distance seen across all queries
    best_distance: dict[str, float] = {}

    for query_text in queries:
        hits = query_controls(collection, query_text, top_k=top_k)
        for hit in hits:
            ctrl_id = hit["control_id"]
            dist = hit["distance"]
            if ctrl_id not in best_distance or dist < best_distance[ctrl_id]:
                best_distance[ctrl_id] = dist

    # ── Rank by best distance and cap ────────────────────────────────────────
    ranked_ids = sorted(best_distance.keys(), key=lambda cid: best_distance[cid])
    top_ids = set(ranked_ids[:max_controls])

    logger.info(
        "Retrieved %d unique controls from %d total inventory items "
        "(reduction: %.0f%%).",
        len(top_ids),
        len(inventory),
        (1 - len(top_ids) / max(len(inventory), 1)) * 100,
    )

    # ── Return matching controls in relevance order ───────────────────────────
    # Preserve the full original control dict (not the ChromaDB metadata copy)
    # so the comparator receives all fields as expected.
    id_to_control = {ctrl["control_id"]: ctrl for ctrl in inventory}
    result = []
    for ctrl_id in ranked_ids[:max_controls]:
        ctrl = id_to_control.get(ctrl_id)
        if ctrl:
            result.append(ctrl)

    return result


def retrieve_relevant_controls_with_scores(
    themes: list[str],
    root_causes: list[dict],
    inventory: list[dict],
    top_k: int = None,
    max_controls: int = None,
    collection=None,
) -> list[tuple[dict, float]]:
    """
    Same as retrieve_relevant_controls but also returns similarity scores.

    Useful for debugging and UI display (showing why a control was selected).

    Returns:
        List of (control_dict, distance_score) tuples, ordered by relevance (best first).
        Lower distance = more similar = more relevant.
    """
    top_k = top_k or AppConfig.RETRIEVAL_TOP_K
    max_controls = max_controls or AppConfig.MAX_RETRIEVED_CONTROLS

    if collection is None:
        collection = get_or_build_control_index(inventory)

    queries: list[str] = []
    for theme in themes:
        if theme and theme.strip():
            queries.append(theme.strip())
    for rc in root_causes:
        finding = rc.get("finding", "").strip()
        if finding:
            queries.append(finding)

    if not queries:
        return [(ctrl, 0.0) for ctrl in inventory[:max_controls]]

    best_distance: dict[str, float] = {}
    for query_text in queries:
        hits = query_controls(collection, query_text, top_k=top_k)
        for hit in hits:
            ctrl_id = hit["control_id"]
            dist = hit["distance"]
            if ctrl_id not in best_distance or dist < best_distance[ctrl_id]:
                best_distance[ctrl_id] = dist

    ranked_ids = sorted(best_distance.keys(), key=lambda cid: best_distance[cid])
    top_ids = ranked_ids[:max_controls]

    id_to_control = {ctrl["control_id"]: ctrl for ctrl in inventory}
    return [
        (id_to_control[cid], best_distance[cid])
        for cid in top_ids
        if cid in id_to_control
    ]
