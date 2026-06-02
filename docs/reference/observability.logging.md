# `metadata_architect.observability.logging`

**Package:** `metadata_architect`  
**Module:** `observability.logging`  
**Source:** `src/metadata_architect/observability/logging.py`  
**Generated:** 2026-06-02  

> Structured logging setup — JSON (production) or console (development).

## Overview

Structured logging setup.

Configures structlog with JSON rendering for production and
pretty-printed console output for development.

Call configure_logging() once at app startup (done in api/main.py).

## Functions

```python
def configure_logging() → None
```

Configure structlog + stdlib logging for the application.

**Returns:** `None`
