# modelkb Documentation

Start here. The root [`README.md`](../README.md) holds the full technical
README (architecture, setup, end-to-end runbook, layout); this directory adds
audience-specific documents.

## What this project is (60 seconds)

modelkb ingests 28 interconnected financial-model documentation PDFs, a
`model_info.json` connection file, and a monolithic Python model library into
a **governed, evidence-first knowledge base**: every fact traces to an exact
page/section/table/equation in an immutable source, every version is
preserved, and PDFs outrank secondary sources when they disagree. PostgreSQL
stores the data and the relationship graph; Markdown/YAML artifacts make the
knowledge reviewable by humans. It is the trustworthy foundation for later
retrieval, graph reasoning, and quantitative execution — deliberately **not**
a chatbot.

## Documents

| Document | Audience | Read when |
|---|---|---|
| [`project_overview.md`](project_overview.md) | executives, stakeholders | you need the why and the value, not the code |
| [`architecture.md`](architecture.md) | engineers, architects | you need the system shape and data flow |
| [`implementation_plan.md`](implementation_plan.md) | coding agents, developers | you are building milestones 4–8 |
| [`Copilot_instructions.md`](Copilot_instructions.md) | coding agents | you are editing this repo (invariants + gotchas) |
| [`packages.md`](packages.md) | developers, agents | you are recreating or auditing `pyproject.toml` |
| [`../README.md`](../README.md) | developers | setup, runbook, quality gates |
| [`../adrs/`](../adrs/) | engineers | you wonder *why* a decision was made |

## Status snapshot

Milestones 1–3 of 8 complete: project skeleton + 31-table database + immutable
archive; deterministic PDF extraction + corpus discovery; LLM schema-proposal
workflow with full audit. Next: schema-guided semantic extraction
(milestone 4). Details in [`implementation_plan.md`](implementation_plan.md).

## Quick commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/kb db-init
.venv/bin/kb discover-corpus --input var/input
.venv/bin/kb report
.venv/bin/python -m pytest tests/     # quality gates: pytest, ruff, mypy
```
