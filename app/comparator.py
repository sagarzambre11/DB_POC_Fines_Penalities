"""
app/comparator.py
-----------------
Step 4: LLM-based comparison of enforcement findings against the GRC inventory.

Phase 2 — RAG-Enhanced Implementation:
  1. Enforcement themes + root causes are embedded via the active provider
     (Azure OpenAI or Google — configured in .env, no code changes needed).
  2. Semantic search retrieves ONLY the most relevant controls from the vector
     index (default: top 15 from up to MAX_RETRIEVED_CONTROLS).
  3. Only those retrieved controls are assessed by the LLM — not the full inventory.
  4. Batched LLM calls (BATCH_SIZE items per call) prevent output truncation.
  5. A final summary call produces overall_assessment + unaddressed_findings.

Mode selection (via use_rag parameter):
  use_rag=True  (default) — RAG path: semantic retrieval → focused LLM analysis
  use_rag=False           — Full-scan path: all controls batched (Phase 1 behaviour)

Single Layer — CONTROLS COVERAGE:
  "Does your firm have a Control that would have required this to be addressed?"
"""

import json
from config import AzureOpenAIConfig, AppConfig
from app.inventory import inventory_to_combined_prompt_text
from app.extractor import _build_client, _call_llm_with_retry, _sum_usage

# ---------------------------------------------------------------------------
# Batching configuration
# ---------------------------------------------------------------------------

BATCH_SIZE = 6  # inventory items assessed per LLM call

# ---------------------------------------------------------------------------
# Condensed enforcement helper
# ---------------------------------------------------------------------------

def _condense_enforcement_for_comparison(extracted: dict) -> dict:
    """
    Return only the fields from the extraction result that are relevant
    to gap analysis. Reduces comparison input tokens by ~60%.

    Excluded: source_citations, customer_or_market_impact details,
    confidence_score, settlement_discount, reference_number, etc.
    """
    action = extracted.get("enforcement_action", {})
    return {
        "regulator": extracted.get("regulator", {}),
        "jurisdiction": extracted.get("jurisdiction"),
        "regulatory_domain": extracted.get("regulatory_domain", []),
        "regulated_entity": {
            "name": extracted.get("regulated_entity", {}).get("name"),
            "entity_type": extracted.get("regulated_entity", {}).get("entity_type"),
        },
        "scenario_description": extracted.get("scenario_description"),
        "misconduct_control_failure_themes": extracted.get(
            "misconduct_control_failure_themes", []
        ),
        "root_cause_evidence": extracted.get("root_cause_evidence", []),
        "regulatory_requirements": extracted.get("regulatory_requirements", []),
        "penalty": (
            f"{action.get('penalty_currency', '')} {action.get('penalty_amount', '')}".strip()
        ),
    }


# ---------------------------------------------------------------------------
# Batch gap analysis prompt
# ---------------------------------------------------------------------------

BATCH_SYSTEM_PROMPT = """You are a senior GRC (Governance, Risk and Compliance) analyst
specialising in regulatory enforcement gap analysis.

Perform a CONTROLS GAP ANALYSIS for each inventory item provided:

CONTROLS COVERAGE: Does the firm's CONTROL (objective/statement/mechanism) address the enforcement finding?

Coverage labels (use EXACTLY these):
  "Covered"               — Fully addressed by this control
  "Partially Covered"     — Exists but incomplete or narrow
  "Potential Gap"         — No matching control
  "Insufficient Evidence" — Cannot determine

Stakeholder roles: "Controls Owner" | "Risk Manager" | "Compliance Head" | "Technology"

Return ONLY a JSON object in this exact format:
{
  "gap_analysis": [
    {
      "id": "<control_id>",
      "name": "<control_name>",
      "domain": "<regulatory_domain>",
      "owner": "<owner>",
      "related_enforcement_themes": ["<theme>"],
      "related_root_causes": ["<finding>"],
      "controls_layer": {
        "coverage_classification": "<label>",
        "rationale": "<explanation referencing the enforcement finding>",
        "enforcement_evidence": "<direct quote or paraphrase>",
        "shift_left_signal": "<proactive forward-looking signal>",
        "recommended_action": "<what the controls owner should do>"
      },
      "stakeholder_signals": [
        {"stakeholder": "<role>", "signal": "<action>", "priority": "<High|Medium|Low>"}
      ],
      "overall_gap_severity": "<Critical|High|Medium|Low>"
    }
  ]
}

RULES: Assess EVERY item in the batch. Return ONLY the JSON. No markdown. No explanation."""

BATCH_USER_TEMPLATE = """Perform controls gap analysis for this batch of inventory items.

=== ENFORCEMENT FINDINGS ===
{enforcement_json}

=== INVENTORY ITEMS (this batch) ===
{inventory_text}

Return only the JSON object as specified."""


# ---------------------------------------------------------------------------
# Summary / overall assessment prompt
# ---------------------------------------------------------------------------

SUMMARY_SYSTEM_PROMPT = """You are a senior GRC analyst. Based on the completed gap analysis results
provided, generate the overall assessment and identify enforcement themes with no inventory coverage.

Return ONLY a JSON object:
{
  "overall_assessment": {
    "regulator": "<regulator from enforcement data>",
    "jurisdiction": "<jurisdiction>",
    "regulatory_domain": ["<domain>"],
    "total_assessed": <number>,
    "controls_layer_summary": {
      "covered": <n>, "partially_covered": <n>, "potential_gap": <n>, "insufficient_evidence": <n>
    },
    "overall_risk_rating": "<Critical|High|Medium|Low>",
    "shift_left_headline": "<1-sentence headline on shift-left value>",
    "executive_summary": "<3-4 sentence executive summary of controls gaps>"
  },
  "unaddressed_findings": [
    {
      "theme": "<enforcement theme with NO matching control>",
      "risk_implication": "<why this gap is significant>",
      "suggested_control": "<new control statement needed>",
      "suggested_owner": "<who should own this>"
    }
  ]
}

Rules: Return ONLY the JSON. No markdown. No explanation."""

SUMMARY_USER_TEMPLATE = """Generate the overall assessment and unaddressed findings from:

=== ENFORCEMENT CONTEXT ===
{enforcement_json}

=== COMPLETED GAP ANALYSIS RESULTS ===
{gap_analysis_json}

Identify any enforcement themes or root causes not addressed by any inventory item."""


# ---------------------------------------------------------------------------
# Internal batch processor
# ---------------------------------------------------------------------------

def _compare_batch(
    client,
    condensed_enforcement: dict,
    batch: list[dict],
) -> tuple[list[dict], dict]:
    """
    Run gap analysis for a single batch of inventory items.

    Returns (gap_analysis list, token_usage dict) for this batch.
    """
    enforcement_json = json.dumps(condensed_enforcement, indent=2)
    inventory_text = inventory_to_combined_prompt_text(batch)

    user_prompt = BATCH_USER_TEMPLATE.format(
        enforcement_json=enforcement_json,
        inventory_text=inventory_text,
    )

    raw, usage = _call_llm_with_retry(
        client,
        model=AzureOpenAIConfig.DEPLOYMENT,
        messages=[
            {"role": "system", "content": BATCH_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=AppConfig.MAX_TOKENS_COMPARISON,
    )

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned invalid JSON for batch: {exc}\n"
            f"Raw response (first 500 chars):\n{raw[:500]}"
        ) from exc

    return result.get("gap_analysis", []), usage


def _generate_summary(
    client,
    condensed_enforcement: dict,
    all_gap_analysis: list[dict],
) -> tuple[dict, dict]:
    """
    Generate overall_assessment and unaddressed_findings after all batches complete.

    Returns (summary dict, token_usage dict).
    """
    enforcement_json = json.dumps(condensed_enforcement, indent=2)
    gap_analysis_json = json.dumps({"gap_analysis": all_gap_analysis}, indent=2)

    user_prompt = SUMMARY_USER_TEMPLATE.format(
        enforcement_json=enforcement_json,
        gap_analysis_json=gap_analysis_json,
    )

    raw, usage = _call_llm_with_retry(
        client,
        model=AzureOpenAIConfig.DEPLOYMENT,
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=AppConfig.MAX_TOKENS_SUMMARY,
    )

    try:
        summary = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned invalid JSON for summary: {exc}\n"
            f"Raw response (first 500 chars):\n{raw[:500]}"
        ) from exc

    return summary, usage


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compare_findings_to_inventory(
    extracted_enforcement: dict,
    inventory: list[dict],
    progress_callback=None,
    use_rag: bool = True,
    rag_collection=None,
) -> dict:
    """
    Controls gap analysis of enforcement findings against the GRC inventory.

    Phase 2 RAG mode (use_rag=True, default):
      1. Extracts themes + root causes from the enforcement data
      2. Runs semantic search to retrieve only the most relevant controls
      3. Batches ONLY those retrieved controls to the LLM for assessment
      4. Generates overall assessment and unaddressed findings

    Full-scan mode (use_rag=False):
      - Phase 1 behaviour: all controls batched regardless of relevance

    Args:
        extracted_enforcement: Dict from extractor.extract_enforcement_data().
        inventory:             List of control dicts from inventory.load_inventory().
        progress_callback:     Optional callable(message: str) for UI status updates.
        use_rag:               If True (default), use semantic retrieval to pre-filter
                               controls before LLM assessment. If False, assess all controls.
        rag_collection:        Pre-built ChromaDB collection (optional). If None and
                               use_rag=True, the collection is loaded/built automatically.

    Returns:
        Structured comparison dict with:
          - gap_analysis:        List of per-control gap analysis results
          - overall_assessment:  Summary metrics and executive summary
          - unaddressed_findings: Enforcement themes with no matching control
          - _token_usage:        Total token usage across all LLM calls
          - _rag_metadata:       RAG retrieval info (controls assessed, reduction %)

    Raises:
        ValueError:   If any LLM response cannot be parsed as valid JSON.
        RuntimeError: If Azure OpenAI config is missing or API calls fail.
    """
    missing = AzureOpenAIConfig.validate()
    if missing:
        raise RuntimeError(
            f"Missing Azure OpenAI configuration: {', '.join(missing)}. "
            "Please update your .env file."
        )

    client = _build_client()
    condensed = _condense_enforcement_for_comparison(extracted_enforcement)

    # ── RAG: semantic retrieval of relevant controls ───────────────────────────
    controls_to_assess = inventory  # default: full inventory (full-scan mode)
    rag_metadata = {
        "mode": "full_scan",
        "total_inventory": len(inventory),
        "controls_assessed": len(inventory),
        "reduction_pct": 0,
    }

    if use_rag:
        try:
            from app.retriever import retrieve_relevant_controls

            themes = condensed.get("misconduct_control_failure_themes", [])
            root_causes = condensed.get("root_cause_evidence", [])

            if progress_callback:
                progress_callback(
                    f"🔍 Semantic search: finding relevant controls for "
                    f"{len(themes)} enforcement themes..."
                )

            controls_to_assess = retrieve_relevant_controls(
                themes=themes,
                root_causes=root_causes,
                inventory=inventory,
                collection=rag_collection,
            )

            reduction_pct = (
                (1 - len(controls_to_assess) / max(len(inventory), 1)) * 100
            )
            rag_metadata = {
                "mode": "rag",
                "total_inventory": len(inventory),
                "controls_assessed": len(controls_to_assess),
                "reduction_pct": round(reduction_pct, 1),
            }

            if progress_callback:
                progress_callback(
                    f"✅ Semantic search complete: {len(controls_to_assess)} of "
                    f"{len(inventory)} controls selected "
                    f"({reduction_pct:.0f}% reduction in LLM input)."
                )

        except Exception as exc:
            # RAG failure: graceful fallback to full-scan to avoid data loss
            if progress_callback:
                progress_callback(
                    f"⚠️ Semantic search failed ({exc}). "
                    "Falling back to full inventory scan."
                )
            controls_to_assess = inventory
            rag_metadata = {
                "mode": "fallback_full_scan",
                "total_inventory": len(inventory),
                "controls_assessed": len(inventory),
                "reduction_pct": 0,
                "fallback_reason": str(exc),
            }

    # ── Batch the selected controls for LLM assessment ────────────────────────
    batches = [
        controls_to_assess[i: i + BATCH_SIZE]
        for i in range(0, len(controls_to_assess), BATCH_SIZE)
    ]
    total_batches = len(batches)
    all_gap_analysis: list[dict] = []
    total_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    for idx, batch in enumerate(batches):
        if progress_callback:
            progress_callback(
                f"🤖 Analysing batch {idx + 1}/{total_batches} "
                f"({min((idx + 1) * BATCH_SIZE, len(controls_to_assess))} of "
                f"{len(controls_to_assess)} controls processed)..."
            )
        gap_items, batch_usage = _compare_batch(client, condensed, batch)
        all_gap_analysis.extend(gap_items)
        total_usage = _sum_usage(total_usage, batch_usage)

    # ── Final summary call ────────────────────────────────────────────────────
    if progress_callback:
        progress_callback("📊 Generating overall assessment and executive summary...")

    summary, summary_usage = _generate_summary(client, condensed, all_gap_analysis)
    total_usage = _sum_usage(total_usage, summary_usage)

    return {
        "gap_analysis": all_gap_analysis,
        "overall_assessment": summary.get("overall_assessment", {}),
        "unaddressed_findings": summary.get("unaddressed_findings", []),
        "_token_usage": total_usage,
        "_rag_metadata": rag_metadata,
    }


# ---------------------------------------------------------------------------
# Row extraction helpers (for reporter.py)
# ---------------------------------------------------------------------------

def get_controls_gap_rows(comparison: dict) -> list[dict]:
    """Flatten the controls layer of gap_analysis into display-ready rows."""
    rows = []
    for item in comparison.get("gap_analysis", []):
        cl = item.get("controls_layer", {})
        rows.append({
            "ID": item.get("id", ""),
            "Name": item.get("name", ""),
            "Domain": item.get("domain", ""),
            "Controls Owner": item.get("owner", ""),
            "Controls Coverage": cl.get("coverage_classification", ""),
            "Rationale": cl.get("rationale", ""),
            "Enforcement Evidence": cl.get("enforcement_evidence", ""),
            "Shift Left Signal": cl.get("shift_left_signal", ""),
            "Recommended Action": cl.get("recommended_action", ""),
            "Gap Severity": item.get("overall_gap_severity", ""),
            "Related Themes": "; ".join(item.get("related_enforcement_themes", [])),
        })
    return rows


def get_stakeholder_signal_rows(comparison: dict) -> list[dict]:
    """Flatten stakeholder signals across all gap_analysis items into display-ready rows."""
    rows = []
    for item in comparison.get("gap_analysis", []):
        for signal in item.get("stakeholder_signals", []):
            rows.append({
                "ID": item.get("id", ""),
                "Name": item.get("name", ""),
                "Stakeholder": signal.get("stakeholder", ""),
                "Signal": signal.get("signal", ""),
                "Priority": signal.get("priority", ""),
                "Gap Severity": item.get("overall_gap_severity", ""),
            })
    return rows


def get_unaddressed_findings_rows(comparison: dict) -> list[dict]:
    """Flatten unaddressed_findings into display-ready rows."""
    rows = []
    for item in comparison.get("unaddressed_findings", []):
        rows.append({
            "Enforcement Theme": item.get("theme", ""),
            "Risk Implication": item.get("risk_implication", ""),
            "Suggested Control": item.get("suggested_control", ""),
            "Suggested Owner": item.get("suggested_owner", ""),
        })
    return rows


def get_overall_assessment(comparison: dict) -> dict:
    """Return the overall_assessment section of the comparison result."""
    return comparison.get("overall_assessment", {})


def get_comparison_summary(comparison: dict) -> dict:
    """Return a concise human-readable summary of the comparison result."""
    assessment = get_overall_assessment(comparison)
    rag_meta = comparison.get("_rag_metadata", {})
    cl = assessment.get("controls_layer_summary", {})
    return {
        "Overall Risk Rating": assessment.get("overall_risk_rating", "N/A"),
        "Total Assessed": assessment.get("total_assessed", 0),
        "Controls: Covered": cl.get("covered", 0),
        "Controls: Partially Covered": cl.get("partially_covered", 0),
        "Controls: Potential Gap": cl.get("potential_gap", 0),
        "Controls: Insufficient Evidence": cl.get("insufficient_evidence", 0),
        "Unaddressed Findings": len(comparison.get("unaddressed_findings", [])),
        "Analysis Mode": rag_meta.get("mode", "unknown"),
        "Controls Assessed": rag_meta.get("controls_assessed", 0),
        "Total Inventory": rag_meta.get("total_inventory", 0),
        "Token Reduction": f"{rag_meta.get('reduction_pct', 0):.0f}%",
    }
