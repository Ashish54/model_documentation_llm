---
name: migrate-to-aiaas-auth
description: Align Python projects that use vLLM or other LLM authentication with the company-approved AIAAS authentication pattern.
---

# Migrate Python LLM Authentication to AIAAS

## Goal

Bring the current workspace or repository into compliance with the company-hosted AIAAS authentication standard.

The primary target is Python code using vLLM. Also identify any other LLM client, framework, wrapper, or direct HTTP integration that performs LLM authentication.

## Required AIAAS context

Before changing authentication, obtain the AIAAS implementation details from the user or repository documentation. Record and follow the provided information exactly:

```text
[AIAAS authentication context goes here]

Include, where applicable:
- approved Python package(s) and version constraints
- endpoint/base URL
- credential source and required environment-variable names
- token acquisition or refresh flow
- required headers, scopes, tenant/project identifiers, or TLS settings
- approved vLLM client configuration
- model naming or routing conventions
- test/mocking guidance
- migration examples and prohibited legacy patterns
```

If this context is absent, inspect the repository for internal AIAAS documentation or an existing approved implementation. If none is available, explain what information is needed and stop before modifying authentication code.

## Workflow

1. Inspect the repository to map all Python LLM usage, including vLLM clients, OpenAI-compatible clients, wrappers, LangChain/LiteLLM adapters, direct HTTP calls, configuration files, tests, fixtures, and dependency declarations.

2. Classify each integration:
   - **Recognized:** its authentication flow can be mapped confidently to the supplied AIAAS pattern.
   - **Unfamiliar or risky:** its purpose, authentication behavior, or migration path is unclear; it may affect production access, security, or non-LLM services.

3. For every unfamiliar or risky integration, present a migration plan and wait for approval before changing it. The plan must identify:
   - affected files and integration points
   - current authentication method
   - proposed AIAAS approach
   - compatibility, operational, and testing risks
   - any assumptions or missing information

4. For recognized integrations, implement the AIAAS authentication pattern consistently across production code and tests. Preserve existing non-authentication behavior unless a change is required for the migration.

5. Remove superseded LLM authentication mechanisms after all affected call paths use AIAAS. This includes obsolete credentials, auth helpers, environment-variable references, dependencies, configuration, fixtures, mocks, and documentation that would otherwise encourage the legacy approach.

6. Update tests so they validate the approved configuration without using real credentials or making unintended external calls. Add or revise focused tests for:
   - AIAAS client configuration
   - credential loading and missing-credential errors
   - the migrated vLLM call path
   - removal of legacy authentication assumptions

7. Run the repository’s relevant checks. Report the files changed, integrations migrated, legacy authentication removed, tests run, and any remaining decisions or blocked integrations.

## Guardrails

- Treat AIAAS credentials and tokens as secrets: never print, commit, hard-code, or place them in test fixtures.
- Use only the authentication details supplied as AIAAS context or found in approved internal repository documentation.
- Keep credentials configurable through the approved runtime mechanism.
- Do not silently substitute a different provider, endpoint, token format, or fallback authentication method.
- Do not remove an authentication path until its replacement is implemented and covered by relevant tests.
- Limit changes to LLM authentication, the code directly needed to support it, and its tests/configuration.