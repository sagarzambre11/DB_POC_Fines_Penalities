"""
app/comparator.py
-----------------
Step 4: LLM-based comparison of enforcement findings against the GRC inventory.

Optimised implementation:
  - Condensed enforcement JSON (only gap-relevant fields sent to LLM)
  - Batched comparison (BATCH_SIZE items per call) to prevent output truncation
  - Final summary call for overall_assessment and unaddressed_findings
  - JSON fence stripping + exponential-backoff retry (shared with extractor)

Single Layer — CONTROLS COVERAGE:
  Answers: "Does your firm have a Control that would have required this to be addressed?"
"""

import json
from openai import AzureOpenAI, OpenAI
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
    to gap analysis.  Reduces comparison input tokens by ~60%.

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
) -> dict:
    """
    Single-layer controls gap analysis of enforcement findings against the GRC inventory.

    Optimised: uses condensed enforcement JSON and batched LLM calls
    (BATCH_SIZE items per call) to prevent output truncation and improve
    response quality.

    Args:
        extracted_enforcement: Dict from extractor.extract_enforcement_data().
        inventory:             List of control dicts from inventory.load_inventory().
        progress_callback:     Optional callable(current_batch, total_batches) for
                               UI progress reporting.

    Returns:
        Structured comparison dict with gap_analysis, overall_assessment,
        and unaddressed_findings.

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

    # Split inventory into batches
    batches = [
        inventory[i: i + BATCH_SIZE]
        for i in range(0, len(inventory), BATCH_SIZE)
    ]
    total_batches = len(batches)
    all_gap_analysis: list[dict] = []

    total_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    for idx, batch in enumerate(batches):
        gap_items, batch_usage = _compare_batch(client, condensed, batch)
        all_gap_analysis.extend(gap_items)
        total_usage = _sum_usage(total_usage, batch_usage)
        if progress_callback:
            progress_callback(idx + 1, total_batches)

    # Final call: overall_assessment + unaddressed_findings
    summary, summary_usage = _generate_summary(client, condensed, all_gap_analysis)
    total_usage = _sum_usage(total_usage, summary_usage)

    return {
        "gap_analysis": all_gap_analysis,
        "overall_assessment": summary.get("overall_assessment", {}),
        "unaddressed_findings": summary.get("unaddressed_findings", []),
        "_token_usage": total_usage,
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
