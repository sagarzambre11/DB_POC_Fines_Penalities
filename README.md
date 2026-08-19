# 🏦 Regulatory Enforcement Intelligence PoC

> Automated gap analysis between regulatory enforcement findings and your GRC Control Inventory — powered by **Azure OpenAI GPT-4o** and **Streamlit**.

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [How It Works — The 5-Step Pipeline](#how-it-works)
3. [Architecture](#architecture)
4. [Project Structure](#project-structure)
5. [Prerequisites](#prerequisites)
6. [Installation](#installation)
7. [Configuration](#configuration)
8. [Running Locally](#running-locally)
9. [Using the Application](#using-the-application)
10. [GRC Inventory Format](#grc-inventory-format)
11. [Output Report](#output-report)
12. [Coverage Classifications](#coverage-classifications)
13. [Docker Deployment](#docker-deployment)
14. [Troubleshooting](#troubleshooting)

---

## Overview

This Proof of Concept (PoC) automates the end-to-end process of:

1. **Ingesting** regulatory enforcement documents (FCA Final Notices, SEC Orders, MAS Notices, etc.)
2. **Extracting** structured intelligence from them using an LLM (Azure OpenAI GPT-4o)
3. **Comparing** extracted findings against your firm's GRC Control Inventory
4. **Classifying** coverage gaps per control
5. **Generating** a colour-coded Excel gap analysis report

**Source document used in this PoC:**
> *Final Notice 2026 — Dinosaur Merchant Bank Limited (DMBL)* — FCA enforcement action for failure to maintain effective market abuse surveillance arrangements under UK MAR Article 16(2), Principle 3, and SYSC 6.1.1R.

---

## How It Works

### Step 1 — Upload the Document
- Accept a regulatory enforcement document in **DOCX** or **PDF** format
- Extract raw text using `python-docx` (DOCX) or `pdfplumber` (PDF)

### Step 2 — Extract Structured JSON
- Send the extracted text to **Azure OpenAI GPT-4o** with a structured extraction prompt
- The LLM returns a validated JSON object containing 13 standardised fields:

| Field | Description |
|---|---|
| `regulator` | Regulator name and abbreviation |
| `jurisdiction` | Country or region |
| `regulated_entity` | Firm name, type, and business context |
| `enforcement_action` | Action type, penalty, legal basis, settlement discount |
| `regulatory_domain` | Domain areas covered (e.g. Market Abuse, STOR) |
| `scenario_description` | Detailed description of the misconduct |
| `misconduct_control_failure_themes` | List of control failure themes |
| `root_cause_evidence` | Findings with supporting evidence |
| `regulatory_requirements` | Breached rules with obligations and findings |
| `customer_or_market_impact` | Impact assessment and affected trading data |
| `fca_source_citations` | Document references and paragraph citations |
| `confidence_score` | LLM confidence score (0–1) with rationale |

### Step 3 — Load GRC Control Inventory
- Automatically loads `docs/grc_inventory.xlsx`
- Displays 7 controls (MAB-SURV-001 through MAB-QA-007) covering Market Abuse domain

### Step 4 — LLM Gap Analysis
- Sends the extracted enforcement JSON **+** GRC inventory to GPT-4o
- The LLM assesses coverage of each control against the enforcement findings
- Returns structured comparison JSON with per-control classifications

### Step 5 — Generate Gap Analysis Report
- Displays colour-coded results table in the UI
- Highlights unmatched findings with no existing control
- Generates a downloadable multi-sheet **Excel report**

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                   Streamlit Web Application                          │
│                                                                     │
│  ┌──────────┐   ┌──────────────┐   ┌────────────┐   ┌──────────┐  │
│  │  Step 1  │   │   Step 2     │   │  Step 3    │   │  Step 4  │  │
│  │  Upload  │──▶│  LLM Extract │──▶│  Load GRC  │──▶│  LLM Gap │  │
│  │  DOCX/   │   │  (GPT-4o)    │   │ Inventory  │   │ Analysis │  │
│  │   PDF    │   │              │   │  (Excel)   │   │ (GPT-4o) │  │
│  └──────────┘   └──────────────┘   └────────────┘   └──────────┘  │
│                                                            │        │
│                                                     ┌──────▼──────┐ │
│                                                     │   Step 5    │ │
│                                                     │ Gap Report  │ │
│                                                     │  + Excel    │ │
│                                                     │  Download   │ │
│                                                     └─────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  Azure OpenAI      │
                    │  GPT-4o            │
                    │  (Extraction +     │
                    │   Comparison)      │
                    └────────────────────┘
```

**Tech Stack:**

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| Frontend / UI | Streamlit |
| LLM | Azure OpenAI GPT-4o |
| Document Parsing | `python-docx` (DOCX), `pdfplumber` (PDF) |
| GRC Inventory | `pandas` + `openpyxl` (Excel) |
| LLM Client | `openai` Python SDK (Azure mode) |
| Report Export | `openpyxl` (styled Excel workbook) |
| Deployment | Local (`streamlit run`) / Docker |

---

## Project Structure

```
DB_POC_Fines_Penalities/
│
├── docs/
│   ├── PoC_highlevel steps.docx   # Original PoC specification
│   └── grc_inventory.xlsx          # GRC Control Inventory (input)
│
├── app/
│   ├── __init__.py                 # Package init
│   ├── parser.py                   # Step 1: DOCX/PDF text extraction
│   ├── extractor.py                # Step 2: LLM JSON extraction
│   ├── inventory.py                # Step 3: Excel GRC inventory loader
│   ├── comparator.py               # Step 4: LLM gap analysis comparison
│   └── reporter.py                 # Step 5: DataFrame + Excel report generator
│
├── streamlit_app.py                # Main Streamlit UI entry point
├── config.py                       # Azure OpenAI config loader
├── requirements.txt                # Python dependencies
├── Dockerfile                      # Docker container definition
├── .env.example                    # Environment variable template
├── .env                            # Your actual credentials (DO NOT commit)
└── README.md                       # This guide
```

---

## Prerequisites

- **Python 3.11+** — [Download](https://www.python.org/downloads/)
- **Azure OpenAI resource** with a `gpt-4o` deployment
  - Azure subscription required
  - Create resource at: [Azure Portal](https://portal.azure.com)
- **Git** (optional, for cloning)

---

## Installation

### 1. Clone or navigate to the project directory

```bash
cd DB_POC_Fines_Penalities
```

### 2. Create a virtual environment (recommended)

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## Configuration

### 1. Create your `.env` file

Copy the example template:

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

### 2. Fill in your Azure OpenAI credentials

Open `.env` and populate all values:

```env
AZURE_OPENAI_ENDPOINT=https://<your-resource-name>.openai.azure.com/
AZURE_OPENAI_API_KEY=<your-api-key>
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-02-01
```

| Variable | Where to find it |
|---|---|
| `AZURE_OPENAI_ENDPOINT` | Azure Portal → Your OpenAI resource → Keys and Endpoint |
| `AZURE_OPENAI_API_KEY` | Azure Portal → Your OpenAI resource → Keys and Endpoint |
| `AZURE_OPENAI_DEPLOYMENT` | Azure OpenAI Studio → Deployments → your deployment name |
| `AZURE_OPENAI_API_VERSION` | Use `2024-02-01` (or check Azure docs for latest) |

> ⚠️ **Never commit your `.env` file to source control.** Add it to `.gitignore`.

### 3. Verify GRC inventory path

The app auto-loads `docs/grc_inventory.xlsx`. If you move the file, update `GRC_INVENTORY_PATH` in `.env`:

```env
GRC_INVENTORY_PATH=docs/grc_inventory.xlsx
GRC_SHEET_NAME=grc_control_inv1
```

---

## Running Locally

```bash
streamlit run streamlit_app.py
```

The app will open automatically in your browser at:
```
http://localhost:8501
```

To stop the server: press `Ctrl+C` in the terminal.

---

## Using the Application

### Step-by-Step Walkthrough

#### 1️⃣ Upload Document
- Click **Browse files** or drag and drop your enforcement document
- Supported: `.docx` (Word) and `.pdf`
- The document text is extracted and a preview is shown

#### 2️⃣ Extract Data
- Click **🔍 Extract Data**
- GPT-4o analyses the document and extracts 13 structured fields
- View the extraction summary metrics and expand the full JSON

#### 3️⃣ GRC Inventory
- Automatically loaded from `docs/grc_inventory.xlsx`
- Expand the preview to see all 7 controls

#### 4️⃣ Run Gap Analysis
- Click **🤖 Run Gap Analysis**
- GPT-4o compares each enforcement finding against each GRC control
- Typically takes 20–40 seconds

#### 5️⃣ View Results & Download
- Review the **Overall Assessment** metrics (risk rating, coverage counts)
- Read the **Executive Summary**
- Filter the **Gap Analysis Table** by coverage classification
- Review **Unmatched Findings** (findings with no matching control)
- Click **📥 Download Excel Report** to save the full report

---

## GRC Inventory Format

The `docs/grc_inventory.xlsx` file must contain a sheet named `grc_control_inv1` with the following columns:

| Column | Description | Example |
|---|---|---|
| `control_id` | Unique control identifier | `MAB-SURV-001` |
| `control_name` | Short control name | `Market Abuse Surveillance Monitoring` |
| `control_objective` | What the control aims to achieve | `Detect potentially suspicious orders...` |
| `control_description` | Detailed operational description | `Automated surveillance monitors all...` |
| `control_type` | `Detective`, `Preventive`, or `Corrective` | `Detective` |
| `frequency` | How often the control runs | `Daily`, `Monthly`, `Event Driven` |
| `trigger` | What activates the control | `Order or transaction executed` |
| `process` | Business process the control belongs to | `Market Abuse Surveillance` |
| `regulatory_domain` | Regulatory domain | `Market Abuse` |
| `owner` | Control owner role | `Head of Compliance` |
| `status` | Control status | `Proposed`, `Active`, `Retired` |

### Current Inventory (7 Controls)

| Control ID | Control Name | Type |
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

The downloaded Excel report contains **5 sheets**:

| Sheet | Contents |
|---|---|
| **Summary** | Report metadata, coverage count table, overall risk rating, executive summary |
| **Gap Analysis** | Per-control classification with rationale, related findings, enforcement evidence, recommended actions |
| **Unmatched Findings** | Enforcement findings/themes with no matching control, risk implications, suggested new controls |
| **Enforcement Data** | All 13 extracted fields from the enforcement document |
| **GRC Inventory** | Full GRC control inventory used in the analysis |

---

## Coverage Classifications

| Classification | Meaning | Colour |
|---|---|---|
| ✅ **Covered** | The control directly and fully addresses the enforcement finding | 🟩 Green |
| 🟡 **Partially Covered** | The control exists but is incomplete, narrow, or has documented gaps | 🟨 Yellow |
| 📄 **Policy-Only Coverage** | Only a policy exists; no operational or detective control is in place | 🟦 Blue |
| 🔴 **Potential Control Gap** | No control in the inventory addresses this finding | 🟥 Red |
| ❓ **Insufficient Evidence** | Insufficient information to determine coverage | ⬜ Grey |

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
