# Regulatory Enforcement Intelligence — Solution Architecture

**Version:** 2.0
**Date:** 2026-08-19
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
> *"If the enforcement action taken against [Firm X] had happened at our firm — which of our policies and controls would have failed?"*

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

## 3. What This Is NOT

| This System | Existing Tools |
|---|---|
| Real enforcement documents (Final Notices, Consent Orders) | News articles (Bloomberg, Reuters) |
| Scenario details + control breakdowns + failure specifics | Headlines + penalty amounts |
| Control gap intelligence | News analytics / sentiment |
| Policy-level proactive signals | Regulatory change alerts |
| Specific to what went wrong operationally | Generic regulatory updates |

**Key differentiator:** Real enforcement reports contain:
- The exact control that failed and why
- The specific scenario (e.g. DMA trading not ingested into surveillance)
- Root cause evidence cited by the regulator
- The regulatory obligation that was breached

News articles provide none of this depth.

---

## 4. Data Sources

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

- GRC Control Inventory (Excel/database)
- Policy document corpus (DOCX/PDF)
- Risk register mappings

### Why NOT Bloomberg / Reuters?

Bloomberg and Reuters provide:
- ✅ Penalty amounts
- ✅ Firm name and regulator
- ❌ **NO** scenario detail
- ❌ **NO** control failure specifics
- ❌ **NO** root cause evidence
- ❌ **NO** regulatory paragraph citations

The system requires the **original enforcement document**, not a media summary.

---

## 5. Solution Architecture — Three Phases

---

### Phase 1 — PoC (CURRENT — BUILT ✅)

**Approach:** Direct LLM comparison (prompt-based)

```
┌─────────────┐    ┌──────────────┐    ┌────────────────┐    ┌─────────────┐
│  Enforcement │    │  LLM Extract │    │  GRC Inventory │    │  Two-Layer  │
│  Document    │───▶│  (GPT-4o-    │───▶│  (Excel)       │───▶│  LLM Gap    │
│  (PDF/DOCX)  │    │   mini)      │    │  Dual-role     │    │  Analysis   │
└─────────────┘    └──────────────┘    │  Policy+Control│    └──────┬──────┘
                                        └────────────────┘           │
                                                               ┌──────▼──────┐
                                                               │   Output    │
                                                               │  Policy Gap │
                                                               │  Control Gap│
                                                               │  Stakeholder│
                                                               │  Signals    │
                                                               │  Excel Rpt  │
                                                               └─────────────┘
```

**Capabilities:**
- Single enforcement document ingestion (any regulator, any domain)
- 13-field structured extraction
- Two-layer gap analysis (Policy → Control)
- Stakeholder signal routing
- 7-sheet Excel report download
- Streamlit UI

**Limitations:**
- Entire GRC inventory passed in prompt (limits scale to ~50 controls)
- Single document at a time
- No persistent storage
- No semantic search

**Best used for:** Pioneer demo, concept validation, stakeholder buy-in

---

### Phase 2 — RAG-Enhanced (RECOMMENDED NEXT BUILD)

**Approach:** Retrieval-Augmented Generation with vector embeddings

```
┌──────────────────────────────────────────────────────────────────────┐
│  INGESTION PIPELINE (run once at setup, refreshed periodically)       │
│                                                                      │
│  Policy Docs ──▶ Chunker ──▶ Embedder ──▶ Vector DB                │
│  GRC Controls──▶ (500 tok) ──▶ (Azure AI ──▶ (Azure AI Search /    │
│  Past Enforce.   50 overlap)   Embeddings)   pgvector / ChromaDB)   │
└──────────────────────────────────────────────────────────────────────┘
                                      │
                           ┌──────────▼──────────┐
                           │  Vector Store        │
                           │  ┌────────────────┐ │
                           │  │ Policy chunks  │ │
                           │  │ Control chunks │ │
                           │  │ Past enforcem. │ │
                           │  └────────────────┘ │
                           └──────────┬──────────┘
                                      │ Semantic search
┌──────────────────────────────────────────────────────────────────────┐
│  QUERY PIPELINE (real-time, per enforcement document)                │
│                                                                      │
│  New Enforcement Doc                                                 │
│          │                                                           │
│          ▼                                                           │
│  [LLM Extract] ──▶ Misconduct themes + Root causes                  │
│          │                                                           │
│          ▼                                                           │
│  [Vector Search] ──▶ Top-K relevant policy/control chunks           │
│  (cosine similarity)                                                 │
│          │                                                           │
│          ▼                                                           │
│  [LLM Gap Analysis] ──▶ Policy/Control coverage classification       │
│  (focused, only relevant chunks — not entire corpus)                 │
│          │                                                           │
│          ▼                                                           │
│  [Output] ──▶ Gap signals + Stakeholder alerts + Report             │
└──────────────────────────────────────────────────────────────────────┘
```

**New modules:**
```
app/
├── embedder.py       ← chunk + embed policy/control documents
├── vector_store.py   ← store, index and query vectors
├── retriever.py      ← semantic search: enforcement theme → relevant policies
└── (updated) comparator.py ← uses retrieved chunks instead of full corpus
```

**Tech stack additions:**
| Component | Technology | Rationale |
|---|---|---|
| Embeddings | Azure OpenAI `text-embedding-3-small` | Same Azure resource, low cost |
| Vector Store | Azure AI Search (cloud) or ChromaDB (local) | Azure = production ready; ChromaDB = PoC |
| Chunking | LangChain `RecursiveCharacterTextSplitter` | Smart paragraph-aware chunking |
| Retrieval | Cosine similarity, Top-K = 5–10 | Focused, relevant context only |

**How RAG improves the output:**

```python
# Phase 1 (current — entire inventory in prompt):
inventory_text = all_7_controls_as_text()          # ~2,000 tokens
response = llm.compare(enforcement, inventory_text)

# Phase 2 (RAG — only relevant chunks):
themes = extract_themes(enforcement_json)           # e.g. "surveillance failure"
relevant = vector_store.search(themes, k=8)         # top 8 most relevant policy chunks
response = llm.compare(enforcement, relevant)       # focused, precise comparison
```

**Scale:** Works with 500+ policies, 1,000+ controls, across all divisions.

---

### Phase 3 — Multi-Document Intelligence (FULL PRODUCT)

**Approach:** Batch enforcement intelligence with pattern detection

```
                    ┌─────────────────────────────┐
  50+ FCA notices   │  Enforcement Intelligence    │
  30+ DFS orders ──▶│  Database                    │──▶ Pattern Analysis
  20+ SEC orders    │  (structured extractions)    │
                    └─────────────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────────┐
                    │  Trend Detection Engine      │
                    │  "AML controls gaps are      │
                    │   appearing in 60% of DFS    │
                    │   enforcement actions in     │
                    │   2025-2026"                 │
                    └─────────────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────────┐
                    │  Proactive Policy Signals    │
                    │  Sent to policy owners       │
                    │  BEFORE any new rules        │
                    └─────────────────────────────┘
```

**Capabilities:**
- Batch ingestion of enforcement libraries
- Cross-document pattern detection
- Regulatory trend analysis ("which domains are being targeted most?")
- Division-specific gap reports (CB, PB, IB, AFC)
- Policy review prioritisation score

---

## 6. Two-Layer Analysis Model

### Why Two Layers?

A single enforcement finding can be addressed at two levels:

```
Enforcement Finding: "Firm failed to ingest DMA trading data into surveillance"
         │
         ├──▶ POLICY LAYER: "Do we have a policy requiring all trading systems
         │                   to be integrated into surveillance before go-live?"
         │                   → If NO: POLICY GAP (shift-left signal)
         │
         └──▶ CONTROL LAYER: "Do we have a control that tests trading system
                              integration into surveillance?"
                              → If NO: CONTROL GAP (operational signal)
```

### Coverage Classifications

**Policy Layer (Primary — "Shift Left"):**
| Classification | Meaning |
|---|---|
| ✅ Covered | Policy intent fully requires the missing governance |
| 🟡 Partially Covered | Policy exists but is too narrow |
| 🔴 Potential Gap | No policy requires this — **this is the primary signal** |
| ❓ Insufficient Evidence | Cannot determine |

**Control Layer (Secondary — Operational):**
| Classification | Meaning |
|---|---|
| ✅ Covered | Operational control would have detected/prevented this |
| 🟡 Partially Covered | Control exists but has gaps |
| 📄 Policy-Only Coverage | Policy exists but no operational control exists |
| 🔴 Potential Gap | No control addresses this |
| ❓ Insufficient Evidence | Cannot determine |

---

## 7. Target Stakeholder Flow

```
System detects Policy Gap in "Market Abuse Surveillance Policy"
         │
         ├──▶ SIGNAL TO: Policy Owner (Head of Compliance)
         │    "Enforcement at DMBL shows gap in DMA integration policy.
         │     Your Market Abuse Surveillance Policy may not require
         │     pre-go-live integration testing for new trading systems."
         │
         ├──▶ SIGNAL TO: Control Owner (CTO / Technology)
         │    "No operational control exists to verify trading system
         │     integration into surveillance. Consider adding a mandatory
         │     integration test gate before production release."
         │
         └──▶ SIGNAL TO: Risk Manager
              "This enforcement pattern represents a potential High risk
               exposure. Recommend updating the market abuse risk
               assessment to include DMA platform change risk."
```

**The system does NOT create policies** — it identifies gaps and sends signals to the right stakeholders for action.

---

## 8. Cross-Division Applicability

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

## 9. Pioneer Pitch Narrative

### The Slide Story

**Slide 1 — The Problem:**
> "Every year, regulators fine firms billions for failures that other firms had already experienced. We keep reacting instead of learning."

**Slide 2 — The Shift-Left Insight:**
> "When another firm gets fined, the detailed failure report is public. We can use it to check if our firm has the same weakness — before the regulator asks."

**Slide 3 — The Solution:**
> "An AI system that reads real enforcement documents, extracts what went wrong, and automatically checks whether your policies and controls would have prevented it."

**Slide 4 — The Output:**
> "For each enforcement action: a policy gap signal, a control gap signal, stakeholder routing, and a recommended action. Shift left — act on someone else's lesson."

**Slide 5 — The Value:**
> "Potential risk avoidance value: average FCA penalty avoided + remediation cost avoidance + reputational protection. Expressed as a pre-regulatory early warning signal."

### Key Differentiators to Emphasise

1. **It's not news** — it's the actual enforcement document with scenario detail
2. **It's not a control checker** — it's a policy intelligence system (higher level)
3. **It's not reactive** — it operates before regulations are formalised
4. **It's not division-specific** — it's reusable across CB, PB, IB, AFC

---

## 10. Implementation Roadmap

| Phase | Deliverable | Timeline | Value |
|---|---|---|---|
| **Phase 1** ✅ | PoC: single doc, GRC inventory, Streamlit UI | Done | Pioneer demo |
| **Phase 2** | RAG: Azure AI Search, embedding pipeline, policy corpus | 4–6 weeks | Pilot (1 division) |
| **Phase 3** | Multi-document intelligence, pattern detection, trend signals | 8–12 weeks | Full product |

---

## 11. Current PoC vs. Full Vision Gap Summary

| Capability | Phase 1 PoC | Phase 2 RAG | Phase 3 Product |
|---|---|---|---|
| Single enforcement doc | ✅ | ✅ | ✅ |
| Any regulator / domain | ✅ | ✅ | ✅ |
| Policy layer mapping | ✅ | ✅ | ✅ |
| Control layer mapping | ✅ | ✅ | ✅ |
| Stakeholder signals | ✅ | ✅ | ✅ |
| Excel report | ✅ | ✅ | ✅ |
| Scale (100s of policies) | ❌ | ✅ | ✅ |
| Semantic similarity search | ❌ | ✅ | ✅ |
| Multiple enforcement docs | ❌ | ❌ | ✅ |
| Trend / pattern detection | ❌ | ❌ | ✅ |
| Division-specific reports | ❌ | ✅ | ✅ |
| Persistent enforcement DB | ❌ | ❌ | ✅ |

---

## 12. RAG Technical Design (Phase 2 Detail)

### Embedding Strategy

```
Policy Document (DOCX)
        │
        ▼
  Text Extraction
        │
        ▼
  Chunking (500 tokens, 50 token overlap)
  Preserves paragraph and sentence boundaries
        │
        ▼
  Each chunk tagged with metadata:
  {
    "source": "Market Abuse Policy v2.1",
    "section": "3.2 Surveillance Requirements",
    "domain": "Market Abuse",
    "owner": "Head of Compliance",
    "chunk_id": "map-v21-032-001"
  }
        │
        ▼
  Azure OpenAI text-embedding-3-small
  → 1536-dimension vector
        │
        ▼
  Stored in Vector DB with metadata
```

### Retrieval Strategy

For each enforcement document:
1. Extract `misconduct_control_failure_themes` (e.g. 9 themes for DMBL)
2. For each theme, run vector similarity search → Top-5 policy chunks
3. Deduplicate and rank by relevance score
4. Pass top-15 chunks to LLM for gap analysis

### Why This Is Better Than Full-Prompt

| | Phase 1 (full prompt) | Phase 2 (RAG) |
|---|---|---|
| Tokens per comparison | ~3,000 (entire inventory) | ~800 (relevant chunks only) |
| Policy corpus size | ~10 controls max | Unlimited |
| Relevance | All controls assessed equally | Most relevant first |
| Cost per analysis | Higher | Lower |
| Quality | Good for small corpus | Better for large corpus |

---

## 13. Answering the Key Business Questions

### Q: How do you demonstrate business value?
**A:** Show the DMBL Final Notice → run the system → the output says "Your Market Abuse Surveillance Policy has a Potential Gap — no requirement for pre-go-live DMA integration testing." DMBL was fined £338,000. This signal, if acted on proactively, would have prevented the enforcement.

### Q: How is this different from existing news tools?
**A:** News tools tell you THAT DMBL was fined. This system tells you WHY (DMA trading not integrated, no pre-go-live test, no calibration review) and WHETHER YOUR FIRM has the same weakness.

### Q: Why is this not redundant?
**A:** No existing tool maps enforcement findings to internal policies. GRC tools manage existing controls. Legal tools track regulatory changes. This is the missing layer: external enforcement → internal policy gap.

### Q: What is the adoption path?
**A:** Start with policy owners as early signal adopters. They receive a proactive alert when a peer firm is fined in their domain. Value is immediate and tangible. Expand to risk managers and compliance heads over time.

---

## 14. Technology Summary

```
┌─────────────────────────────────────────────────────────────┐
│                    FULL TECH STACK                           │
│                                                             │
│  Frontend:    Streamlit (Phase 1/2) → React/Next.js (Phase 3)│
│  LLM:         Azure OpenAI GPT-4o-mini                      │
│  Embeddings:  Azure OpenAI text-embedding-3-small           │
│  Vector DB:   ChromaDB (Phase 2 local) → Azure AI Search    │
│  Doc Parsing: python-docx + pdfplumber                      │
│  GRC Input:   Excel (Phase 1) → PostgreSQL / GRC API        │
│  Orchestration: LangChain (Phase 2+)                        │
│  Deployment:  Local → Docker → Azure Container Apps         │
│  Output:      Excel → Dashboard → Email alerts → Teams      │
└─────────────────────────────────────────────────────────────┘
```

---

*Document prepared for Pioneer presentation. For internal use only. Not legal advice.*
