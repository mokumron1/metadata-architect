# `metadata_architect.policy.emitter`

**Package:** `metadata_architect`  
**Module:** `policy.emitter`  
**Source:** `src/metadata_architect/policy/emitter.py`  
**Generated:** 2026-06-02  

> YAML Policy-as-Code emitter (ruamel.yaml) and async MinIO uploader.

## Overview

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

## Classes

### `class PolicyDocument`

---

### `class PolicyEmitter`

Generates and stores YAML policy documents for approved assets.

#### Methods

```python
def emit(asset_id: uuid.UUID, asset_name: str, statement_of_intent: str, clarity_standard: str, reading_level: str, context_authority: str, tdk_score: float, verification_status: str, workflow_id: uuid.UUID, draft_version: int, jargon_compliant: bool) → PolicyDocument
```

Build the policy document and render it to YAML.

**Parameters:**

- **`asset_id`** `uuid.UUID`
- **`asset_name`** `str`
- **`statement_of_intent`** `str`
- **`clarity_standard`** `str`
- **`reading_level`** `str`
- **`context_authority`** `str`
- **`tdk_score`** `float`
- **`verification_status`** `str`
- **`workflow_id`** `uuid.UUID`
- **`draft_version`** `int`
- **`jargon_compliant`** `bool`

**Returns:** `PolicyDocument`

```python
def object_key(asset_id: uuid.UUID, draft_version: int) → str
```

MinIO/S3 object key for this policy document.

**Parameters:**

- **`asset_id`** `uuid.UUID`
- **`draft_version`** `int`

**Returns:** `str`

```python
async def upload(doc: PolicyDocument, draft_version: int) → str | None
```

Upload the policy YAML to MinIO.  Returns the object key on success,
or None if MinIO is not reachable (graceful degradation for dev/test).

**Parameters:**

- **`doc`** `PolicyDocument`
- **`draft_version`** `int`

**Returns:** `str | None`

---
