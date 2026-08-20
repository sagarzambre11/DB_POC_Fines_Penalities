# Regulatory Enforcement Intelligence — Testing Guide & How It Works

**Version:** 3.0
**Date:** 2026-08-20

---

## Part 1: How the System Works

### Overview

The system reads a regulatory enforcement document (e.g. an FCA Final Notice), extracts what went wrong, and checks whether your firm's GRC controls would have prevented it — using **semantic similarity** to match enforcement failures to controls, not keyword matching.

```
You upload this:         The system does this:            You get this:
──────────────           ────────────────────             ────────────
FCA Final Notice    →    Extract 13 structured     →      "Your Market
(DMBL fined             fields (penalty, scenario,         Surveillance
£338,000 for            root causes, themes)               control has a
DMA surveillance                                           POTENTIAL GAP —
failure)                         │                         no requirement
                                 ▼                         for pre-go-live
                         Semantic search:                   DMA integration
                         "Which of your controls            testing"
                         match these failure
                         themes?"
                                 │
                                 ▼
                         LLM assesses ONLY the
                         matched controls
                         (not all 500+)
```

---

### Step-by-Step Pipeline

#### Step 1 — Document Upload & Parsing (`app/parser.py`)

- You upload a PDF or DOCX enforcement document
- The system extracts raw text using `pdfplumber` (PDF) or `python-docx` (DOCX)
- Text is cleaned: excessive whitespace collapsed, page numbers removed, boilerplate stripped
- Document is capped at **40,000 characters** (~30,000 tokens) — sufficient for any enforcement notice while reducing LLM costs by 30–50%

```
Input:  50-page FCA Final Notice PDF
Output: Clean plain text, ~35,000 characters
```

---

#### Step 2 — LLM Extraction (`app/extractor.py`)

- The cleaned text is sent to Azure OpenAI (GPT model)
- The LLM extracts **13 structured fields** into a JSON object
- This is regulator-agnostic — auto-detects FCA, DFS, SEC, MAS, etc.

**What gets extracted:**

| Field | Example |
|---|---|
| `regulator` | `{ "name": "Financial Conduct Authority", "abbreviation": "FCA" }` |
| `regulated_entity` | `{ "name": "Dinosaur Merchant Bank Limited", "abbreviation": "DMBL" }` |
| `enforcement_action.penalty_amount` | `338000` |
| `enforcement_action.penalty_currency` | `"GBP"` |
| `regulatory_domain` | `["Market Abuse", "Trade Surveillance"]` |
| `scenario_description` | `"DMBL failed to ingest DMA trading data..."` |
| `misconduct_control_failure_themes` | `["Failure to maintain effective surveillance", "No pre-go-live DMA integration testing", ...]` |
| `root_cause_evidence` | `[{ "finding": "DMA not in surveillance scope", "evidence": "Para 4.12..." }]` |
| `regulatory_requirements` | `[{ "requirement": "UK MAR Article 16(2)", "obligation": "..." }]` |
| `confidence_score` | `{ "score": 0.92, "rationale": "Clear documentary evidence" }` |

**Token cost:** ~5,000–15,000 tokens (depending on document length)

---

#### Step 3 — GRC Inventory Load + Semantic Index (`app/inventory.py`, `app/embedder.py`, `app/vector_store.py`)

**3a. Inventory Load**
- Reads `docs/grc_inventory.xlsx` (sheet: `grc_control_inv1`)
- Validates 11 required columns: `control_id`, `control_name`, `control_objective`, `control_description`, `control_type`, `frequency`, `trigger`, `process`, `regulatory_domain`, `owner`, `status`
- Returns a list of control dicts

**3b. Semantic Index Build (RAG — Phase 2)**
- Each control is formatted as rich text for embedding:
  ```
  "Market Abuse Surveillance Review: Objective: Ensure all trading activity 
   is captured in surveillance. Mechanism: Monthly review of surveillance 
   system coverage against active trading books. Domain: Market Abuse. 
   Process: Trade Surveillance."
  ```
- All controls are embedded using the active provider (Azure or Google)
- Embeddings are stored in **ChromaDB** (persisted to `.chromadb/` on disk)
- A **SHA-256 hash** of the inventory content is stored alongside the embeddings
- On subsequent runs: if the hash matches → index is loaded from disk (zero API calls)
- If the inventory Excel changes → hash changes → index rebuilds automatically

**Why this matters:** A 20-control inventory takes ~2 seconds to embed (one-time). A 500-control inventory takes ~10 seconds. After that, it's instant from cache.

---

#### Step 4 — RAG Retrieval + Gap Analysis (`app/retriever.py`, `app/comparator.py`)

This is the core Phase 2 improvement over Phase 1.

**Phase 1 approach (full scan):**
```
All 20 controls → batch into groups of 6 → 4 LLM calls → assess everything
Problem: irrelevant controls waste tokens and dilute LLM attention
```

**Phase 2 approach (RAG):**
```
9 enforcement themes + 7 root cause findings = 16 queries
Each query → embed → cosine similarity search → top-8 closest controls
Deduplicate across all 16 queries → 10-15 unique controls
Only those 10-15 controls → LLM assessment → 2-3 batched calls
```

**Retrieval in detail (`app/retriever.py`):**
1. Extract themes from the enforcement data (e.g. "Failure to maintain effective surveillance arrangements")
2. Extract root cause findings (e.g. "DMA trading data not ingested into surveillance system")
3. For each query, embed it as a `RETRIEVAL_QUERY` vector
4. Query ChromaDB: find the K nearest controls by cosine distance
5. Track the **best (lowest) distance** for each control across all queries
6. Sort by best distance → take top `MAX_RETRIEVED_CONTROLS` (default: 15)
7. Return the original full control dicts (not ChromaDB metadata copies)

**Gap analysis (`app/comparator.py`):**
- Only the retrieved controls are assessed by the LLM
- Batched into groups of 6 (prevents output truncation)
- Each item gets a `controls_layer` assessment:
  - `coverage_classification`: Covered / Partially Covered / Potential Gap / Insufficient Evidence
  - `rationale`: why the control does/doesn't address the enforcement finding
  - `enforcement_evidence`: direct quote from the document
  - `shift_left_signal`: proactive forward-looking recommendation
  - `recommended_action`: what the controls owner should do
- `stakeholder_signals`: who needs to act (Controls Owner, Risk Manager, Compliance Head, Technology)
- `overall_gap_severity`: Critical / High / Medium / Low
- Final summary call: `overall_assessment` + `unaddressed_findings`

**Token efficiency:**

| Inventory Size | Phase 1 (full scan) | Phase 2 (RAG) | Reduction |
|---|---|---|---|
| 20 controls | ~18,000 tokens | ~6,000 tokens | ~67% |
| 100 controls | ~90,000 tokens | ~6,000 tokens | ~93% |
| 500 controls | ~450,000 (infeasible) | ~6,000 tokens | ~97% |

---

#### Step 5 — Results & Report (`app/reporter.py`)

The results are displayed in 3 tabs:

**Tab 1 — Controls Gap Analysis**
- Table of all assessed controls with coverage classification (colour-coded)
- Shift-left signal callouts for every Potential Gap
- Filterable by coverage label

**Tab 2 — Stakeholder Signals**
- Who needs to act, what action is required, priority (High/Medium/Low)
- High priority action callouts highlighted in red

**Tab 3 — Unaddressed Findings**
- Enforcement themes with NO matching control in the inventory
- Suggested new control + suggested owner for each

**Download:** 6-sheet Excel report:
1. Summary (risk rating, RAG metadata, executive summary)
2. Controls Gap Analysis (colour-coded)
3. Stakeholder Signals
4. Unaddressed Findings
5. Enforcement Data (all 13 extracted fields)
6. GRC Inventory (reference)

---

### Embedding Provider Design

The system uses a **factory pattern** for embeddings — switching providers requires only one `.env` change:

```
EMBEDDING_PROVIDER=azure   → uses AzureEmbedder (text-embedding-3-small, 1536 dims)
EMBEDDING_PROVIDER=google  → uses GoogleEmbedder (text-embedding-004, 768 dims)
```

**Why Google is better for retrieval (when available):**
Google's `text-embedding-004` uses `task_type` — vectors for documents and queries are optimised differently for retrieval tasks. This asymmetric embedding outperforms generic embeddings for semantic search.

**Current state:** Azure is active (uses existing credentials, no extra setup). Google is fully coded and ready — add `GOOGLE_API_KEY` to `.env` and set `EMBEDDING_PROVIDER=google` to activate.

---

## Part 2: How to Test

### Prerequisites

Ensure the following are set in your `.env` file:
```
AZURE_OPENAI_ENDPOINT=https://...
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT=gpt-5-mini
AZURE_EMBEDDING_DEPLOYMENT=text-embedding-3-small
EMBEDDING_PROVIDER=azure
```

Ensure the GRC inventory exists at `docs/grc_inventory.xlsx`.

---

### Test 1: Verify All Imports Load Correctly

```bash
python -c "
from config import AzureOpenAIConfig, EmbeddingConfig, AppConfig
from app.embedder import get_embedder, format_control_for_embedding
from app.vector_store import get_index_info, get_or_build_control_index
from app.retriever import retrieve_relevant_controls
from app.comparator import compare_findings_to_inventory
from app.inventory import load_inventory, inventory_to_combined_prompt_text
from app.reporter import generate_excel_report
print('All imports OK')
print(f'Embedding provider: {EmbeddingConfig.PROVIDER}')
print(f'LLM deployment: {AzureOpenAIConfig.DEPLOYMENT}')
print(f'Missing LLM config: {AzureOpenAIConfig.validate()}')
print(f'Missing embedding config: {EmbeddingConfig.validate()}')
"
```

**Expected output:**
```
All imports OK
Embedding provider: azure
LLM deployment: gpt-5-mini
Missing LLM config: []
Missing embedding config: []
```

---

### Test 2: GRC Inventory Load

```bash
python -c "
from app.inventory import load_inventory, get_inventory_summary
inventory = load_inventory()
summary = get_inventory_summary(inventory)
print(f'Controls loaded: {summary[\"Total Controls\"]}')
print(f'Domains: {summary[\"Regulatory Domains\"]}')
print(f'First control: {inventory[0][\"control_name\"]}')
"
```

**Expected output:**
```
Controls loaded: 20          ← (or however many are in the Excel)
Domains: ['Market Abuse', 'AML', ...]
First control: <name of first control>
```

---

### Test 3: Control Text Formatting for Embedding

```bash
python -c "
from app.inventory import load_inventory
from app.embedder import format_control_for_embedding
inventory = load_inventory()
for ctrl in inventory[:3]:
    print('---')
    print(format_control_for_embedding(ctrl))
"
```

**Expected output:** Rich text strings like:
```
---
Market Abuse Surveillance Review. Objective: Ensure all trading activity 
is captured in surveillance. Mechanism: Monthly review of surveillance 
coverage. Domain: Market Abuse. Process: Trade Surveillance
---
```

---

### Test 4: Build Semantic Index (Embedding API Call)

```bash
python -c "
from app.inventory import load_inventory
from app.vector_store import get_or_build_control_index, get_index_info

print('Loading inventory...')
inventory = load_inventory()
print(f'{len(inventory)} controls loaded')

print('Building vector index...')
collection = get_or_build_control_index(
    inventory,
    force_rebuild=True,
    progress_callback=lambda msg: print(f'  {msg}')
)
print(f'Index built: {collection.count()} controls indexed')

info = get_index_info()
print(f'Provider: {info[\"provider\"]}')
print(f'Model: {info[\"embedding_model\"]}')
"
```

**Expected output:**
```
Loading inventory...
20 controls loaded
Building vector index...
  🔄 Building semantic index for 20 controls using Azure OpenAI · text-embedding-3-small...
  ✅ Semantic index built — 20 controls indexed and ready.
Index built: 20 controls indexed
Provider: azure
Model: text-embedding-3-small
```

**What this tests:** The Azure embedding API is reachable, `text-embedding-3-small` deployment exists, ChromaDB writes to disk correctly.

---

### Test 5: Semantic Retrieval

```bash
python -c "
from app.inventory import load_inventory
from app.retriever import retrieve_relevant_controls_with_scores

inventory = load_inventory()

# Simulate enforcement themes from a market surveillance failure
themes = [
    'Failure to maintain effective surveillance arrangements',
    'DMA trading data not ingested into surveillance system',
    'No pre-go-live integration testing for new trading platforms',
]
root_causes = [
    {'finding': 'Surveillance system did not cover all trading activity'},
    {'finding': 'No periodic review of surveillance coverage'},
]

results = retrieve_relevant_controls_with_scores(
    themes=themes,
    root_causes=root_causes,
    inventory=inventory,
    max_controls=8,
)

print(f'Retrieved {len(results)} controls (from {len(inventory)} total):')
for ctrl, distance in results:
    print(f'  [{distance:.3f}] {ctrl[\"control_id\"]} — {ctrl[\"control_name\"]}')
"
```

**Expected output:**
```
Retrieved 8 controls (from 20 total):
  [0.142] C001 — Market Abuse Surveillance Review
  [0.187] C003 — Trading System Change Control
  [0.241] C007 — Surveillance Coverage Assessment
  ...
```

**What this tests:** Semantic matching works — controls related to surveillance appear at the top even if they don't share exact keywords with the query.

---

### Test 6: Document Parsing

```bash
python -c "
from app.parser import parse_document, get_document_preview
with open('docs/Final Notice 2026_ Dinosaur Merchant Bank Limited.pdf', 'rb') as f:
    text = parse_document(f.read(), 'Final Notice 2026_ Dinosaur Merchant Bank Limited.pdf')
print(f'Extracted: {len(text):,} characters')
print('Preview:')
print(get_document_preview(text, 300))
"
```

**Expected output:**
```
Extracted: 28,450 characters    ← (approximate)
Preview:
FINAL NOTICE
To: Dinosaur Merchant Bank Limited
...
```

---

### Test 7: Full End-to-End Pipeline (No UI)

Run this script to test the complete pipeline programmatically without the Streamlit UI:

```bash
python -c "
import json
from app.parser import parse_document
from app.extractor import extract_enforcement_data, get_extraction_summary
from app.inventory import load_inventory
from app.comparator import compare_findings_to_inventory
from app.comparator import get_controls_gap_rows

# Step 1: Parse
print('Step 1: Parsing document...')
with open('docs/Final Notice 2026_ Dinosaur Merchant Bank Limited.pdf', 'rb') as f:
    doc_text = parse_document(f.read(), 'Final Notice 2026_ Dinosaur Merchant Bank Limited.pdf')
print(f'  Extracted {len(doc_text):,} characters')

# Step 2: Extract
print('Step 2: Extracting enforcement intelligence...')
extracted = extract_enforcement_data(doc_text)
summary = get_extraction_summary(extracted)
print(f'  Regulator: {summary[\"Regulator\"]}')
print(f'  Entity: {summary[\"Regulated Entity\"]}')
print(f'  Penalty: {summary[\"Penalty\"]}')
print(f'  Themes: {summary[\"Misconduct Themes\"]}')
tokens_2 = extracted.get('_token_usage', {}).get('total_tokens', 0)
print(f'  Tokens used: {tokens_2:,}')

# Step 3: Load inventory
print('Step 3: Loading GRC inventory...')
inventory = load_inventory()
print(f'  {len(inventory)} controls loaded')

# Step 4: Gap analysis (RAG mode)
print('Step 4: Running RAG gap analysis...')
def show_progress(msg): print(f'  {msg}')
comparison = compare_findings_to_inventory(
    extracted, inventory,
    progress_callback=show_progress,
    use_rag=True
)
tokens_4 = comparison.get('_token_usage', {}).get('total_tokens', 0)
rag = comparison.get('_rag_metadata', {})
print(f'  Controls assessed: {rag.get(\"controls_assessed\")} of {rag.get(\"total_inventory\")}')
print(f'  Token reduction: {rag.get(\"reduction_pct\")}%')
print(f'  Tokens used: {tokens_4:,}')

# Step 5: Display results
print('Step 5: Results summary')
assessment = comparison.get('overall_assessment', {})
cl = assessment.get('controls_layer_summary', {})
print(f'  Risk rating: {assessment.get(\"overall_risk_rating\")}')
print(f'  Covered: {cl.get(\"covered\")}')
print(f'  Partially covered: {cl.get(\"partially_covered\")}')
print(f'  Potential gaps: {cl.get(\"potential_gap\")}')
print(f'  Unaddressed findings: {len(comparison.get(\"unaddressed_findings\", []))}')
print(f'  Total tokens: {tokens_2 + tokens_4:,}')
print()
print('Gap analysis results:')
for row in get_controls_gap_rows(comparison):
    print(f'  {row[\"ID\"]} | {row[\"Controls Coverage\"]:20s} | {row[\"Name\"]}')
"
```

**Expected output (approximate):**
```
Step 1: Parsing document...
  Extracted 28,450 characters
Step 2: Extracting enforcement intelligence...
  Regulator: FCA
  Entity: Dinosaur Merchant Bank Limited
  Penalty: GBP 338000
  Themes: 9
  Tokens used: 12,450
Step 3: Loading GRC inventory...
  20 controls loaded
Step 4: Running RAG gap analysis...
  🔍 Semantic search: finding relevant controls for 9 enforcement themes...
  ✅ Semantic search complete: 14 of 20 controls selected (30% reduction in LLM input).
  🤖 Analysing batch 1/3 (6 of 14 controls processed)...
  🤖 Analysing batch 2/3 (12 of 14 controls processed)...
  🤖 Analysing batch 3/3 (14 of 14 controls processed)...
  📊 Generating overall assessment and executive summary...
  Controls assessed: 14 of 20
  Token reduction: 30.0%
  Tokens used: 18,200
Step 5: Results summary
  Risk rating: High
  Covered: 6
  Partially covered: 4
  Potential gaps: 3
  Unaddressed findings: 2
  Total tokens: 30,650

Gap analysis results:
  C001 | Covered              | Market Abuse Surveillance Review
  C002 | Potential Gap        | Trading System Change Control
  ...
```

---

### Test 8: Verify RAG Cache

Run Test 4 (build index) once, then run this to confirm the cache is used:

```bash
python -c "
from app.inventory import load_inventory
from app.vector_store import get_or_build_control_index, get_index_info

inventory = load_inventory()

# This should load from cache (no API call)
import time
t0 = time.time()
collection = get_or_build_control_index(
    inventory,
    force_rebuild=False,
    progress_callback=lambda msg: print(f'  {msg}')
)
elapsed = time.time() - t0
print(f'Collection loaded in {elapsed:.2f}s (should be < 0.5s if cached)')
info = get_index_info()
print(f'Controls in index: {info[\"control_count\"]}')
"
```

**Expected:** Loads in < 0.5 seconds with the cache message. No embedding API call is made.

---

### Test 9: Verify Embedding Provider Switch (Without Google Key)

```bash
python -c "
import os
os.environ['EMBEDDING_PROVIDER'] = 'google'
os.environ['GOOGLE_API_KEY'] = ''   # intentionally blank

from config import EmbeddingConfig
from app.embedder import reset_embedder
reset_embedder()

missing = EmbeddingConfig.validate()
print(f'Missing config (expected [GOOGLE_API_KEY]): {missing}')

# Confirm it raises RuntimeError, not ImportError
try:
    from app.embedder import get_embedder
    embedder = get_embedder()
    print('ERROR: should have raised RuntimeError')
except RuntimeError as e:
    print(f'Correct error raised: RuntimeError — {e}')
except Exception as e:
    print(f'Unexpected error type: {type(e).__name__} — {e}')
"
```

**Expected output:**
```
Missing config (expected [GOOGLE_API_KEY]): ['GOOGLE_API_KEY']
Correct error raised: RuntimeError — Missing embedding configuration: GOOGLE_API_KEY. Please update your .env file.
```

**What this tests:** When `EMBEDDING_PROVIDER=google` but `GOOGLE_API_KEY` is blank, the system fails with a clear config error (not an import error, not a URL error).

---

### Test 10: Run the Streamlit App

```bash
python -m streamlit run streamlit_app.py
```

Opens at `http://localhost:8501`. Follow the UI steps:

1. **Step 1:** Upload `docs/Final Notice 2026_ Dinosaur Merchant Bank Limited.pdf`
2. **Step 2:** Click **Extract Intelligence** — wait ~30–60s
3. **Step 3:** Click **Build Semantic Index** — wait ~5s (first time), instant on repeat
4. **Step 4:** Ensure **RAG mode** toggle is ON, click **Run Gap Analysis** — wait ~60–120s
5. **Step 5:** Review results, download Excel report

---

## Part 3: Troubleshooting

### Issue: `AZURE_EMBEDDING_DEPLOYMENT not found` or 404 on embedding call

**Cause:** The `text-embedding-3-small` model is not deployed in your Azure OpenAI resource.

**Fix:**
1. Go to Azure AI Foundry → your resource → Deployments
2. Deploy `text-embedding-3-small` (or `text-embedding-ada-002`)
3. Update `.env`: `AZURE_EMBEDDING_DEPLOYMENT=text-embedding-3-small`

Alternatively, use Google embeddings:
```
EMBEDDING_PROVIDER=google
GOOGLE_API_KEY=your_key
```

---

### Issue: `ChromaDB` error on index build

**Cause:** ChromaDB version conflict or corrupted `.chromadb/` directory.

**Fix:**
```bash
# Delete the cached index and rebuild
rmdir /s /q .chromadb
python -m streamlit run streamlit_app.py
# Then click "Build Semantic Index" in Step 3
```

---

### Issue: RAG returns 0 controls or all controls

**Cause:** Index was built with a different embedding provider than is currently active.

**Fix:** Click **Rebuild Index** in Step 3 UI. This forces `force_rebuild=True` which deletes and recreates the collection with the current provider.

---

### Issue: LLM returns empty JSON / parse error

**Cause:** The reasoning model consumed all tokens on reasoning without producing output. This happens when `max_completion_tokens` is too low.

**Fix:** In `config.py`, increase:
```python
MAX_TOKENS_COMPARISON: int = 32000   # was 25000
MAX_TOKENS_SUMMARY: int = 20000      # was 16000
```

---

### Issue: Gap analysis falls back to full scan despite RAG mode enabled

**Cause:** The semantic index hasn't been built yet, or the embedding API is unavailable.

**Symptoms:** Progress message shows `⚠️ Semantic search failed`. Results banner shows "Fallback Full Scan".

**Fix:** Build the semantic index first (Step 3 → Build Semantic Index button). Check embedding config is valid (`EmbeddingConfig.validate()` returns `[]`).

---

## Part 4: Quick Reference

### Key Configuration Variables

| Variable | Default | When to Change |
|---|---|---|
| `EMBEDDING_PROVIDER` | `azure` | Set to `google` when Google API key available |
| `AZURE_EMBEDDING_DEPLOYMENT` | `text-embedding-3-small` | If using a different Azure embedding model |
| `GOOGLE_API_KEY` | _(blank)_ | Set when switching to Google embeddings |
| `RETRIEVAL_TOP_K` | `8` | Increase for more recall, decrease for fewer tokens |
| `MAX_RETRIEVED_CONTROLS` | `15` | Max controls assessed per enforcement doc |
| `VECTOR_DB_PATH` | `.chromadb` | Change if you want the index stored elsewhere |

### When to Rebuild the Index

| Situation | Rebuild needed? |
|---|---|
| App restart (inventory unchanged) | ❌ No — loaded from cache automatically |
| GRC inventory Excel file edited | ✅ Yes — hash changes, auto-rebuilds |
| Switching from Azure to Google embeddings | ✅ Yes — different vector space, click Rebuild |
| Same provider, app reinstalled | ❌ No — `.chromadb/` persists |

### Data Flow Summary

```
PDF/DOCX
  │ parse_document()           → clean text (40k char cap)
  ▼
LLM (Azure OpenAI)
  │ extract_enforcement_data() → 13-field JSON
  ▼
Enforcement Themes + Root Causes
  │ embed_query() × N themes   → query vectors
  ▼
ChromaDB cosine search
  │ retrieve_relevant_controls()→ top-K controls (≤15)
  ▼
LLM (Azure OpenAI)
  │ compare_findings_to_inventory() → gap analysis JSON (batched)
  ▼
reporter.py
  │ generate_excel_report()    → 6-sheet Excel workbook
  ▼
Streamlit UI
  → Controls Gap tab → Stakeholder Signals tab → Unaddressed Findings tab
  → Download Excel button
```
