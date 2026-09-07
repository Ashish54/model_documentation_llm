"""Unit tests per tool (plan Verification 1): JSON Schema conformance and
ToolResult contract, with upstream calls mocked/faked at the seam."""

import pytest

from tools import (
    CompareScenariosTool,
    GetScenarioDataTool,
    ListScenariosTool,
    SearchKnowledgeBaseTool,
)
from tools.base import ToolResult, validate_args
from tools.scenario_api import ScenarioAPIError


class FakeScenarioAPI:
    def __init__(self, scenarios=None, fail=False):
        self._scenarios = scenarios or []
        self._fail = fail
        self.calls = []

    async def list_scenarios(self, obo_token):
        self.calls.append(("list", obo_token))
        if self._fail:
            raise ScenarioAPIError("upstream 500")
        return self._scenarios

    async def get_scenario(self, scenario_id, obo_token):
        self.calls.append(("get", scenario_id, obo_token))
        if self._fail:
            raise ScenarioAPIError("upstream 500")
        for s in self._scenarios:
            if s["id"] == scenario_id:
                return s
        raise ScenarioAPIError(f"unknown scenario: {scenario_id}")


SCENARIOS = [
    {"id": "scn-a", "name": "Baseline FY26", "version": "1.2"},
    {"id": "scn-b", "name": "Downside FY26", "version": "1.0"},
]


def all_tools():
    api = FakeScenarioAPI(SCENARIOS)
    return [
        ListScenariosTool(api),
        GetScenarioDataTool(api),
        CompareScenariosTool(compare_fn=lambda a, b: {"metrics": {}}),
    ]


# --- Schema conformance (contract shared by every registered tool) ---

@pytest.mark.parametrize("tool", all_tools(), ids=lambda t: t.name)
def test_tool_declares_valid_openai_schema(tool):
    schema = tool.openai_schema()
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == tool.name
    assert fn["description"]
    params = fn["parameters"]
    assert params["type"] == "object"
    for required_arg in params.get("required", []):
        assert required_arg in params["properties"]


@pytest.mark.parametrize("tool", all_tools(), ids=lambda t: t.name)
def test_tool_result_shape(tool):
    result = ToolResult.ok({"x": 1}).to_dict()
    assert set(result) == {"status", "data", "error"}
    assert result["status"] == "ok"


def test_validate_args_reports_missing_required():
    schema = GetScenarioDataTool.args_schema
    assert validate_args(schema, {}) == "missing required argument: scenario_id"
    assert validate_args(schema, {"scenario_id": "scn-a"}) is None


def test_validate_args_rejects_wrong_type_and_unknown_args():
    schema = CompareScenariosTool.args_schema
    assert "must be of type" in validate_args(
        schema, {"scenario_a": 1, "scenario_b": "b"}
    )
    assert validate_args(
        schema, {"scenario_a": "a", "scenario_b": "b", "extra": 1}
    ) == "unexpected argument: extra"


# --- list_scenarios ---

async def test_list_scenarios_returns_live_api_data(context):
    tool = ListScenariosTool(FakeScenarioAPI(SCENARIOS))
    result = await tool.call({}, context)
    assert result.status == "ok"
    assert result.data["scenarios"] == SCENARIOS


async def test_list_scenarios_passes_obo_token(context):
    api = FakeScenarioAPI(SCENARIOS)
    await ListScenariosTool(api).call({}, context)
    assert api.calls == [("list", "obo-token-xyz")]


async def test_list_scenarios_upstream_failure_is_structured_error(context):
    tool = ListScenariosTool(FakeScenarioAPI(fail=True))
    result = await tool.call({}, context)
    assert result.status == "error"
    assert result.error


# --- get_scenario_data ---

async def test_get_scenario_data_returns_one_scenario(context):
    tool = GetScenarioDataTool(FakeScenarioAPI(SCENARIOS))
    result = await tool.call({"scenario_id": "scn-b"}, context)
    assert result.status == "ok"
    assert result.data["scenario"]["name"] == "Downside FY26"


async def test_get_scenario_data_unknown_id_is_error(context):
    tool = GetScenarioDataTool(FakeScenarioAPI(SCENARIOS))
    result = await tool.call({"scenario_id": "nope"}, context)
    assert result.status == "error"
    assert "nope" in result.error


async def test_get_scenario_data_missing_arg_is_error(context):
    tool = GetScenarioDataTool(FakeScenarioAPI(SCENARIOS))
    result = await tool.call({}, context)
    assert result.status == "error"


# --- compare_scenarios ---

def make_compare_fn():
    calls = []

    def compare(a, b):
        calls.append((a, b))
        return {
            "scenario_a": a,
            "scenario_b": b,
            "workflow_version": "3.1.0",
            "metrics": {
                "gdp_growth_fy26": {"delta_pp": -0.4},
                "cpi_fy26": {"delta_pp": 0.2},
            },
        }

    compare.calls = calls
    return compare


async def test_compare_scenarios_wraps_existing_workflow(context):
    compare = make_compare_fn()
    tool = CompareScenariosTool(compare_fn=compare)
    result = await tool.call({"scenario_a": "scn-a", "scenario_b": "scn-b"}, context)
    assert result.status == "ok"
    assert compare.calls == [("scn-a", "scn-b")]
    assert result.data["workflow_version"] == "3.1.0"
    assert result.data["metrics"]["gdp_growth_fy26"]["delta_pp"] == -0.4


async def test_compare_scenarios_metrics_filter_is_output_only(context):
    compare = make_compare_fn()
    tool = CompareScenariosTool(compare_fn=compare)
    result = await tool.call(
        {"scenario_a": "scn-a", "scenario_b": "scn-b", "metrics": ["cpi_fy26"]},
        context,
    )
    assert result.status == "ok"
    # The workflow still received only the two scenario IDs (filter is on output).
    assert compare.calls == [("scn-a", "scn-b")]
    assert list(result.data["metrics"]) == ["cpi_fy26"]


async def test_compare_scenarios_rejects_same_scenario(context):
    tool = CompareScenariosTool(compare_fn=make_compare_fn())
    result = await tool.call({"scenario_a": "scn-a", "scenario_b": "scn-a"}, context)
    assert result.status == "error"


async def test_compare_scenarios_workflow_failure_is_structured_error(context):
    def boom(a, b):
        raise RuntimeError("model run missing")

    tool = CompareScenariosTool(compare_fn=boom)
    result = await tool.call({"scenario_a": "scn-a", "scenario_b": "scn-b"}, context)
    assert result.status == "error"
    assert "model run missing" in result.error


# --- search_knowledge_base ---

class FakeEmbedder:
    def __init__(self):
        self.queries = []

    async def embed_query(self, text):
        self.queries.append(text)
        return [1.0] + [0.0] * 1023


def make_chunk(doc_id, acl_groups, embedding, title="Doc", url="https://sp/doc"):
    from vector_store import Chunk

    return Chunk(
        doc_id=doc_id,
        chunk_index=0,
        content=f"content of {doc_id}",
        title=title,
        source_url=url,
        site="economics",
        acl_groups=frozenset(acl_groups),
    )


async def seed_store():
    from vector_store import InMemoryVectorStore

    store = InMemoryVectorStore()
    chunks = [
        make_chunk("doc-public", ["grp-all-staff"], [1.0] + [0.0] * 1023),
        make_chunk("doc-secret", ["grp-leadership"], [1.0] + [0.0] * 1023),
    ]
    await store.upsert_chunks(chunks, [[1.0] + [0.0] * 1023] * 2)
    return store


async def test_search_returns_passages_with_citations(context):
    from vector_store import InMemoryVectorStore

    store = await seed_store()
    tool = SearchKnowledgeBaseTool(FakeEmbedder(), store)
    result = await tool.call({"query": "gdp methodology"}, context)
    assert result.status == "ok"
    passages = result.data["passages"]
    assert passages, "expected at least one passage"
    for p in passages:
        assert p["citation"]["title"]
        assert p["citation"]["source_url"].startswith("https://")


async def test_search_applies_acl_security_filter(context):
    """Plan Verification 4: a user without SharePoint access to a source doc
    must not see its chunks in results."""
    store = await seed_store()
    tool = SearchKnowledgeBaseTool(FakeEmbedder(), store)
    # context has grp-economists + grp-all-staff but NOT grp-leadership.
    result = await tool.call({"query": "anything", "top_k": 10}, context)
    assert result.status == "ok"
    contents = [p["content"] for p in result.data["passages"]]
    assert "content of doc-public" in contents
    assert "content of doc-secret" not in contents


async def test_search_top_k_bounds(context):
    store = await seed_store()
    tool = SearchKnowledgeBaseTool(FakeEmbedder(), store)
    assert (await tool.call({"query": "q", "top_k": 0}, context)).status == "error"
    assert (await tool.call({"query": "q", "top_k": 21}, context)).status == "error"


async def test_search_embeds_query_with_query_prefix(context):
    from ingestion.embedder import Embedder

    class RecordingClient:
        async def embed(self, texts, *, model):
            self.texts, self.model = texts, model
            return [[0.5] * 1024 for _ in texts]

    client = RecordingClient()
    embedder = Embedder(client, model="Qwen/Qwen3-Embedding-8B")
    tool = SearchKnowledgeBaseTool(embedder, await seed_store())
    await tool.call({"query": "  gdp   methodology "}, context)
    assert client.texts == ["query: gdp methodology"]
    assert client.model == "Qwen/Qwen3-Embedding-8B"
