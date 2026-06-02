# `metadata_architect.agents.claude_client`

**Package:** `metadata_architect`  
**Module:** `agents.claude_client`  
**Source:** `src/metadata_architect/agents/claude_client.py`  
**Generated:** 2026-06-02  

> Low-level Anthropic API wrapper with prompt caching and exponential-backoff retry.

## Overview

Thin wrapper around the Anthropic Python SDK.

Responsibilities:
- Prompt caching via cache_control blocks on stable system prompt sections
- Exponential-backoff retry on transient errors (overload, rate-limit)
- Structured token usage logging for observability
- JSON response extraction with fallback error

## Classes

### `class ClaudeResponse`

#### Methods

```
@property
```
```python
def cache_hit() → bool
```

**Returns:** `bool`

```python
def parse_json() → dict[str, Any]
```

Parse content as JSON, raising ValueError on failure.

**Returns:** `dict[str, Any]`

---

### `class CachedBlock`

Helper to build a cacheable system prompt text block.

#### Methods

```
@staticmethod
```
```python
def make(text: str, cache: bool = True) → dict[str, Any]
```

**Parameters:**

- **`text`** `str`
- **`cache`** `bool` *(default: `True`)*

**Returns:** `dict[str, Any]`

---

### `class ClaudeClient`

Reusable Claude API client with caching and retry.

Each agent instantiates one ClaudeClient with its chosen model.
System prompt blocks that are large and stable should pass cache=True
to CachedBlock.make() — this activates prompt caching and reduces
per-call token cost for those blocks by ~90% on cache hits.

#### Methods

```python
def __init__(model: str, max_tokens: int = 1024) → None
```

**Parameters:**

- **`model`** `str`
- **`max_tokens`** `int` *(default: `1024`)*

**Returns:** `None`

```
@retry(retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIStatusError)), wait=wait_exponential(multiplier=1, min=2, max=30), stop=stop_after_attempt(4), reraise=True)
```
```python
def call(system_blocks: list[dict[str, Any]], user_message: str) → ClaudeResponse
```

Send a request to the Claude API and return a structured response.

system_blocks: list of content block dicts (use CachedBlock.make()).
user_message:  the dynamic per-call user turn.

**Parameters:**

- **`system_blocks`** `list[dict[str, Any]]`
- **`user_message`** `str`

**Returns:** `ClaudeResponse`

---
