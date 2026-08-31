# Model Docs Wiki — Pilot Runbook

Compile 28 model-documentation PDFs (~150 pages each) into an interlinked,
citation-traceable markdown knowledge base that an LLM queries through
llmwiki (`query` / `context` / MCP), powered by a company-hosted Qwen endpoint.

## Architecture at a glance

```text
PDFs ──split──▶ sources/*.md ──llmwiki compile──▶ wiki/concepts/   (automatic KB)
                                                  wiki/models/ …   (typed layer, you/agent)
                                                                        ▲
                                        .llmwiki/profile.json (modeldocs) enforces
                                        entities, relations, lifecycle gates

LLM fetches info:  llmwiki query │ llmwiki context --json │ llmwiki serve (MCP)
```

Two ground rules discovered while studying the compiler (they shape this runbook):

1. **Every ingested source is hard-truncated at 100,000 chars.** A 150-page PDF
   is 400k–700k chars of text — never ingest a whole PDF directly. Always split
   first (`tools/split-pdf.mjs`), which is why that tool exists.
2. **Concept extraction asks for 3–8 concepts per source.** Chapter-sized parts
   (~60k chars) yield a rich, fine-grained wiki; whole PDFs would yield a
   handful of shallow pages each.

## One-time setup

```bash
cd ~/Desktop/model-docs-wiki

# 1. Provider credentials → company-hosted Qwen (OpenAI-compatible)
cp .env.example .env   # then fill in OPENAI_BASE_URL, OPENAI_API_KEY, LLMWIKI_MODEL

# 2. Tooling for the PDF splitter
npm install

# 3. Convenience alias to the locally built CLI (or `npm i -g llm-wiki-compiler`)
alias llmwiki="node /Users/ashish/llm-wiki-compiler/llm-wiki-compiler/dist/cli.js"

# 4. Sanity-check the domain profile
llmwiki profile validate    # → "Profile 'modeldocs' is valid"
```

## Pilot: 1–2 PDFs, end to end

```bash
# 1. Split one PDF into page-range parts (staging dir, NOT sources/)
node tools/split-pdf.mjs /path/to/model-a.pdf --out-dir staging
#    → staging/model-a_part-1_pages-0001-0018.md … (~8 parts for 150 pages)
#    ⚠ watch for "extracted no text" warnings → those pages are scans; see Troubleshooting

# 2. Spot-check one part: page markers present? tables readable? formulas intact?
head -60 staging/model-a_part-1_*.md

# 3. Ingest the parts (adds provenance frontmatter, journals, dedups)
for f in staging/model-a_*.md; do llmwiki ingest "$f"; done

# 4. Compile: extraction (1 LLM call/source) + page generation (1 call/concept)
llmwiki compile                 # add --concurrency 2 if the endpoint is small

# 5. Inspect the result
llmwiki status
llmwiki view --open             # browser UI: search, graph, citations
llmwiki lint

# 6. Query it the way the consuming LLM will
llmwiki query "What are the key assumptions of model A?"
llmwiki context "compare model A's validation methodology" --json

# 7. Measure quality
llmwiki eval --suite fast
```

Judge the pilot on: Are concept pages granular enough? Are citations usable
(`[page N]` markers map back to the PDF)? Does query return the right pages?
If pages are too coarse, re-split with a smaller `--max-chars` (e.g. 40000);
too fine/duplicative, raise it.

## The typed layer (profile)

`llmwiki compile` always writes `wiki/concepts/`. The `modeldocs` profile adds a
structured registry on top, written via typed surfaces (MCP tools or the SDK —
run `llmwiki serve` and let your agent create pages):

| Entity | Directory | Lifecycle gate worth knowing |
|---|---|---|
| `models` | `wiki/models/` | `validated` requires ≥1 passed `validated-by` relation |
| `methodologies` | `wiki/methodologies/` | — |
| `assumptions` | `wiki/assumptions/` | `confirmed` requires a `rationale` |
| `formulas` | `wiki/formulas/` | — |
| `datasets` | `wiki/datasets/` | — |
| `validations` | `wiki/validations/` | any verdict requires `findingsSummary` + `validator` |
| `limitations` | `wiki/limitations/` | `mitigated` requires a `mitigation` |

Relations: `uses-methodology`, `relies-on-assumption`, `defined-by-formula`,
`consumes-data`, `validated-by`, `has-limitation`. The `model-onboarding`
workflow sequences draft → link-evidence → approve, with the approve stage
trust-gated (`LLMWIKI_TRUSTED_WRITE`).

Invalid writes fail closed — a model page cannot enter `validated` without a
passing validation linked, no matter which surface writes it.

## Scaling to all 28 PDFs

- ~8 parts per PDF → ~224 sources total. Split them all into `staging/` first.
- Compile is incremental: unchanged sources never re-hit the LLM, so you can
  ingest in batches and re-run `llmwiki compile` freely.
- Rough LLM cost per full compile: ~224 extraction calls + one page call per
  concept (~3–8 per source ⇒ ~700–1,800 pages). Size your endpoint's
  concurrency accordingly (`LLMWIKI_COMPILE_CONCURRENCY`).
- Embeddings: batch-computed after page generation; content-hash-aware, so
  recompiles only embed changed pages.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Compile fails on first extraction call | Qwen deployment lacks tool-call support | Use an Instruct/Tool-capable model; extraction uses a tool call |
| `context length exceeded` | Part too big for the model window | Re-split with smaller `--max-chars`; lower `LLMWIKI_PROMPT_BUDGET_CHARS` |
| `…truncated…` warning in compile | Concept's combined sources over budget | Expected on merged concepts; raise budget only if the window allows |
| `extracted no text` from splitter | Scanned/image pages | OCR those pages first (no OCR in this toolchain yet) |
| Query warns about lexical fallback | No embedding endpoint | Works fine; add `LLMWIKI_EMBEDDING_MODEL` when one is available |
| Requests time out | Slow endpoint | `LLMWIKI_REQUEST_TIMEOUT_MS=1800000` |
| Want to drop a bad source | — | `llmwiki rm <source-file> --dry-run`, then without the flag |
