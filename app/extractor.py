"""
app/extractor.py
----------------
Step 2: LLM-based structured JSON extraction from regulatory enforcement documents.

Uses Azure OpenAI GPT-4o to extract 13 standardised fields from the raw document text
and returns a validated Python dict matching the PoC JSON schema.
"""

import json
from openai import AzureOpenAI
from config import AzureOpenAIConfig, AppConfig

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """You are a specialist regulatory compliance analyst.
Your task is to extract structured intelligence from regulatory enforcement documents
(e.g. FCA Final Notices, SEC Orders, MAS Notices) and return ONLY a valid JSON object.

Extract the following fields exactly as specified. If a field cannot be determined from
the document, use null for scalar fields or [] for array fields.

Required JSON schema:
{
  "regulator": {
    "name": "<full regulator name>",
    "abbreviation": "<abbreviation>"
  },
  "jurisdiction": "<country or region>",
  "regulated_entity": {
    "name": "<full entity name>",
    "abbreviation": "<abbreviation or null>",
    "entity_type": "<type of firm>",
    "business_context": "<brief description of business activities>"
  },
  "enforcement_action": {
    "action_type": "<type of action e.g. Final Notice and financial penalty>",
    "penalty_amount_gbp": <number or null>,
    "legal_basis": "<statutory basis>",
    "settlement_discount": {
      "percentage": <number or null>,
      "stage": "<stage name or null>",
      "pre_discount_penalty_gbp": <number or null>
    },
    "notice_date": "<YYYY-MM-DD or null>",
    "reference_number": "<reference or null>",
    "additional_remedial_outcome": "<any additional remedies or null>"
  },
  "regulatory_domain": ["<domain 1>", "<domain 2>"],
  "scenario_description": "<detailed description of the misconduct scenario>",
  "misconduct_control_failure_themes": ["<theme 1>", "<theme 2>"],
  "root_cause_evidence": [
    {
      "finding": "<finding summary>",
      "evidence": "<supporting evidence from the document>"
    }
  ],
  "regulatory_requirements": [
    {
      "requirement": "<rule/article reference>",
      "obligation": "<what the rule requires>",
      "breach_finding": "<how the entity breached it>"
    }
  ],
  "customer_or_market_impact": {
    "customer_impact": "<description or null>",
    "market_impact": "<description or null>",
    "affected_trading": {
      "trade_count": <number or null>,
      "notional_value_usd": <number or null>
    },
    "post_remediation_review": {
      "alerts_generated": <number or null>,
      "suspected_insider_dealing_alerts": <number or null>,
      "suspected_market_manipulation_alerts": <number or null>,
      "reporting_outcome": "<description or null>"
    },
    "financial_benefit_from_breach": "<description or null>"
  },
  "fca_source_citations": [
    {
      "source_document": "<document title>",
      "document_date": "<YYYY-MM-DD or null>",
      "reference_number": "<reference or null>",
      "citations": ["<citation 1>", "<citation 2>"]
    }
  ],
  "confidence_score": {
    "score": <float between 0 and 1>,
    "scale": "0 to 1",
    "rationale": "<brief rationale for the score>"
  }
}

IMPORTANT:
- Return ONLY the JSON object. No markdown, no explanation, no code fences.
- All monetary amounts should be numbers (not strings).
- Dates must be in YYYY-MM-DD format.
- Be precise and faithful to the source document.
"""

EXTRACTION_USER_PROMPT_TEMPLATE = """Please extract structured intelligence from the
following regulatory enforcement document text:

---BEGIN DOCUMENT---
{document_text}
---END DOCUMENT---

Return only the JSON object as specified."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_enforcement_data(document_text: str) -> dict:
    """
    Extract structured enforcement intelligence from raw document text.

    Args:
        document_text: Plain text extracted from the regulatory document.

    Returns:
        A Python dict matching the enforcement JSON schema.

    Raises:
        ValueError:  If the LLM response cannot be parsed as valid JSON.
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

    user_prompt = EXTRACTION_USER_PROMPT_TEMPLATE.format(
        document_text=document_text
    )

    response = client.chat.completions.create(
        model=AzureOpenAIConfig.DEPLOYMENT,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=AppConfig.MAX_TOKENS_EXTRACTION,
        temperature=AppConfig.TEMPERATURE,
        response_format={"type": "json_object"},
    )

    raw_content = response.choices[0].message.content.strip()

    try:
        extracted = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned invalid JSON during extraction: {exc}\n"
            f"Raw response:\n{raw_content[:500]}"
        ) from exc

    return extracted


def get_extraction_summary(extracted: dict) -> dict:
    """
    Return a concise human-readable summary of the extracted enforcement data.

    Args:
        extracted: The full extraction dict returned by extract_enforcement_data().

    Returns:
        A simplified summary dict for display purposes.
    """
    entity = extracted.get("regulated_entity", {})
    action = extracted.get("enforcement_action", {})
    regulator = extracted.get("regulator", {})

    return {
        "Regulator": regulator.get("abbreviation") or regulator.get("name", "N/A"),
        "Jurisdiction": extracted.get("jurisdiction", "N/A"),
        "Regulated Entity": entity.get("name", "N/A"),
        "Entity Type": entity.get("entity_type", "N/A"),
        "Action Type": action.get("action_type", "N/A"),
        "Penalty (GBP)": action.get("penalty_amount_gbp", "N/A"),
        "Notice Date": action.get("notice_date", "N/A"),
        "Reference": action.get("reference_number", "N/A"),
        "Misconduct Themes": len(
            extracted.get("misconduct_control_failure_themes", [])
        ),
        "Root Cause Findings": len(extracted.get("root_cause_evidence", [])),
        "Regulatory Requirements": len(
            extracted.get("regulatory_requirements", [])
        ),
        "Confidence Score": extracted.get("confidence_score", {}).get(
            "score", "N/A"
        ),
    }
