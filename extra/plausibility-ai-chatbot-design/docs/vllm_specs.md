# Qwen3.6-27B LLM Integration Guide

> **Purpose:** This document captures the LLM/model information shown in the supplied AIMart model-catalog screenshots so that a coding agent can use it to integrate with the model.
>
> **Source:** AIMart model catalog / model page screenshots supplied with this task. Values below are transcribed from those screenshots and should be treated as the source of truth for this handoff.

## 1. Model Identity

| Field | Value |
|---|---|
| Model name | `Qwen3.6-27B` |
| Model identifier used by API example | `Qwen/Qwen3.6-27B` |
| Model type | Open Weight |
| Description | Large-scale, general-purpose language model with advanced reasoning, tool calling, and multimodal capabilities |
| Parameters | 27B |
| Architecture family | Causal Language Model with Vision Encoder |
| Training stage | Pre-training + post-training |
| Availability | General availability |
| Retirement date | N/A |
| Hosting region | `westeurope` |
| GPU type | H100 |
| Quantization | BF16 |
| Copyright indemnity | No |

## 2. Modalities and Capabilities

### Modalities

- Text
- Vision
- Video

### Listed capabilities

- Reasoning
- Chat
- Completions
- Responses API
- Function calling / tool calling
- JSON mode
- Streaming
- Multimodal workflows

The model page specifically describes:

- **Function Calling:** structured function invocation with arguments.
- **Structured Outputs:** schema-aligned outputs for reliable parsing.
- **Tool Endpoints:** dedicated tool endpoints exposed by the model deployment.

## 3. Context and Output Limits

| Setting | Value |
|---|---:|
| Context window | `262,144` tokens |
| Extended context | N/A |
| Maximum output | Up to `8K` tokens |

### Important limitation

The model page states that large contexts (`262K+`) are supported, but **cost and latency grow quickly**.

For coding agents, avoid sending the entire repository or unnecessarily large histories on every request. Prefer targeted file/context retrieval and incremental conversations.

## 4. Reliability

The model catalog states:

> High performance; verify in high-stakes or fast-changing contexts.

Do not treat model output as authoritative for high-stakes decisions or rapidly changing information.

## 5. Developer Experience

### SDK / client support shown

- Python
- JavaScript
- cURL
- OpenAI-compatible clients

The supplied API example uses the OpenAI Python client against the AIMart gateway.

### Prompting guidance from the model page

1. Be clear and moderately structured, but avoid over-constraining.
2. Use role/context framing to guide reasoning and depth.
3. Add examples only when consistency or format matters.

For coding-agent prompts, this suggests providing explicit task context, constraints, relevant files, and expected output format without unnecessarily micromanaging the reasoning.

---

# 6. API Connection

## Endpoint

The supplied Python example configures the OpenAI-compatible client with:

```text
https://gateway.aimart-apim-prod.azpriv-cloud.ubs.net/aiaas/v1
```

The API is accessed through the AIMart gateway.

## Authentication

The screenshots show **DevPod broker authentication** for obtaining a token before calling the AIMart gateway.

The broker URL shown is:

```text
https://aiaas-broker.uk8s-tsshared-weu-gt021-ext-p001.azpriv-cloud.ubs.net/
```

The authentication flow shown is:

1. Create an `AzureAuthClient`.
2. Use `AuthMode.DEVPOD`.
3. Enable automatic token refresh.
4. Call `authenticate_broker()`.
5. Read `.access_token`.
6. Pass that token as `api_key` to the OpenAI-compatible client.

The screenshot notes:

> The broker handles the Azure AD OAuth flow externally.

---

# 7. Python Integration Example

The following reproduces the integration pattern shown in the supplied model page:

```python
import httpx
from openai import OpenAI
from aiaas_auth import AuthMode, AzureAuthClient

# DevPod authentication note:
# The broker handles the Azure AD OAuth flow externally.
BROKER_URL = "https://aiaas-broker.uk8s-tsshared-weu-gt021-ext-p001.azpriv-cloud.ubs.net/"

auth = AzureAuthClient(
    broker_url=BROKER_URL,
    mode=AuthMode.DEVPOD,
    auto_refresh=True,
)

token_data = auth.authenticate_broker().access_token

client = OpenAI(
    base_url="https://gateway.aimart-apim-prod.azpriv-cloud.ubs.net/aiaas/v1",
    api_key=token_data,
    http_client=httpx.Client(verify=False),
)

completion = client.chat.completions.create(
    model="Qwen/Qwen3.6-27B",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello! Give me one sentence about AIAAS."},
    ],
    max_tokens=300,
)

print(completion.choices[0].message.content)
print("Token usage:", completion.usage)
```

## Security note about TLS verification

The supplied example explicitly uses:

```python
httpx.Client(verify=False)
```

This disables TLS certificate verification. A coding agent **should not blindly copy this setting into production**. If the environment has an internal CA/certificate requirement, configure the appropriate trusted CA/certificate instead. Only retain `verify=False` when it is explicitly required and approved for the target environment.

---

# 8. Minimal Integration Recipe for a Coding Agent

A coding agent connecting to this model should follow this sequence:

```text
1. Obtain an Azure/DevPod-authenticated access token through aiaas_auth.
2. Create an OpenAI-compatible client.
3. Set the AIMart gateway as base_url.
4. Pass the broker access token as api_key.
5. Use model = "Qwen/Qwen3.6-27B".
6. Call the desired OpenAI-compatible API operation.
7. Capture response text and token usage.
8. Handle authentication refresh, rate limits, latency, and request failures.
```

Conceptually:

```python
auth -> AzureAuthClient -> broker -> access_token
                                |
                                v
                         OpenAI-compatible client
                                |
                                v
                     AIMart /aiaas/v1 gateway
                                |
                                v
                       Qwen/Qwen3.6-27B
```

---

# 9. Suggested Agent Configuration

A coding agent can represent the model connection using configuration similar to:

```yaml
llm:
  provider: aimart
  model: Qwen/Qwen3.6-27B
  base_url: https://gateway.aimart-apim-prod.azpriv-cloud.ubs.net/aiaas/v1

authentication:
  method: devpod_broker
  broker_url: https://aiaas-broker.uk8s-tsshared-weu-gt021-ext-p001.azpriv-cloud.ubs.net/
  mode: DEVPOD
  auto_refresh: true

limits:
  context_window_tokens: 262144
  max_output_tokens: 8192

capabilities:
  reasoning: true
  tool_calling: true
  function_calling: true
  structured_outputs: true
  json_mode: true
  streaming: true
  vision: true
  video: true
```

> The YAML above is a normalized representation for agent configuration. The screenshots do not specify that this exact YAML schema is supported by AIMart.

---

# 10. Recommended Use Cases

The model page explicitly recommends:

- General-purpose chat
- Reasoning-heavy workflows
- Agentic coding
- Tool-augmented assistants
- Vision + text analysis

For coding agents, the strongest directly indicated use case is **agentic coding**, with tool calling/function calling and structured outputs available for reliable machine-readable workflows.

---

# 11. Tool / Function Calling

The model page indicates support for:

```text
Function Calling
Structured function invocation with arguments.
```

It also lists:

- Structured outputs
- Tool endpoints
- JSON mode
- Streaming

A coding agent can therefore be designed around a tool loop:

```text
User task
   |
   v
LLM reasoning
   |
   +-----> tool/function call
   |             |
   |             v
   |        execute tool
   |             |
   |             v
   +<------ tool result
   |
   v
final response
```

When implementing tools, keep function schemas explicit and validate returned arguments before executing side effects.

---

# 12. Performance and Capacity

## Catalog-level cost information

The model overview shows estimated token pricing of:

| Metric | Cost (USD / 1M tokens) |
|---|---:|
| Input | `0.032` |
| Output | `0.216` |

The catalog also displays a blended cost of:

```text
$0.247 / 1M tokens
```

Last pricing update shown:

```text
24 Jul 2026
```

## Benchmark / capacity information

The screenshots show:

| Metric | Value |
|---|---:|
| Max APIM RPS | `15` |
| Minimum success rate | `0.95` |
| P95 latency SLO | `45s` |

### Scenario benchmark table

| Scenario | Input cost / 1M | Output cost / 1M | Blended cost / 1M | Max request latency | Max concurrency | Input tokens/sec | Output tokens/sec | Input vs output throughput ratio |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Chat | `0.114` | `0.228` | `0.342` | `45.0s` | `64` | `3,061.47/s` | `1,505.34/s` | `2.034` |
| Small prompt | `0.004` | `0.183` | `0.187` | `45.0s` | `100` | `8,188.2/s` | `182.61/s` | `44.84` |

### Important pricing note

The catalog contains both general model pricing (`0.032` input / `0.216` output and `0.247` blended) and scenario benchmark pricing (shown above). Do not assume these numbers mean the same thing. For billing decisions, use the applicable AIMart consumption/pricing source for the actual deployment and plan.

---

# 13. Traffic Governance

The model catalog states that:

> Service-level traffic governance parameters (including request rate controls and token throughput limits) are centrally maintained in Consumption Plans & Capacity Limits.

Therefore, an agent should not hard-code the displayed benchmark concurrency/RPS values as universal production limits. Treat them as benchmark/catalog information and obtain the applicable consumption-plan limits for the deployment.

Recommended client behavior:

- Implement retries with backoff for transient failures.
- Respect HTTP/API rate-limit responses.
- Avoid uncontrolled parallel request fan-out.
- Bound concurrency.
- Track token usage.
- Keep prompts/context as small as practical.
- Set request timeouts appropriate to the displayed `45s` latency target.

---

# 14. Coding-Agent Implementation Checklist

## Connection

- [ ] Use the internal AIMart gateway.
- [ ] Use `Qwen/Qwen3.6-27B` as the model identifier.
- [ ] Authenticate through the DevPod broker shown in the model example.
- [ ] Use automatic token refresh.
- [ ] Use an OpenAI-compatible client/API.

## Request handling

- [ ] Support chat/completions as required by the client framework.
- [ ] Support streaming if the agent framework benefits from incremental output.
- [ ] Support tool/function calls.
- [ ] Validate structured/JSON outputs before consuming them.
- [ ] Capture token usage from responses where available.
- [ ] Implement retries and bounded concurrency.

## Context management

- [ ] Maximum context shown: `262,144` tokens.
- [ ] Maximum output shown: `8K` tokens.
- [ ] Do not assume that using the full context is cheap or low-latency.
- [ ] Retrieve only relevant repository files/context for coding tasks.

## Multimodal

- [ ] Text supported.
- [ ] Vision supported.
- [ ] Video supported.
- [ ] Verify the exact request schema supported by the gateway/client before sending multimodal payloads.

## Reliability

- [ ] Treat high-stakes or rapidly changing answers as requiring verification.
- [ ] Do not rely on the model as the sole source of truth for external facts.
- [ ] Add deterministic validation around tool calls and code changes.

## Security

- [ ] Do not hard-code long-lived credentials.
- [ ] Use the broker/token mechanism shown by the platform.
- [ ] Avoid `verify=False` unless explicitly required by the environment.
- [ ] Keep internal gateway/broker configuration out of public logs.
- [ ] Never log access tokens.

---

# 15. Agent Prompting Baseline

Based on the model-page prompting guidance, a reasonable baseline system instruction for a coding agent is:

```text
You are a coding agent.

Be clear and moderately structured in your responses.
Use the provided repository, task, and tool context to guide your reasoning.
Use tools when they are available and appropriate.
Return structured output when a schema is provided.
Do not invent repository facts. Inspect the relevant files before making
claims about the codebase.
When making changes, keep the scope focused on the requested task.
```

This is an agent-side prompt recommendation, not a prompt supplied verbatim by the model catalog.

---

# 16. Known Limitations / Caveats

From the supplied model page:

- Large contexts are supported, but **cost and latency grow quickly**.
- High-stakes or fast-changing contexts should be verified.
- Copyright indemnity is listed as **No**.
- Extended context is listed as **N/A**.
- The catalog does not show a retirement date.
- The displayed benchmark/cost figures should not automatically be interpreted as universal deployment limits or billing rates.
- Exact multimodal payload formats are not shown in the supplied screenshots.

---

# 17. Quick Reference

```text
MODEL
Qwen/Qwen3.6-27B

TYPE
Open Weight

MODALITY
Text + Vision + Video

CONTEXT
262,144 tokens

MAX OUTPUT
Up to 8K tokens

QUANTIZATION
BF16

GPU
H100

REGION
westeurope

API STYLE
OpenAI-compatible

GATEWAY
https://gateway.aimart-apim-prod.azpriv-cloud.ubs.net/aiaas/v1

AUTH
DevPod broker + AzureAuthClient

BROKER
https://aiaas-broker.uk8s-tsshared-weu-gt021-ext-p001.azpriv-cloud.ubs.net/

PYTHON CLIENT
openai + httpx + aiaas_auth

CAPABILITIES
Reasoning
Chat
Completions
Responses API
Function/tool calling
Structured outputs
JSON mode
Streaming
Vision
Video

RECOMMENDED
General-purpose chat
Reasoning-heavy workflows
Agentic coding
Tool-augmented assistants
Vision + text analysis

CATALOG INPUT PRICE
$0.032 / 1M tokens

CATALOG OUTPUT PRICE
$0.216 / 1M tokens

CATALOG BLENDED PRICE
$0.247 / 1M tokens

MAX APIM RPS
15

MIN SUCCESS RATE
0.95

P95 LATENCY SLO
45s
```

## Source fidelity

This handoff intentionally preserves the information visible in the supplied screenshots. Where the screenshots do not specify an exact SDK version, API schema, multimodal payload format, or configuration schema, this document does **not** invent one.
