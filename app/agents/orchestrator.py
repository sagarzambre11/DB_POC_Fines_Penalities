"""
app/agents/orchestrator.py
--------------------------
Agentic RAG orchestration pipeline — v4

Three self-correcting agents wired together:

  Agent 1 — Extraction Agent
    Runs extract_enforcement_data(), inspects the confidence score, and
    applies a structured refinement loop if the initial extraction is
    below threshold or yields too few themes.

  Agent 2 — Retrieval Agent (HyDE)
    Generates Hypothetical Document Embeddings (HyDE) — synthetic GRC
    controls phrased as if they *should* exist — to expand the query set
    before semantic search.  Applies a quality gate to filter out low-
    similarity hits and falls back to domain-based selection if the gate
    over-filters.

  Agent 3 — Gap Analysis Agent
    Quick-screens all retrieved controls in small batches, then runs
    targeted deep-dive re-assessments for every control flagged as a
    high-severity gap.  A reflection pass detects and resolves
    contradictions between the quick-screen and deep-dive verdicts.
    Produces the final gap_analysis list + overall_assessment summary.

Public API
----------
    run_agentic_pipeline(document_text, inventory, rag_collection, progress_callback)
        -> dict  (same schema as comparator.compare_findings_to_inventory plus
                  _agent_metadata with per-agent trace data)
"""

from __future__ import annotations

import json
import logging

from config import AzureOpenAIConfig, AppConfig
from app.extractor import (
    _build_client,
    _call_llm_with_retry,
    _sum_usage,
    extract_enforcement_data,
)
from app.comparator import (
    _condense_enforcement_for_comparison,
    _compare_batch,
    _generate_summary,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agentic tuning constants
# ---------------------------------------------------------------------------

AGENTIC_BATCH_SIZE: int = 4
CONFIDENCE_THRESHOLD: float = 0.70
MIN_THEME_COUNT: int = 3
QUALITY_GATE_DISTANCE: float = 1.20
MIN_CONTROLS_AFTER_GATE: int = 5
DEEP_DIVE_SEVERITIES: frozenset = frozenset({"Critical", "High"})
DEEP_DIVE_COVERAGES: frozenset = frozenset({"Potential Gap"})

# ---------------------------------------------------------------------------
# Agent 1 — Extraction Agent
# ---------------------------------------------------------------------------

_REFINEMENT_SYSTEM_PROMPT = (
    "You are a specialist regulatory enforcement analyst.\n\n"
    "The initial extraction of the enforcement document below is provided. Your task is\n"
    "to REVIEW it critically and REFINE the following fields:\n"
    "  - misconduct_control_failure_themes  (aim for 5-10 specific, actionable themes)\n"
    "  - root_cause_evidence                (each finding must cite document evidence)\n"
    "  - confidence_score                   (re-score based on the improved extraction)\n\n"
    "Return ONLY a valid JSON object with EXACTLY these three top-level keys:\n"
    "{\n"
    '  "misconduct_control_failure_themes": ["<theme 1>", ...],\n'
    '  "root_cause_evidence": [\n'
    '    {"finding": "<finding>", "evidence": "<evidence from document>"},\n'
    "    ...\n"
    "  ],\n"
    '  "confidence_score": {\n'
    '    "score": <float 0.0-1.0>,\n'
    '    "scale": "0 to 1",\n'
    '    "rationale": "<explanation>"\n'
    "  }\n"
    "}\n\n"
    "Return ONLY raw JSON. No markdown fences. No explanation text."
)

_REFINEMENT_USER_TEMPLATE = (
    "Original enforcement document (excerpt):\n"
    "---\n"
    "{document_excerpt}\n"
    "---\n\n"
    "Initial extraction result:\n"
    "{initial_extraction_json}\n\n"
    "Critically review the themes and root causes. Return the refined JSON as specified."
)


def _run_extraction_agent(
    client,
    document_text: str,
    progress_callback=None,
) -> tuple[dict, dict, dict]:
    """
    Extraction Agent: extract enforcement data with optional self-correction.

    Returns:
        (extracted_data, agent_metadata, token_usage)
    """
    if progress_callback:
        progress_callback("🔍 Extraction Agent: parsing enforcement document...")

    extracted = extract_enforcement_data(document_text)
    initial_usage = extracted.pop("_token_usage", {})

    initial_confidence = extracted.get("confidence_score", {}).get("score") or 0.0
    initial_theme_count = len(extracted.get("misconduct_control_failure_themes", []))

    agent_meta: dict = {
        "iterations": 1,
        "refinements_applied": [],
        "initial_confidence": initial_confidence,
        "final_confidence": initial_confidence,
        "final_theme_count": initial_theme_count,
    }
    total_usage = dict(initial_usage)

    needs_refinement = (
        initial_confidence < CONFIDENCE_THRESHOLD or initial_theme_count < MIN_THEME_COUNT
    )

    if needs_refinement:
        reason = []
        if initial_confidence < CONFIDENCE_THRESHOLD:
            reason.append(f"low confidence ({initial_confidence:.2f})")
        if initial_theme_count < MIN_THEME_COUNT:
            reason.append(f"only {initial_theme_count} theme(s) detected")

        if progress_callback:
            progress_callback(
                f"🔄 Extraction Agent: refining extraction ({', '.join(reason)})..."
            )

        try:
            user_prompt = _REFINEMENT_USER_TEMPLATE.format(
                document_excerpt=document_text[:6000],
                initial_extraction_json=json.dumps(
                    {
                        "misconduct_control_failure_themes": extracted.get(
                            "misconduct_control_failure_themes", []
                        ),
                        "root_cause_evidence": extracted.get("root_cause_evidence", []),
                        "confidence_score": extracted.get("confidence_score", {}),
                    },
                    indent=2,
                ),
            )

            raw, ref_usage = _call_llm_with_retry(
                client,
                model=AzureOpenAIConfig.DEPLOYMENT,
                messages=[
                    {"role": "system", "content": _REFINEMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_completion_tokens=AppConfig.MAX_TOKENS_EXTRACTION,
            )

            refinement = json.loads(raw)
            total_usage = _sum_usage(total_usage, ref_usage)

            if refinement.get("misconduct_control_failure_themes"):
                extracted["misconduct_control_failure_themes"] = refinement[
                    "misconduct_control_failure_themes"
                ]
                agent_meta["refinements_applied"].append("themes")

            if refinement.get("root_cause_evidence"):
                extracted["root_cause_evidence"] = refinement["root_cause_evidence"]
                agent_meta["refinements_applied"].append("root_causes")

            if refinement.get("confidence_score"):
                extracted["confidence_score"] = refinement["confidence_score"]

            agent_meta["iterations"] = 2
            agent_meta["final_confidence"] = (
                extracted.get("confidence_score", {}).get("score") or initial_confidence
            )
            agent_meta["final_theme_count"] = len(
                extracted.get("misconduct_control_failure_themes", [])
            )

        except Exception as exc:
            logger.warning("Extraction refinement failed (%s) — using initial result.", exc)

    if progress_callback:
        progress_callback(
            f"✅ Extraction Agent complete — "
            f"{agent_meta['final_theme_count']} themes, "
            f"confidence {agent_meta['final_confidence']:.2f}, "
            f"{agent_meta['iterations']} iteration(s)"
        )

    extracted["_token_usage"] = total_usage
    return extracted, agent_meta, total_usage


# ---------------------------------------------------------------------------
# Agent 2 — Retrieval Agent (HyDE)
# ---------------------------------------------------------------------------

_HYDE_SYSTEM_PROMPT = (
    "You are a GRC (Governance, Risk & Compliance) policy author.\n\n"
    "Given a list of regulatory enforcement themes and root causes, generate\n"
    "hypothetical GRC control statements that a well-governed firm SHOULD have\n"
    "had in place to prevent the enforcement action.\n\n"
    "Return ONLY a JSON object:\n"
    "{\n"
    '  "hypothetical_controls": [\n'
    '    "<control statement 1>",\n'
    '    "<control statement 2>",\n'
    "    ...\n"
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Generate 1-2 hypothetical controls per enforcement theme (aim for 8-15 total).\n"
    "- Each statement should be 1-3 sentences describing the control objective.\n"
    "- Return ONLY raw JSON. No markdown. No explanation."
)

_HYDE_USER_TEMPLATE = (
    "Generate hypothetical GRC controls for the following enforcement findings:\n\n"
    "=== ENFORCEMENT THEMES ===\n"
    "{themes_text}\n\n"
    "=== ROOT CAUSE FINDINGS ===\n"
    "{root_causes_text}\n\n"
    "Return the JSON as specified."
)


def _run_retrieval_agent(
    client,
    condensed_enforcement: dict,
    inventory: list[dict],
    rag_collection=None,
    progress_callback=None,
) -> tuple[list[dict], dict, dict]:
    """
    Retrieval Agent: HyDE-augmented semantic search with quality gate.

    Returns:
        (selected_controls, agent_metadata, token_usage)
    """
    themes = condensed_enforcement.get("misconduct_control_failure_themes", [])
    root_causes = condensed_enforcement.get("root_cause_evidence", [])
    regulatory_domains = condensed_enforcement.get("regulatory_domain", [])

    total_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    hyde_queries: list[str] = []
    hyde_count = 0

    # ── Step 1: HyDE query generation ─────────────────────────────────────────
    if progress_callback:
        progress_callback(
            f"🧠 Retrieval Agent: generating HyDE queries for "
            f"{len(themes)} enforcement theme(s)..."
        )

    try:
        themes_text = "\n".join(f"- {t}" for t in themes if t)
        root_causes_text = "\n".join(
            f"- {rc.get('finding', '')}" for rc in root_causes if rc.get("finding")
        )
        raw, hyde_usage = _call_llm_with_retry(
            client,
            model=AzureOpenAIConfig.DEPLOYMENT,
            messages=[
                {"role": "system", "content": _HYDE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _HYDE_USER_TEMPLATE.format(
                        themes_text=themes_text or "(none provided)",
                        root_causes_text=root_causes_text or "(none provided)",
                    ),
                },
            ],
            max_completion_tokens=4096,
        )
        hyde_result = json.loads(raw)
        hyde_queries = hyde_result.get("hypothetical_controls", [])
        hyde_count = len(hyde_queries)
        total_usage = _sum_usage(total_usage, hyde_usage)
    except Exception as exc:
        logger.warning("HyDE generation failed (%s) — using base queries only.", exc)

    # ── Step 2: Assemble query set ─────────────────────────────────────────────
    base_queries: list[str] = [t for t in themes if t and t.strip()]
    for rc in root_causes:
        finding = rc.get("finding", "").strip()
        if finding:
            base_queries.append(finding)

    all_queries = base_queries + hyde_queries
    total_queries_run = len(all_queries)

    if progress_callback:
        progress_callback(
            f"🔍 Retrieval Agent: running {total_queries_run} semantic queries "
            f"({len(base_queries)} original + {hyde_count} HyDE)..."
        )

    # ── Step 3: Semantic search ────────────────────────────────────────────────
    try:
        from app.vector_store import get_or_build_control_index, query_controls

        if rag_collection is None:
            rag_collection = get_or_build_control_index(inventory)

        best_distance: dict[str, float] = {}
        for query_text in all_queries:
            if not query_text.strip():
                continue
            hits = query_controls(rag_collection, query_text, top_k=AppConfig.RETRIEVAL_TOP_K)
            for hit in hits:
                ctrl_id = hit["control_id"]
                dist = hit["distance"]
                if ctrl_id not in best_distance or dist < best_distance[ctrl_id]:
                    best_distance[ctrl_id] = dist

        ranked_ids = sorted(best_distance, key=lambda cid: best_distance[cid])

    except Exception as exc:
        logger.warning("Semantic search failed (%s) — falling back to full inventory.", exc)
        selected = inventory[: AppConfig.MAX_RETRIEVED_CONTROLS]
        return (
            selected,
            {
                "query_expansion": {
                    "hyde_queries_generated": hyde_count,
                    "total_queries_run": total_queries_run,
                },
                "quality_gate": {
                    "controls_filtered_out": 0,
                    "domain_fallback_triggered": True,
                },
                "final_controls_count": len(selected),
            },
            total_usage,
        )

    # ── Step 4: Quality gate ───────────────────────────────────────────────────
    before_gate = len(ranked_ids)
    gated_ids = [
        cid for cid in ranked_ids if best_distance[cid] <= QUALITY_GATE_DISTANCE
    ]
    filtered_out = before_gate - len(gated_ids)
    domain_fallback = False

    if len(gated_ids) < MIN_CONTROLS_AFTER_GATE:
        domain_fallback = True
        if progress_callback:
            progress_callback(
                f"⚠️ Retrieval Agent: quality gate left {len(gated_ids)} controls — "
                "applying domain fallback top-up..."
            )
        domains_lower = {d.lower() for d in regulatory_domains}
        id_to_ctrl = {c["control_id"]: c for c in inventory}
        gated_set = set(gated_ids)
        domain_topup = [
            ctrl_id
            for ctrl_id in ranked_ids
            if ctrl_id not in gated_set
            and any(
                d.lower() in domains_lower
                for d in (id_to_ctrl.get(ctrl_id) or {}).get("regulatory_domain", "").split(",")
            )
        ]
        gated_ids = gated_ids + domain_topup[: max(0, MIN_CONTROLS_AFTER_GATE - len(gated_ids))]

    # Cap to MAX_RETRIEVED_CONTROLS
    final_ids = gated_ids[: AppConfig.MAX_RETRIEVED_CONTROLS]
    id_to_ctrl_full = {c["control_id"]: c for c in inventory}
    selected_controls = [
        id_to_ctrl_full[cid] for cid in final_ids if cid in id_to_ctrl_full
    ]

    if progress_callback:
        progress_callback(
            f"✅ Retrieval Agent complete — {len(selected_controls)} controls selected "
            f"(filtered out {filtered_out}, domain_fallback={domain_fallback})"
        )

    agent_meta = {
        "query_expansion": {
            "hyde_queries_generated": hyde_count,
            "total_queries_run": total_queries_run,
        },
        "quality_gate": {
            "controls_filtered_out": filtered_out,
            "domain_fallback_triggered": domain_fallback,
        },
        "final_controls_count": len(selected_controls),
    }
    return selected_controls, agent_meta, total_usage


# ---------------------------------------------------------------------------
# Agent 3 — Gap Analysis Agent
# ---------------------------------------------------------------------------

_DEEP_DIVE_SYSTEM_PROMPT = (
    "You are a senior GRC analyst performing a DEEP-DIVE gap analysis.\n\n"
    "You have been given a single GRC control that was flagged as a potential gap\n"
    "in a quick-screen assessment. Re-examine it carefully against the enforcement\n"
    "findings and determine the FINAL coverage classification.\n\n"
    "Return ONLY a JSON object matching this schema exactly:\n"
    "{\n"
    '  "gap_analysis": [\n'
    "    {\n"
    '      "id": "<control_id>",\n'
    '      "name": "<control_name>",\n'
    '      "domain": "<domain>",\n'
    '      "owner": "<owner>",\n'
    '      "related_enforcement_themes": ["<theme>"],\n'
    '      "related_root_causes": ["<finding>"],\n'
    '      "controls_layer": {\n'
    '        "coverage_classification": "<Covered|Partially Covered|Potential Gap|Insufficient Evidence>",\n'
    '        "rationale": "<detailed rationale>",\n'
    '        "enforcement_evidence": "<quote or paraphrase from enforcement doc>",\n'
    '        "shift_left_signal": "<proactive forward-looking signal>",\n'
    '        "recommended_action": "<specific action for the controls owner>"\n'
    "      },\n"
    '      "stakeholder_signals": [\n'
    '        {"stakeholder": "<role>", "signal": "<action>", "priority": "<High|Medium|Low>"}\n'
    "      ],\n"
    '      "overall_gap_severity": "<Critical|High|Medium|Low>"\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Return ONLY raw JSON. No markdown. No explanation."
)

_DEEP_DIVE_USER_TEMPLATE = (
    "Perform a DEEP-DIVE re-assessment for this flagged control.\n\n"
    "=== ENFORCEMENT FINDINGS ===\n"
    "{enforcement_json}\n\n"
    "=== FLAGGED CONTROL (quick-screen verdict: {quick_verdict}) ===\n"
    "{control_json}\n\n"
    "Carefully re-examine and return the final verdict JSON."
)


def _run_gap_analysis_agent(
    client,
    condensed_enforcement: dict,
    selected_controls: list[dict],
    progress_callback=None,
) -> tuple[list[dict], dict, dict, dict]:
    """
    Gap Analysis Agent: quick-screen + targeted deep dives + reflection.

    Returns:
        (final_gap_analysis, summary_dict, agent_metadata, token_usage)
    """
    import json as _json
    from app.inventory import inventory_to_combined_prompt_text

    total_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    enforcement_json = _json.dumps(condensed_enforcement, indent=2)

    # ── Quick screen — batch all controls ─────────────────────────────────────
    if progress_callback:
        progress_callback(
            f"⚡ Gap Analysis Agent: quick-screening {len(selected_controls)} controls..."
        )

    batches = [
        selected_controls[i: i + AGENTIC_BATCH_SIZE]
        for i in range(0, len(selected_controls), AGENTIC_BATCH_SIZE)
    ]
    total_batches = len(batches)
    quick_screen_results: list[dict] = []

    for idx, batch in enumerate(batches):
        if progress_callback:
            progress_callback(
                f"⚡ Quick screen: batch {idx + 1}/{total_batches} "
                f"({min((idx + 1) * AGENTIC_BATCH_SIZE, len(selected_controls))} of "
                f"{len(selected_controls)} controls)..."
            )
        gap_items, batch_usage = _compare_batch(client, condensed_enforcement, batch)
        quick_screen_results.extend(gap_items)
        total_usage = _sum_usage(total_usage, batch_usage)

    quick_screen_count = len(quick_screen_results)

    # ── Identify controls needing deep dives ──────────────────────────────────
    flagged_for_deep_dive: list[dict] = []
    flagged_ids: set[str] = set()
    id_to_quick: dict[str, dict] = {}

    for item in quick_screen_results:
        ctrl_id = item.get("id", "")
        id_to_quick[ctrl_id] = item
        cl = item.get("controls_layer", {})
        coverage = cl.get("coverage_classification", "")
        severity = item.get("overall_gap_severity", "")
        if coverage in DEEP_DIVE_COVERAGES and severity in DEEP_DIVE_SEVERITIES:
            flagged_for_deep_dive.append(item)
            flagged_ids.add(ctrl_id)

    reflection_flags = len(flagged_for_deep_dive)
    deep_dive_results: dict[str, dict] = {}
    deep_dive_control_ids: list[str] = []

    if flagged_for_deep_dive:
        if progress_callback:
            progress_callback(
                f"🔬 Gap Analysis Agent: deep-diving {len(flagged_for_deep_dive)} "
                "flagged controls..."
            )

        id_to_inventory = {c["control_id"]: c for c in selected_controls}

        for item in flagged_for_deep_dive:
            ctrl_id = item.get("id", "")
            quick_verdict = (
                item.get("controls_layer", {}).get("coverage_classification", "Potential Gap")
            )
            ctrl_dict = id_to_inventory.get(ctrl_id, {"control_id": ctrl_id})

            try:
                user_prompt = _DEEP_DIVE_USER_TEMPLATE.format(
                    enforcement_json=enforcement_json,
                    quick_verdict=quick_verdict,
                    control_json=_json.dumps(ctrl_dict, indent=2),
                )
                raw, dd_usage = _call_llm_with_retry(
                    client,
                    model=AzureOpenAIConfig.DEPLOYMENT,
                    messages=[
                        {"role": "system", "content": _DEEP_DIVE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_completion_tokens=AppConfig.MAX_TOKENS_COMPARISON,
                )
                dd_result = _json.loads(raw)
                dd_items = dd_result.get("gap_analysis", [])
                if dd_items:
                    deep_dive_results[ctrl_id] = dd_items[0]
                    deep_dive_control_ids.append(ctrl_id)
                total_usage = _sum_usage(total_usage, dd_usage)
            except Exception as exc:
                logger.warning("Deep dive failed for %s (%s) — keeping quick-screen result.", ctrl_id, exc)

    # ── Reflection: detect and resolve contradictions ─────────────────────────
    contradictions_resolved = 0
    final_gap_analysis: list[dict] = []

    for item in quick_screen_results:
        ctrl_id = item.get("id", "")
        if ctrl_id in deep_dive_results:
            quick_cov = item.get("controls_layer", {}).get("coverage_classification", "")
            deep_cov = deep_dive_results[ctrl_id].get("controls_layer", {}).get(
                "coverage_classification", ""
            )
            if quick_cov != deep_cov:
                contradictions_resolved += 1
            # Deep dive verdict takes precedence
            final_gap_analysis.append(deep_dive_results[ctrl_id])
        else:
            final_gap_analysis.append(item)

    # ── Generate overall summary ───────────────────────────────────────────────
    if progress_callback:
        progress_callback("📊 Gap Analysis Agent: generating overall assessment...")

    summary, summary_usage = _generate_summary(client, condensed_enforcement, final_gap_analysis)
    total_usage = _sum_usage(total_usage, summary_usage)

    agent_meta = {
        "quick_screen_count": quick_screen_count,
        "reflection_flags_raised": reflection_flags,
        "deep_dives_performed": len(deep_dive_control_ids),
        "deep_dive_control_ids": deep_dive_control_ids,
        "contradictions_detected_and_resolved": contradictions_resolved,
    }

    if progress_callback:
        progress_callback(
            f"✅ Gap Analysis Agent complete — "
            f"{quick_screen_count} screened, {len(deep_dive_control_ids)} deep dives, "
            f"{contradictions_resolved} contradiction(s) resolved"
        )

    return final_gap_analysis, summary, agent_meta, total_usage


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_agentic_pipeline(
    document_text: str,
    inventory: list[dict],
    rag_collection=None,
    progress_callback=None,
) -> dict:
    """
    Run the full three-agent agentic RAG pipeline.

    Args:
        document_text:     Plain text of the enforcement document (from parser).
        inventory:         Full GRC inventory list (from inventory.load_inventory()).
        rag_collection:    Pre-built ChromaDB collection (optional).  If None,
                           the Retrieval Agent builds/loads it automatically.
        progress_callback: Optional callable(message: str) for UI status updates.

    Returns:
        dict with keys:
          gap_analysis          — list of per-control gap analysis results
          overall_assessment    — overall risk rating, metrics, executive summary
          unaddressed_findings  — enforcement themes with no matching control
          _token_usage          — combined token usage across all agents
          _rag_metadata         — mode, controls_assessed, total_inventory, reduction_pct
          _agent_metadata       — per-agent trace: extraction_agent, retrieval_agent,
                                  gap_analysis_agent

    Raises:
        RuntimeError: If Azure OpenAI configuration is missing.
    """
    missing = AzureOpenAIConfig.validate()
    if missing:
        raise RuntimeError(
            f"Missing Azure OpenAI configuration: {', '.join(missing)}. "
            "Please update your .env file."
        )

    client = _build_client()
    grand_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    # ── Agent 1: Extraction ────────────────────────────────────────────────────
    extracted_data, extraction_meta, ext_usage = _run_extraction_agent(
        client, document_text, progress_callback=progress_callback
    )
    grand_usage = _sum_usage(grand_usage, ext_usage)

    # ── Condense enforcement for downstream agents ─────────────────────────────
    condensed = _condense_enforcement_for_comparison(extracted_data)

    # ── Agent 2: Retrieval ────────────────────────────────────────────────────
    selected_controls, retrieval_meta, ret_usage = _run_retrieval_agent(
        client,
        condensed,
        inventory,
        rag_collection=rag_collection,
        progress_callback=progress_callback,
    )
    grand_usage = _sum_usage(grand_usage, ret_usage)

    # ── Agent 3: Gap Analysis ─────────────────────────────────────────────────
    final_gap_analysis, summary, gap_meta, gap_usage = _run_gap_analysis_agent(
        client,
        condensed,
        selected_controls,
        progress_callback=progress_callback,
    )
    grand_usage = _sum_usage(grand_usage, gap_usage)

    # ── Assemble RAG metadata ─────────────────────────────────────────────────
    total_inventory = len(inventory)
    controls_assessed = retrieval_meta.get("final_controls_count", len(selected_controls))
    reduction_pct = (1 - controls_assessed / max(total_inventory, 1)) * 100

    rag_metadata = {
        "mode": "agentic_rag",
        "total_inventory": total_inventory,
        "controls_assessed": controls_assessed,
        "reduction_pct": round(reduction_pct, 1),
    }

    # ── Assemble agent metadata ───────────────────────────────────────────────
    agent_metadata = {
        "extraction_agent": extraction_meta,
        "retrieval_agent": retrieval_meta,
        "gap_analysis_agent": gap_meta,
    }

    return {
        "gap_analysis": final_gap_analysis,
        "overall_assessment": summary.get("overall_assessment", {}),
        "unaddressed_findings": summary.get("unaddressed_findings", []),
        "_token_usage": grand_usage,
        "_rag_metadata": rag_metadata,
        "_agent_metadata": agent_metadata,
    }
