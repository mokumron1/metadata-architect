# `metadata_architect.scoring.tdk_calculator`

**Package:** `metadata_architect`  
**Module:** `scoring.tdk_calculator`  
**Source:** `src/metadata_architect/scoring/tdk_calculator.py`  
**Generated:** 2026-06-02  

> TDK composite score calculator: clarity (60%) × ownership (40%) formula.

## Overview

Trusted Data KPI (TDK) Score Calculator.

Implements the formula from the governance framework specification:

  clarity_score  = reading_level_ok*0.30 + no_jargon*0.30
                 + soi_length_ok*0.20 + glossary_coverage*0.20

  ownership_score = authority_assigned*0.50 + sla_met*0.30
                  + approved_not_rejected*0.20

  composite = clarity*0.6 + ownership*0.4

  # SLA breach penalty:
  composite = max(0.0, composite - SLA_BREACH_PENALTY)

All scores are in [0.0, 1.0].

## Constants

| Name | Value |
|---|---|
| `_SOI_MIN_WORDS` | `20` |
| `_SOI_MAX_WORDS` | `100` |
| `_FK_GRADE_PASS` | `9.0` |

## Classes

### `class TdkInputs`

All inputs needed to compute a TDK score at a given lifecycle event.

---

### `class TdkScoreBreakdown`

---

### `class TdkCalculator`

Stateless calculator — call compute() with TdkInputs to get a breakdown.
Instantiate once and reuse; reads SLA breach penalty from settings.

#### Methods

```python
def __init__() → None
```

**Returns:** `None`

```python
def compute(inputs: TdkInputs, sla_breached: bool = False) → TdkScoreBreakdown
```

Compute TDK scores.

sla_breached: set True when the SLA monitor triggers Automated
              Confidence Throttling (48-hour window elapsed).

**Parameters:**

- **`inputs`** `TdkInputs`
- **`sla_breached`** `bool` *(default: `False`)*

**Returns:** `TdkScoreBreakdown`

---
