# `metadata_architect.api.routers.gates`

**Package:** `metadata_architect`  
**Module:** `api.routers.gates`  
**Source:** `src/metadata_architect/api/routers/gates.py`  
**Generated:** 2026-06-02  

> CI/CD gate endpoints: Context-First (Gate 1) and Jargon Scrubber (Gate 2).

## Overview

CI/CD Gate endpoints.

Gate 1 — Context-First: rejects pipeline assets that have no registered
          Statement of Intent.  Blocks deployment until metadata is
          authored and approved.

Gate 2 — Jargon Scrubber: runs the JargonScrubber agent against a
          supplied SoI text.  Returns the violation list so CI/CD
          pipelines can fail on non-compliant prose.

Both endpoints require the X-Gate-API-Key header to authenticate the
calling CI/CD system.

## Classes

### `class ContextFirstRequest(BaseModel)`

---

### `class ContextFirstResponse(BaseModel)`

---

### `class JargonScrubRequest(BaseModel)`

---

### `class ViolationItem(BaseModel)`

---

### `class JargonScrubResponse(BaseModel)`

---

## Functions

```
@router.post('/context-first', response_model=ContextFirstResponse, summary='Gate 1 — Context-First: verify asset has an approved SoI')
```
```python
async def context_first_gate(body: ContextFirstRequest, _: GateAuth, db: AsyncSession = Depends(get_db)) → ContextFirstResponse
```

Blocks CI/CD pipelines that attempt to deploy an asset with no
registered or approved Statement of Intent.

Returns 200 with `passed=True` only when the asset has at least one
workflow in SME_APPROVED state.  All other states (including absent
records) return 200 with `passed=False` so the CI/CD runner can
distinguish a gate failure from an API error.

**Parameters:**

- **`body`** `ContextFirstRequest`
- **`_`** `GateAuth`
- **`db`** `AsyncSession` *(default: `Depends(get_db)`)*

**Returns:** `ContextFirstResponse`

```
@router.post('/jargon-scrub', response_model=JargonScrubResponse, summary='Gate 2 — Jargon Scrubber: validate SoI against ISO 24495-1')
```
```python
async def jargon_scrub_gate(body: JargonScrubRequest, _: GateAuth) → JargonScrubResponse
```

Runs the JargonScrubber agent against the supplied Statement of Intent.

Returns a violation list.  When `fail_on_violation=True` (default),
any violation sets `passed=False` so the CI/CD pipeline can fail the
build.

**Parameters:**

- **`body`** `JargonScrubRequest`
- **`_`** `GateAuth`

**Returns:** `JargonScrubResponse`
