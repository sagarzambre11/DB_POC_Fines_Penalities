"""
frontend/pipeline.py
--------------------
Pipeline runner and all chat response builders.

run_pipeline(progress_placeholder)
    Calls the agentic orchestrator, stores results in session state,
    and pre-builds the Excel report.

Response builders (return markdown strings for chat display):
    build_summary_response()      → enforcement case summary
    build_gap_response()          → gap analysis results + agent intel
    build_retrieve_response()     → semantically retrieved controls
    build_inventory_response()    → GRC inventory summary
    build_stakeholder_response()  → high-priority stakeholder signals
    build_unaddressed_response()  → unaddressed enforcement findings
"""
import streamlit as st

from app.agents.langgraph_pipeline import run_langgraph_pipeline
from app.comparator import get_overall_assessment
from app.inventory import get_inventory_summary
from app.reporter import (
    build_controls_gap_dataframe,
    build_stakeholder_signals_dataframe,
    build_unaddressed_findings_dataframe,
    generate_excel_report,
    get_report_filename,
)
from frontend.helpers import log, log_kind_from_msg, push_message


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run_pipeline(progress_ph) -> None:
    """
    Execute the full three-agent agentic RAG pipeline.

    Updates session state with:
      comparison, extracted_data, a1/a2/a3 status,
      xl_bytes (pre-built Excel report), xl_name.

    Args:
        progress_ph: A Streamlit placeholder used to display live status messages.

    Raises:
        Re-raises any exception from the orchestrator after setting error status.
    """
    def _cb(msg: str) -> None:
        log(msg, log_kind_from_msg(msg))
        progress_ph.info(msg)

    try:
        st.session_state.a1 = "running"
        st.session_state.a2 = "running"
        st.session_state.a3 = "running"

        result = run_langgraph_pipeline(
            document_text=st.session_state.document_text,
            inventory=st.session_state.inventory,
            rag_collection=st.session_state.rag_collection,
            progress_callback=_cb,
        )

        # Ensure extracted_data is populated for display (orchestrator runs it internally)
        if st.session_state.extracted_data is None:
            from app.extractor import extract_enforcement_data
            try:
                st.session_state.extracted_data = extract_enforcement_data(
                    st.session_state.document_text
                )
            except Exception:
                pass

        st.session_state.comparison = result
        st.session_state.a1 = "done"
        st.session_state.a2 = "done"
        st.session_state.a3 = "done"

        # Pre-build Excel report
        try:
            xl = generate_excel_report(
                comparison=result,
                extracted_enforcement=st.session_state.extracted_data,
                inventory=st.session_state.inventory,
            )
            st.session_state.xl_bytes = xl
            st.session_state.xl_name  = get_report_filename(st.session_state.extracted_data)
        except Exception:
            pass

        log("All agents complete.", "s")

    except Exception as exc:
        st.session_state.a1 = "error"
        st.session_state.a2 = "error"
        st.session_state.a3 = "error"
        log(f"Pipeline error: {exc}", "s")
        raise


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------

def build_summary_response() -> str:
    """
    Build a markdown string summarising the extracted enforcement case data.
    Uses Agent 1 (Extraction Agent) output stored in session state.
    """
    ed = st.session_state.extracted_data
    if not ed:
        return "No enforcement data extracted yet — upload a PDF and run the analysis first."

    reg    = ed.get("regulator", {})
    entity = ed.get("regulated_entity", {})
    action = ed.get("enforcement_action", {})
    themes = ed.get("misconduct_control_failure_themes", [])
    rcs    = ed.get("root_cause_evidence", [])
    domain = ", ".join(ed.get("regulatory_domain", []))
    pen    = action.get("penalty_amount")
    cur    = action.get("penalty_currency", "")
    conf   = ed.get("confidence_score", {}).get("score", "N/A")

    lines = [
        "### 📋 Enforcement Case Summary", "",
        "| Field | Value |", "|---|---|",
        f"| **Regulator** | {reg.get('name', 'N/A')} ({reg.get('abbreviation', '')}) |",
        f"| **Jurisdiction** | {ed.get('jurisdiction', 'N/A')} |",
        f"| **Entity** | {entity.get('name', 'N/A')} — {entity.get('entity_type', '')} |",
        f"| **Action Type** | {action.get('action_type', 'N/A')} |",
        (f"| **Penalty** | {cur} {pen:,} |" if pen else "| **Penalty** | N/A |"),
        f"| **Notice Date** | {action.get('notice_date', 'N/A')} |",
        f"| **Domain(s)** | {domain} |",
        f"| **Confidence Score** | {conf} |", "",
        "**Scenario Description:**",
        ed.get("scenario_description", "N/A"), "",
    ]

    if themes:
        lines.append(f"**Misconduct / Control Failure Themes ({len(themes)}):**")
        lines += [f"{i}. {t}" for i, t in enumerate(themes, 1)]
        lines.append("")

    if rcs:
        lines.append(f"**Root Cause Findings ({len(rcs)}):**")
        for rc in rcs[:6]:
            lines.append(f"- **{rc.get('finding', '')}**")
            if rc.get("evidence"):
                lines.append(f"  *Evidence:* {rc['evidence']}")
        lines.append("")

    reqs = ed.get("regulatory_requirements", [])
    if reqs:
        lines.append(f"**Regulatory Requirements Breached ({len(reqs)}):**")
        for req in reqs[:4]:
            lines.append(f"- {req.get('requirement', '')} — {req.get('breach_finding', '')}")
        lines.append("")

    return "\n".join(lines)


def build_gap_response() -> str:
    """
    Build a markdown summary of the gap analysis results.
    Uses Agent 3 (Gap Analysis Agent) output stored in session state.
    """
    cmp = st.session_state.comparison
    if not cmp:
        return "Gap analysis has not been run yet — upload both files and ask me to run the analysis."

    assessment = get_overall_assessment(cmp)
    cl   = assessment.get("controls_layer_summary", {})
    rag  = cmp.get("_rag_metadata", {})
    am   = cmp.get("_agent_metadata", {})
    risk = assessment.get("overall_risk_rating", "N/A")
    ri   = {"Low": "🟢", "Medium": "🟡", "High": "🟠", "Critical": "🔴"}.get(risk, "⚪")
    gap_a = am.get("gap_analysis_agent", {})
    ret_a = am.get("retrieval_agent", {})
    ext_a = am.get("extraction_agent", {})

    lines = [
        "### 📊 Agentic Gap Analysis Results", "",
        f"**Overall Risk Rating:** {ri} **{risk}**",
        f"**RAG Mode:** {rag.get('mode', 'N/A').replace('_', ' ').title()}",
        f"**Controls Assessed:** {rag.get('controls_assessed', '?')} of "
        f"{rag.get('total_inventory', '?')} ({rag.get('reduction_pct', 0):.0f}% token reduction)",
        "",
        "| Classification | Count |", "|---|---|",
        f"| ✅ Covered | {cl.get('covered', 0)} |",
        f"| 🟡 Partially Covered | {cl.get('partially_covered', 0)} |",
        f"| 🔴 Potential Gap | {cl.get('potential_gap', 0)} |",
        f"| ❓ Insufficient Evidence | {cl.get('insufficient_evidence', 0)} |",
        "",
    ]

    if assessment.get("executive_summary"):
        lines += ["**Executive Summary:**", assessment["executive_summary"], ""]

    if assessment.get("shift_left_headline"):
        lines += [f"⚡ **Shift-Left Signal:** {assessment['shift_left_headline']}", ""]

    # Agent intelligence trace
    agent_lines = ["**Agent Pipeline Intelligence:**"]
    if ext_a:
        agent_lines.append(
            f"- 📄 **Intelligence Extractor**: {ext_a.get('final_theme_count', '?')} themes extracted, "
            f"confidence {ext_a.get('final_confidence', 0):.2f}, "
            f"{ext_a.get('iterations', 1)} iteration(s)"
        )
    if ret_a:
        qe = ret_a.get("query_expansion", {})
        qg = ret_a.get("quality_gate", {})
        agent_lines.append(
            f"- 🔍 **Semantic Retrieval Agent**: {qe.get('hyde_queries_generated', 0)} HyDE queries, "
            f"{qe.get('total_queries_run', 0)} total queries, "
            f"{qg.get('controls_filtered_out', 0)} filtered out, "
            f"{ret_a.get('final_controls_count', '?')} controls selected"
        )
    if gap_a:
        agent_lines.append(
            f"- 📊 **Compliance Gap Analyser**: {gap_a.get('quick_screen_count', 0)} quick-screened, "
            f"{gap_a.get('deep_dives_performed', 0)} deep dives, "
            f"{gap_a.get('contradictions_detected_and_resolved', 0)} contradictions resolved"
        )
    lines += agent_lines + [""]
    lines.append("*See the Results tabs above for detailed tables. "
                 "Ask about 'stakeholder signals' or 'unaddressed findings' for more.*")

    return "\n".join(lines)


def build_retrieve_response() -> str:
    """
    Retrieve and display the most semantically relevant controls for the enforcement case.
    Uses Agent 2 (Retrieval Agent) — calls the retriever directly.
    """
    inv = st.session_state.inventory
    if not inv:
        return "No GRC inventory loaded — please upload an Excel file in the sidebar."
    if not st.session_state.extracted_data:
        return "Please run the full analysis first so I can find controls relevant to the enforcement case."

    try:
        from app.retriever import retrieve_relevant_controls_with_scores
        from app.vector_store import get_or_build_control_index

        themes = st.session_state.extracted_data.get("misconduct_control_failure_themes", [])
        rcs    = st.session_state.extracted_data.get("root_cause_evidence", [])
        coll   = st.session_state.rag_collection

        if coll is None:
            coll = get_or_build_control_index(inv)
            st.session_state.rag_collection = coll

        hits = retrieve_relevant_controls_with_scores(themes, rcs, inv, collection=coll)
        if not hits:
            return "No relevant controls found in the inventory for this enforcement case."

        lines = [f"### 🔍 Most Relevant Controls ({len(hits)} retrieved)", ""]
        for ctrl, dist in hits[:10]:
            lines += [
                f"**{ctrl['control_id']} — {ctrl['control_name']}**  "
                f"*(similarity score: {dist:.4f})*",
                f"> **Objective:** {ctrl.get('control_objective', '')[:250]}",
                f"> **Mechanism:** {ctrl.get('control_description', '')[:200]}",
                f"> Domain: `{ctrl.get('regulatory_domain', '')}` | "
                f"Owner: `{ctrl.get('owner', '')}` | "
                f"Type: `{ctrl.get('control_type', '')}`",
                "",
            ]
        return "\n".join(lines)

    except Exception as exc:
        return f"Retrieval error: {exc}"


def build_inventory_response() -> str:
    """Build a markdown summary of the loaded GRC inventory."""
    inv = st.session_state.inventory
    if not inv:
        return "No GRC inventory loaded — upload an Excel file in the sidebar."

    s = get_inventory_summary(inv)
    lines = [
        "### 📊 GRC Inventory Summary", "",
        f"| Field | Value |", "|---|---|",
        f"| **Total Controls** | {s['Total Controls']} |",
        f"| **Regulatory Domain(s)** | {', '.join(s['Regulatory Domains'])} |",
        f"| **Status Breakdown** | {', '.join(f'{k}: {v}' for k, v in s['Status Breakdown'].items())} |",
        "", "**Control IDs:**",
        ", ".join(f"`{cid}`" for cid in s["Control IDs"]),
    ]
    return "\n".join(lines)


def build_stakeholder_response() -> str:
    """Build a markdown summary of high-priority stakeholder action signals."""
    cmp = st.session_state.comparison
    if not cmp:
        return "No analysis results yet — run the gap analysis first."

    df = build_stakeholder_signals_dataframe(cmp)
    if df.empty:
        return "No stakeholder signals generated — all controls appear to be covered."

    high   = df[df["Priority"] == "High"]
    medium = df[df["Priority"] == "Medium"]
    low    = df[df["Priority"] == "Low"]

    lines = [f"### 🔔 Stakeholder Action Signals ({len(df)} total)", ""]

    if not high.empty:
        lines.append(f"#### 🔴 High Priority ({len(high)} actions)")
        for _, r in high.iterrows():
            lines += [
                f"**{r['Stakeholder']}** — `{r['ID']}` {r['Name']}",
                f"> {r['Signal']}  *(Severity: {r.get('Gap Severity', 'N/A')})*",
                "",
            ]

    if not medium.empty:
        lines.append(f"#### 🟡 Medium Priority ({len(medium)} actions)")
        for _, r in medium.iterrows():
            lines.append(f"- **{r['Stakeholder']}** — `{r['ID']}` {r['Name']}: {r['Signal']}")
        lines.append("")

    if not low.empty:
        lines.append(f"*{len(low)} Low priority signal(s) also present — see the Stakeholder Signals tab.*")

    lines.append("*See the Stakeholder Signals tab in the Results section for the full table.*")
    return "\n".join(lines)


def build_unaddressed_response() -> str:
    """Build a markdown list of enforcement themes with no matching control."""
    cmp = st.session_state.comparison
    if not cmp:
        return "No analysis results yet — run the gap analysis first."

    df = build_unaddressed_findings_dataframe(cmp)
    if df.empty:
        return "All enforcement themes are addressed by at least one control in your inventory."

    lines = [f"### ⚠️ Unaddressed Enforcement Findings ({len(df)} themes)", "",
             "These enforcement themes have **no matching control** in your GRC inventory:", ""]
    for _, r in df.iterrows():
        lines += [
            f"**{r['Enforcement Theme']}**",
            f"- *Risk Implication:* {r['Risk Implication']}",
            f"- *Suggested Control:* {r['Suggested Control']}",
            f"- *Suggested Owner:* {r['Suggested Owner']}",
            "",
        ]
    lines.append("*New controls should be created to address these gaps.*")
    return "\n".join(lines)


def handle_chat_message(user_text: str) -> str:
    """
    Route a user chat message to the appropriate response builder.

    Returns one of:
      - A markdown string to display directly in chat
      - "__RUN_PIPELINE__"  — trigger the agentic pipeline
      - "__DOWNLOAD__"      — show a download button
    """
    from frontend.helpers import classify_intent

    intent   = classify_intent(user_text)
    files_ok = (st.session_state.document_text is not None
                and st.session_state.inventory is not None)
    done     = st.session_state.comparison is not None

    if intent == "download":
        return "__DOWNLOAD__" if done else "Please run the gap analysis first."

    if intent == "inventory":
        return build_inventory_response()

    if intent == "summarise":
        if st.session_state.extracted_data:
            return build_summary_response()
        if not files_ok:
            return "Please upload both a PDF and an Excel file first."
        return "Files are loaded. Ask me to **run the analysis** and I will extract and summarise the enforcement case."

    if intent == "retrieve":
        return build_retrieve_response()

    if "stakeholder" in user_text.lower():
        return build_stakeholder_response()

    if "unaddressed" in user_text.lower():
        return build_unaddressed_response()

    if intent == "gap":
        if done:
            return build_gap_response()
        if not files_ok:
            return "Please upload both a PDF enforcement document and Excel GRC inventory."
        return "__RUN_PIPELINE__"

    if any(w in user_text.lower() for w in ["run", "start", "begin", "analyse", "analyze", "go", "execute"]):
        if not files_ok:
            return "Please upload both files first (PDF + Excel GRC inventory)."
        return "__RUN_PIPELINE__"

    if not files_ok:
        return ("I'm ready to help!\n\n"
                "**To get started:**\n"
                "1. 📄 Upload a **PDF** enforcement document (sidebar)\n"
                "2. 📊 Upload your **Excel** GRC inventory (sidebar)\n"
                "3. Ask me to **run the analysis** or ask any question about the case.")

    if done:
        return (build_gap_response()
                + "\n\n---\n*You can also ask about: enforcement summary, "
                "relevant controls, stakeholder signals, unaddressed findings, download report.*")

    return ("Both files are loaded! Ask me to **run the gap analysis**, or try:\n"
            "- *'What happened in this enforcement case?'*\n"
            "- *'Which controls are relevant?'*\n"
            "- *'Run the analysis'*")
