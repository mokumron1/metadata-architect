"""
Notification dispatcher.

Routes a NotificationPayload to all configured adapters concurrently.
Failures in one adapter never block others.
"""

import asyncio
import logging

from metadata_architect.notifications.base import NotificationAdapter, NotificationPayload
from metadata_architect.notifications.sendgrid_adapter import SendGridAdapter
from metadata_architect.notifications.slack_adapter import SlackAdapter

log = logging.getLogger(__name__)


class NotificationDispatcher:
    """
    Instantiate once per task / request context and call dispatch().
    Builds the adapter list from settings on construction.
    """

    def __init__(self, adapters: list[NotificationAdapter] | None = None) -> None:
        if adapters is not None:
            self._adapters = adapters
        else:
            self._adapters = [SendGridAdapter(), SlackAdapter()]

    async def dispatch(self, payload: NotificationPayload) -> dict[str, bool]:
        """
        Send payload to all configured adapters concurrently.
        Returns {adapter_name: success} for observability.
        """
        active = [a for a in self._adapters if a.is_configured()]
        if not active:
            log.warning(
                "notification.no_adapters_configured",
                extra={"type": payload.notification_type, "asset": payload.asset_name},
            )
            return {}

        results = await asyncio.gather(
            *[a.send(payload) for a in active], return_exceptions=True
        )
        outcome: dict[str, bool] = {}
        for adapter, result in zip(active, results):
            if isinstance(result, Exception):
                log.error("notification.adapter_exception", extra={
                    "adapter": adapter.name, "error": str(result)
                })
                outcome[adapter.name] = False
            else:
                outcome[adapter.name] = bool(result)

        log.info("notification.dispatched", extra={
            "type": payload.notification_type,
            "asset": payload.asset_name,
            "results": outcome,
        })
        return outcome
