# `metadata_architect.agents.jargon_scrubber`

**Package:** `metadata_architect`  
**Module:** `agents.jargon_scrubber`  
**Source:** `src/metadata_architect/agents/jargon_scrubber.py`  
**Generated:** 2026-06-02  

> Claude-powered ISO 24495-1 plain-language violation detector.

## Overview

Jargon Scrubber agent.

Evaluates a Statement of Intent for ISO 24495-1 plain language violations.
Runs as a second, focused Claude call after SoI drafting — or standalone
when called from the Gate 2 CI/CD endpoint on hand-authored metadata.

## Classes

### `class JargonViolation`

---

### `class JargonScrubResult`

---

### `class JargonScrubber`

Evaluates a Statement of Intent for plain language violations.

The scrubber rules and glossary are cached system prompt blocks.
The SoI text is injected as the dynamic user turn.

#### Methods

```python
def __init__(glossary: dict[str, str] | None = None) → None
```

**Parameters:**

- **`glossary`** `dict[str, str] | None` *(default: `None`)*

**Returns:** `None`

```python
def scrub(soi_text: str) → JargonScrubResult
```

Analyse `soi_text` for ISO 24495-1 violations.
Returns a JargonScrubResult with a list of zero or more violations.

**Parameters:**

- **`soi_text`** `str`

**Returns:** `JargonScrubResult`

```python
def _build_system_blocks() → list[dict]
```

**Returns:** `list[dict]`

---
