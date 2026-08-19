"""
app/extractor.py
----------------
Step 2: LLM-based structured JSON extraction from regulatory enforcement documents.

Uses Azure OpenAI GPT-4o to extract standardised fields from ANY enforcement document
(FCA, DFS, SEC, MAS, FINRA, PRA, EBA, etc.) across ANY regulatory domain.

Design principle: fully regulator-agnostic and domain-agnostic.
"""

import json
import time
from openai import AzureOpenAI, OpenAI
from config import AzureOpenAIConfig, AppConfig

# ---------------------------------------------------------------------------
# Shared LLM utilities
# ---------------------------------------------------------------------------

def _build_client() -> "OpenAI | AzureOpenAI":
    """Return the correct OpenAI client based on the configured endpoint."""
    _endpoint = AzureOpenAIConfig.ENDPOINT.rstrip("/")
    if "services.ai.azure.com" in _endpoint:
        return OpenAI(
            base_url=f"{_endpoint}/openai/v1/",
            api_key=AzureOpenAIConfig.API_KEY,
        )
    return AzureOpenAI(
        azure_endpoint=AzureOpenAIConfig.ENDPOINT,
        api_key=AzureOpenAIConfig.API_KEY,
        api_version=AzureOpenAIConfig.API_VERSION,
    )


def _strip_json_fences(text: str) -> str:
    """Remove markdown code fences (```json … ```) wrapping a JSON response."""
    text = text.strip()
    if text.startswith("```"):
        # Drop the opening fence line (```json or ```)
        newline = text.find("\n")
        text = text[newline + 1:] if newline != -1 else text[3:]
        # Drop the closing fence
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _call_llm_with_retry(client, max_retries: int = 2, **kwargs) -> tuple[str, dict]:
    """
    Call client.chat.completions.create with exponential-backoff retry.

    Returns:
        (content, usage) where content is the stripped response string and
        usage is a dict with prompt_tokens, completion_tokens, total_tokens.

    Raises RuntimeError if all retries are exhausted or content is empty.
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(**kwargs)
            content = _strip_json_fences(
                response.choices[0].message.content or ""
            )
            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            if content:
                return content, usage
            # Empty content — retry
        except Exception as exc:
            last_exc = exc
        if attempt < max_retries:
            time.sleep(2 ** attempt)  # 1 s, 2 s
    raise RuntimeError(
        f"LLM returned empty/invalid response after {max_retries + 1} attempts."
        + (f" Last error: {last_exc}" if last_exc else "")
    )


def _sum_usage(a: dict, b: dict) -> dict:
    """Merge two token usage dicts by summing each field."""
    return {
        "prompt_tokens": a.get("prompt_tokens", 0) + b.get("prompt_tokens", 0),
        "completion_tokens": a.get("completion_tokens", 0) + b.get("completion_tokens", 0),
        "total_tokens": a.get("total_tokens", 0) + b.get("total_tokens", 0),
    }


# ---------------------------------------------------------------------------
# Extraction system prompt — fully regulator-agnostic
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """You are a specialist regulatory enforcement intelligence analyst.

Your task is to extract structured intelligence from ANY regulatory enforcement document —
including but not limited to:
- FCA (UK Financial Conduct Authority) Final Notices
- DFS (NY Department of Financial Services) Consent Orders
- SEC (US Securities and Exchange Commission) Orders
- MAS (Monetary Authority of Singapore) Notices
- FINRA Disciplinary Actions
- PRA (Prudential Regulation Authority) Notices
- EBA (European Banking Authority) Decisions
- Any other national or international financial regulator

You must extract information across ANY regulatory domain including:
- Market Abuse / Market Surveillance
- AML / Anti-Money Laundering / Sanctions
- Trade Surveillance / Trade Reporting
- Conduct Risk / Consumer Duty
- Operational Risk / Resilience
- Financial Crime / Fraud
- Capital / Prudential Requirements
- Data / Privacy / GDPR
- Any other compliance domain

Return ONLY a valid JSON object. If a field cannot be determined, use null for scalars or [] for arrays.

Required JSON schema:
{
  "regulator": {
    "name": "<full regulator name — auto-detect from document>",
    "abbreviation": "<abbreviation e.g. FCA, DFS, SEC, MAS>",
    "country": "<country of regulator>"
  },
  "jurisdiction": "<country or region e.g. United Kingdom, United States - New York>",
  "regulated_entity": {
    "name": "<full legal name of the penalised firm>",
    "abbreviation": "<abbreviation or null>",
    "entity_type": "<type of firm e.g. investment bank, broker-dealer, retail bank>",
    "business_context": "<brief description of the firm's relevant business activities>"
  },
  "enforcement_action": {
    "action_type": "<type e.g. Final Notice, Consent Order, Administrative Order, Civil Penalty>",
    "penalty_amount": <number or null>,
    "penalty_currency": "<ISO currency code e.g. GBP, USD, SGD or null>",
    "legal_basis": "<statutory or regulatory basis for the action>",
    "settlement_discount": {
      "percentage": <number or null>,
      "stage": "<settlement stage name or null>",
      "pre_discount_penalty": <number or null>
    },
    "notice_date": "<YYYY-MM-DD or null>",
    "reference_number": "<case/reference number or null>",
    "additional_remedial_outcome": "<any additional remedies, undertakings or null>"
  },
  "regulatory_domain": ["<domain 1 e.g. Market Abuse>", "<domain 2>"],
  "scenario_description": "<detailed, factual description of what went wrong and the timeline>",
  "misconduct_control_failure_themes": [
    "<concise theme 1 — e.g. Failure to maintain effective surveillance arrangements>",
    "<concise theme 2>"
  ],
  "root_cause_evidence": [
    {
      "finding": "<root cause finding summary>",
      "evidence": "<specific evidence cited in the document supporting this finding>"
    }
  ],
  "regulatory_requirements": [
    {
      "requirement": "<rule/article/principle reference e.g. UK MAR Article 16(2), 17 CFR 240.10b-5>",
      "obligation": "<what the regulation requires the firm to do>",
      "breach_finding": "<how the firm failed to meet this obligation>"
    }
  ],
  "customer_or_market_impact": {
    "customer_impact": "<description of direct customer harm or null>",
    "market_impact": "<description of market integrity risk or null>",
    "affected_activity": {
      "transaction_count": <number or null>,
      "notional_value": <number or null>,
      "notional_currency": "<ISO currency code or null>"
    },
    "post_remediation_review": {
      "description": "<description of any retrospective review conducted or null>",
      "findings": "<key findings from retrospective review or null>"
    },
    "financial_benefit_from_breach": "<any financial benefit derived by the firm or null>"
  },
  "source_citations": [
    {
      "source_document": "<document title>",
      "document_date": "<YYYY-MM-DD or null>",
      "reference_number": "<reference or null>",
      "key_paragraphs": ["<paragraph reference 1>", "<paragraph reference 2>"]
    }
  ],
  "confidence_score": {
    "score": <float 0.0 to 1.0>,
    "scale": "0 to 1",
    "rationale": "<brief explanation of confidence level>"
  }
}

CRITICAL RULES:
- Return ONLY the raw JSON object. No markdown fences, no explanation text.
- Auto-detect the regulator, jurisdiction and domain — do NOT assume FCA or UK by default.
- All monetary amounts must be numbers, not strings.
- Dates must be YYYY-MM-DD format.
- Be precise and faithful to the source document — do not infer beyond what is stated.
- misconduct_control_failure_themes should be specific and actionable (3-10 themes).
- root_cause_evidence must cite actual evidence from the document.
"""

EXTRACTION_USER_PROMPT_TEMPLATE = """Extract structured enforcement intelligence from the
following regulatory enforcement document:

---BEGIN DOCUMENT---
{document_text}
---END DOCUMENT---

Auto-detect the regulator, jurisdiction, regulatory domain and entity type from the document content.
Return only the JSON object as specified. Do not assume any specific regulator or domain."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_enforcement_data(document_text: str) -> dict:
    """
    Extract structured enforcement intelligence from raw document text.

    Works for any regulator (FCA, DFS, SEC, MAS, FINRA, PRA, EBA, etc.)
    and any regulatory domain (Market Abuse, AML, Trade Surveillance, etc.)

    Args:
        document_text: Plain text extracted from the enforcement document.

    Returns:
        A Python dict matching the enforcement JSON schema.

    Raises:
        ValueError:   If the LLM response cannot be parsed as valid JSON.
        RuntimeError: If the Azure OpenAI API call fails or config is missing.
    """
    missing = AzureOpenAIConfig.validate()
    if missing:
        raise RuntimeError(
            f"Missing Azure OpenAI configuration: {', '.join(missing)}. "
            "Please update your .env file."
        )

    client = _build_client()
    user_prompt = EXTRACTION_USER_PROMPT_TEMPLATE.format(document_text=document_text)

    raw_content, usage = _call_llm_with_retry(
        client,
        model=AzureOpenAIConfig.DEPLOYMENT,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=AppConfig.MAX_TOKENS_EXTRACTION,
    )

    try:
        extracted = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned invalid JSON during extraction: {exc}\n"
            f"Raw response (first 500 chars):\n{raw_content[:500]}"
        ) from exc

    # Attach token usage as metadata (underscore prefix = internal field)
    extracted["_token_usage"] = usage
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
    penalty = action.get("penalty_amount")
    currency = action.get("penalty_currency", "")
    penalty_display = f"{currency} {penalty:,}" if penalty else "N/A"

    return {
        "Regulator": regulator.get("abbreviation") or regulator.get("name", "N/A"),
        "Jurisdiction": extracted.get("jurisdiction", "N/A"),
        "Regulated Entity": entity.get("name", "N/A"),
        "Entity Type": entity.get("entity_type", "N/A"),
        "Action Type": action.get("action_type", "N/A"),
        "Penalty": penalty_display,
        "Notice Date": action.get("notice_date", "N/A"),
        "Reference": action.get("reference_number", "N/A"),
        "Domains": ", ".join(extracted.get("regulatory_domain", [])) or "N/A",
        "Misconduct Themes": len(extracted.get("misconduct_control_failure_themes", [])),
        "Root Cause Findings": len(extracted.get("root_cause_evidence", [])),
        "Regulatory Requirements": len(extracted.get("regulatory_requirements", [])),
        "Confidence Score": extracted.get("confidence_score", {}).get("score", "N/A"),
    }
