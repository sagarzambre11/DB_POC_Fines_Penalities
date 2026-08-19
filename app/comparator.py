"""
app/comparator.py
-----------------
Step 4: Two-layer LLM-based comparison of enforcement findings against the GRC inventory.

Layer 1 — POLICY COVERAGE (primary):
  Maps enforcement findings against the policy intent (control_objective) of each
  inventory row. Answers: "Does your firm have a policy that would have required
  this problem to be addressed?"

Layer 2 — CONTROL COVERAGE (secondary):
  Maps enforcement findings against the operational control (control_description)
  of each inventory row. Answers: "Is there an operational control that would have
  detected or prevented this?"

Both layers are assessed in a single GPT-4o call for efficiency.
The "shift left" value: policy gaps are the primary signal; control gaps are the
downstream operational consequence.
"""

import json
from openai import AzureOpenAI
from config import AzureOpenAIConfig, AppConfig
from app.inventory import inventory_to_combined_prompt_text

# ---------------------------------------------------------------------------
# Two-layer comparison system prompt
# ---------------------------------------------------------------------------

COMPARISON_SYSTEM_PROMPT = """You are a senior GRC (Governance, Risk and Compliance) analyst
specialising in regulatory enforcement gap analysis and compliance intelligence.

Your task is to perform a TWO-LAYER gap analysis comparing enforcement findings from a
regulatory action (any regulator, any jurisdiction, any domain) against a firm's
GRC inventory that serves dual purpose as both a policy corpus and a control inventory.

=== TWO LAYERS OF ANALYSIS ===

LAYER 1 — POLICY COVERAGE (primary, "shift left" signal):
  Assess whether the firm's POLICY INTENT (the objective/statement) would have
  required the governance, process, or risk management that was absent in the
  enforcement case. A policy gap means the firm's framework did not mandate the
  right behaviour at the strategic/governance level.

LAYER 2 — CONTROL COVERAGE (secondary, operational signal):
  Assess whether the firm has an OPERATIONAL CONTROL (the actual mechanism) that
  would have detected, prevented, or mitigated the specific failure described
  in the enforcement action.

=== COVERAGE CLASSIFICATIONS (use EXACTLY these labels) ===

  "Covered"               : Fully addressed at this layer.
  "Partially Covered"     : Exists but incomplete, narrow, or with documented gaps.
  "Policy-Only Coverage"  : A policy/objective exists but no operational control (Layer 2 only).
  "Potential Gap"         : No matching policy/control addresses this finding.
  "Insufficient Evidence" : Cannot determine from available information.

=== STAKEHOLDER SIGNAL ===

For each gap or partial coverage, identify the most appropriate stakeholder to act:
  - "Policy Owner"    : Policy needs creating or updating
  - "Control Owner"   : Control needs strengthening or adding
  - "Risk Manager"    : Risk assessment needs updating
  - "Compliance Head" : Escalation or governance intervention needed
  - "Technology"      : System/tooling change required

=== REQUIRED JSON OUTPUT ===

{
  "gap_analysis": [
    {
      "id": "<control_id from inventory>",
      "name": "<control_name from inventory>",
      "domain": "<regulatory_domain>",
      "owner": "<owner from inventory>",
      "related_enforcement_themes": ["<theme from misconduct_control_failure_themes>"],
      "related_root_causes": ["<finding from root_cause_evidence>"],
      "policy_layer": {
        "coverage_classification": "<one of the 5 labels>",
        "rationale": "<specific explanation referencing the enforcement finding>",
        "enforcement_evidence": "<direct quote or paraphrase from the enforcement findings>",
        "shift_left_signal": "<proactive signal: what this means for the firm's policy framework>",
        "recommended_action": "<what the policy owner should do>"
      },
      "control_layer": {
        "coverage_classification": "<one of the 5 labels>",
        "rationale": "<specific explanation referencing the enforcement finding>",
        "enforcement_evidence": "<direct quote or paraphrase from the enforcement findings>",
        "recommended_action": "<what the control owner should do>"
      },
      "stakeholder_signals": [
        {
          "stakeholder": "<stakeholder role>",
          "signal": "<specific action signal for this stakeholder>",
          "priority": "<High | Medium | Low>"
        }
      ],
      "overall_gap_severity": "<Critical | High | Medium | Low>"
    }
  ],
  "overall_assessment": {
    "regulator": "<auto-detected regulator from enforcement data>",
    "jurisdiction": "<auto-detected jurisdiction>",
    "regulatory_domain": ["<domain 1>", "<domain 2>"],
    "total_assessed": <number>,
    "policy_layer_summary": {
      "covered": <number>,
      "partially_covered": <number>,
      "potential_gap": <number>,
      "insufficient_evidence": <number>
    },
    "control_layer_summary": {
      "covered": <number>,
      "partially_covered": <number>,
      "policy_only": <number>,
      "potential_gap": <number>,
      "insufficient_evidence": <number>
    },
    "overall_risk_rating": "<Critical | High | Medium | Low>",
    "shift_left_headline": "<1-sentence headline summarising the shift-left value e.g. 'X out of Y policies need urgent review to prevent a similar enforcement action'>",
    "executive_summary": "<3-4 sentence executive summary covering both policy and control gaps>"
  },
  "unaddressed_findings": [
    {
      "theme": "<enforcement theme or root cause with NO matching policy or control>",
      "risk_implication": "<why this gap is significant>",
      "suggested_policy": "<description of a new policy statement needed>",
      "suggested_control": "<description of a new operational control needed>",
      "suggested_owner": "<who should own this>"
    }
  ]
}

IMPORTANT RULES:
- Assess EVERY item in the inventory at BOTH layers. Do not skip any.
- The analysis must be based ENTIRELY on the enforcement findings provided.
- Do NOT assume the regulator or domain — use what is in the enforcement data.
- Return ONLY the JSON object. No markdown fences, no explanation.
- Be specific: reference actual findings, themes and evidence from the enforcement data.
- The shift_left_signal should be forward-looking and proactive, not retrospective.
"""

COMPARISON_USER_PROMPT_TEMPLATE = """Perform a two-layer gap analysis (Policy Layer + Control Layer)
comparing the enforcement findings below against the GRC inventory.

=== ENFORCEMENT FINDINGS (extracted from enforcement document) ===
{enforcement_json}

=== GRC INVENTORY (serves as both Policy Corpus and Control Inventory) ===
{inventory_text}

Instructions:
1. For each inventory item, assess BOTH the Policy Layer (objective/intent) and Control Layer (operational mechanism).
2. Identify enforcement themes and root causes that have NO matching policy or control.
3. Generate stakeholder signals for each gap.
4. Auto-use the regulator, jurisdiction and domain from the enforcement data — do not assume.

Return only the JSON object as specified."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compare_findings_to_inventory(
    extracted_enforcement: dict,
    inventory: list[dict],
) -> dict:
    """
    Two-layer comparison of enforcement findings against the GRC inventory.

    Layer 1: Policy coverage (strategic/governance level)
    Layer 2: Control coverage (operational level)

    Works for any regulator, jurisdiction, or regulatory domain.

    Args:
        extracted_enforcement: Dict from extractor.extract_enforcement_data().
        inventory:             List of control dicts from inventory.load_inventory().

    Returns:
        Structured comparison dict with gap_analysis, overall_assessment,
        and unaddressed_findings.

    Raises:
        ValueError:   If the LLM response cannot be parsed as valid JSON.
        RuntimeError: If Azure OpenAI config is missing or API call fails.
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
    inventory_text = inventory_to_combined_prompt_text(inventory)

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
            f"Raw response (first 500 chars):\n{raw_content[:500]}"
        ) from exc

    return comparison


# ---------------------------------------------------------------------------
# Row extraction helpers (for reporter.py)
# ---------------------------------------------------------------------------

def get_policy_gap_rows(comparison: dict) -> list[dict]:
    """
    Flatten the policy layer of gap_analysis into display-ready rows.

    Args:
        comparison: Dict from compare_findings_to_inventory().

    Returns:
        List of dicts suitable for a Pandas DataFrame.
    """
    rows = []
    for item in comparison.get("gap_analysis", []):
        pl = item.get("policy_layer", {})
        rows.append({
            "ID": item.get("id", ""),
            "Name": item.get("name", ""),
            "Domain": item.get("domain", ""),
            "Policy Owner": item.get("owner", ""),
            "Policy Coverage": pl.get("coverage_classification", ""),
            "Rationale": pl.get("rationale", ""),
            "Enforcement Evidence": pl.get("enforcement_evidence", ""),
            "Shift Left Signal": pl.get("shift_left_signal", ""),
            "Recommended Action": pl.get("recommended_action", ""),
            "Gap Severity": item.get("overall_gap_severity", ""),
            "Related Themes": "; ".join(item.get("related_enforcement_themes", [])),
        })
    return rows


def get_control_gap_rows(comparison: dict) -> list[dict]:
    """
    Flatten the control layer of gap_analysis into display-ready rows.

    Args:
        comparison: Dict from compare_findings_to_inventory().

    Returns:
        List of dicts suitable for a Pandas DataFrame.
    """
    rows = []
    for item in comparison.get("gap_analysis", []):
        cl = item.get("control_layer", {})
        rows.append({
            "ID": item.get("id", ""),
            "Name": item.get("name", ""),
            "Domain": item.get("domain", ""),
            "Control Owner": item.get("owner", ""),
            "Control Coverage": cl.get("coverage_classification", ""),
            "Rationale": cl.get("rationale", ""),
            "Enforcement Evidence": cl.get("enforcement_evidence", ""),
            "Recommended Action": cl.get("recommended_action", ""),
            "Gap Severity": item.get("overall_gap_severity", ""),
            "Related Themes": "; ".join(item.get("related_enforcement_themes", [])),
        })
    return rows


def get_stakeholder_signal_rows(comparison: dict) -> list[dict]:
    """
    Flatten stakeholder signals across all gap_analysis items into display-ready rows.

    Args:
        comparison: Dict from compare_findings_to_inventory().

    Returns:
        List of dicts suitable for a Pandas DataFrame.
    """
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
    """
    Flatten unaddressed_findings into display-ready rows.

    Args:
        comparison: Dict from compare_findings_to_inventory().

    Returns:
        List of dicts suitable for a Pandas DataFrame.
    """
    rows = []
    for item in comparison.get("unaddressed_findings", []):
        rows.append({
            "Enforcement Theme": item.get("theme", ""),
            "Risk Implication": item.get("risk_implication", ""),
            "Suggested Policy": item.get("suggested_policy", ""),
            "Suggested Control": item.get("suggested_control", ""),
            "Suggested Owner": item.get("suggested_owner", ""),
        })
    return rows


def get_overall_assessment(comparison: dict) -> dict:
    """Return the overall_assessment section of the comparison result."""
    return comparison.get("overall_assessment", {})
