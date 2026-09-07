"""Microsoft Graph webhook handler (ARCHITECTURE §3.4.1).

Graph requires a validation handshake (echo the `validationToken` query
param) when the subscription is created, then POSTs change notifications.
Webhooks can miss events, so notifications only trigger a delta-sync run for
the affected site — the delta query remains the source of truth.

A renewal timer must re-subscribe before expiry (max ~30 days for drives);
that scheduling lives with the deployment, not here.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Mapping, Sequence

logger = logging.getLogger(__name__)

# callback(site_id) -> awaitable; typically DeltaSync.run_once
SyncTrigger = Callable[[str], Awaitable[Any]]


def parse_site_id(resource: str) -> str:
    """Extract the site ID from a Graph resource path like
    `/sites/{site-id}/drive/root`."""
    parts = [p for p in resource.split("/") if p]
    if len(parts) >= 2 and parts[0] == "sites":
        return parts[1]
    raise ValueError(f"unrecognized Graph resource path: {resource}")


class WebhookHandler:
    def __init__(self, trigger_sync: SyncTrigger, *, validation_token: str | None = None) -> None:
        self._trigger_sync = trigger_sync
        self._expected_client_state = validation_token

    def handle_validation(self, validation_token: str) -> tuple[int, str]:
        """Subscription-creation handshake: echo the token as text/plain."""
        return 200, validation_token

    async def handle_notification(
        self, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        notifications: Sequence[Mapping[str, Any]] = payload.get("value", [])
        triggered: list[str] = []
        for notification in notifications:
            if (
                self._expected_client_state is not None
                and notification.get("clientState") != self._expected_client_state
            ):
                logger.warning("webhook clientState mismatch; dropping notification")
                continue
            try:
                site_id = parse_site_id(notification.get("resource", ""))
            except ValueError:
                logger.warning("webhook with unparseable resource; dropping")
                continue
            await self._trigger_sync(site_id)
            triggered.append(site_id)
        return {"accepted": len(triggered), "sites": triggered}
