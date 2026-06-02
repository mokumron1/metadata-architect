# `metadata_architect.observability.tracing`

**Package:** `metadata_architect`  
**Module:** `observability.tracing`  
**Source:** `src/metadata_architect/observability/tracing.py`  
**Generated:** 2026-06-02  

> OpenTelemetry TracerProvider setup with OTLP/gRPC export and no-op fallback.

## Overview

OpenTelemetry tracing setup.

Configures a TracerProvider with an OTLP exporter (gRPC) when
OTEL_EXPORTER_OTLP_ENDPOINT is set; falls back to a no-op provider
in development so the app starts without a collector.

Usage:
    from metadata_architect.observability.tracing import setup_tracing, get_tracer
    setup_tracing()           # call once at startup
    tracer = get_tracer()     # use anywhere for manual spans

## Classes

### `class _NoopSpan`

#### Methods

```python
def set_attribute(*_)
```

**Parameters:**

- **`*_`**

```python
def record_exception(*_)
```

**Parameters:**

- **`*_`**

```python
def set_status(*_)
```

**Parameters:**

- **`*_`**

---

### `class _NoopTracer`

#### Methods

```python
def start_as_current_span(name: str, **_)
```

**Parameters:**

- **`name`** `str`
- **`**_`**

```python
def start_span(name: str, **_)
```

**Parameters:**

- **`name`** `str`
- **`**_`**

---

## Functions

```python
def setup_tracing(service_name: str = 'metadata-architect') → None
```

Initialise the global TracerProvider.

When OTEL_EXPORTER_OTLP_ENDPOINT is set, exports spans via OTLP/gRPC.
Otherwise uses a no-op provider so the app works without a collector.

**Parameters:**

- **`service_name`** `str` *(default: `'metadata-architect'`)*

**Returns:** `None`

```python
def get_tracer()
```

Return the global tracer (no-op if OTel is unavailable).
