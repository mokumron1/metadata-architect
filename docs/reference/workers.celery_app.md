# `metadata_architect.workers.celery_app`

**Package:** `metadata_architect`  
**Module:** `workers.celery_app`  
**Source:** `src/metadata_architect/workers/celery_app.py`  
**Generated:** 2026-06-02  

> Celery application factory — queues, Beat schedule, and worker settings.

## Overview

Celery application configuration.

Queues:
  drafting  — SoI generation tasks (CPU/network bound, scales horizontally)
  sla       — SLA monitor beat tasks (low-volume, time-sensitive)
  notify    — notification dispatch (fire-and-forget)
  analysis  — offline SME edit analysis (lowest priority)

## Functions

```python
def make_celery() → Celery
```

**Returns:** `Celery`
