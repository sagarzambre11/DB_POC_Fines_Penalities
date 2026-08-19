"""
app/comparator.py
-----------------
Step 4: LLM-based comparison of extracted enforcement findings against GRC inventory.

Sends the enforcement JSON and GRC control inventory to Azure OpenAI GPT-4o
and returns a structured comparison result for each control.
"""

import json
from openai import AzureOpenAI
from config import AzureOpenAIConfig, AppConfig
from app.inventory import inventory_to_prompt_text

# ---------------------------------------------------------------------------
# Comparison prompt
# ---------------------------------------------------------------------------

COMPARISON_SYSTEM_PROMPT = """You are a senior GRC (Governance, Risk and Compliance) analyst
specialising in regulatory enforcement gap analysis.

Your task is to compare a set of regulatory enforcement findings (extracted from an FCA or other
regulatory Final Notice) against a firm's GRC Control Inventory, and assess the coverage level
of each control against the specific findings in the enforcement action.

Coverage Classifications (use EXACTLY these labels):
  - "Covered"               : The control directly and fully addresses the finding.
  - "Partially Covered"     : The control exists but is incomplete, narrow, or has documented gaps.
  - "Policy-Only Coverage"  : Only a policy exists; no operational/detective control is in place.
  - "Potential Control Gap" : No control in the inventory addresses this finding.
  - "Insufficient Evidence" : Insufficient information to determine coverage.

You must return ONLY a valid JSON object with the following structure:

{
  "gap_analysis": [
    {
      "control_id": "<control ID from inventory>",
      "control_name": "<control name from inventory>",
      "related_findings": ["<brief description of the enforcement finding this maps to>"],
      "related_themes": ["<misconduct/control failure theme from enforcement data>"],
      "coverage_classification": "<one of the 5 labels above>",
      "classification_rationale": "<clear explanation of why this classification was assigned>",
      "enforcement_evidence": "<specific text or paragraph from the enforcement findings supporting this>",
      "recommended_action": "<what the firm should do to close the gap or strengthen the control>"
    }
  ],
  "overall_assessment": {
    "total_controls_assessed": <number>,
    "covered_count": <number>,
    "partially_covered_count": <number>,
    "policy_only_count": <number>,
    "gap_count": <number>,
    "insufficient_evidence_count": <number>,
    "overall_risk_rating": "<Low | Medium | High | Critical>",
    "executive_summary": "<2-3 sentence executive summary of the gap analysis findings>"
  },
  "unmatched_findings": [
    {
      "finding": "<enforcement finding or theme with no matching control>",
      "risk_implication": "<why this gap is significant>",
      "suggested_new_control": "<description of a recommended new control to address this>"
    }
  ]
}

IMPORTANT:
- Assess EVERY control in the inventory. Do not skip any.
- Base your assessment strictly on the enforcement findings provided.
- Return ONLY the JSON object. No markdown, no explanation, no code fences.
- Be specific and cite evidence from the enforcement data in classification_rationale.
"""

COMPARISON_USER_PROMPT_TEMPLATE = """Please perform a gap analysis comparing the enforcement
findings below against the GRC Control Inventory.

=== ENFORCEMENT FINDINGS (extracted JSON) ===
{enforcement_json}

=== GRC CONTROL INVENTORY ===
{inventory_text}

For each control in the inventory, assess its coverage against the enforcement findings.
Also identify any enforcement findings or themes that have NO matching control in the inventory.

Return only the JSON object as specified."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compare_findings_to_inventory(
    extracted_enforcement: dict,
    inventory: list[dict],
) -> dict:
    """
    Compare extracted enforcement findings against the GRC control inventory.

    Args:
        extracted_enforcement: Dict returned by extractor.extract_enforcement_data().
        inventory:             List of control dicts from inventory.load_inventory().

    Returns:
        A structured comparison dict with gap_analysis, overall_assessment,
        and unmatched_findings sections.

    Raises:
        ValueError:   If the LLM response cannot be parsed as valid JSON.
        RuntimeError: If the Azure OpenAI API call fails.
    """
    missing = AzureOpenAIConfig.validate()
    if missing:
        raise RuntimeError(
            f"Missing Azure OpenAI configuration: {', '.join(missing)}. "
            "Please update your .env file."
        )

    client = AzureOpenAI(
        azure_endpoint=AzureOpenAIConfig.ENDPOINT,
        api_key=AzureOpenAIConfig.API_KEY,
        api_version=AzureOpenAIConfig.API_VERSION,
    )

    enforcement_json_str = json.dumps(extracted_enforcement, indent=2)
    inventory_text = inventory_to_prompt_text(inventory)

    user_prompt = COMPARISON_USER_PROMPT_TEMPLATE.format(
        enforcement_json=enforcement_json_str,
        inventory_text=inventory_text,
    )

    response = client.chat.completions.create(
        model=AzureOpenAIConfig.DEPLOYMENT,
        messages=[
            {"role": "system", "content": COMPARISON_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=AppConfig.MAX_TOKENS_COMPARISON,
        temperature=AppConfig.TEMPERATURE,
        response_format={"type": "json_object"},
    )

    raw_content = response.choices[0].message.content.strip()

    try:
        comparison = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned invalid JSON during comparison: {exc}\n"
            f"Raw response:\n{raw_content[:500]}"
        ) from exc

    return comparison


def get_comparison_summary(comparison: dict) -> dict:
    """
    Extract the overall_assessment section for quick display.

    Args:
        comparison: Dict returned by compare_findings_to_inventory().

    Returns:
        The overall_assessment dict, or an empty dict if not present.
    """
    return comparison.get("overall_assessment", {})


def get_gap_analysis_rows(comparison: dict) -> list[dict]:
    """
    Flatten gap_analysis into a list of display-ready rows.

    Args:
        comparison: Dict returned by compare_findings_to_inventory().

    Returns:
        List of dicts suitable for creating a Pandas DataFrame.
    """
    rows = []
    for item in comparison.get("gap_analysis", []):
        rows.append(
            {
                "Control ID": item.get("control_id", ""),
                "Control Name": item.get("control_name", ""),
                "Coverage Classification": item.get("coverage_classification", ""),
                "Classification Rationale": item.get("classification_rationale", ""),
                "Related Findings": "; ".join(item.get("related_findings", [])),
                "Related Themes": "; ".join(item.get("related_themes", [])),
                "Enforcement Evidence": item.get("enforcement_evidence", ""),
                "Recommended Action": item.get("recommended_action", ""),
            }
        )
    return rows


def get_unmatched_findings_rows(comparison: dict) -> list[dict]:
    """
    Flatten unmatched_findings into a list of display-ready rows.

    Args:
        comparison: Dict returned by compare_findings_to_inventory().

    Returns:
        List of dicts suitable for creating a Pandas DataFrame.
    """
    rows = []
    for item in comparison.get("unmatched_findings", []):
        rows.append(
            {
                "Unmatched Finding": item.get("finding", ""),
                "Risk Implication": item.get("risk_implication", ""),
                "Suggested New Control": item.get("suggested_new_control", ""),
            }
        )
    return rows
