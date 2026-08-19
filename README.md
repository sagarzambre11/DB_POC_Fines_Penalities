# 🏦 Regulatory Enforcement Intelligence — PoC v2

> **AI-powered, regulator-agnostic shift-left compliance intelligence.**
> Upload any enforcement document. Auto-detect regulator, jurisdiction and domain.
> Map findings to your GRC inventory at **policy level** (primary) and **control level** (secondary).
> Powered by **Azure OpenAI GPT-4o** + **Streamlit**.

---

## 📋 Table of Contents

1. [What This Is](#what-this-is)
2. [The Shift-Left Value Narrative](#the-shift-left-value-narrative)
3. [How It Works — 5-Step Pipeline](#how-it-works)
4. [Two-Layer Analysis](#two-layer-analysis)
5. [Architecture](#architecture)
6. [Project Structure](#project-structure)
7. [Prerequisites](#prerequisites)
8. [Installation](#installation)
9. [Configuration](#configuration)
10. [Running Locally](#running-locally)
11. [Using the Application](#using-the-application)
12. [GRC Inventory Format](#grc-inventory-format)
13. [Output Report — 7 Sheets](#output-report)
14. [Coverage Classifications](#coverage-classifications)
15. [Supported Regulators & Domains](#supported-regulators--domains)
16. [Docker Deployment](#docker-deployment)
17. [Troubleshooting](#troubleshooting)

---

## What This Is

This is **not** a news analytics tool. It is **enforcement-driven control gap intelligence**.

The system ingests real regulatory enforcement documents (FCA Final Notices, DFS Consent Orders, SEC Orders, MAS Notices, FINRA Actions, etc.), extracts what actually went wrong, and tells you — proactively — whether your firm's **policies** and **controls** would have prevented it.

**Key differentiators:**
- Real enforcement reports, not news summaries
- Scenario details, control breakdowns, failure specifics
- Policy-level mapping (not just controls)
- Shift-left: act before regulators formalise new rules
- Cross-division reusable: CB, PB, IB, AFC, etc.

---

## The Shift-Left Value Narrative

Traditional compliance is **reactive**: wait for regulations, update policies, implement controls.

This system enables **proactive compliance intelligence**:

```
REACTIVE (old):    Regulation → Fine → Policy Update → Control Fix
SHIFT LEFT (new):  Fine (elsewhere) → Gap Detection → Policy Update → Control Fix
                                       ↑ THIS SYSTEM DOES THIS
```

When another firm is fined, this system answers:
> *"If this had happened at our firm, which of our policies and controls would have failed?"*

**Strategic value:** Avoid future penalties and reputational damage. Improve regulatory readiness before rules are formalised.

---

## How It Works

### Step 1 — Upload Document
- Accept any enforcement document (DOCX or PDF)
- Auto-extract raw text via `python-docx` / `pdfplumber`
- Works for: FCA, DFS, SEC, MAS, FINRA, PRA, EBA, and others

### Step 2 — Extract Enforcement Intelligence
- Azure OpenAI GPT-4o **auto-detects** regulator, jurisdiction, domain
- Extracts 13 standardised fields including:
  - Misconduct/control failure themes
  - Root cause evidence with citations
  - Regulatory requirements breached
  - Customer/market impact
  - Confidence score

### Step 3 — Load GRC Inventory (Dual-Role)
- Loads `docs/grc_inventory.xlsx`
- Each row serves **two roles**:
  - **Policy Layer**: `control_objective` → treated as policy statement
  - **Control Layer**: `control_description` → treated as operational control

### Step 4 — Two-Layer Gap Analysis
- GPT-4o compares enforcement findings against every inventory item at **both layers**
- Returns per-item classification, rationale, evidence, shift-left signals, stakeholder routing
- Identifies enforcement themes with **no matching policy or control**

### Step 5 — Results & Download
- Colour-coded results in 4 tabs: Policy Layer | Control Layer | Stakeholder Signals | Unaddressed Findings
- Shift-left headline and executive summary
- Downloadable 7-sheet Excel report

---

## Two-Layer Analysis

### Layer 1 — Policy Coverage (Primary, "Shift Left" Signal)

> *"Does your firm have a policy that would have required this governance to exist?"*

Maps enforcement findings against the **policy intent** (`control_objective`) of each inventory row.
A policy gap = the firm's framework did not mandate the right behaviour at the strategic level.

### Layer 2 — Control Coverage (Secondary, Operational Signal)

> *"Is there an operational control that would have detected or prevented this failure?"*

Maps enforcement findings against the **operational control** (`control_description`) of each inventory row.
A control gap = even if a policy exists, the operational mechanism is missing or inadequate.

### Classification Labels

| Label | Policy Layer | Control Layer |
|---|---|---|
| ✅ **Covered** | Policy fully addresses the finding | Control fully addresses the finding |
| 🟡 **Partially Covered** | Policy exists but is narrow/incomplete | Control exists but has gaps |
| 📄 **Policy-Only Coverage** | N/A | Policy exists, but no operational control |
| 🔴 **Potential Gap** | No policy addresses this finding | No control addresses this finding |
| ❓ **Insufficient Evidence** | Cannot determine | Cannot determine |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│              Regulatory Enforcement Intelligence — v2                 │
│                                                                      │
│  ┌──────────┐  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │ Step 1   │  │  Step 2     │  │   Step 3     │  │   Step 4    │  │
│  │ Upload   │─▶│ LLM Extract │─▶│ GRC Inventory│─▶│ Two-Layer   │  │
│  │ Any Doc  │  │ (GPT-4o)    │  │ Dual-Role    │  │ LLM Compare │  │
│  │ DOCX/PDF │  │ Auto-detect │  │ Policy +     │  │ (GPT-4o)    │  │
│  │          │  │ Regulator,  │  │ Control      │  │             │  │
│  │          │  │ Domain,     │  │              │  │             │  │
│  │          │  │ Jurisdiction│  │              │  │             │  │
│  └──────────┘  └─────────────┘  └──────────────┘  └──────┬──────┘  │
│                                                           │         │
│                                              ┌────────────▼───────┐ │
│                                              │      Step 5        │ │
│                                              │  Policy Gap Tab    │ │
│                                              │  Control Gap Tab   │ │
│                                              │  Stakeholder Tab   │ │
│                                              │  Unaddressed Tab   │ │
│                                              │  Excel Download    │ │
│                                              └────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

**Tech Stack:**

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| UI | Streamlit |
| LLM | Azure OpenAI GPT-4o-mini |
| Document Parsing | `python-docx` + `pdfplumber` |
| GRC Inventory | `pandas` + `openpyxl` |
| LLM Client | `openai` SDK (Azure) |
| Report Export | `openpyxl` (7-sheet styled Excel) |
| Deployment | Local / Docker |

---

## Project Structure

```
DB_POC_Fines_Penalities/
│
├── docs/
│   ├── PoC_highlevel steps.docx      ← Original PoC specification
│   ├── grc_inventory.xlsx             ← GRC inventory (policy + control dual-role)
│   └── Final Notice 2026_DMBL.pdf    ← Sample enforcement document
│
├── app/
│   ├── __init__.py
│   ├── parser.py       ← Step 1: DOCX/PDF text extraction
│   ├── extractor.py    ← Step 2: Regulator-agnostic LLM extraction (13 fields)
│   ├── inventory.py    ← Step 3: Dual-role inventory loader (policy + control views)
│   ├── comparator.py   ← Step 4: Two-layer LLM comparison engine
│   └── reporter.py     ← Step 5: DataFrames + 7-sheet Excel export
│
├── streamlit_app.py    ← Main UI (5-step pipeline, 4 result tabs)
├── config.py           ← Azure OpenAI config loader
├── requirements.txt    ← Python dependencies
├── Dockerfile          ← Container definition
├── .env.example        ← Credential template
├── .gitignore
└── README.md
```

---

## Prerequisites

- **Python 3.11+**
- **Azure OpenAI** resource with a `gpt-4o` deployment
- **Azure subscription** — create resource at [Azure Portal](https://portal.azure.com)

---

## Installation

```bash
# 1. Navigate to project directory
cd DB_POC_Fines_Penalities

# 2. Create virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Configuration

### 1. Create `.env` from template

```bash
# Windows
copy .env.example .env

# macOS/Linux
cp .env.example .env
```

### 2. Fill in Azure OpenAI credentials

```env
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<your-api-key>
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-02-01
```

| Variable | Where to find |
|---|---|
| `AZURE_OPENAI_ENDPOINT` | Azure Portal → OpenAI resource → Keys and Endpoint |
| `AZURE_OPENAI_API_KEY` | Azure Portal → OpenAI resource → Keys and Endpoint |
| `AZURE_OPENAI_DEPLOYMENT` | Azure OpenAI Studio → Deployments (e.g. `gpt-4o-mini`) |
| `AZURE_OPENAI_API_VERSION` | Use `2024-02-01` |

> ⚠️ Never commit `.env` to source control — it is in `.gitignore`.

---

## Running Locally

```bash
streamlit run streamlit_app.py
```

Opens at `http://localhost:8501`. Stop with `Ctrl+C`.

---

## Using the Application

### Step-by-Step

#### 1️⃣ Upload Document
- Drag and drop or browse for any enforcement document (DOCX or PDF)
- Regulator and domain are **auto-detected** — no configuration needed

#### 2️⃣ Extract Intelligence
- Click **Extract Intelligence**
- GPT-4o extracts 13 fields and shows auto-detected metadata:
  - Regulator, Jurisdiction, Entity, Penalty, Domain, Notice Date

#### 3️⃣ GRC Inventory
- Auto-loaded from `docs/grc_inventory.xlsx`
- Each row is used as **both** a policy statement and an operational control

#### 4️⃣ Run Gap Analysis
- Click **Run Gap Analysis**
- GPT-4o performs two-layer comparison (30–60 seconds)

#### 5️⃣ View Results
Four tabs in the results section:

| Tab | Contents |
|---|---|
| **Policy Layer** | Primary shift-left analysis — policy intent coverage with ⚡ signals |
| **Control Layer** | Secondary operational analysis — control mechanism coverage |
| **Stakeholder Signals** | Who needs to act, what action, High/Medium/Low priority |
| **Unaddressed Findings** | Themes with no matching policy or control + suggested new items |

Click **Download Excel Report** for the full 7-sheet workbook.

---

## GRC Inventory Format

File: `docs/grc_inventory.xlsx`, sheet: `grc_control_inv1`

### Required Columns

| Column | Policy Role (Layer 1) | Control Role (Layer 2) |
|---|---|---|
| `control_id` | Policy reference ID | Control ID |
| `control_name` | Policy name | Control name |
| `control_objective` | **Policy statement** ← primary | Supporting objective |
| `control_description` | Supporting detail | **Operational control** ← primary |
| `control_type` | — | Detective / Preventive / Corrective |
| `frequency` | — | Daily / Monthly / Event Driven |
| `trigger` | — | What activates the control |
| `process` | Policy process area | Control process |
| `regulatory_domain` | Policy domain | Control domain |
| `owner` | Policy owner | Control owner |
| `status` | Proposed / Active / Retired | Proposed / Active / Retired |

### Current Inventory (7 Items)

| ID | Name | Type |
|---|---|---|
| MAB-SURV-001 | Market Abuse Surveillance Monitoring | Detective |
| MAB-STOR-002 | STOR Assessment and Regulatory Reporting | Detective |
| MAB-TECH-003 | Trading System Surveillance Integration Testing | Preventive |
| MAB-CAL-004 | Surveillance Alert Calibration Review | Detective |
| MAB-GOV-005 | Market Abuse Surveillance Governance | Detective |
| MAB-MI-006 | Market Abuse Surveillance Management Information | Detective |
| MAB-QA-007 | Market Abuse Surveillance Quality Assurance | Detective |

---

## Output Report

The downloaded Excel report contains **7 sheets**:

| Sheet | Contents |
|---|---|
| **Summary** | Shift-left headline, metadata, policy + control layer counts, risk rating, executive summary |
| **Policy Gap Analysis** | Layer 1 — per-item policy coverage, rationale, enforcement evidence, shift-left signals, recommended actions |
| **Control Gap Analysis** | Layer 2 — per-item control coverage, rationale, enforcement evidence, recommended actions |
| **Stakeholder Signals** | Who needs to act, what action, High/Medium/Low priority per gap |
| **Unaddressed Findings** | Enforcement themes with no matching policy or control, suggested new policies/controls |
| **Enforcement Data** | All 13 extracted fields from the enforcement document |
| **GRC Inventory** | Full GRC inventory used in the analysis |

---

## Coverage Classifications

### Policy Layer (Layer 1)

| Classification | Meaning | Colour |
|---|---|---|
| ✅ **Covered** | Policy intent fully addresses the enforcement finding | 🟩 Green |
| 🟡 **Partially Covered** | Policy exists but is narrow or incomplete | 🟨 Yellow |
| 🔴 **Potential Gap** | No policy addresses this finding | 🟥 Red |
| ❓ **Insufficient Evidence** | Cannot determine from available information | ⬜ Grey |

### Control Layer (Layer 2)

| Classification | Meaning | Colour |
|---|---|---|
| ✅ **Covered** | Operational control fully addresses the finding | 🟩 Green |
| 🟡 **Partially Covered** | Control exists but has documented gaps | 🟨 Yellow |
| 📄 **Policy-Only Coverage** | Policy exists but no operational control | 🟦 Blue |
| 🔴 **Potential Gap** | No control addresses this finding | 🟥 Red |
| ❓ **Insufficient Evidence** | Cannot determine from available information | ⬜ Grey |

### Gap Severity

| Severity | Meaning |
|---|---|
| 🔴 **Critical** | Immediate risk of regulatory action |
| 🟠 **High** | Significant gap requiring urgent remediation |
| 🟡 **Medium** | Gap requiring planned remediation |
| 🟢 **Low** | Minor gap with limited risk exposure |

---

## Supported Regulators & Domains

The system auto-detects the regulator and domain from the document content.

### Regulators (non-exhaustive)

| Regulator | Jurisdiction |
|---|---|
| FCA — Financial Conduct Authority | United Kingdom |
| PRA — Prudential Regulation Authority | United Kingdom |
| DFS — NY Dept of Financial Services | USA (New York) |
| SEC — Securities and Exchange Commission | USA (Federal) |
| FINRA — Financial Industry Regulatory Authority | USA |
| MAS — Monetary Authority of Singapore | Singapore |
| EBA — European Banking Authority | European Union |
| BaFin | Germany |
| ACPR | France |
| Any other financial regulator | Any jurisdiction |

### Compliance Domains (non-exhaustive)

- Market Abuse / Surveillance / STOR
- AML / Anti-Money Laundering / CFT
- Sanctions / Financial Crime
- Trade Surveillance / Reporting (MiFID, EMIR)
- Conduct Risk / Consumer Duty / Suitability
- Operational Risk / Resilience / BCM
- Capital / Prudential / ICAAP
- Data Protection / GDPR / Privacy
- Insider Dealing / Front Running
- Stop-Loss Manipulation / Order Flow


---

## Docker Deployment

When ready to containerise the application:

### Build the image

```bash
docker build -t reg-enforcement-poc .
```

### Run the container

```bash
docker run -p 8501:8501 --env-file .env reg-enforcement-poc
```

Open your browser at `http://localhost:8501`.

### Environment variables in Docker

Pass credentials via `--env-file .env` (as above) or individually:

```bash
docker run -p 8501:8501 \
  -e AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/ \
  -e AZURE_OPENAI_API_KEY=your-key \
  -e AZURE_OPENAI_DEPLOYMENT=gpt-4o \
  -e AZURE_OPENAI_API_VERSION=2024-02-01 \
  reg-enforcement-poc
```

### Mount GRC inventory from host (optional)

```bash
docker run -p 8501:8501 --env-file .env \
  -v $(pwd)/docs:/app/docs \
  reg-enforcement-poc
```

---

## Troubleshooting

### ❌ "Missing Azure OpenAI configuration"
- Ensure your `.env` file exists and all 4 variables are populated
- Check that `python-dotenv` is installed: `pip install python-dotenv`

### ❌ "Failed to load GRC inventory"
- Verify `docs/grc_inventory.xlsx` exists
- Check the sheet is named `grc_control_inv1`
- Ensure all required columns are present (see [GRC Inventory Format](#grc-inventory-format))

### ❌ "Extraction failed" / "Gap analysis failed"
- Verify your Azure OpenAI endpoint URL ends with `/`
- Check your API key is valid and not expired
- Ensure the deployment name matches exactly
