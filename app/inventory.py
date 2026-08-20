"""
app/inventory.py
----------------
Step 3: GRC Controls Inventory loader with display helpers and LLM prompt serialisation.

The GRC inventory represents Controls in the analysis:
  - Each row = one control (objective + description + process = full control context)
  - Each control is assessed as a single unit against enforcement findings
    to identify gaps and generate shift-left signals.
"""

import pandas as pd
from config import AppConfig

# Expected columns in the GRC inventory sheet
EXPECTED_COLUMNS = [
    "control_id",
    "control_name",
    "control_objective",
    "control_description",
    "control_type",
    "frequency",
    "trigger",
    "process",
    "regulatory_domain",
    "owner",
    "status",
]


# ---------------------------------------------------------------------------
# Core loader
# ---------------------------------------------------------------------------

def load_inventory(
    path: str = None,
    sheet_name: str = None,
) -> list[dict]:
    """
    Load the GRC control inventory from an Excel file.

    Args:
        path:       Path to the Excel file. Defaults to AppConfig.GRC_INVENTORY_PATH.
        sheet_name: Sheet name to read. Defaults to AppConfig.GRC_SHEET_NAME.

    Returns:
        A list of dicts, each representing one GRC control row.

    Raises:
        FileNotFoundError: If the Excel file does not exist at the given path.
        ValueError:        If required columns are missing from the sheet.
    """
    path = path or AppConfig.GRC_INVENTORY_PATH
    sheet_name = sheet_name or AppConfig.GRC_SHEET_NAME

    try:
        df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    except FileNotFoundError:
        raise FileNotFoundError(
            f"GRC inventory file not found at: '{path}'. "
            "Please ensure the file exists."
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to read GRC inventory: {exc}") from exc

    # Normalise column names
    df.columns = [col.strip().lower().replace(" ", "_") for col in df.columns]

    # Validate required columns
    missing_cols = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(
            f"GRC inventory is missing expected columns: {missing_cols}. "
            f"Found columns: {list(df.columns)}"
        )

    # Drop fully empty rows and fill NaN
    df = df.dropna(how="all").fillna("")

    return df[EXPECTED_COLUMNS].to_dict(orient="records")


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def inventory_to_dataframe(inventory: list[dict]) -> pd.DataFrame:
    """Convert inventory list to a Pandas DataFrame for UI display."""
    return pd.DataFrame(inventory, columns=EXPECTED_COLUMNS)


def get_inventory_summary(inventory: list[dict]) -> dict:
    """Return summary statistics about the loaded inventory."""
    domains = list({ctrl["regulatory_domain"] for ctrl in inventory if ctrl["regulatory_domain"]})
    statuses: dict = {}
    for ctrl in inventory:
        s = ctrl.get("status", "Unknown")
        statuses[s] = statuses.get(s, 0) + 1

    return {
        "Total Controls": len(inventory),
        "Regulatory Domains": domains,
        "Status Breakdown": statuses,
        "Control IDs": [ctrl["control_id"] for ctrl in inventory],
    }


# ---------------------------------------------------------------------------
# LLM prompt serialisation
# ---------------------------------------------------------------------------

def inventory_to_combined_prompt_text(inventory: list[dict]) -> str:
    """
    Serialise the inventory as a CONTROLS CORPUS for LLM prompt injection.

    Formats each control with its full context (objective, mechanism, operational
    details) so the LLM can assess coverage against enforcement findings.

    Used by comparator.py for both RAG-filtered batches and full-scan batches.

    Args:
        inventory: List of control dicts from load_inventory() — can be the full
                   inventory or a RAG-filtered subset.

    Returns:
        Formatted multi-line string representing all controls in the list.
    """
    lines = []
    for ctrl in inventory:
        lines.append(
            f"[ID: {ctrl['control_id']}] {ctrl['control_name']}\n"
            f"  CONTROL OBJECTIVE  : {ctrl['control_objective']}\n"
            f"  CONTROL MECHANISM  : {ctrl['control_description']}\n"
            f"  Type               : {ctrl['control_type']} | "
            f"Frequency: {ctrl['frequency']} | "
            f"Trigger: {ctrl['trigger']}\n"
            f"  Domain             : {ctrl['regulatory_domain']} | "
            f"Process: {ctrl['process']}\n"
            f"  Owner              : {ctrl['owner']} | "
            f"Status: {ctrl['status']}\n"
        )
    return "\n".join(lines)
