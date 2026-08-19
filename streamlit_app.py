"""
streamlit_app.py
----------------
Regulatory Enforcement Intelligence PoC — v2

AI-powered, regulator-agnostic gap analysis pipeline:
  Step 1 — Upload ANY enforcement document (FCA, DFS, SEC, MAS, etc.)
  Step 2 — Extract structured intelligence via Azure OpenAI GPT-4o
  Step 3 — Load GRC inventory (dual-role: Policy Corpus + Control Inventory)
  Step 4 — Run two-layer LLM gap analysis (Policy Layer + Control Layer)
  Step 5 — View shift-left signals, stakeholder alerts, and download report
"""

import time
import pandas as pd
import streamlit as st

from config import AzureOpenAIConfig, AppConfig
from app.parser import parse_document, get_document_preview
from app.extractor import extract_enforcement_data, get_extraction_summary
from app.inventory import (
    load_inventory,
    inventory_to_dataframe,
    get_inventory_summary,
)
from app.comparator import compare_findings_to_inventory, get_overall_assessment
from app.reporter import (
    build_policy_gap_dataframe,
    build_control_gap_dataframe,
    build_stakeholder_signals_dataframe,
    build_unaddressed_findings_dataframe,
    build_summary_dataframe,
    generate_excel_report,
    get_report_filename,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Regulatory Enforcement Intelligence",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
.main-title  { font-size:2rem; font-weight:700; color:#1F4E79; margin-bottom:.2rem; }
.sub-title   { font-size:1rem; color:#555; margin-bottom:1.2rem; }
.step-header { background:#1F4E79; color:white; padding:.4rem .8rem;
               border-radius:6px; font-weight:600; font-size:1rem; margin-bottom:.5rem; }
.shift-left-box { background:#FFF3CD; border-left:5px solid #FFC107;
                  padding:.8rem 1rem; border-radius:4px; margin:.5rem 0; }
.signal-box { background:#F8D7DA; border-left:5px solid #DC3545;
              padding:.8rem 1rem; border-radius:4px; margin:.5rem 0; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## ⚙️ Configuration")
    missing = AzureOpenAIConfig.validate()
    if missing:
        st.error("Missing Azure OpenAI config:\n\n" +
                 "\n".join(f"- `{k}`" for k in missing) +
                 "\n\nUpdate your `.env` file.")
    else:
        st.success("✅ Azure OpenAI connected")
        st.markdown(f"**Deployment:** `{AzureOpenAIConfig.DEPLOYMENT}`")
        st.markdown(f"**API Version:** `{AzureOpenAIConfig.API_VERSION}`")

    st.divider()
    st.markdown("## 📋 Pipeline")
    st.markdown("""
1. 📄 Upload Enforcement Document
2. 🔍 Extract Intelligence (LLM)
3. 📊 Load GRC Inventory
4. 🤖 Run Two-Layer Gap Analysis
5. 📥 View Results & Download
""")
    st.divider()
    st.markdown("**Version:** 2.0 — Universal")
    st.markdown("**LLM:** Azure OpenAI GPT-4o-mini")
    st.markdown("**Approach:** Shift-Left Compliance Intelligence")

# ---------------------------------------------------------------------------
# Title
# ---------------------------------------------------------------------------
st.markdown('<div class="main-title">🏦 Regulatory Enforcement Intelligence</div>',
            unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">AI-powered gap analysis between enforcement actions and your '
    'GRC inventory — works for any regulator (FCA, DFS, SEC, MAS, FINRA...) '
    'and any compliance domain</div>',
    unsafe_allow_html=True)
st.divider()

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
for key in ["document_text", "extracted_data", "inventory", "comparison",
            "uploaded_filename"]:
    if key not in st.session_state:
        st.session_state[key] = None

# ---------------------------------------------------------------------------
# STEP 1 — Upload Document
# ---------------------------------------------------------------------------
st.markdown('<div class="step-header">Step 1 — Upload Enforcement Document (any regulator)</div>',
            unsafe_allow_html=True)

uploaded_file = st.file_uploader(
    "Upload a regulatory enforcement document — FCA Final Notice, DFS Consent Order, "
    "SEC Order, MAS Notice, FINRA Action, etc.",
    type=["docx", "pdf"],
    help="Supported formats: .docx and .pdf",
)

if uploaded_file is not None:
    if uploaded_file.name != st.session_state.uploaded_filename:
        st.session_state.extracted_data = None
        st.session_state.comparison = None
        st.session_state.uploaded_filename = uploaded_file.name

        with st.spinner(f"Parsing **{uploaded_file.name}**..."):
            try:
                file_bytes = uploaded_file.read()
                st.session_state.document_text = parse_document(file_bytes, uploaded_file.name)
                st.success(
                    f"✅ Document parsed — "
                    f"**{len(st.session_state.document_text):,}** characters extracted."
                )
            except ValueError as e:
                st.error(str(e))
                st.session_state.document_text = None

    if st.session_state.document_text:
        with st.expander("📄 Document Preview (first 1,000 characters)", expanded=False):
            st.text(get_document_preview(st.session_state.document_text, max_chars=1000))

st.divider()

# ---------------------------------------------------------------------------
# STEP 2 — Extract Structured Intelligence
# ---------------------------------------------------------------------------
st.markdown('<div class="step-header">Step 2 — Extract Enforcement Intelligence (GPT-4o)</div>',
            unsafe_allow_html=True)

if st.session_state.document_text is None:
    st.info("⬆️ Upload a document in Step 1 to proceed.")
else:
    col1, _ = st.columns([1, 3])
    with col1:
        extract_btn = st.button("🔍 Extract Intelligence", type="primary",
                                use_container_width=True)

    if extract_btn:
        with st.spinner("GPT-4o extracting enforcement intelligence..."):
            try:
                st.session_state.extracted_data = extract_enforcement_data(
                    st.session_state.document_text
                )
                st.session_state.comparison = None
                st.success("✅ Extraction complete.")
            except Exception as e:
                st.error(f"Extraction failed: {e}")
                st.session_state.extracted_data = None

    if st.session_state.extracted_data:
        summary = get_extraction_summary(st.session_state.extracted_data)

        # Auto-detected metadata banner
        ed = st.session_state.extracted_data
        reg = ed.get("regulator", {})
        entity = ed.get("regulated_entity", {})
        action = ed.get("enforcement_action", {})
        domains = ", ".join(ed.get("regulatory_domain", []))
        penalty = action.get("penalty_amount")
        currency = action.get("penalty_currency", "")

        st.markdown("##### 🌍 Auto-Detected Enforcement Intelligence")
        r1c1, r1c2, r1c3, r1c4 = st.columns(4)
        r1c1.metric("Regulator", reg.get("abbreviation") or reg.get("name", "N/A"))
        r1c2.metric("Jurisdiction", ed.get("jurisdiction", "N/A"))
        r1c3.metric("Entity", entity.get("name", "N/A")[:30])
        r1c4.metric("Penalty", f"{currency} {penalty:,}" if penalty else "N/A")

        r2c1, r2c2, r2c3, r2c4 = st.columns(4)
        r2c1.metric("Domain(s)", domains[:40] if domains else "N/A")
        r2c2.metric("Notice Date", action.get("notice_date", "N/A"))
        r2c3.metric("Misconduct Themes", len(ed.get("misconduct_control_failure_themes", [])))
        r2c4.metric("Confidence", summary.get("Confidence Score", "N/A"))

        with st.expander("🔎 Full Extracted JSON", expanded=False):
            st.json(st.session_state.extracted_data)

st.divider()

# ---------------------------------------------------------------------------
# STEP 3 — GRC Inventory (dual-role)
# ---------------------------------------------------------------------------
st.markdown('<div class="step-header">Step 3 — GRC Inventory (Policy Corpus + Control Inventory)</div>',
            unsafe_allow_html=True)

if st.session_state.inventory is None:
    try:
        st.session_state.inventory = load_inventory()
    except Exception as e:
        st.error(f"Failed to load GRC inventory: {e}")

if st.session_state.inventory:
    inv_summary = get_inventory_summary(st.session_state.inventory)
    ca, cb, cc = st.columns(3)
    ca.metric("Total Items", inv_summary["Total Controls"])
    cb.metric("Domain(s)", ", ".join(inv_summary["Regulatory Domains"]))
    cc.metric("Status", " | ".join(f"{k}: {v}" for k, v in
                                   inv_summary["Status Breakdown"].items()))

    st.info(
        "💡 **Dual-role inventory:** Each row serves as both a **Policy** "
        "(intent/objective — primary mapping) and an **Operational Control** "
        "(mechanism — secondary mapping). This enables the shift-left analysis."
    )

    with st.expander("📊 GRC Inventory Preview", expanded=False):
        inv_df = inventory_to_dataframe(st.session_state.inventory)
        st.dataframe(inv_df, width="stretch", hide_index=True)

st.divider()

# ---------------------------------------------------------------------------
# STEP 4 — Two-Layer Gap Analysis
# ---------------------------------------------------------------------------
st.markdown('<div class="step-header">Step 4 — Two-Layer Gap Analysis (Policy + Control)</div>',
            unsafe_allow_html=True)

step4_ready = (
    st.session_state.extracted_data is not None
    and st.session_state.inventory is not None
)

if not step4_ready:
    st.info("⬆️ Complete Steps 1–3 before running the gap analysis.")
else:
    st.markdown("""
    **Layer 1 — Policy Coverage** *(primary, shift-left signal)*
    Assesses whether your firm's **policy intent** would have mandated the right governance.

    **Layer 2 — Control Coverage** *(secondary, operational signal)*
    Assesses whether an **operational control** would have detected or prevented the failure.
    """)

    col1, _ = st.columns([1, 3])
    with col1:
        analyse_btn = st.button("🤖 Run Gap Analysis", type="primary",
                                use_container_width=True)

    if analyse_btn:
        with st.spinner(
            "GPT-4o running two-layer gap analysis (Policy + Control)... "
            "This may take 30–60 seconds."
        ):
            try:
                t0 = time.time()
                st.session_state.comparison = compare_findings_to_inventory(
                    st.session_state.extracted_data,
                    st.session_state.inventory,
                )
                st.success(f"✅ Gap analysis complete in {time.time() - t0:.1f}s.")
            except Exception as e:
                st.error(f"Gap analysis failed: {e}")
                st.session_state.comparison = None

st.divider()

# ---------------------------------------------------------------------------
# STEP 5 — Results & Download
# ---------------------------------------------------------------------------
st.markdown('<div class="step-header">Step 5 — Results, Signals & Report</div>',
            unsafe_allow_html=True)

if st.session_state.comparison is None:
    st.info("⬆️ Run the gap analysis in Step 4 to see results here.")
else:
    comparison = st.session_state.comparison
    assessment = get_overall_assessment(comparison)

    # ── Shift-Left Headline ──────────────────────────────────────────────────
    headline = assessment.get("shift_left_headline", "")
    if headline:
        st.markdown(
            f'<div class="shift-left-box">⚡ <strong>Shift-Left Signal:</strong> {headline}</div>',
            unsafe_allow_html=True,
        )

    # ── Overall Metrics ──────────────────────────────────────────────────────
    st.markdown("### 📊 Overall Assessment")

    risk = assessment.get("overall_risk_rating", "N/A")
    risk_icon = {"Low": "🟢", "Medium": "🟡", "High": "🟠", "Critical": "🔴"}.get(risk, "⚪")

    pl_s = assessment.get("policy_layer_summary", {})
    cl_s = assessment.get("control_layer_summary", {})

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Assessed", assessment.get("total_assessed", 0))
    c2.metric("Policy Gaps 🔴", pl_s.get("potential_gap", 0))
    c3.metric("Control Gaps 🔴", cl_s.get("potential_gap", 0))
    c4.metric("Partially Covered 🟡",
              pl_s.get("partially_covered", 0) + cl_s.get("partially_covered", 0))
    c5.metric(f"{risk_icon} Risk Rating", risk)

    exec_summary = assessment.get("executive_summary", "")
    if exec_summary:
        st.info(f"**Executive Summary:** {exec_summary}")

    # ── Two-Layer Results Tabs ───────────────────────────────────────────────
    tab_policy, tab_control, tab_signals, tab_unaddressed = st.tabs([
        "📜 Policy Layer (Primary)",
        "🔧 Control Layer (Secondary)",
        "🔔 Stakeholder Signals",
        "⚠️ Unaddressed Findings",
    ])

    # --- Policy Layer Tab ---
    with tab_policy:
        st.markdown("#### � Policy Coverage — Shift-Left Analysis")
        st.caption(
            "Assesses whether existing **policy intent** (objectives/statements) "
            "would have mandated the governance that was absent in the enforcement case."
        )

        policy_df = build_policy_gap_dataframe(comparison)

        policy_labels = ["Covered", "Partially Covered", "Potential Gap", "Insufficient Evidence"]
        sel_policy = st.multiselect(
            "Filter by Policy Coverage:",
            options=policy_labels,
            default=policy_labels,
            key="filter_policy",
        )
        filtered_policy = policy_df[policy_df["Policy Coverage"].isin(sel_policy)]

        def _style_policy(val):
            m = {
                "Covered": "background-color:#d4edda;color:#276221;font-weight:bold",
                "Partially Covered": "background-color:#fff3cd;color:#9C5700;font-weight:bold",
                "Potential Gap": "background-color:#f8d7da;color:#9C0006;font-weight:bold",
                "Insufficient Evidence": "background-color:#e2e3e5;color:#595959;font-weight:bold",
            }
            return m.get(val, "")

        st.dataframe(
            filtered_policy.style.map(_style_policy, subset=["Policy Coverage"]),
            width="stretch", hide_index=True, height=400,
        )

        # Shift-left signal callouts
        gap_items = filtered_policy[filtered_policy["Policy Coverage"] == "Potential Gap"]
        if not gap_items.empty:
            st.markdown("##### ⚡ Shift-Left Signals for Policy Gaps")
            for _, row in gap_items.iterrows():
                sig = row.get("Shift Left Signal", "")
                if sig:
                    st.markdown(
                        f'<div class="shift-left-box"><strong>{row["ID"]} — {row["Name"]}</strong>'
                        f'<br>{sig}</div>',
                        unsafe_allow_html=True,
                    )

    # --- Control Layer Tab ---
    with tab_control:
        st.markdown("#### Control Coverage — Operational Analysis")
        st.caption(
            "Assesses whether an **operational control** (mechanism/procedure) "
            "would have detected or prevented the enforcement failure."
        )

        control_df = build_control_gap_dataframe(comparison)

        control_labels = ["Covered", "Partially Covered", "Policy-Only Coverage",
                          "Potential Gap", "Insufficient Evidence"]
        sel_control = st.multiselect(
            "Filter by Control Coverage:",
            options=control_labels,
            default=control_labels,
            key="filter_control",
        )
        filtered_control = control_df[control_df["Control Coverage"].isin(sel_control)]

        def _style_control(val):
            m = {
                "Covered": "background-color:#d4edda;color:#276221;font-weight:bold",
                "Partially Covered": "background-color:#fff3cd;color:#9C5700;font-weight:bold",
                "Policy-Only Coverage": "background-color:#cce5ff;color:#1F4E79;font-weight:bold",
                "Potential Gap": "background-color:#f8d7da;color:#9C0006;font-weight:bold",
                "Insufficient Evidence": "background-color:#e2e3e5;color:#595959;font-weight:bold",
            }
            return m.get(val, "")

        st.dataframe(
            filtered_control.style.map(_style_control, subset=["Control Coverage"]),
            width="stretch", hide_index=True, height=400,
        )

    # --- Stakeholder Signals Tab ---
    with tab_signals:
        st.markdown("#### Stakeholder Action Signals")
        st.caption(
            "Who needs to act, what action is required, and with what priority."
        )

        signals_df = build_stakeholder_signals_dataframe(comparison)
        if signals_df.empty:
            st.success("No stakeholder signals — all items are fully covered.")
        else:
            # Priority filter
            priorities = ["High", "Medium", "Low"]
            sel_pri = st.multiselect(
                "Filter by Priority:", options=priorities, default=priorities,
                key="filter_priority",
            )
            filtered_signals = signals_df[signals_df["Priority"].isin(sel_pri)]

            def _style_priority(val):
                m = {
                    "High":   "background-color:#f8d7da;color:#9C0006;font-weight:bold",
                    "Medium": "background-color:#fff3cd;color:#9C5700;font-weight:bold",
                    "Low":    "background-color:#d4edda;color:#276221;font-weight:bold",
                }
                return m.get(val, "")

            st.dataframe(
                filtered_signals.style.map(_style_priority, subset=["Priority"]),
                width="stretch", hide_index=True, height=400,
            )

            # High priority signal callouts
            high_signals = filtered_signals[filtered_signals["Priority"] == "High"]
            if not high_signals.empty:
                st.markdown("##### 🔴 High Priority Actions")
                for _, row in high_signals.iterrows():
                    st.markdown(
                        f'<div class="signal-box"><strong>{row["Stakeholder"]}</strong> '
                        f'— {row["ID"]} {row["Name"]}<br>{row["Signal"]}</div>',
                        unsafe_allow_html=True,
                    )

    # --- Unaddressed Findings Tab ---
    with tab_unaddressed:
        st.markdown("#### Unaddressed Enforcement Findings")
        st.caption(
            "Enforcement themes or root causes with **no matching policy or control** "
            "in the current inventory. New policies and/or controls may be required."
        )

        unaddressed_df = build_unaddressed_findings_dataframe(comparison)
        if unaddressed_df.empty:
            st.success(
                "All enforcement themes are addressed by at least one "
                "policy or control in the inventory."
            )
        else:
            st.warning(
                f"**{len(unaddressed_df)} enforcement theme(s)** have no matching "
                "policy or control. Review the suggested policies and controls below."
            )
            st.dataframe(unaddressed_df, width="stretch", hide_index=True)

    # ── Download Report ──────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 📥 Download Full Report")

    try:
        excel_bytes = generate_excel_report(
            comparison=comparison,
            extracted_enforcement=st.session_state.extracted_data,
            inventory=st.session_state.inventory,
        )
        filename = get_report_filename(st.session_state.extracted_data)
        st.download_button(
            label="📥 Download Excel Report (.xlsx)",
            data=excel_bytes,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            width="content",
        )
        st.caption(
            "Report contains 7 sheets: Summary, Policy Gap Analysis, Control Gap Analysis, "
            "Stakeholder Signals, Unaddressed Findings, Enforcement Data, GRC Inventory."
        )
    except Exception as e:
        st.error(f"Failed to generate Excel report: {e}")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.markdown(
    "<div style='text-align:center;color:#aaa;font-size:.8rem;'>"
    "Regulatory Enforcement Intelligence PoC v2 · Azure OpenAI GPT-4o · "
    "Universal — FCA | DFS | SEC | MAS | FINRA · For internal use only · Not legal advice"
    "</div>",
    unsafe_allow_html=True,
)
