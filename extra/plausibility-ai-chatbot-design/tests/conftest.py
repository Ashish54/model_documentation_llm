import pytest

from tools.base import ToolContext


@pytest.fixture
def context() -> ToolContext:
    return ToolContext(
        user_id="user-123",
        group_claims=frozenset({"grp-economists", "grp-all-staff"}),
        correlation_id="corr-abc",
        obo_token="obo-token-xyz",
    )
