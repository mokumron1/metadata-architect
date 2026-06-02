"""
External catalog push adapter.

Pushes approved metadata (asset name, SoI, TDK score, certified_at)
to DataHub and/or Collibra after SME approval.

Adapters are opt-in: they activate only when the relevant env vars are set.
Both adapters are fire-and-forget — failures are logged but never block
the approval workflow.

Configuration (.env):
  DATAHUB_GMS_URL=http://datahub-gms:8080        # DataHub Graph Metadata Service
  COLLIBRA_BASE_URL=https://your-tenant.collibra.com
  COLLIBRA_API_USER=service-account@company.com
  COLLIBRA_API_PASSWORD=secret
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

log = logging.getLogger(__name__)


@dataclass
class CatalogPayload:
    asset_name: str
    asset_uuid: str
    statement_of_intent: str
    tdk_score: float
    reading_level: str
    context_authority: str
    certified_at: str
    verification_status: str


class DataHubAdapter:
    """
    Pushes metadata to DataHub via the GMS REST API (v3 entity upsert).

    Uses the platform=metadata_architect, entity_type=dataset pattern
    so the SoI appears as a "description" on the dataset entity.
    """

    def __init__(self) -> None:
        import os
        self._url = os.getenv("DATAHUB_GMS_URL", "")
        self._enabled = bool(self._url)

    def is_enabled(self) -> bool:
        return self._enabled

    async def push(self, payload: CatalogPayload) -> bool:
        if not self._enabled:
            return False
        try:
            import httpx
            urn = f"urn:li:dataset:(urn:li:dataPlatform:postgres,{payload.asset_name},PROD)"
            body = {
                "proposal": {
                    "entityType": "dataset",
                    "entityUrn": urn,
                    "changeType": "UPSERT",
                    "aspectName": "datasetProperties",
                    "aspect": {
                        "value": _json_encode({
                            "description": payload.statement_of_intent,
                            "customProperties": {
                                "tdk_score": str(round(payload.tdk_score, 4)),
                                "reading_level": payload.reading_level,
                                "context_authority": payload.context_authority,
                                "certified_at": payload.certified_at,
                                "verification_status": payload.verification_status,
                                "metadata_architect_uuid": payload.asset_uuid,
                            },
                        }),
                        "contentType": "application/json",
                    },
                }
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self._url}/aspects?action=ingestProposal",
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
            log.info("datahub.push_ok asset=%s", payload.asset_name)
            return True
        except Exception as exc:
            log.warning("datahub.push_failed asset=%s err=%s", payload.asset_name, exc)
            return False


class CollibraAdapter:
    """
    Upserts an asset description in Collibra via the REST API v2.

    Looks up the asset by full name, then PATCHes the description attribute.
    """

    def __init__(self) -> None:
        import os
        self._base = os.getenv("COLLIBRA_BASE_URL", "").rstrip("/")
        self._user = os.getenv("COLLIBRA_API_USER", "")
        self._password = os.getenv("COLLIBRA_API_PASSWORD", "")
        self._enabled = bool(self._base and self._user and self._password)

    def is_enabled(self) -> bool:
        return self._enabled

    async def push(self, payload: CatalogPayload) -> bool:
        if not self._enabled:
            return False
        try:
            import httpx
            auth = (self._user, self._password)
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Find asset by name
                search = await client.get(
                    f"{self._base}/rest/2.0/assets",
                    params={"name": payload.asset_name, "nameMatchMode": "EXACT", "limit": 1},
                    auth=auth,
                )
                search.raise_for_status()
                items = search.json().get("results", [])
                if not items:
                    log.warning("collibra.asset_not_found asset=%s", payload.asset_name)
                    return False

                asset_id = items[0]["id"]

                # Patch description attribute (type ID 00000000-0000-0000-0001-000400000002)
                patch_body = [{
                    "assetId": asset_id,
                    "typeId": "00000000-0000-0000-0001-000400000002",
                    "value": (
                        f"{payload.statement_of_intent}\n\n"
                        f"TDK Score: {round(payload.tdk_score, 4)} | "
                        f"Certified: {payload.certified_at} | "
                        f"Authority: {payload.context_authority}"
                    ),
                }]
                patch = await client.patch(
                    f"{self._base}/rest/2.0/attributes",
                    json=patch_body,
                    auth=auth,
                )
                patch.raise_for_status()
            log.info("collibra.push_ok asset=%s", payload.asset_name)
            return True
        except Exception as exc:
            log.warning("collibra.push_failed asset=%s err=%s", payload.asset_name, exc)
            return False


class CatalogPushDispatcher:
    """
    Dispatches an approved policy to all enabled catalog adapters concurrently.
    """

    def __init__(self) -> None:
        self._adapters: list[DataHubAdapter | CollibraAdapter] = [
            DataHubAdapter(),
            CollibraAdapter(),
        ]

    async def dispatch(self, payload: CatalogPayload) -> dict[str, bool]:
        import asyncio
        active = [a for a in self._adapters if a.is_enabled()]
        if not active:
            return {}

        results = await asyncio.gather(
            *[a.push(payload) for a in active],
            return_exceptions=True,
        )
        return {
            type(adapter).__name__: bool(result) if not isinstance(result, Exception) else False
            for adapter, result in zip(active, results)
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_encode(obj) -> str:
    import json
    return json.dumps(obj)
