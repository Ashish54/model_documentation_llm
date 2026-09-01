# Project Overview — modelkb

*For executives and stakeholders. Five minutes, no code.*

## The problem

The organization maintains **28 interconnected financial models** —
macroeconomics, Swiss and US housing, equity indices, policy rates, pension,
and interest-rate-risk. What we know about them lives in three places that
don't agree with each other:

* **PDF documentation** — authoritative, but scattered across SharePoint with
  **no usable version history**;
* **`model_info.json`** — describes how models connect, but may be stale;
* **a large Python model library** — the actual implementation, with years of
  Git history.

Today, answering "where does this assumption come from, which model consumes
it, and what changed since last quarter?" requires manual archaeology.
For governed financial models, that is an audit and model-risk problem.

## What we are building

A **governed knowledge base** that ingests all three sources and remembers
*everything, forever, with proof*:

* **Evidence first.** Every extracted fact — an assumption, a coefficient, an
  equation, a model-to-model dependency — links to the exact page, section,
  table, or equation in an immutable, fingerprinted copy of the source PDF.
* **Nothing is ever overwritten.** New document versions add to history; the
  old state can always be reconstructed and compared.
* **Conflicts are surfaced, not hidden.** When a PDF contradicts
  `model_info.json`, both statements are kept and marked; the PDF wins by
  rule, and the disagreement stays visible for review.
* **AI assists, but may not invent.** A controlled regional AI service helps
  read and structure the documents. Every AI action is logged with its inputs
  and outputs; every AI-extracted value must cite its evidence or be marked
  uncertain — humans review before anything becomes authoritative.

## What it is not (yet)

Not a chatbot, not a search service, not an auto-updating system. Those are
deliberately deferred: they become safe to build **on top of** a trustworthy
evidence layer, not before. The interfaces for retrieval, change detection,
approval workflows, and graph reasoning are already designed in.

## Where we are

**Foundation complete (3 of 8 milestones).** The pipeline already: archives
PDFs immutably; analyzes their structure deterministically; detects headings,
tables, equations, citations, and code references with quality reporting; and
uses AI to *propose* a corpus-wide extraction schema that humans review as a
versioned artifact. Next: schema-guided extraction of the actual model
knowledge (assumptions, variables, equations, relationships), then the
Python-library cross-reference, then reviewable knowledge documents.

## The payoff

* **Audit readiness**: every number in the knowledge base answers "show me"
  with a page and a paragraph.
* **Safe change**: when a new PDF lands, the system shows exactly what
  changed and preserves what was true before.
* **Connected understanding**: the model dependency graph — which model feeds
  which — becomes queryable, conflict-aware, and backed by evidence.
