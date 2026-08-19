"""
app/reporter.py
---------------
Step 5: Gap classification, report generation, and Excel export.

Takes the comparison result from comparator.py and produces:
  - A styled Pandas DataFrame for UI display
  - A downloadable Excel workbook with multiple sheets
"""

import io
from datetime import datetime

import pandas as pd
import openpyxl
from openpyxl.styles import (
    PatternFill,
    Font,
    Alignment,
    Border,
    Side,
)
from openpyxl.utils import get_column_letter

from config import AppConfig
from app.comparator import get_gap_analysis_rows, get_unmatched_findings_rows


# ---------------------------------------------------------------------------
# Coverage colour mapping for Excel cell fills
# ---------------------------------------------------------------------------

EXCEL_FILL_COLORS = {
    "Covered": "C6EFCE",               # green
    "Partially Covered": "FFEB9C",     # yellow
    "Policy-Only Coverage": "BDD7EE",  # blue
    "Potential Control Gap": "FFC7CE", # red
    "Insufficient Evidence": "D9D9D9", # grey
}

EXCEL_FONT_COLORS = {
    "Covered": "276221",
    "Partially Covered": "9C5700",
    "Policy-Only Coverage": "1F4E79",
    "Potential Control Gap": "9C0006",
    "Insufficient Evidence": "595959",
}

RISK_RATING_FILL = {
    "Low": "C6EFCE",
    "Medium": "FFEB9C",
    "High": "FFC7CE",
    "Critical": "FF0000",
}


# ---------------------------------------------------------------------------
# DataFrame helpers
# ---------------------------------------------------------------------------

def build_gap_analysis_dataframe(comparison: dict) -> pd.DataFrame:
    """
    Build a Pandas DataFrame from the gap_analysis section of the comparison result.

    Args:
        comparison: Dict returned by comparator.compare_findings_to_inventory().

    Returns:
        A DataFrame with one row per assessed control.
    """
    rows = get_gap_analysis_rows(comparison)
    if not rows:
        return pd.DataFrame(
            columns=[
                "Control ID",
                "Control Name",
                "Coverage Classification",
                "Classification Rationale",
                "Related Findings",
                "Related Themes",
                "Enforcement Evidence",
                "Recommended Action",
            ]
        )
    return pd.DataFrame(rows)


def build_unmatched_findings_dataframe(comparison: dict) -> pd.DataFrame:
    """
    Build a Pandas DataFrame from the unmatched_findings section.

    Args:
        comparison: Dict returned by comparator.compare_findings_to_inventory().

    Returns:
        A DataFrame with one row per unmatched finding.
    """
    rows = get_unmatched_findings_rows(comparison)
    if not rows:
        return pd.DataFrame(
            columns=["Unmatched Finding", "Risk Implication", "Suggested New Control"]
        )
    return pd.DataFrame(rows)


def build_summary_dataframe(comparison: dict) -> pd.DataFrame:
    """
    Build a summary DataFrame from the overall_assessment section.

    Args:
        comparison: Dict returned by comparator.compare_findings_to_inventory().

    Returns:
        A two-column DataFrame (Metric, Value).
    """
    assessment = comparison.get("overall_assessment", {})
    rows = [
        ("Total Controls Assessed", assessment.get("total_controls_assessed", 0)),
        ("Covered", assessment.get("covered_count", 0)),
        ("Partially Covered", assessment.get("partially_covered_count", 0)),
        ("Policy-Only Coverage", assessment.get("policy_only_count", 0)),
        ("Potential Control Gap", assessment.get("gap_count", 0)),
        ("Insufficient Evidence", assessment.get("insufficient_evidence_count", 0)),
        ("Overall Risk Rating", assessment.get("overall_risk_rating", "N/A")),
    ]
    return pd.DataFrame(rows, columns=["Metric", "Value"])


# ---------------------------------------------------------------------------
# Excel helper utilities
# ---------------------------------------------------------------------------

def _apply_header_style(ws, row: int, num_cols: int) -> None:
    """Apply bold header styling to a row in a worksheet."""
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    for col in range(1, num_cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _apply_border(cell) -> None:
    """Apply a thin border to a cell."""
    thin = Side(style="thin")
    cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)


def _auto_fit_columns(ws, min_width: int = 12, max_width: int = 60) -> None:
    """Auto-fit column widths based on content."""
    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except Exception:
                pass
        adjusted = max(min_width, min(max_length + 4, max_width))
        ws.column_dimensions[col_letter].width = adjusted


# ---------------------------------------------------------------------------
# Main Excel report generator
# ---------------------------------------------------------------------------

def generate_excel_report(
    comparison: dict,
    extracted_enforcement: dict,
    inventory: list[dict],
) -> bytes:
    """
    Generate a multi-sheet Excel workbook containing the full gap analysis report.

    Sheets:
      1. Summary            - Overall assessment metrics
      2. Gap Analysis       - Per-control coverage classification with colour coding
      3. Unmatched Findings - Enforcement findings with no matching control
      4. Enforcement Data   - Key fields from the extracted enforcement JSON
      5. GRC Inventory      - The full GRC control inventory used in the analysis

    Args:
        comparison:            Dict from comparator.compare_findings_to_inventory().
        extracted_enforcement: Dict from extractor.extract_enforcement_data().
        inventory:             List of control dicts from inventory.load_inventory().

    Returns:
        Excel file content as bytes (suitable for Streamlit download button).
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default empty sheet

    entity = extracted_enforcement.get("regulated_entity", {})
    action = extracted_enforcement.get("enforcement_action", {})
    regulator = extracted_enforcement.get("regulator", {})
    assessment = comparison.get("overall_assessment", {})

    # ── Sheet 1: Summary ────────────────────────────────────────────────────
    ws_summary = wb.create_sheet("Summary")

    ws_summary.merge_cells("A1:B1")
    title_cell = ws_summary["A1"]
    title_cell.value = "Regulatory Enforcement Gap Analysis — Summary"
    title_cell.font = Font(bold=True, size=14, color="1F4E79")
    title_cell.alignment = Alignment(horizontal="center")
    ws_summary.row_dimensions[1].height = 30

    meta_rows = [
        ("Report Generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Regulated Entity", entity.get("name", "N/A")),
        ("Regulator", regulator.get("name", "N/A")),
        ("Notice Date", action.get("notice_date", "N/A")),
        ("Penalty (GBP)", action.get("penalty_amount_gbp", "N/A")),
        ("Reference Number", action.get("reference_number", "N/A")),
    ]
    for i, (label, value) in enumerate(meta_rows, start=2):
        ws_summary.cell(row=i, column=1, value=label).font = Font(bold=True)
        ws_summary.cell(row=i, column=2, value=str(value))

    ws_summary.append([])

    # Coverage count table
    ws_summary.append(["Coverage Classification", "Count"])
    _apply_header_style(ws_summary, ws_summary.max_row, 2)

    coverage_data = [
        ("Covered", assessment.get("covered_count", 0)),
        ("Partially Covered", assessment.get("partially_covered_count", 0)),
        ("Policy-Only Coverage", assessment.get("policy_only_count", 0)),
        ("Potential Control Gap", assessment.get("gap_count", 0)),
        ("Insufficient Evidence", assessment.get("insufficient_evidence_count", 0)),
    ]
    for label, count in coverage_data:
        row_num = ws_summary.max_row + 1
        ws_summary.cell(row=row_num, column=1, value=label)
        ws_summary.cell(row=row_num, column=2, value=count)
        hex_bg = EXCEL_FILL_COLORS.get(label, "FFFFFF")
        hex_fg = EXCEL_FONT_COLORS.get(label, "000000")
        for col in [1, 2]:
            cell = ws_summary.cell(row=row_num, column=col)
            cell.fill = PatternFill(start_color=hex_bg, end_color=hex_bg, fill_type="solid")
            cell.font = Font(color=hex_fg, bold=True)
            _apply_border(cell)

    ws_summary.append([])
    risk = assessment.get("overall_risk_rating", "N/A")
    ws_summary.append(["Overall Risk Rating", risk])
    risk_row = ws_summary.max_row
    hex_bg_risk = RISK_RATING_FILL.get(risk, "FFFFFF")
    for col in [1, 2]:
        cell = ws_summary.cell(row=risk_row, column=col)
        cell.fill = PatternFill(start_color=hex_bg_risk, end_color=hex_bg_risk, fill_type="solid")
        cell.font = Font(bold=True, size=12)

    ws_summary.append([])
    ws_summary.append(["Executive Summary"])
    ws_summary.cell(row=ws_summary.max_row, column=1).font = Font(bold=True)
    exec_summary_row = ws_summary.max_row + 1
    ws_summary.cell(row=exec_summary_row, column=1, value=assessment.get("executive_summary", ""))
    ws_summary.cell(row=exec_summary_row, column=1).alignment = Alignment(wrap_text=True)
    ws_summary.merge_cells(
        start_row=exec_summary_row, start_column=1,
        end_row=exec_summary_row, end_column=2
    )
    ws_summary.row_dimensions[exec_summary_row].height = 80

    _auto_fit_columns(ws_summary)

    # ── Sheet 2: Gap Analysis ────────────────────────────────────────────────
    ws_gap = wb.create_sheet("Gap Analysis")
    gap_df = build_gap_analysis_dataframe(comparison)

    headers = list(gap_df.columns)
    ws_gap.append(headers)
    _apply_header_style(ws_gap, 1, len(headers))

    classification_col_idx = headers.index("Coverage Classification") + 1

    for _, row in gap_df.iterrows():
        ws_gap.append(list(row))
        row_num = ws_gap.max_row
        classification = str(row.get("Coverage Classification", ""))
        hex_bg = EXCEL_FILL_COLORS.get(classification, "FFFFFF")
        hex_fg = EXCEL_FONT_COLORS.get(classification, "000000")

        for col_idx in range(1, len(headers) + 1):
            cell = ws_gap.cell(row=row_num, column=col_idx)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            _apply_border(cell)
            if col_idx == classification_col_idx:
                cell.fill = PatternFill(
                    start_color=hex_bg, end_color=hex_bg, fill_type="solid"
                )
                cell.font = Font(color=hex_fg, bold=True)

        ws_gap.row_dimensions[row_num].height = 60

    _auto_fit_columns(ws_gap)
    ws_gap.freeze_panes = "A2"

    # ── Sheet 3: Unmatched Findings ──────────────────────────────────────────
    ws_unmatched = wb.create_sheet("Unmatched Findings")
    unmatched_df = build_unmatched_findings_dataframe(comparison)

    if not unmatched_df.empty:
        headers_u = list(unmatched_df.columns)
        ws_unmatched.append(headers_u)
        _apply_header_style(ws_unmatched, 1, len(headers_u))
        for _, row in unmatched_df.iterrows():
            ws_unmatched.append(list(row))
            row_num = ws_unmatched.max_row
            for col_idx in range(1, len(headers_u) + 1):
                cell = ws_unmatched.cell(row=row_num, column=col_idx)
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                cell.fill = PatternFill(
                    start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"
                )
                _apply_border(cell)
            ws_unmatched.row_dimensions[row_num].height = 60
    else:
        ws_unmatched["A1"] = (
            "No unmatched findings — all enforcement themes are addressed by controls."
        )

    _auto_fit_columns(ws_unmatched)

    # ── Sheet 4: Enforcement Data ────────────────────────────────────────────
    ws_enf = wb.create_sheet("Enforcement Data")
    ws_enf.append(["Field", "Value"])
    _apply_header_style(ws_enf, 1, 2)

    enf_rows = [
        ("Regulator", regulator.get("name", "")),
        ("Abbreviation", regulator.get("abbreviation", "")),
        ("Jurisdiction", extracted_enforcement.get("jurisdiction", "")),
        ("Regulated Entity", entity.get("name", "")),
        ("Entity Type", entity.get("entity_type", "")),
        ("Business Context", entity.get("business_context", "")),
        ("Action Type", action.get("action_type", "")),
        ("Penalty (GBP)", action.get("penalty_amount_gbp", "")),
        ("Legal Basis", action.get("legal_basis", "")),
        ("Settlement Discount %", action.get("settlement_discount", {}).get("percentage", "")),
        ("Pre-Discount Penalty (GBP)", action.get("settlement_discount", {}).get("pre_discount_penalty_gbp", "")),
        ("Notice Date", action.get("notice_date", "")),
        ("Reference Number", action.get("reference_number", "")),
        ("Remedial Outcome", action.get("additional_remedial_outcome", "")),
        ("Scenario Description", extracted_enforcement.get("scenario_description", "")),
        ("Regulatory Domains", ", ".join(extracted_enforcement.get("regulatory_domain", []))),
        (
            "Misconduct Themes",
            "\n".join(extracted_enforcement.get("misconduct_control_failure_themes", [])),
        ),
        (
            "Confidence Score",
            str(extracted_enforcement.get("confidence_score", {}).get("score", "")),
        ),
    ]
    for label, value in enf_rows:
        row_num = ws_enf.max_row + 1
        ws_enf.cell(row=row_num, column=1, value=label).font = Font(bold=True)
        cell_val = ws_enf.cell(row=row_num, column=2, value=str(value))
        cell_val.alignment = Alignment(wrap_text=True, vertical="top")
        _apply_border(ws_enf.cell(row=row_num, column=1))
        _apply_border(ws_enf.cell(row=row_num, column=2))

    _auto_fit_columns(ws_enf)

    # ── Sheet 5: GRC Inventory ───────────────────────────────────────────────
    ws_inv = wb.create_sheet("GRC Inventory")
    if inventory:
        inv_headers = list(inventory[0].keys())
        ws_inv.append(inv_headers)
        _apply_header_style(ws_inv, 1, len(inv_headers))
        for ctrl in inventory:
            ws_inv.append([ctrl.get(h, "") for h in inv_headers])
            row_num = ws_inv.max_row
            for col_idx in range(1, len(inv_headers) + 1):
                cell = ws_inv.cell(row=row_num, column=col_idx)
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                _apply_border(cell)
            ws_inv.row_dimensions[row_num].height = 40
        _auto_fit_columns(ws_inv)
        ws_inv.freeze_panes = "A2"

    # ── Save to bytes buffer ─────────────────────────────────────────────────
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()


def get_report_filename(extracted_enforcement: dict) -> str:
    """
    Generate a descriptive filename for the Excel report.

    Args:
        extracted_enforcement: Dict from extractor.extract_enforcement_data().

    Returns:
        A filename string like 'gap_analysis_DMBL_2026-03-24.xlsx'.
    """
    entity = extracted_enforcement.get("regulated_entity", {})
    abbrev = entity.get("abbreviation") or entity.get("name", "entity")
    abbrev = abbrev.replace(" ", "_").replace("/", "-")[:20]
    action = extracted_enforcement.get("enforcement_action", {})
    date = action.get("notice_date", datetime.now().strftime("%Y-%m-%d"))
    return f"gap_analysis_{abbrev}_{date}.xlsx"
