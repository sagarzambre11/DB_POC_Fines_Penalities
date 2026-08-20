# Regulatory Enforcement Intelligence — Solution Architecture

**Version:** 3.0
**Date:** 2026-08-20
**Classification:** Internal — Pioneer Presentation

---

## 1. Problem Statement

### What Exists Today (Reactive Compliance)

Financial institutions monitor regulatory developments through:
- Legal/compliance team subscriptions to regulatory news
- Bloomberg / Reuters summaries of enforcement actions
- Internal policy review cycles triggered by new rules

**The gap:** By the time a new regulation is formalised or a peer firm is fined, the firm has already been exposed to the risk for months or years. The remediation cycle is:

```
Regulation published → Policy updated → Control designed → Control tested → Deployed
         ↑
     Too late — risk already existed
```

### What This System Does (Shift-Left Intelligence)

```
Peer firm fined → Enforcement document ingested → Gap detected → Policy signal sent → Proactive fix
         ↑
     Early — before it becomes YOUR firm's problem
```

**Core question the system answers:**
> *"If the enforcement action taken against [Firm X] had happened at our firm — which of our controls would have failed?"*

---

## 2. The Shift-Left Value Narrative

### Why "Shift Left"?

The term comes from software engineering — shift testing earlier in the development lifecycle. Applied to compliance:

| | Reactive (current) | Shift Left (this system) |
|---|---|---|
| **Trigger** | Regulator publishes new rule | Regulator fines another firm |
| **Signal** | Mandatory | Proactive / voluntary |
| **Timing** | After rule is formalised | Before rule is formalised |
| **Action** | Update policy to comply | Update policy to pre-empt |
| **Value** | Avoid breach of existing rules | Avoid becoming the next enforcement case |

### Value Quantification

Value is expressed as **potential risk avoidance**:
- Average FCA penalty (2023–2026): £50M–£500M
- Reputational damage multiplier: 3–10x the financial penalty
- Remediation cost after enforcement: typically 5–15x prevention cost

---

## 3. Current Implementation Status

| Phase | Status | Description |
|---|---|---|
| **Phase 1** | ✅ Complete | PoC: direct LLM comparison, single doc, GRC inventory, Streamlit UI |
| **Phase 2** | ✅ **BUILT** | RAG-Enhanced: semantic retrieval, provider-agnostic embeddings, ChromaDB |
| **Phase 3** | 🔲 Planned | Multi-document intelligence, pattern detection, trend signals |

---

## 4. Architecture — Phase 2 RAG Implementation (CURRENT)

### High-Level Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│  INGESTION (one-time, cached to disk — rebuilds only if inventory   │
│  changes via SHA-256 hash comparison)                               │
│                                                                     │
│  GRC Controls (Excel)                                               │
│       │                                                             │
│       ▼                                                             │
│  format_control_for_embedding()  ← rich text: name + objective +   │
│       │                            mechanism + domain + process     │
│       ▼                                                             │
│  Embedding Provider (provider-agnostic)                             │
│  ┌─────────────────────────────────────────────────────┐            │
│  │  EMBEDDING_PROVIDER=azure  →  AzureEmbedder         │            │
│  │  text-embedding-3-small (1536 dims)                 │            │
│  │                                                     │            │
│  │  EMBEDDING_PROVIDER=google →  GoogleEmbedder        │            │
│  │  text-embedding-004 (768 dims)                      │            │
│  │  task_type=RETRIEVAL_DOCUMENT for indexing          │            │
│  └─────────────────────────────────────────────────────┘            │
│       │                                                             │
│       ▼                                                             │
│  ChromaDB (PersistentClient → .chromadb/ on disk)                  │
│  Collection: grc_controls                                           │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                │ (persists across restarts)
                                │
┌─────────────────────────────────────────────────────────────────────┐
│  QUERY PIPELINE (real-time, per enforcement document)               │
│                                                                     │
│  Step 1: Upload PDF/DOCX                                            │
│       │  → parse_document() → clean_document_text() (40k char cap) │
│       ▼                                                             │
│  Step 2: LLM Extraction (Azure OpenAI)                              │
│       │  → 13-field structured JSON                                 │
│       │  → misconduct_themes + root_cause_evidence extracted        │
│       ▼                                                             │
│  Step 3: Semantic Retrieval (RAG core)                              │
│       │  For each theme + root cause:                               │
│       │    → embed_query() [task_type=RETRIEVAL_QUERY for Google]   │
│       │    → ChromaDB cosine similarity search                      │
│       │    → deduplicate + rank by best distance                    │
│       │    → return TOP-K controls (default: 15 max)                │
│       ▼                                                             │
│  Step 4: LLM Gap Analysis (batched, BATCH_SIZE=6)                   │
│       │  → ONLY retrieved controls assessed (not full inventory)    │
│       │  → Batched to prevent output truncation                     │
│       │  → Final summary call for overall_assessment                │
│       ▼                                                             │
│  Step 5: Report                                                     │
│       → 6-sheet Excel workbook with RAG metadata                   │
│       → Streamlit UI with RAG metrics display                       │
└─────────────────────────────────────────────────────────────────────┘
```

### Token Efficiency (Phase 1 vs Phase 2)

| | Phase 1 (full scan) | Phase 2 (RAG) |
|---|---|---|
| Controls assessed | All N controls | Top-K relevant only (≤15) |
| Tokens per comparison (20 controls) | ~18,000 | ~6,000 |
| Tokens per comparison (500 controls) | ~450,000 (infeasible) | ~6,000 (flat) |
| Scale ceiling | ~50 controls | Unlimited |
| Retrieval method | None (keyword batching) | Semantic cosine similarity |
| Index rebuild cost | N/A | One-time embedding, cached on disk |

---

## 5. Module Architecture

```
app/
├── parser.py        ← Step 1: PDF/DOCX text extraction + cleaning
├── extractor.py     ← Step 2: LLM structured JSON extraction (13 fields)
├── inventory.py     ← Step 3: GRC Excel loader + LLM prompt serialisation
├── embedder.py      ← NEW: Provider-agnostic embedding (Azure or Google)
├── vector_store.py  ← NEW: ChromaDB persistent index with hash-based cache
├── retriever.py     ← NEW: Semantic theme→controls retrieval
├── comparator.py    ← Step 4: RAG-enhanced batched LLM gap analysis
└── reporter.py      ← Step 5: DataFrame builders + 6-sheet Excel report

config.py            ← AzureOpenAIConfig + EmbeddingConfig + AppConfig
streamlit_app.py     ← Full UI: Steps 1–5 with RAG mode toggle
```

---

## 6. Embedding Provider Design

The embedding layer is **fully provider-agnostic**. Switching providers requires only `.env` changes — no code changes anywhere.

```python
# config.py — EmbeddingConfig
PROVIDER = "azure"   # or "google"

# app/embedder.py — factory pattern
get_embedder()  →  AzureEmbedder   (if PROVIDER=azure)
                   GoogleEmbedder  (if PROVIDER=google, lazy-imported)
```

### Azure OpenAI Embedder (active default)
- Model: `text-embedding-3-small`
- Dimensions: 1536
- Auth: reuses existing `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_API_KEY`
- Handles both `openai.azure.com` and `services.ai.azure.com` endpoints automatically
- No additional credentials required

### Google Embedder (ready, activate when key available)
- Model: `text-embedding-004`
- Dimensions: 768
- Auth: `GOOGLE_API_KEY` (free tier from [aistudio.google.com/apikeys](https://aistudio.google.com/apikeys))
- Uses `task_type` distinction:
  - `RETRIEVAL_DOCUMENT` for indexing controls
  - `RETRIEVAL_QUERY` for searching by enforcement themes
- This asymmetric embedding is specifically trained for retrieval — significantly outperforms generic embeddings

### Switching to Google Embeddings

```bash
# .env — only change needed:
EMBEDDING_PROVIDER=google
GOOGLE_API_KEY=your_api_key_here
```

Then click **"Rebuild Index"** in the Step 3 UI to re-embed with Google vectors.

---

## 7. ChromaDB Vector Store Design

```
.chromadb/                    ← persists to disk (git-ignored)
  └── grc_controls collection
        ├── embeddings         ← one vector per control
        ├── documents          ← formatted control text
        ├── metadatas          ← full control fields as strings
        └── metadata
              ├── inventory_hash   ← SHA-256 of inventory content
              ├── provider         ← "azure" or "google"
              └── embedding_model  ← deployment/model name
```

**Cache strategy:** On every app start, the stored `inventory_hash` is compared to the current inventory's hash. If they match, the cached index is reused (zero embedding API calls). If the inventory Excel file changes, the hash changes and the index rebuilds automatically.

---

## 8. RAG Retrieval Strategy

For each enforcement document:

1. Extract `misconduct_control_failure_themes` (e.g. 9 themes)
2. Extract `root_cause_evidence[].finding` (e.g. 7 findings)
3. For each query (themes + findings):
   - Embed with `task_type=RETRIEVAL_QUERY`
   - Query ChromaDB for top-K nearest controls (cosine distance)
4. Track best (lowest) distance per control across all queries
5. Sort by best distance, take top `MAX_RETRIEVED_CONTROLS` (default: 15)
6. Return original control dicts (full fields preserved for LLM)

**Result:** For a 9-theme enforcement doc against a 20-control inventory, typically 10–15 controls are retrieved. For a 500-control inventory, the same 10–15 are retrieved — cost stays flat.

---

## 9. Two-Layer Analysis Model (Controls Focus)

A single enforcement finding is assessed at the controls level:

```
Enforcement Finding: "Firm failed to ingest DMA trading data into surveillance"
         │
         └──▶ CONTROLS LAYER: "Does the firm have a Control that would have
                               required pre-go-live DMA integration into surveillance?"
                               → If NO: POTENTIAL GAP (shift-left signal)
```

### Coverage Classifications

| Label | Meaning |
|---|---|
| ✅ Covered | Control fully addresses the enforcement finding |
| 🟡 Partially Covered | Control exists but is incomplete or too narrow |
| 🔴 Potential Gap | No control addresses this — **primary shift-left signal** |
| ❓ Insufficient Evidence | Cannot determine from available information |

---

## 10. Data Sources

### Tier 1 — Regulatory Enforcement Actions (Primary)

| Source | Document Type | Domain |
|---|---|---|
| FCA (UK) | Final Notices, Decision Notices | All UK financial regulation |
| DFS (New York) | Consent Orders | Banking, AML, Cybersecurity |
| SEC (US) | Administrative Orders, Litigation Releases | Securities, Market Abuse |
| MAS (Singapore) | Enforcement Actions | Capital Markets, Banking |
| FINRA (US) | Disciplinary Actions | Broker-dealers |
| PRA (UK) | Final Notices | Prudential, Banking |
| EBA (EU) | Breach of Union Law Decisions | Banking supervision |

### Tier 2 — Internal GRC Data (Comparison Target)

- GRC Control Inventory (Excel — Phase 2)
- Policy document corpus (Phase 3+)
- Risk register mappings (Phase 3+)

---

## 11. Technology Stack

```
┌─────────────────────────────────────────────────────────────────┐
│                    FULL TECH STACK (v3.0)                        │
│                                                                  │
│  Frontend:     Streamlit (Phase 1/2) → React/Next.js (Phase 3)  │
│  LLM:          Azure OpenAI (GPT-4o-mini / gpt-5-mini)          │
│  Embeddings:   Azure OpenAI text-embedding-3-small (default)    │
│                Google text-embedding-004 (switchable via .env)  │
│  Vector DB:    ChromaDB PersistentClient (local .chromadb/)     │
│  Doc Parsing:  python-docx + pdfplumber                         │
│  GRC Input:    Excel (Phase 2) → PostgreSQL / GRC API (Phase 3) │
│  Deployment:   Local → Docker → Azure Container Apps            │
│  Output:       Excel (6 sheets) → Dashboard → Email (Phase 3)  │
└─────────────────────────────────────────────────────────────────┘
```

### Environment Configuration

| Variable | Default | Description |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | — | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_API_KEY` | — | Azure OpenAI API key |
| `AZURE_OPENAI_DEPLOYMENT` | `gpt-4o-mini` | LLM deployment name |
| `EMBEDDING_PROVIDER` | `azure` | `azure` or `google` |
| `AZURE_EMBEDDING_DEPLOYMENT` | `text-embedding-3-small` | Azure embedding model |
| `GOOGLE_API_KEY` | _(blank)_ | Google AI Studio API key |
| `GOOGLE_EMBEDDING_MODEL` | `models/text-embedding-004` | Google embedding model |
| `VECTOR_DB_PATH` | `.chromadb` | ChromaDB persistence path |
| `RETRIEVAL_TOP_K` | `8` | Controls retrieved per query |
| `MAX_RETRIEVED_CONTROLS` | `15` | Max controls after dedup |

---

## 12. Implementation Roadmap

| Phase | Deliverable | Status | Value |
|---|---|---|---|
| **Phase 1** | PoC: single doc, GRC inventory, Streamlit UI | ✅ Done | Pioneer demo |
| **Phase 2** | RAG: semantic retrieval, provider-agnostic embeddings, ChromaDB | ✅ **Done** | Scalable pilot |
| **Phase 3** | Multi-document intelligence, pattern detection, trend signals | 🔲 Planned | Full product |

### Phase 3 Scope (Next Build)

- Batch ingestion of enforcement libraries (50+ documents)
- Cross-document pattern detection ("AML gaps in 60% of DFS actions")
- Regulatory trend analysis by domain and regulator
- Division-specific gap reports (CB, PB, IB, AFC)
- Policy review prioritisation score
- Azure AI Search (cloud vector store) replacing ChromaDB
- LangChain orchestration for complex multi-step retrieval

---

## 13. Cross-Division Applicability

The solution is **domain-agnostic** and reusable across all divisions:

| Division | Applicable Domains | Example Enforcement Source |
|---|---|---|
| CB (Corporate Banking) | AML, Sanctions, Financial Crime | DFS Consent Orders |
| PB (Private Banking) | Conduct, Suitability, AML | FCA Final Notices |
| IB (Investment Banking) | Market Abuse, Trade Surveillance | FCA, SEC Orders |
| AFC (Anti-Financial Crime) | AML, Sanctions, CFT | DFS, FinCEN |
| Operations | Operational Risk, Data | PRA, EBA |

Same system, same pipeline, different enforcement documents and GRC inventories.

---

## 14. Pioneer Pitch Narrative

**Slide 1 — The Problem:**
> "Every year, regulators fine firms billions for failures that other firms had already experienced. We keep reacting instead of learning."

**Slide 2 — The Shift-Left Insight:**
> "When another firm gets fined, the detailed failure report is public. We can use it to check if our firm has the same weakness — before the regulator asks."

**Slide 3 — The Solution:**
> "An AI system that reads real enforcement documents, extracts what went wrong, and uses semantic search to automatically check whether your controls would have prevented it."

**Slide 4 — The Output:**
> "For each enforcement action: a controls gap signal, stakeholder routing, recommended actions, and a full report. Shift left — act on someone else's lesson."

**Slide 5 — The Value:**
> "Potential risk avoidance value: average FCA penalty avoided + remediation cost avoidance + reputational protection. Phase 2 scales to 500+ controls with flat token cost."

### Key Differentiators

1. **It's not news** — it's the actual enforcement document with scenario detail
2. **It's not a keyword matcher** — it's semantic similarity (finds "surveillance control" even when worded differently)
3. **It's not reactive** — it operates before regulations are formalised
4. **It's not expensive** — RAG reduces token cost by 50–97% vs. full inventory scan
5. **It's not locked in** — switch embedding providers (Azure → Google) via one `.env` change

---

## 15. Capability Matrix

| Capability | Phase 1 PoC | Phase 2 RAG (Current) | Phase 3 Product |
|---|---|---|---|
| Single enforcement doc | ✅ | ✅ | ✅ |
| Any regulator / domain | ✅ | ✅ | ✅ |
| Controls layer mapping | ✅ | ✅ | ✅ |
| Stakeholder signals | ✅ | ✅ | ✅ |
| Excel report | ✅ | ✅ | ✅ |
| Scale (100s of controls) | ❌ | ✅ | ✅ |
| Semantic similarity search | ❌ | ✅ | ✅ |
| Provider-agnostic embeddings | ❌ | ✅ | ✅ |
| Persistent vector index | ❌ | ✅ | ✅ |
| RAG/Full-scan toggle | ❌ | ✅ | ✅ |
| RAG token reduction metrics | ❌ | ✅ | ✅ |
| Multiple enforcement docs | ❌ | ❌ | ✅ |
| Trend / pattern detection | ❌ | ❌ | ✅ |
| Division-specific reports | ❌ | ❌ | ✅ |
| Persistent enforcement DB | ❌ | ❌ | ✅ |

---

*Document prepared for Pioneer presentation. Version 3.0 reflects Phase 2 RAG implementation. For internal use only. Not legal advice.*
