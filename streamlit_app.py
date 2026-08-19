"""
streamlit_app.py
----------------
Main Streamlit UI for the Regulatory Enforcement Intelligence PoC.

5-Step Pipeline:
  Step 1 — Upload regulatory enforcement document (DOCX/PDF)
  Step 2 — Extract structured JSON using Azure OpenAI GPT-4o
  Step 3 — Load and preview GRC Control Inventory
  Step 4 — Run LLM-based gap analysis comparison
  Step 5 — Display results and download Excel report
"""

import json
import time

import pandas as pd
import streamlit as st

from config import AzureOpenAIConfig, AppConfig
from app.parser import parse_document, get_document_preview
from app.extractor import extract_enforcement_data, get_extraction_summary
from app.inventory import load_inventory, inventory_to_dataframe, get_inventory_summary
from app.comparator import compare_findings_to_inventory
from app.reporter import (
    build_gap_analysis_dataframe,
    build_unmatched_findings_dataframe,
    build_summary_dataframe,
    generate_excel_report,
    get_report_filename,
)

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Regulatory Enforcement Intelligence PoC",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    .main-title {
        font-size: 2rem;
        font-weight: 700;
        color: #1F4E79;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1rem;
        color: #666;
        margin-bottom: 1.5rem;
    }
    .step-header {
        background: #1F4E79;
        color: white;
        padding: 0.4rem 0.8rem;
        border-radius: 6px;
        font-weight: 600;
        font-size: 1rem;
        margin-bottom: 0.5rem;
    }
    .metric-card {
        background: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
    }
    .covered       { background-color: #d4edda; color: #276221; font-weight: bold; }
    .partial       { background-color: #fff3cd; color: #9C5700; font-weight: bold; }
    .policy-only   { background-color: #cce5ff; color: #1F4E79; font-weight: bold; }
    .gap           { background-color: #f8d7da; color: #9C0006; font-weight: bold; }
    .insufficient  { background-color: #e2e3e5; color: #595959; font-weight: bold; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar — configuration status
# ---------------------------------------------------------------------------

with st.sidebar:
    st.image(
        "https://upload.wikimedia.org/wikipedia/commons/4/44/Microsoft_logo.svg",
        width=120,
    )
    st.markdown("## ⚙️ Configuration")

    missing_keys = AzureOpenAIConfig.validate()
    if missing_keys:
        st.error(
            f"Missing Azure OpenAI config:\n\n"
            + "\n".join(f"- `{k}`" for k in missing_keys)
            + "\n\nPlease update your `.env` file."
        )
    else:
        st.success("✅ Azure OpenAI connected")
        st.markdown(f"**Deployment:** `{AzureOpenAIConfig.DEPLOYMENT}`")
        st.markdown(f"**API Version:** `{AzureOpenAIConfig.API_VERSION}`")

    st.divider()
    st.markdown("## 📋 Pipeline Steps")
    st.markdown(
        """
        1. 📄 Upload Document
        2. 🔍 Extract JSON Data
        3. 📊 Load GRC Inventory
        4. 🤖 Run Gap Analysis
        5. 📥 Download Report
        """
    )
    st.divider()
    st.markdown("**PoC Version:** 1.0.0")
    st.markdown("**LLM:** Azure OpenAI GPT-4o")

# ---------------------------------------------------------------------------
# Main title
# ---------------------------------------------------------------------------

st.markdown(
    '<div class="main-title">🏦 Regulatory Enforcement Intelligence PoC</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="sub-title">Automated gap analysis between regulatory enforcement findings '
    "and your GRC Control Inventory — powered by Azure OpenAI GPT-4o</div>",
    unsafe_allow_html=True,
)

st.divider()

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

if "document_text" not in st.session_state:
    st.session_state.document_text = None
if "extracted_data" not in st.session_state:
    st.session_state.extracted_data = None
if "inventory" not in st.session_state:
    st.session_state.inventory = None
if "comparison" not in st.session_state:
    st.session_state.comparison = None
if "uploaded_filename" not in st.session_state:
    st.session_state.uploaded_filename = None

# ---------------------------------------------------------------------------
# STEP 1 — Upload Document
# ---------------------------------------------------------------------------

st.markdown('<div class="step-header">Step 1 — Upload Regulatory Enforcement Document</div>', unsafe_allow_html=True)

uploaded_file = st.file_uploader(
    "Upload a regulatory enforcement document (FCA Final Notice, SEC Order, etc.)",
    type=["docx", "pdf"],
    help="Supported formats: .docx and .pdf",
)

if uploaded_file is not None:
    if uploaded_file.name != st.session_state.uploaded_filename:
        # Reset downstream state when a new file is uploaded
        st.session_state.extracted_data = None
        st.session_state.comparison = None
        st.session_state.uploaded_filename = uploaded_file.name

        with st.spinner(f"Parsing **{uploaded_file.name}**..."):
            try:
                file_bytes = uploaded_file.read()
                st.session_state.document_text = parse_document(file_bytes, uploaded_file.name)
                st.success(
                    f"✅ Document parsed successfully — "
                    f"**{len(st.session_state.document_text):,}** characters extracted."
                )
            except ValueError as e:
                st.error(str(e))
                st.session_state.document_text = None

    if st.session_state.document_text:
        with st.expander("📄 Document Preview (first 1,000 characters)", expanded=False):
            preview = get_document_preview(st.session_state.document_text, max_chars=1000)
            st.text(preview)

st.divider()

# ---------------------------------------------------------------------------
# STEP 2 — Extract Structured JSON
# ---------------------------------------------------------------------------

st.markdown('<div class="step-header">Step 2 — Extract Structured Enforcement Data (LLM)</div>', unsafe_allow_html=True)

if st.session_state.document_text is None:
    st.info("⬆️ Please upload a document in Step 1 to proceed.")
else:
    col1, col2 = st.columns([1, 3])
    with col1:
        extract_btn = st.button(
            "🔍 Extract Data",
            disabled=(st.session_state.document_text is None),
            use_container_width=True,
            type="primary",
        )

    if extract_btn:
        with st.spinner("Calling Azure OpenAI GPT-4o to extract enforcement data..."):
            try:
                st.session_state.extracted_data = extract_enforcement_data(
                    st.session_state.document_text
                )
                st.session_state.comparison = None  # reset downstream
                st.success("✅ Extraction complete.")
            except Exception as e:
                st.error(f"Extraction failed: {e}")
                st.session_state.extracted_data = None

    if st.session_state.extracted_data:
        summary = get_extraction_summary(st.session_state.extracted_data)

        st.markdown("##### 📋 Extraction Summary")
        cols = st.columns(4)
        summary_items = list(summary.items())
        for i, (key, val) in enumerate(summary_items):
            with cols[i % 4]:
                st.metric(label=key, value=str(val))

        with st.expander("🔎 Full Extracted JSON", expanded=False):
            st.json(st.session_state.extracted_data)

st.divider()

# ---------------------------------------------------------------------------
# STEP 3 — Load GRC Inventory
# ---------------------------------------------------------------------------

st.markdown('<div class="step-header">Step 3 — GRC Control Inventory</div>', unsafe_allow_html=True)

# Auto-load inventory
if st.session_state.inventory is None:
    try:
        st.session_state.inventory = load_inventory()
    except Exception as e:
        st.error(f"Failed to load GRC inventory: {e}")

if st.session_state.inventory:
    inv_summary = get_inventory_summary(st.session_state.inventory)
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("Total Controls", inv_summary["Total Controls"])
    with col_b:
        st.metric("Regulatory Domain", ", ".join(inv_summary["Regulatory Domains"]))
    with col_c:
        status_str = " | ".join(f"{k}: {v}" for k, v in inv_summary["Status Breakdown"].items())
        st.metric("Status", status_str)

    with st.expander("📊 GRC Inventory Preview", expanded=False):
        inv_df = inventory_to_dataframe(st.session_state.inventory)
        st.dataframe(inv_df, width='stretch', hide_index=True)

st.divider()

# ---------------------------------------------------------------------------
# STEP 4 — Run Gap Analysis
# ---------------------------------------------------------------------------

st.markdown('<div class="step-header">Step 4 — Run LLM Gap Analysis (Azure OpenAI GPT-4o)</div>', unsafe_allow_html=True)

step4_ready = (
    st.session_state.extracted_data is not None
    and st.session_state.inventory is not None
)

if not step4_ready:
    st.info("⬆️ Complete Steps 1–3 before running the gap analysis.")
else:
    col1, col2 = st.columns([1, 3])
    with col1:
        analyse_btn = st.button(
            "🤖 Run Gap Analysis",
            use_container_width=True,
            type="primary",
        )

    if analyse_btn:
        with st.spinner(
            "Comparing enforcement findings against GRC inventory using GPT-4o... "
            "This may take 20–40 seconds."
        ):
            try:
                start = time.time()
                st.session_state.comparison = compare_findings_to_inventory(
                    st.session_state.extracted_data,
                    st.session_state.inventory,
                )
                elapsed = time.time() - start
                st.success(f"✅ Gap analysis complete in {elapsed:.1f}s.")
            except Exception as e:
                st.error(f"Gap analysis failed: {e}")
                st.session_state.comparison = None

st.divider()

# ---------------------------------------------------------------------------
# STEP 5 — Results & Download
# ---------------------------------------------------------------------------

st.markdown('<div class="step-header">Step 5 — Gap Analysis Results & Report</div>', unsafe_allow_html=True)

if st.session_state.comparison is None:
    st.info("⬆️ Run the gap analysis in Step 4 to see results here.")
else:
    comparison = st.session_state.comparison
    assessment = comparison.get("overall_assessment", {})

    # ── Overall Assessment ───────────────────────────────────────────────────
    st.markdown("### 📊 Overall Assessment")

    risk = assessment.get("overall_risk_rating", "N/A")
    risk_colors = {"Low": "🟢", "Medium": "🟡", "High": "🟠", "Critical": "🔴"}
    risk_icon = risk_colors.get(risk, "⚪")

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Total Assessed", assessment.get("total_controls_assessed", 0))
    col2.metric("✅ Covered", assessment.get("covered_count", 0))
    col3.metric("🟡 Partial", assessment.get("partially_covered_count", 0))
    col4.metric("📄 Policy-Only", assessment.get("policy_only_count", 0))
    col5.metric("🔴 Gap", assessment.get("gap_count", 0))
    col6.metric(f"{risk_icon} Risk Rating", risk)

    exec_summary = assessment.get("executive_summary", "")
    if exec_summary:
        st.info(f"**Executive Summary:** {exec_summary}")

    # ── Gap Analysis Table ───────────────────────────────────────────────────
    st.markdown("### 🗂️ Per-Control Gap Analysis")

    gap_df = build_gap_analysis_dataframe(comparison)

    # Coverage classification filter
    all_classifications = AppConfig.COVERAGE_LABELS
    selected = st.multiselect(
        "Filter by Coverage Classification:",
        options=all_classifications,
        default=all_classifications,
    )
    filtered_df = gap_df[gap_df["Coverage Classification"].isin(selected)]

    def _highlight_classification(val: str) -> str:
        color_map = {
            "Covered": "background-color: #d4edda; color: #276221; font-weight: bold",
            "Partially Covered": "background-color: #fff3cd; color: #9C5700; font-weight: bold",
            "Policy-Only Coverage": "background-color: #cce5ff; color: #1F4E79; font-weight: bold",
            "Potential Control Gap": "background-color: #f8d7da; color: #9C0006; font-weight: bold",
            "Insufficient Evidence": "background-color: #e2e3e5; color: #595959; font-weight: bold",
        }
        return color_map.get(val, "")

    styled_df = filtered_df.style.applymap(
        _highlight_classification, subset=["Coverage Classification"]
    )

    st.dataframe(styled_df, width='stretch', hide_index=True, height=420)

    # ── Unmatched Findings ───────────────────────────────────────────────────
    unmatched_df = build_unmatched_findings_dataframe(comparison)
    if not unmatched_df.empty:
        st.markdown("### ⚠️ Unmatched Findings (No Existing Control)")
        st.warning(
            f"**{len(unmatched_df)} enforcement finding(s)** have no matching control "
            "in the GRC inventory. New controls may be required."
        )
        st.dataframe(unmatched_df, width='stretch', hide_index=True)
    else:
        st.success("✅ All enforcement findings are addressed by at least one control in the inventory.")

    # ── Download Excel Report ────────────────────────────────────────────────
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
            f"Report contains 5 sheets: Summary, Gap Analysis, Unmatched Findings, "
            "Enforcement Data, GRC Inventory."
        )
    except Exception as e:
        st.error(f"Failed to generate Excel report: {e}")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.divider()
st.markdown(
    "<div style='text-align:center; color:#aaa; font-size:0.8rem;'>"
    "Regulatory Enforcement Intelligence PoC · Azure OpenAI GPT-4o · "
    "For internal use only · Not legal advice"
    "</div>",
    unsafe_allow_html=True,
)
