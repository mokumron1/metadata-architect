# `metadata_architect.prompts.reading_level`

**Package:** `metadata_architect`  
**Module:** `prompts.reading_level`  
**Source:** `src/metadata_architect/prompts/reading_level.py`  
**Generated:** 2026-06-02  

> System prompt blocks for the reading-level semantic validation agent.

## Overview

Prompt template for the semantic reading level check.
Only called when textstat score lands in the ambiguous 8.5–10.5 boundary zone.

## Constants

| Name | Value |
|---|---|
| `BLOCK_ROLE` | `'You are a Plain Language Analyst specialising in CEFR B1 / 9th Grade readability. You receive a short text passage a...` |
| `USER_TEMPLATE` | `'Evaluate the reading level compliance of the following passage.\n\n## Mechanical Flesch-Kincaid Grade Score\n{fk_sco...` |
