# Developer & Coding Agent Handover Document: AIaaS Embedding Model Integration (`Qwen/Qwen3-Embedding-8B`)

## 1. Overview & Model Profile

This document captures all technical details, specifications, authentication procedures, and usage guidelines for integrating the **Qwen3-Embedding-8B** embedding model hosted on UBS AIaaS (AI-as-a-Service) platform (`d4118.devcloud.ubs.net`).

### 1.1 Summary
* **Model Name:** `Qwen/Qwen3-Embedding-8B`
* **Provider / Host:** UBS-Hosted GZ-WEU (Western Europe)
* **Description:** High-quality text embedding model optimized for semantic representations, search, retrieval, and document clustering. Supports Matryoshka multi-resolution embeddings for flexible vector dimensionality based on performance vs. storage tradeoffs.
* **Modalities:** Text Input $ightarrow$ Embedding Vector Output
* **AI Output Compliance:** Adhere strictly to enterprise AI-Assisted Software Development Guidelines. Keep inputs clean, concise, and semantically focused.

---

## 2. Technical Specifications & Hosting Profile

| Property | Value / Specification | Notes |
| :--- | :--- | :--- |
| **Model ID** | `Qwen/Qwen3-Embedding-8B` | Used in OpenAI client `model` parameter |
| **Modality** | Text | Text-to-embedding vector |
| **Hosting Region** | `westeurope` (GZ-WEU) | UBS Internal Cloud Platform |
| **Availability** | General Availability (GA) | Long-term support |
| **Context Window** | **8,192 tokens** | Max input token length |
| **Embedding Dimensions** | Matryoshka (Multi-Resolution) | Dimension scalable depending on quality/storage requirements |
| **Quantization** | `BF16` (Bfloat16) | High precision vector fidelity |
| **GPU Hardware** | NVIDIA A10 | High-performance inference engine |
| **Copyright Indemnity** | No | |
| **Deprecation / Retirement Policy** | Minimum 6 months advance notice prior to deprecation with guaranteed migration path | N/A currently |

---

## 3. Reliability & Traffic Governance (SLOs & Benchmarks)

* **Reliability Notes:** High performance; verify in high-stakes or fast-changing context scenarios.
* **Service Governance:** Traffic governance parameters (request rate controls, token throughput limits) are centrally managed via *Consumption Plans & Capacity Limits*.
* **P95 Latency SLO:** **45 seconds**
* **Cost & Pricing:** Enterprise internal benchmark-based pricing (Coming soon).

---

## 4. Developer Experience & Integration Guide

### 4.1 Prerequisites & Dependencies
To interact with the AIaaS Gateway, install the required Python packages within your project environment:
```bash
pip install openai httpx
```
*Note: Ensure the internal UBS Python package `aiaas_auth` is available in your environment/DevPod setup.*

### 4.2 Gateway & Authentication Endpoints
* **DevPod Broker URL:** `https://aiaas-broker.uk8s-tsshared-weu-gt021-ext-p001.azpriv-cloud.ubs.net/`
* **AIaaS Gateway Base URL:** `https://gateway.aimart-apim-prod.azpriv-cloud.ubs.net/aiaas/v1`

---

## 5. Reference Python Implementation

Below is the production-ready code snippet to authenticate via DevPod broker and invoke the embedding model.

```python
import httpx
from openai import OpenAI
from aiaas_auth import AuthMode, AzureAuthClient

# 1. Target Endpoints Configuration
BROKER_URL = "https://aiaas-broker.uk8s-tsshared-weu-gt021-ext-p001.azpriv-cloud.ubs.net/"
GATEWAY_BASE_URL = "https://gateway.aimart-apim-prod.azpriv-cloud.ubs.net/aiaas/v1"
MODEL_ID = "Qwen/Qwen3-Embedding-8B"

# 2. Authenticate via DevPod Broker to obtain access token
auth = AzureAuthClient(broker_url=BROKER_URL, mode=AuthMode.DEVPOD, auto_refresh=True)
token_data = auth.authenticate_broker().access_token

# 3. Initialize OpenAI-compatible Client pointing to AIaaS Gateway
client = OpenAI(
    base_url=GATEWAY_BASE_URL,
    api_key=token_data,
    http_client=httpx.Client(verify=False), # Enterprise internal proxy / SSL handling
)

# 4. Generate Embeddings
response = client.embeddings.create(
    model=MODEL_ID,
    input="AIaaS provides enterprise AI model access."
)

# 5. Extract Embeddings & Output Usage Info
embedding_vector = response.data[0].embedding
print("Embedding snippet (first 10 dimensions):", embedding_vector[:10])
print("Token usage stats:", response.usage)
```

---

## 6. Prompting & Embedding Best Practices

1. **Keep Inputs Focused:** Keep text inputs clean, concise, and semantically focused. Remove unnecessary noise/formatting markup where possible.
2. **Consistent Normalization:** Apply consistent text normalization (casing, whitespace stripping) across both indexing documents and runtime queries before generating embeddings.
3. **Contextual Prefixing:** If required by specific downstream task scenarios, include task-specific context tags (e.g., distinguishing `"query:"` vs `"document:"`).
4. **Dimension Selection:** Leverage Matryoshka multi-resolution dimensions to balance vector search accuracy vs vector database index storage costs.

---

## 7. Operational & Platform Links
* **AIMART Model Page:** `aimart-aiaas-bd4118.devcloud.ubs.net/models/model-page.html?id=Qwen%2FQwen3-Embedding-8B`
* **Platform Services:** AIaaS / AIMART Platform
