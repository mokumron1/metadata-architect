# `metadata_architect.agents.reading_level`

**Package:** `metadata_architect`  
**Module:** `agents.reading_level`  
**Source:** `src/metadata_architect/agents/reading_level.py`  
**Generated:** 2026-06-02  

> Flesch-Kincaid reading-level validator with Claude semantic fallback.

## Overview

Reading Level Validator.

Two-stage approach:
  Stage 1 (fast, free): textstat Flesch-Kincaid Grade Level.
              FK ≤ 8.5  → PASS immediately (no Claude call).
              FK > 10.5 → FAIL immediately (no Claude call).
  Stage 2 (Claude):     8.5 < FK ≤ 10.5 boundary zone —
              semantic ruling from Claude covers idioms, nominalisations,
              stacked clauses that mechanical scores miss.

This design minimises Claude API calls to only the ambiguous cases.

## Constants

| Name | Value |
|---|---|
| `_FK_PASS_THRESHOLD` | `8.5` |
| `_FK_FAIL_THRESHOLD` | `10.5` |

## Classes

### `class ReadingLevelResult`

---

### `class ReadingLevelValidator`

Validates that a Statement of Intent meets CEFR B1 / 9th Grade standard.
Uses textstat for fast mechanical pre-filtering; Claude for boundary cases.

#### Methods

```python
def __init__() → None
```

**Returns:** `None`

```python
def validate(text: str) → ReadingLevelResult
```

**Parameters:**

- **`text`** `str`

**Returns:** `ReadingLevelResult`

```python
def _claude_ruling(text: str, fk_score: float) → ReadingLevelResult
```

**Parameters:**

- **`text`** `str`
- **`fk_score`** `float`

**Returns:** `ReadingLevelResult`

---
