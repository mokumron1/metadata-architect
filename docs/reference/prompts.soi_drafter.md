# `metadata_architect.prompts.soi_drafter`

**Package:** `metadata_architect`  
**Module:** `prompts.soi_drafter`  
**Source:** `src/metadata_architect/prompts/soi_drafter.py`  
**Generated:** 2026-06-02  

> Cacheable system prompt blocks and user template for the SoI drafter agent.

## Overview

Prompt templates for the Statement of Intent Drafter.

BLOCK_ROLE        — cached: agent identity + output schema + ISO-24495-1 rules
BLOCK_GLOSSARY    — cached: enterprise glossary (injected at runtime)
USER_TEMPLATE     — dynamic: per-asset context packet (not cached)

## Constants

| Name | Value |
|---|---|
| `BLOCK_ROLE` | `'You are the Metadata Architect — an AI agent that writes precise, plain-language business documentation for technica...` |
| `BLOCK_GLOSSARY_HEADER` | `'## Enterprise Glossary\nThe following terms are approved for use in Statements of Intent. Only reference acronyms an...` |
| `USER_TEMPLATE` | `'Draft a Statement of Intent for the following data asset.\n\n## Asset Context Packet\n{context_json}\n\nReturn only ...` |

## Functions

```python
def build_glossary_block(terms: dict[str, str]) → str
```

Build the glossary content block from a {term: definition} dict.
Returns the full text to inject as a cached system prompt block.

**Parameters:**

- **`terms`** `dict[str, str]`

**Returns:** `str`
