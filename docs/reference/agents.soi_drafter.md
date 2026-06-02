# `metadata_architect.agents.soi_drafter`

**Package:** `metadata_architect`  
**Module:** `agents.soi_drafter`  
**Source:** `src/metadata_architect/agents/soi_drafter.py`  
**Generated:** 2026-06-02  

> Primary AI agent that drafts Statements of Intent from DDL schemas.

## Overview

Statement of Intent Drafter.

Takes a ParsedSchema + optional lineage and glossary context,
calls Claude with cached system prompt blocks, and returns a
structured SoIDraftResult ready to be persisted as a SoIDraft record.

## Constants

| Name | Value |
|---|---|
| `_MIN_CACHE_TOKENS` | `200` |

## Classes

### `class SoIDraftResult`

#### Methods

```
@property
```
```python
def tdk_initial_score() → float
```

Provisional TDK score from the draft alone (before SME review).
The full score is computed by TdkScoreCalculator after SME action.

**Returns:** `float`

---

### `class SoIDrafter`

Drafts a Statement of Intent for a data asset.

The enterprise glossary and ISO-24495-1 rules are injected as cached
system prompt blocks, amortising their token cost across all drafting calls.

#### Methods

```python
def __init__(glossary: dict[str, str] | None = None) → None
```

**Parameters:**

- **`glossary`** `dict[str, str] | None` *(default: `None`)*

**Returns:** `None`

```python
def draft(schema: ParsedSchema, lineage_context: list[str] | None = None, asset_type: str = 'table') → SoIDraftResult
```

Generate a SoI draft for the given schema.

If Claude's confidence is below the escalation threshold,
the draft is automatically retried with the Opus escalation model.

**Parameters:**

- **`schema`** `ParsedSchema`
- **`lineage_context`** `list[str] | None` *(default: `None`)*
- **`asset_type`** `str` *(default: `'table'`)*

**Returns:** `SoIDraftResult`

```python
def _build_system_blocks(escalating: bool = False) → list[dict]
```

**Parameters:**

- **`escalating`** `bool` *(default: `False`)*

**Returns:** `list[dict]`

---
