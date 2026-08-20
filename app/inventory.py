"""
app/inventory.py
----------------
Step 3: GRC Controls Inventory loader with display helpers and LLM prompt serialisation.

Three ways to load the GRC inventory:
  1. load_inventory(path)             — from an Excel file on disk (default)
  2. load_inventory_from_bytes(bytes) — from uploaded Excel bytes (in-memory)
  3. extract_controls_from_document(text) — from a DOCX/PDF controls document
                                            via LLM extraction

The GRC inventory represents Controls in the analysis:
  - Each row = one control (objective + description + process = full control context)
  - Each control is assessed as a single unit against enforcement findings
    to identify gaps and generate shift-left signals.
"""

import io
import json

import pandas as pd
from config import AppConfig, AzureOpenAIConfig

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
# Shared DataFrame helper
# ---------------------------------------------------------------------------

def _load_from_dataframe(df: pd.DataFrame) -> list[dict]:
    """
    Shared helper: normalise, validate and convert a DataFrame to inventory records.

    Args:
        df: Raw DataFrame read from an Excel sheet.

    Returns:
        List of control dicts with exactly the EXPECTED_COLUMNS fields.

    Raises:
        ValueError: If required columns are missing.
    """
    df.columns = [col.strip().lower().replace(" ", "_") for col in df.columns]

    missing_cols = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(
            f"GRC inventory is missing expected columns: {missing_cols}. "
            f"Found columns: {list(df.columns)}"
        )

    df = df.dropna(how="all").fillna("")
    return df[EXPECTED_COLUMNS].to_dict(orient="records")


# ---------------------------------------------------------------------------
# Loader 1 — from Excel file on disk
# ---------------------------------------------------------------------------

def load_inventory(
    path: str = None,
    sheet_name: str = None,
) -> list[dict]:
    """
    Load the GRC control inventory from an Excel file on disk.

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

    return _load_from_dataframe(df)


# ---------------------------------------------------------------------------
# Loader 2 — from uploaded Excel bytes
# ---------------------------------------------------------------------------

def load_inventory_from_bytes(
    file_bytes: bytes,
    sheet_name: str = None,
) -> list[dict]:
    """
    Load the GRC control inventory from raw Excel file bytes (e.g. an uploaded file).

    Tries the configured sheet name first; falls back to the first available sheet
    if not found.

    Args:
        file_bytes:  Raw bytes of the .xlsx file.
        sheet_name:  Sheet name to read. Defaults to AppConfig.GRC_SHEET_NAME.

    Returns:
        A list of dicts, each representing one GRC control row.

    Raises:
        ValueError:   If required columns are missing.
        RuntimeError: If the Excel bytes are invalid or unreadable.
    """
    sheet_name = sheet_name or AppConfig.GRC_SHEET_NAME

    try:
        buffer = io.BytesIO(file_bytes)
        try:
            df = pd.read_excel(buffer, sheet_name=sheet_name, engine="openpyxl")
        except Exception:
            buffer.seek(0)
            xl = pd.ExcelFile(buffer, engine="openpyxl")
            available_sheets = xl.sheet_names
            if not available_sheets:
                raise ValueError("The uploaded Excel file contains no sheets.")
            buffer.seek(0)
            df = pd.read_excel(buffer, sheet_name=available_sheets[0], engine="openpyxl")
    except (ValueError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(
            f"Failed to read uploaded GRC inventory: {exc}. "
            "Ensure the file is a valid .xlsx workbook."
        ) from exc

    return _load_from_dataframe(df)


# ---------------------------------------------------------------------------
# Loader 3 — from a DOCX/PDF controls document via LLM extraction
# ---------------------------------------------------------------------------

_CONTROLS_EXTRACTION_SYSTEM = """You are a GRC (Governance, Risk and Compliance) specialist.

Your task: read a controls document and extract every GRC control described in it
as a structured JSON array. Each control must conform exactly to the schema below.

Rules:
- Extract EVERY distinct control described in the document
- Assign a unique control_id using pattern: DOMAIN-TYPE-NNN (e.g. MAB-SURV-001)
- Use "Active" as the default status unless the document says otherwise
- For missing fields use empty string "" — never use null
- control_type must be one of: Detective, Preventive, Corrective
- Return ONLY a valid JSON array — no markdown, no explanation

Required JSON schema per control:
{
  "control_id":          "<unique ID, e.g. AML-MON-001>",
  "control_name":        "<short descriptive name>",
  "control_objective":   "<what the control is designed to achieve>",
  "control_description": "<how the control works operationally>",
  "control_type":        "<Detective|Preventive|Corrective>",
  "frequency":           "<Daily|Weekly|Monthly|Quarterly|Annual|Event Driven|Continuous>",
  "trigger":             "<what activates this control>",
  "process":             "<business process area>",
  "regulatory_domain":   "<compliance domain e.g. Market Abuse, AML, Conduct Risk>",
  "owner":               "<role responsible for this control>",
  "status":              "<Active|Proposed|Retired>"
}"""

_CONTROLS_EXTRACTION_USER = """Extract all GRC controls from this document.

---BEGIN CONTROLS DOCUMENT---
{document_text}
---END CONTROLS DOCUMENT---

Return ONLY a JSON array of control objects. No markdown."""


def extract_controls_from_document(
    document_text: str,
    progress_callback=None,
) -> list[dict]:
    """
    Use the LLM to extract GRC controls from a parsed controls document (DOCX/PDF).

    The document can be in any format: a Word policy document, a controls framework
    PDF, a procedure manual, etc. The LLM identifies each distinct control and maps
    it to the 11-field GRC inventory schema.

    Args:
        document_text:     Plain text from app/parser.parse_document().
        progress_callback: Optional callable(message: str) for UI status updates.

    Returns:
        List of control dicts matching EXPECTED_COLUMNS.

    Raises:
        RuntimeError: If Azure OpenAI config is missing or the API call fails.
        ValueError:   If the LLM response cannot be parsed or no controls found.
    """
    from app.extractor import _build_client, _call_llm_with_retry, _strip_json_fences

    missing = AzureOpenAIConfig.validate()
    if missing:
        raise RuntimeError(
            f"Missing Azure OpenAI configuration: {', '.join(missing)}. "
            "Please update your .env file."
        )

    if progress_callback:
        progress_callback("🤖 Extracting controls from document via LLM...")

    client = _build_client()
    user_prompt = _CONTROLS_EXTRACTION_USER.format(
        document_text=document_text[:35000]  # cap to stay within context window
    )

    raw, usage = _call_llm_with_retry(
        client,
        model=AzureOpenAIConfig.DEPLOYMENT,
        messages=[
            {"role": "system", "content": _CONTROLS_EXTRACTION_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=AppConfig.MAX_TOKENS_EXTRACTION,
    )

    try:
        controls_raw = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned invalid JSON during controls extraction: {exc}\n"
            f"Raw response (first 500 chars): {raw[:500]}"
        ) from exc

    if not isinstance(controls_raw, list) or not controls_raw:
        raise ValueError(
            "LLM did not return a list of controls. "
            f"Got: {type(controls_raw).__name__}. "
            "Check that the document contains GRC control definitions."
        )

    # Normalise each control: ensure all EXPECTED_COLUMNS are present
    controls: list[dict] = []
    for i, ctrl in enumerate(controls_raw):
        if not isinstance(ctrl, dict):
            continue
        normalised = {col: str(ctrl.get(col, "")).strip() for col in EXPECTED_COLUMNS}
        # Assign a fallback control_id if missing
        if not normalised["control_id"]:
            normalised["control_id"] = f"CTRL-{i + 1:03d}"
        controls.append(normalised)

    if not controls:
        raise ValueError(
            "No valid controls could be extracted from the document. "
            "Ensure the document describes GRC controls."
        )

    if progress_callback:
        progress_callback(
            f"✅ Extracted {len(controls)} controls from document "
            f"({usage.get('total_tokens', 0):,} tokens used)."
        )

    return controls


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

    Args:
        inventory: List of control dicts — full inventory or RAG-filtered subset.

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
