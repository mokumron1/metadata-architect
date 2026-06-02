"""
YAML Policy Emitter.

Generates the machine-readable policy file on SME approval.
Output format matches the Universal Service Catalog spec from the functional specification:

  asset_metadata:
    asset_id: global_revenue_agg_v1
    statement_of_intent: "..."
    clarity_standard: "ISO-24495-1-Compliant"
    reading_level: "B1 / 9th Grade"
    context_authority: "sme@example.com"
    tdk_initial_score: 0.85
    verification_status: "SME_APPROVED"

The emitted YAML is stored in MinIO (bucket: policy-outputs).
"""

import io
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from ruamel.yaml import YAML

log = logging.getLogger(__name__)

_yaml = YAML()
_yaml.default_flow_style = False
_yaml.width = 120


@dataclass
class PolicyDocument:
    asset_id: str
    asset_name: str
    statement_of_intent: str
    clarity_standard: str
    reading_level: str
    context_authority: str
    tdk_score: float
    verification_status: str
    certified_at: str
    jargon_compliant: bool
    workflow_id: str
    draft_version: int
    raw_yaml: str  # the rendered YAML string


class PolicyEmitter:
    """
    Generates and stores YAML policy documents for approved assets.
    """

    def emit(
        self,
        *,
        asset_id: uuid.UUID,
        asset_name: str,
        statement_of_intent: str,
        clarity_standard: str,
        reading_level: str,
        context_authority: str,
        tdk_score: float,
        verification_status: str,
        workflow_id: uuid.UUID,
        draft_version: int,
        jargon_compliant: bool,
    ) -> PolicyDocument:
        """Build the policy document and render it to YAML."""
        certified_at = datetime.now(timezone.utc).isoformat()

        doc = {
            "asset_metadata": {
                "asset_id": asset_name,
                "asset_uuid": str(asset_id),
                "statement_of_intent": statement_of_intent,
                "clarity_standard": clarity_standard,
                "reading_level": reading_level,
                "jargon_compliant": jargon_compliant,
                "context_authority": context_authority,
                "tdk_score": round(tdk_score, 4),
                "verification_status": verification_status,
                "draft_version": draft_version,
                "workflow_id": str(workflow_id),
                "certified_at": certified_at,
                "schema_version": "1.0",
            }
        }

        buf = io.StringIO()
        _yaml.dump(doc, buf)
        raw_yaml = buf.getvalue()

        return PolicyDocument(
            asset_id=str(asset_id),
            asset_name=asset_name,
            statement_of_intent=statement_of_intent,
            clarity_standard=clarity_standard,
            reading_level=reading_level,
            context_authority=context_authority,
            tdk_score=tdk_score,
            verification_status=verification_status,
            certified_at=certified_at,
            jargon_compliant=jargon_compliant,
            workflow_id=str(workflow_id),
            draft_version=draft_version,
            raw_yaml=raw_yaml,
        )

    def object_key(self, asset_id: uuid.UUID, draft_version: int) -> str:
        """MinIO/S3 object key for this policy document."""
        return f"policies/{asset_id}/v{draft_version:04d}/policy.yaml"

    async def upload(self, doc: PolicyDocument, draft_version: int) -> str | None:
        """
        Upload the policy YAML to MinIO.  Returns the object key on success,
        or None if MinIO is not reachable (graceful degradation for dev/test).
        """
        try:
            from miniopy_async import Minio  # type: ignore[import-untyped]
            from metadata_architect.config import get_settings

            settings = get_settings()
            client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )

            bucket = settings.minio_bucket_policy
            if not await client.bucket_exists(bucket):
                await client.make_bucket(bucket)

            key = self.object_key(uuid.UUID(doc.asset_id), draft_version)
            data = doc.raw_yaml.encode()
            await client.put_object(
                bucket,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type="application/yaml",
            )
            log.info("policy_uploaded bucket=%s key=%s", bucket, key)
            return key
        except Exception as exc:
            log.warning("minio_upload_skipped reason=%s", exc)
            return None
