"""
Unit tests for PolicyEmitter.

Validates YAML output structure, field presence, and schema compliance
against the Universal Service Catalog spec — without touching MinIO.
"""

import uuid

import pytest
from ruamel.yaml import YAML

from metadata_architect.policy.emitter import PolicyEmitter, PolicyDocument

_yaml = YAML()


def _emit(**overrides) -> PolicyDocument:
    defaults = dict(
        asset_id=uuid.uuid4(),
        asset_name="finance.global_revenue_agg_v1",
        statement_of_intent="This table stores daily revenue totals by region and currency.",
        clarity_standard="ISO-24495-1-Compliant",
        reading_level="B1 / 9th Grade",
        context_authority="sme@example.com",
        tdk_score=0.85,
        verification_status="SME_APPROVED",
        workflow_id=uuid.uuid4(),
        draft_version=1,
        jargon_compliant=True,
    )
    defaults.update(overrides)
    return PolicyEmitter().emit(**defaults)


# ---------------------------------------------------------------------------
# PolicyDocument dataclass
# ---------------------------------------------------------------------------

class TestPolicyDocument:
    def test_returns_policy_document(self):
        doc = _emit()
        assert isinstance(doc, PolicyDocument)

    def test_raw_yaml_is_string(self):
        doc = _emit()
        assert isinstance(doc.raw_yaml, str)
        assert len(doc.raw_yaml) > 0

    def test_tdk_score_rounded(self):
        doc = _emit(tdk_score=0.849999)
        assert doc.tdk_score == pytest.approx(0.85, abs=0.01)

    def test_asset_id_stored_as_str(self):
        aid = uuid.uuid4()
        doc = _emit(asset_id=aid)
        assert doc.asset_id == str(aid)

    def test_certified_at_is_iso_string(self):
        doc = _emit()
        from datetime import datetime
        dt = datetime.fromisoformat(doc.certified_at)
        assert dt.tzinfo is not None  # timezone-aware


# ---------------------------------------------------------------------------
# YAML structure
# ---------------------------------------------------------------------------

class TestYamlStructure:
    @pytest.fixture
    def parsed(self):
        import io
        doc = _emit()
        return _yaml.load(io.StringIO(doc.raw_yaml))

    def test_top_level_key_is_asset_metadata(self, parsed):
        assert "asset_metadata" in parsed

    def test_required_fields_present(self, parsed):
        meta = parsed["asset_metadata"]
        required = {
            "asset_id", "asset_uuid", "statement_of_intent", "clarity_standard",
            "reading_level", "context_authority", "tdk_score",
            "verification_status", "certified_at", "schema_version",
            "jargon_compliant", "draft_version", "workflow_id",
        }
        for field in required:
            assert field in meta, f"Missing field: {field}"

    def test_statement_of_intent_matches(self, parsed):
        soi = "This table stores daily revenue totals by region and currency."
        assert parsed["asset_metadata"]["statement_of_intent"] == soi

    def test_tdk_score_is_float(self, parsed):
        score = parsed["asset_metadata"]["tdk_score"]
        assert isinstance(score, float)

    def test_verification_status_matches(self, parsed):
        assert parsed["asset_metadata"]["verification_status"] == "SME_APPROVED"

    def test_schema_version_is_1_0(self, parsed):
        assert parsed["asset_metadata"]["schema_version"] == "1.0"

    def test_jargon_compliant_is_bool(self, parsed):
        assert isinstance(parsed["asset_metadata"]["jargon_compliant"], bool)


# ---------------------------------------------------------------------------
# Object key
# ---------------------------------------------------------------------------

class TestObjectKey:
    def test_key_format(self):
        emitter = PolicyEmitter()
        aid = uuid.uuid4()
        key = emitter.object_key(aid, draft_version=3)
        assert key.startswith(f"policies/{aid}/")
        assert key.endswith("v0003/policy.yaml")

    def test_key_zero_padded(self):
        emitter = PolicyEmitter()
        key = emitter.object_key(uuid.uuid4(), draft_version=1)
        assert "v0001" in key

    def test_key_version_100(self):
        emitter = PolicyEmitter()
        key = emitter.object_key(uuid.uuid4(), draft_version=100)
        assert "v0100" in key


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_jargon_non_compliant_stored(self):
        doc = _emit(jargon_compliant=False)
        import io
        parsed = _yaml.load(io.StringIO(doc.raw_yaml))
        assert parsed["asset_metadata"]["jargon_compliant"] is False

    def test_high_draft_version(self):
        doc = _emit(draft_version=99)
        assert doc.draft_version == 99

    def test_different_verification_status(self):
        doc = _emit(verification_status="SME_EDITED")
        import io
        parsed = _yaml.load(io.StringIO(doc.raw_yaml))
        assert parsed["asset_metadata"]["verification_status"] == "SME_EDITED"
