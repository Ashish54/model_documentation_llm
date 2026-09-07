# Scenario Comparison Chatbot

An internal chatbot that lets users compare two economic scenarios and get explanations grounded in an economist knowledge base.

## Language

**Scenario**:
A versioned, economist-authored forecast run with fixed inputs and precomputed outputs. The unit of comparison is two whole scenarios.
_Avoid_: Forecast, model run, assumption set

**Comparison**:
The deterministic computation of deltas/metrics between two whole scenarios, with metrics applied as a filter on the output — never on the inputs.
_Avoid_: Diff, analysis

**Orchestrator**:
The custom Python service that owns the tool-calling loop and conversation state. It is the only component that calls the AIaaS chat model.
_Avoid_: Agent, router

**Tool**:
A registered, allowlisted capability the orchestrator can invoke (e.g. `compare_scenarios`, `search_knowledge_base`). Returns a structured result, never prose.
_Avoid_: Plugin, action

**AIaaS**:
The internal AI-as-a-Service platform hosting the chat (`Qwen/Qwen3.6-27B`) and embedding (`Qwen/Qwen3-Embedding-8B`) models, reached via the AIMart gateway with DevPod broker authentication.
_Avoid_: vLLM (implementation detail), LLM service

**Knowledge Base (KB)**:
The SharePoint-hosted economist content used only as grounding knowledge (definitions, methodology, assumptions) — never as a source of scenario numbers.
_Avoid_: RAG store, document store
