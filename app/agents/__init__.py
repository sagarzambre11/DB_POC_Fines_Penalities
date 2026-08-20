"""
app/agents
----------
Agentic RAG pipeline components for the Regulatory Enforcement Intelligence PoC v4.

Agents:
  Intelligence Extractor       — Extracts structured enforcement intelligence from
                                  raw document text; applies confidence-based refinement.
                                  (orchestrator._run_extraction_agent)

  Semantic Retrieval Agent     — HyDE-augmented semantic search; generates hypothetical
                                  GRC controls as query expansions; applies a quality gate
                                  to filter low-similarity hits.
                                  (orchestrator._run_retrieval_agent)

  Compliance Gap Analyser      — Quick-screens all retrieved controls in small batches;
                                  performs targeted deep-dives on high-severity gaps;
                                  resolves contradictions between quick-screen and deep-dive.
                                  (orchestrator._run_gap_analysis_agent)

  Supervisor Agent             — Conversational follow-up Q&A; answers any question
                                  not handled by the specialised agents using full
                                  enforcement + gap analysis context.
                                  (supervisor.answer_followup_question)

Modules:
  orchestrator        — Three self-correcting agent implementations + run_agentic_pipeline()
  langgraph_pipeline  — LangGraph StateGraph wiring: extract_node → retrieve_node → gap_analysis_node
  supervisor          — Supervisor Agent for follow-up question answering
"""
