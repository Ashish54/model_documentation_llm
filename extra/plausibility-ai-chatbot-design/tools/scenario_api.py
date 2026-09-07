"""Client seam for the internal scenario APIs (owned by the economist/data team).

The exact API contracts (auth method, request/response schema) are an open
decision (ARCHITECTURE §6). The tools depend on the ``ScenarioAPI`` protocol
below, not on a concrete HTTP client, so the confirmed contract can be wired
in without touching tool code. ``HttpScenarioAPIClient`` encodes the current
best-guess contract: OBO bearer token, JSON in/out.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, Sequence

import httpx


class ScenarioAPI(Protocol):
    """What the tools need from the internal scenario data platform."""

    async def list_scenarios(self, obo_token: Optional[str]) -> Sequence[dict[str, Any]]:
        """Return scenario summaries (id, name, version, ...)."""
        ...

    async def get_scenario(
        self, scenario_id: str, obo_token: Optional[str]
    ) -> dict[str, Any]:
        """Return the full precomputed output set for one scenario."""
        ...


class ScenarioAPIError(Exception):
    pass


class HttpScenarioAPIClient:
    """Best-guess HTTP implementation pending the confirmed contract (§6)."""

    def __init__(
        self,
        base_url: str,
        *,
        http_client: Optional[httpx.AsyncClient] = None,
        ca_bundle: Optional[str] = None,
        timeout_s: float = 30.0,
    ) -> None:
        if http_client is not None:
            self._client = http_client
        else:
            self._client = httpx.AsyncClient(
                base_url=base_url.rstrip("/"),
                timeout=httpx.Timeout(timeout_s),
                verify=ca_bundle or True,
            )

    def _headers(self, obo_token: Optional[str]) -> dict[str, str]:
        if not obo_token:
            raise ScenarioAPIError(
                "an on-behalf-of token is required to call the scenario API"
            )
        return {"Authorization": f"Bearer {obo_token}"}

    async def list_scenarios(self, obo_token: Optional[str]) -> Sequence[dict[str, Any]]:
        response = await self._client.get(
            "/scenarios", headers=self._headers(obo_token)
        )
        if response.status_code != 200:
            raise ScenarioAPIError(f"list_scenarios failed: {response.status_code}")
        return response.json()["scenarios"]

    async def get_scenario(
        self, scenario_id: str, obo_token: Optional[str]
    ) -> dict[str, Any]:
        response = await self._client.get(
            f"/scenarios/{scenario_id}", headers=self._headers(obo_token)
        )
        if response.status_code == 404:
            raise ScenarioAPIError(f"unknown scenario: {scenario_id}")
        if response.status_code != 200:
            raise ScenarioAPIError(f"get_scenario failed: {response.status_code}")
        return response.json()
