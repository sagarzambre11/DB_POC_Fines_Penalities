"""
app/agents/supervisor.py
------------------------
Supervisor Agent — conversational follow-up Q&A for the enforcement intelligence system.

The Supervisor Agent receives a user question along with the current enforcement
context (extracted data + gap analysis results) and uses the LLM to generate a
direct, contextual answer. It acts as the catch-all handler for any question that
the intent classifier cannot route to a specialised agent.

Responsibilities:
  - Answer follow-up questions about the enforcement case
  - Answer questions about specific controls, gaps, or findings
  - Clarify analysis results in plain language
  - Handle general compliance/regulatory questions in context

Public API:
  answer_followup_question(user_question, extracted_data, comparison) → str
"""

from __future__ import annotations

import json
import logging

from config import AzureOpenAIConfig, AppConfig
from app.extractor import _build_client, _call_llm_with_retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supervisor system prompt
# ---------------------------------------------------------------------------

_SUPERVISOR_SYSTEM = """You are a senior Regulatory Enforcement Intelligence assistant.

You have access to structured intelligence extracted from a regulatory enforcement
document and a completed gap analysis comparing the enforcement findings against a
GRC (Governance, Risk & Compliance) controls inventory.

Your role is to answer the user's follow-up question in a clear, concise, and
accurate way based on the enforcement context provided. 

Guidelines:
- Answer directly and specifically — do not repeat the entire analysis
- Reference specific controls, findings, themes, or gaps when relevant
- Use plain, professional language appropriate for compliance professionals
- If the question is about something not in the context, say so clearly
- Keep answers focused — 2-6 sentences for simple questions, up to 10 for complex ones
- Use bullet points or numbered lists when listing multiple items
- Do NOT fabricate information not in the provided context
"""

_SUPERVISOR_USER_TEMPLATE = """
=== ENFORCEMENT CONTEXT ===
{enforcement_summary}

=== GAP ANALYSIS CONTEXT ===
{gap_summary}

=== USER QUESTION ===
{user_question}

Answer the user's question based on the enforcement context above.
Be specific, concise, and accurate. Do not repeat the full analysis."""


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

def _build_enforcement_summary(extracted_data: dict) -> str:
    """Build a concise text summary of the extracted enforcement data."""
    if not extracted_data:
        return "No enforcement data available."

    reg    = extracted_data.get("regulator", {})
    entity = extracted_data.get("regulated_entity", {})
    action = extracted_data.get("enforcement_action", {})
    themes = extracted_data.get("misconduct_control_failure_themes", [])
    rcs    = extracted_data.get("root_cause_evidence", [])
    reqs   = extracted_data.get("regulatory_requirements", [])
    domain = ", ".join(extracted_data.get("regulatory_domain", []))
    pen    = action.get("penalty_amount")
    cur    = action.get("penalty_currency", "")

    lines = [
        f"Regulator: {reg.get('name', 'N/A')} ({reg.get('abbreviation', '')})",
        f"Jurisdiction: {extracted_data.get('jurisdiction', 'N/A')}",
        f"Entity: {entity.get('name', 'N/A')} ({entity.get('entity_type', '')})",
        f"Action: {action.get('action_type', 'N/A')}",
        f"Penalty: {cur} {pen:,}" if pen else "Penalty: N/A",
        f"Notice Date: {action.get('notice_date', 'N/A')}",
        f"Regulatory Domain(s): {domain}",
        f"Scenario: {extracted_data.get('scenario_description', 'N/A')[:500]}",
        "",
        f"Misconduct Themes ({len(themes)}):",
    ]
    for i, t in enumerate(themes, 1):
        lines.append(f"  {i}. {t}")

    if rcs:
        lines.append(f"\nRoot Causes ({len(rcs)}):")
        for rc in rcs[:5]:
            lines.append(f"  - {rc.get('finding', '')}")
            if rc.get("evidence"):
                lines.append(f"    Evidence: {rc['evidence'][:200]}")

    if reqs:
        lines.append(f"\nRegulatory Requirements Breached ({len(reqs)}):")
        for req in reqs[:4]:
            lines.append(f"  - {req.get('requirement', '')}: {req.get('breach_finding', '')[:150]}")

    return "\n".join(lines)


def _build_gap_summary(comparison: dict) -> str:
    """Build a concise text summary of the gap analysis results."""
    if not comparison:
        return "No gap analysis results available."

    from app.comparator import get_overall_assessment
    assessment = get_overall_assessment(comparison)
    cl  = assessment.get("controls_layer_summary", {})
    rag = comparison.get("_rag_metadata", {})

    lines = [
        f"Overall Risk Rating: {assessment.get('overall_risk_rating', 'N/A')}",
        f"Controls Assessed: {rag.get('controls_assessed', '?')} of {rag.get('total_inventory', '?')}",
        f"Covered: {cl.get('covered', 0)} | Partially Covered: {cl.get('partially_covered', 0)} | "
        f"Potential Gap: {cl.get('potential_gap', 0)} | Insufficient Evidence: {cl.get('insufficient_evidence', 0)}",
        f"Executive Summary: {assessment.get('executive_summary', 'N/A')}",
        f"Shift-Left Signal: {assessment.get('shift_left_headline', 'N/A')}",
        "",
    ]

    # List all gap analysis items
    gap_items = comparison.get("gap_analysis", [])
    if gap_items:
        lines.append(f"Per-Control Results ({len(gap_items)} controls):")
        for item in gap_items:
            cl_layer = item.get("controls_layer", {})
            coverage = cl_layer.get("coverage_classification", "N/A")
            lines.append(
                f"  [{coverage}] {item.get('id', '')} — {item.get('name', '')} "
                f"(Severity: {item.get('overall_gap_severity', 'N/A')})"
            )
            rationale = cl_layer.get("rationale", "")
            if rationale:
                lines.append(f"    Rationale: {rationale[:200]}")

    # Unaddressed findings
    unaddressed = comparison.get("unaddressed_findings", [])
    if unaddressed:
        lines.append(f"\nUnaddressed Findings ({len(unaddressed)}):")
        for item in unaddressed:
            lines.append(f"  - Theme: {item.get('theme', '')}")
            lines.append(f"    Risk: {item.get('risk_implication', '')[:150]}")
            lines.append(f"    Suggested Control: {item.get('suggested_control', '')[:150]}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def answer_followup_question(
    user_question: str,
    extracted_data: dict | None = None,
    comparison: dict | None = None,
) -> str:
    """
    Answer a follow-up question about the enforcement case using the LLM.

    The Supervisor Agent has full context about the enforcement case and gap
    analysis results. It generates a direct, contextual answer to any question
    not handled by the specialised agents (Intelligence Extractor, Semantic
    Retrieval Agent, Compliance Gap Analyser).

    Args:
        user_question:  The user's follow-up question.
        extracted_data: Enforcement extraction result (from Intelligence Extractor).
        comparison:     Gap analysis result (from Compliance Gap Analyser).

    Returns:
        A markdown string with the LLM's answer to the question.

    Returns a fallback message if Azure OpenAI is not configured or if the
    LLM call fails.
    """
    missing = AzureOpenAIConfig.validate()
    if missing:
        return (
            "I cannot answer follow-up questions right now — "
            "Azure OpenAI configuration is missing. Please check your `.env` file."
        )

    enforcement_summary = _build_enforcement_summary(extracted_data)
    gap_summary         = _build_gap_summary(comparison)

    user_prompt = _SUPERVISOR_USER_TEMPLATE.format(
        enforcement_summary=enforcement_summary,
        gap_summary=gap_summary,
        user_question=user_question,
    )

    try:
        client = _build_client()
        raw, _usage = _call_llm_with_retry(
            client,
            model=AzureOpenAIConfig.DEPLOYMENT,
            messages=[
                {"role": "system", "content": _SUPERVISOR_SYSTEM},
                {"role": "user",   "content": user_prompt},
            ],
            max_completion_tokens=min(AppConfig.MAX_TOKENS_SUMMARY, 4096),
        )
        return raw.strip() if raw else "I'm unable to provide an answer at this time."

    except Exception as exc:
        logger.warning("Supervisor Agent LLM call failed: %s", exc)
        return (
            f"I encountered an error answering your question: {exc}\n\n"
            "Please try rephrasing or ask about a specific aspect of the analysis."
        )
