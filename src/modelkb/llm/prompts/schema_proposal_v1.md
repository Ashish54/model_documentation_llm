You are designing the canonical extraction schema for a governed financial-model
knowledge base. You receive a STRUCTURAL DISCOVERY REPORT for a corpus of model
documentation PDFs (headings, table shapes, equation labels, code references,
metadata candidates, relationship language samples — not full page text).

The corpus covers financial models: macroeconomics, Swiss and US housing,
equity indices, policy rates, pension, and interest-rate-risk. The models are
interconnected (outputs of one model are inputs to another).

Propose:

1. taxonomy — the model types you can identify from the evidence;
2. base_components — the canonical extraction components applied to EVERY
   document. You MUST keep these baseline component names (add fields, never
   drop them): document_metadata, model_identity, model_version, sections,
   claims, assumptions, variables, equations, coefficients, code_references,
   citations, relationships, evidence;
3. extensions — per-model-type additional components where the evidence shows
   specialised structure (e.g. housing_model → property_segments;
   interest_rate_risk_model → curve_specification, scenario_definition;
   pension_model → demographic_assumptions, benefit_rules) — only when
   supported by the discovery report;
4. section_mappings — canonical section names → the actual heading variants
   observed across documents (use the report's common_headings);
5. relationship_types — relationship predicates the corpus needs. Start from:
   depends_on, provides_input_to, produces, consumes, implemented_by,
   documented_by, calibrated_by, uses_assumption, affects, supersedes,
   contradicts — add only if the evidence demands it;
6. confidence_rules — when extractors should return null, mark
   inferred_from_text vs explicit, or route to manual review;
7. manual_review_cases — ambiguity patterns you expect to require humans.

Rules:
- Base every proposal on the discovery report. Do NOT invent document
  structure that is not evidenced there.
- Every component field needs a name and dtype
  (string|number|integer|date|boolean|enum|array|object); mark required only
  when truly universal.
- Every substantive extraction will later need evidence locators — design
  components so fields can carry evidence IDs.
