# Metadata Architect AI Agent — API Reference

**Version:** 0.1.0  
**Generated:** 2026-06-02  

Complete reference documentation for all Python modules in the Metadata Architect AI Agent.

## Module Index

### Core

| Module | Description |
|---|---|
| [`config`](config.md) | Application settings loaded from environment variables via pydantic-settings. |
| [`database`](database.md) | Async SQLAlchemy engine, session factory, and FastAPI dependency for DB access. |

### API

| Module | Description |
|---|---|
| [`api.main`](api.main.md) | FastAPI application factory — middleware, routers, startup hooks. |
| [`api.routers.assets`](api.routers.assets.md) | Asset Registry CRUD endpoints (create, read, update, delete, parse, transition). |
| [`api.routers.batch`](api.routers.batch.md) | Batch ingestion endpoint — register up to 200 assets in one request. |
| [`api.routers.gates`](api.routers.gates.md) | CI/CD gate endpoints: Context-First (Gate 1) and Jargon Scrubber (Gate 2). |
| [`api.routers.workflows`](api.routers.workflows.md) | SME HITL review portal — approve, edit, reject, list, and get workflows. |

### Agents

| Module | Description |
|---|---|
| [`agents.claude_client`](agents.claude_client.md) | Low-level Anthropic API wrapper with prompt caching and exponential-backoff retry. |
| [`agents.soi_drafter`](agents.soi_drafter.md) | Primary AI agent that drafts Statements of Intent from DDL schemas. |
| [`agents.jargon_scrubber`](agents.jargon_scrubber.md) | Claude-powered ISO 24495-1 plain-language violation detector. |
| [`agents.reading_level`](agents.reading_level.md) | Flesch-Kincaid reading-level validator with Claude semantic fallback. |

### Intelligence

| Module | Description |
|---|---|
| [`scoring.tdk_calculator`](scoring.tdk_calculator.md) | TDK composite score calculator: clarity (60%) × ownership (40%) formula. |
| [`parsers.schema_parser`](parsers.schema_parser.md) | sqlglot-based DDL parser — extracts columns, PKs, FKs from 20+ SQL dialects. |
| [`policy.emitter`](policy.emitter.md) | YAML Policy-as-Code emitter (ruamel.yaml) and async MinIO uploader. |

### Prompts

| Module | Description |
|---|---|
| [`prompts.soi_drafter`](prompts.soi_drafter.md) | Cacheable system prompt blocks and user template for the SoI drafter agent. |
| [`prompts.jargon_scrubber`](prompts.jargon_scrubber.md) | System prompt blocks for the ISO 24495-1 jargon scrubber agent. |
| [`prompts.reading_level`](prompts.reading_level.md) | System prompt blocks for the reading-level semantic validation agent. |

### Workflow

| Module | Description |
|---|---|
| [`auth.tokens`](auth.tokens.md) | JWT one-time review token creation and verification for SME email links. |
| [`models.asset_registry`](models.asset_registry.md) | SQLAlchemy ORM models: Asset, SoIDraft, SmeWorkflow, TdkScoreLog and state machine. |
| [`schemas.asset_schemas`](schemas.asset_schemas.md) | Pydantic request/response schemas for the Asset Registry API. |

### Notifications

| Module | Description |
|---|---|
| [`notifications.base`](notifications.base.md) | Abstract notification adapter interface, payload schema, and type enum. |
| [`notifications.dispatcher`](notifications.dispatcher.md) | Concurrent notification dispatcher — sends to all enabled adapters. |
| [`notifications.sendgrid_adapter`](notifications.sendgrid_adapter.md) | SendGrid HTML email adapter for Verification Pulse and Orphan Notices. |
| [`notifications.slack_adapter`](notifications.slack_adapter.md) | Slack Block Kit adapter with TDK score bar visualisation. |

### Workers

| Module | Description |
|---|---|
| [`workers.celery_app`](workers.celery_app.md) | Celery application factory — queues, Beat schedule, and worker settings. |
| [`workers.tasks`](workers.tasks.md) | Celery tasks: draft pipeline, SLA monitor, orphan notice, edit analysis. |

### Catalog

| Module | Description |
|---|---|
| [`catalog.push_adapter`](catalog.push_adapter.md) | DataHub GMS and Collibra REST adapters for post-approval metadata push. |

### Observability

| Module | Description |
|---|---|
| [`observability.tracing`](observability.tracing.md) | OpenTelemetry TracerProvider setup with OTLP/gRPC export and no-op fallback. |
| [`observability.logging`](observability.logging.md) | Structured logging setup — JSON (production) or console (development). |

### Middleware

| Module | Description |
|---|---|
| [`middleware.request_id`](middleware.request_id.md) | X-Request-ID propagation middleware with structlog context binding. |
| [`middleware.rate_limit`](middleware.rate_limit.md) | Sliding-window rate limiter (per API key) for the CI/CD gate endpoints. |
