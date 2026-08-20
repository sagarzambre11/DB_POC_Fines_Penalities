"""
frontend/results.py
-------------------
Results section UI component.

render_results()
    Renders the post-analysis section:
      - Shift-left signal banner
      - 4 key metrics (risk rating, gaps, partial, covered)
      - Three result tabs:
          📋 Controls Gap Analysis
          🔔 Stakeholder Signals
          ⚠️ Unaddressed Findings
      - Excel download button
"""
import streamlit as st

from app.comparator import get_overall_assessment
from app.reporter import (
    build_controls_gap_dataframe,
    build_stakeholder_signals_dataframe,
    build_unaddressed_findings_dataframe,
)
from frontend.helpers import style_coverage, style_priority


def render_results() -> None:
    """
    Render the full results section.
    Only called when st.session_state.comparison is not None.
    """
    cmp        = st.session_state.comparison
    assessment = get_overall_assessment(cmp)
    cl         = assessment.get("controls_layer_summary", {})
    rag        = cmp.get("_rag_metadata", {})
    risk       = assessment.get("overall_risk_rating", "N/A")
    ri         = {"Low": "🟢", "Medium": "🟡", "High": "🟠", "Critical": "🔴"}.get(risk, "⚪")

    # ── Shift-Left Signal Banner ───────────────────────────────────────────────
    headline = assessment.get("shift_left_headline", "Analysis complete.")
    st.markdown(
        f'<div class="banner-yellow">⚡ <strong>Shift-Left Signal:</strong> {headline}</div>',
        unsafe_allow_html=True,
    )

    # ── RAG Mode Banner ────────────────────────────────────────────────────────
    mode_label = rag.get("mode", "unknown").replace("_", " ").title()
    st.markdown(
        f'<div class="banner-blue">🧠 <strong>Mode: {mode_label}</strong> — '
        f'{rag.get("controls_assessed", "?")} of {rag.get("total_inventory", "?")} '
        f'controls assessed · {rag.get("reduction_pct", 0):.0f}% token reduction '
        f'via RAG + HyDE semantic search</div>',
        unsafe_allow_html=True,
    )

    # ── Key Metrics ────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Risk Rating",         f"{ri} {risk}")
    c2.metric("🔴 Potential Gaps",   cl.get("potential_gap", 0))
    c3.metric("🟡 Partial Coverage", cl.get("partially_covered", 0))
    c4.metric("✅ Covered",           cl.get("covered", 0))

    exec_sum = assessment.get("executive_summary", "")
    if exec_sum:
        st.info(f"**Executive Summary:** {exec_sum}")

    # ── Result Tabs ───────────────────────────────────────────────────────────
    tab_gap, tab_signals, tab_unaddressed = st.tabs([
        "📋 Controls Gap Analysis",
        "🔔 Stakeholder Signals",
        "⚠️ Unaddressed Findings",
    ])

    with tab_gap:
        _render_controls_gap_tab(cmp)

    with tab_signals:
        _render_stakeholder_tab(cmp)

    with tab_unaddressed:
        _render_unaddressed_tab(cmp)

    # ── Download Button ────────────────────────────────────────────────────────
    st.divider()
    _render_download_button()


# ---------------------------------------------------------------------------
# Tab renderers
# ---------------------------------------------------------------------------

def _render_controls_gap_tab(cmp: dict) -> None:
    """Render the Controls Gap Analysis tab."""
    st.markdown("#### 📋 Controls Coverage — Gap Analysis")
    st.caption(
        "Assesses whether each GRC control would have prevented or detected "
        "the enforcement failures."
    )

    df = build_controls_gap_dataframe(cmp)
    if df.empty:
        st.info("No gap analysis data available.")
        return

    labels = ["Covered", "Partially Covered", "Potential Gap", "Insufficient Evidence"]
    sel = st.multiselect(
        "Filter by coverage:",
        options=labels,
        default=labels,
        key="filter_gap_tab",
    )
    fdf = df[df["Controls Coverage"].isin(sel)]

    if fdf.empty:
        st.info("No results match the selected filters.")
    else:
        st.dataframe(
            fdf.style.map(style_coverage, subset=["Controls Coverage"]),
            use_container_width=True,
            hide_index=True,
            height=380,
        )
        st.caption(f"Showing {len(fdf)} of {len(df)} controls.")

    # Shift-Left signals for gap items
    gap_rows = fdf[fdf["Controls Coverage"] == "Potential Gap"]
    if not gap_rows.empty:
        st.markdown("##### ⚡ Shift-Left Signals for Potential Gaps")
        for _, row in gap_rows.iterrows():
            sig = row.get("Shift Left Signal", "")
            if sig:
                st.markdown(
                    f'<div class="banner-yellow"><strong>{row["ID"]} — {row["Name"]}'
                    f'</strong><br>{sig}</div>',
                    unsafe_allow_html=True,
                )


def _render_stakeholder_tab(cmp: dict) -> None:
    """Render the Stakeholder Signals tab."""
    st.markdown("#### 🔔 Stakeholder Action Signals")
    st.caption(
        "Who needs to act, what they should do, and how urgently."
    )

    df = build_stakeholder_signals_dataframe(cmp)
    if df.empty:
        st.success("No stakeholder signals — all controls are fully covered.")
        return

    priorities = ["High", "Medium", "Low"]
    sel = st.multiselect(
        "Filter by priority:",
        options=priorities,
        default=priorities,
        key="filter_signals_tab",
    )
    fdf = df[df["Priority"].isin(sel)]

    if fdf.empty:
        st.info("No results match the selected filters.")
    else:
        st.dataframe(
            fdf.style.map(style_priority, subset=["Priority"]),
            use_container_width=True,
            hide_index=True,
            height=380,
        )

    # High priority callouts
    high_rows = fdf[fdf["Priority"] == "High"]
    if not high_rows.empty:
        st.markdown("##### 🔴 High Priority Actions")
        for _, row in high_rows.iterrows():
            st.markdown(
                f'<div class="banner-red"><strong>{row["Stakeholder"]}</strong> — '
                f'`{row["ID"]}` {row["Name"]}<br>{row["Signal"]}</div>',
                unsafe_allow_html=True,
            )


def _render_unaddressed_tab(cmp: dict) -> None:
    """Render the Unaddressed Findings tab."""
    st.markdown("#### ⚠️ Unaddressed Enforcement Findings")
    st.caption(
        "Enforcement themes with **no matching control** in the GRC inventory. "
        "New controls should be created to address these."
    )

    df = build_unaddressed_findings_dataframe(cmp)
    if df.empty:
        st.success("All enforcement themes are addressed by at least one control.")
        return

    st.warning(f"**{len(df)} enforcement theme(s)** have no matching control.")
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_download_button() -> None:
    """Render the Excel report download button."""
    if not st.session_state.xl_bytes:
        st.info("Excel report not available — run the full analysis to generate it.")
        return

    st.markdown("### 📥 Download Full Report")
    st.download_button(
        label="📥 Download Excel Report (.xlsx)",
        data=st.session_state.xl_bytes,
        file_name=st.session_state.xl_name or "enforcement_gap_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )
    st.caption(
        "Report includes: Summary · Controls Gap Analysis · Stakeholder Signals · "
        "Unaddressed Findings · Enforcement Data · GRC Inventory"
    )
