# Domain docs

This is a **single-context** repo. Domain documentation lives at:

- `CONTEXT.md` (repo root) — the domain glossary. Canonical terms for this project's concepts, with `_Avoid_` lists of terms not to use.
- `docs/adr/` — Architecture Decision Records, numbered sequentially (`0001-*.md`, `0002-*.md`, ...).

## Consumer rules

- Use the vocabulary from `CONTEXT.md` in specs, tickets, plans, and code discussion. When a term conflicts with what a user says, surface the conflict rather than silently picking one.
- Respect ADRs in the area being touched. An ADR is a settled decision; do not quietly re-litigate it. If a change would contradict an ADR, flag it explicitly and either propose superseding the ADR or adjust the change.
- `CONTEXT.md` is a glossary only — no implementation details, no specs, no decisions. Decisions belong in ADRs.
