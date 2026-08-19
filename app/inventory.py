"""
app/inventory.py
----------------
Step 3: GRC Control Inventory loader with dual-role parsing.

The GRC inventory serves TWO roles in the analysis:
  - POLICY LAYER  (primary):  control_objective + process → treated as policy intent
  - CONTROL LAYER (secondary): control_description + control_type → operational control

This dual-role approach supports the "shift left" value narrative:
  map enforcement findings → policies first, then controls.
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
# Dual-role representations for LLM prompts
# ---------------------------------------------------------------------------

def inventory_to_policy_prompt_text(inventory: list[dict]) -> str:
    """
    Serialise the inventory as a POLICY CORPUS for LLM prompt injection.

    Each row is represented at the policy/intent level:
      - Policy ID  = control_id
      - Policy Name = control_name
      - Policy Statement = control_objective  ← PRIMARY for policy mapping
      - Policy Domain = regulatory_domain
      - Policy Owner = owner
      - Process Area = process

    Args:
        inventory: List of control dicts from load_inventory().

    Returns:
        Formatted multi-line string representing all policies.
    """
    lines = []
    for ctrl in inventory:
        lines.append(
            f"[POLICY: {ctrl['control_id']}] {ctrl['control_name']}\n"
            f"  Policy Statement : {ctrl['control_objective']}\n"
            f"  Process Area     : {ctrl['process']}\n"
            f"  Domain           : {ctrl['regulatory_domain']}\n"
            f"  Policy Owner     : {ctrl['owner']}\n"
            f"  Status           : {ctrl['status']}\n"
        )
    return "\n".join(lines)


def inventory_to_control_prompt_text(inventory: list[dict]) -> str:
    """
    Serialise the inventory as an OPERATIONAL CONTROL set for LLM prompt injection.

    Each row is represented at the operational control level:
      - Control ID = control_id
      - Control Name = control_name
      - Control Description = control_description  ← PRIMARY for control mapping
      - Control Type = control_type
      - Frequency + Trigger = operational cadence
      - Owner = control owner

    Args:
        inventory: List of control dicts from load_inventory().

    Returns:
        Formatted multi-line string representing all controls.
    """
    lines = []
    for ctrl in inventory:
        lines.append(
            f"[CONTROL: {ctrl['control_id']}] {ctrl['control_name']}\n"
            f"  Description  : {ctrl['control_description']}\n"
            f"  Type         : {ctrl['control_type']} | "
            f"Frequency: {ctrl['frequency']} | "
            f"Trigger: {ctrl['trigger']}\n"
            f"  Domain       : {ctrl['regulatory_domain']} | "
            f"Process: {ctrl['process']}\n"
            f"  Owner        : {ctrl['owner']} | "
            f"Status: {ctrl['status']}\n"
        )
    return "\n".join(lines)


def inventory_to_combined_prompt_text(inventory: list[dict]) -> str:
    """
    Serialise the inventory showing BOTH policy intent AND control detail.

    Used for the unified two-layer comparison where the LLM assesses
    both policy coverage and control coverage in a single pass.

    Args:
        inventory: List of control dicts from load_inventory().

    Returns:
        Formatted multi-line string showing combined policy + control view.
    """
    lines = []
    for ctrl in inventory:
        lines.append(
            f"[ID: {ctrl['control_id']}] {ctrl['control_name']}\n"
            f"  POLICY INTENT (primary)  : {ctrl['control_objective']}\n"
            f"  OPERATIONAL CONTROL      : {ctrl['control_description']}\n"
            f"  Type         : {ctrl['control_type']} | "
            f"Frequency: {ctrl['frequency']} | "
            f"Trigger: {ctrl['trigger']}\n"
            f"  Domain       : {ctrl['regulatory_domain']} | "
            f"Process: {ctrl['process']}\n"
            f"  Owner        : {ctrl['owner']} | "
            f"Status: {ctrl['status']}\n"
        )
    return "\n".join(lines)


def get_policy_view(inventory: list[dict]) -> list[dict]:
    """
    Return a policy-focused view of the inventory.

    Extracts the policy-level fields from each inventory row.

    Args:
        inventory: List of control dicts from load_inventory().

    Returns:
        List of dicts with policy-level fields only.
    """
    return [
        {
            "policy_id": ctrl["control_id"],
            "policy_name": ctrl["control_name"],
            "policy_statement": ctrl["control_objective"],
            "process_area": ctrl["process"],
            "regulatory_domain": ctrl["regulatory_domain"],
            "policy_owner": ctrl["owner"],
            "status": ctrl["status"],
        }
        for ctrl in inventory
    ]


def get_control_view(inventory: list[dict]) -> list[dict]:
    """
    Return a control-focused view of the inventory.

    Extracts the operational control fields from each inventory row.

    Args:
        inventory: List of control dicts from load_inventory().

    Returns:
        List of dicts with operational control fields only.
    """
    return [
        {
            "control_id": ctrl["control_id"],
            "control_name": ctrl["control_name"],
            "control_description": ctrl["control_description"],
            "control_type": ctrl["control_type"],
            "frequency": ctrl["frequency"],
            "trigger": ctrl["trigger"],
            "regulatory_domain": ctrl["regulatory_domain"],
            "process": ctrl["process"],
            "control_owner": ctrl["owner"],
            "status": ctrl["status"],
        }
        for ctrl in inventory
    ]
