# `metadata_architect.prompts.jargon_scrubber`

**Package:** `metadata_architect`  
**Module:** `prompts.jargon_scrubber`  
**Source:** `src/metadata_architect/prompts/jargon_scrubber.py`  
**Generated:** 2026-06-02  

> System prompt blocks for the ISO 24495-1 jargon scrubber agent.

## Overview

Prompt templates for the Jargon Scrubber agent.

BLOCK_ROLE        — cached: scrubber identity + violation schema + rules
BLOCK_GLOSSARY    — reuses build_glossary_block from soi_drafter
USER_TEMPLATE     — dynamic: the SoI text to evaluate

## Constants

| Name | Value |
|---|---|
| `BLOCK_ROLE` | `'You are a Plain Language Compliance Auditor. Your task is to review a Statement of Intent (SoI) for a data asset and...` |
| `USER_TEMPLATE` | `'Audit the following Statement of Intent for ISO 24495-1 plain language compliance.\n\n## Statement of Intent to Audi...` |
