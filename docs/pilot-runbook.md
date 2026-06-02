# Metadata Architect — One-Domain Pilot Runbook

**Target:** Finance domain, single Postgres source system.  
**Scope:** 50–200 table assets, one SME reviewer, one governance manager.  
**Goal:** End-to-end flow from DDL ingestion → AI draft → SME approval → YAML policy → CI/CD gate.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Docker + Compose | ≥ 24 | For Postgres, Redis, MinIO |
| Python | 3.11+ | Virtual env recommended |
| Anthropic API key | — | Set in `.env` |
| SendGrid API key | — | Optional; Slack fallback works without it |
| Slack bot token | — | Optional |

---

## 1. Infrastructure Startup

```bash
# Clone and configure
git clone https://github.com/mokumron1/metadata-architect.git
cd metadata-architect
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY, SENDGRID_API_KEY, SLACK_BOT_TOKEN,
#              JWT_SECRET_KEY (generate: openssl rand -hex 32),
#              GATE_API_KEY (share with CI/CD team)

# Start backing services
docker compose up -d

# Wait for healthchecks
docker compose ps   # all services should show "healthy"
```

---

## 2. Database Setup

```bash
# Install Python dependencies
pip install -e ".[dev]"

# Run migrations
alembic upgrade head
# Expected output: Running upgrade  -> 0001, 0002
```

---

## 3. Start the API

```bash
# Development
uvicorn metadata_architect.api.main:app --reload --port 8000

# Production (4 workers)
uvicorn metadata_architect.api.main:app --host 0.0.0.0 --port 8000 --workers 4

# Verify
curl http://localhost:8000/health
# {"status": "ok"}
```

---

## 4. Start Celery Workers

```bash
# Drafting + analysis worker
celery -A metadata_architect.workers.celery_app worker \
  -Q drafting,analysis -c 4 --loglevel=info &

# SLA + notification worker
celery -A metadata_architect.workers.celery_app worker \
  -Q sla,notify -c 2 --loglevel=info &

# Celery Beat (SLA monitor scheduler)
celery -A metadata_architect.workers.celery_app beat --loglevel=info &
```

---

## 5. Ingest Finance Domain Assets

### Option A — Register assets via API

```bash
# Register a single table
curl -s -X POST http://localhost:8000/assets \
  -H "Content-Type: application/json" \
  -d '{
    "asset_name": "finance.global_revenue_agg_v1",
    "asset_type": "table",
    "source_system": "postgres",
    "context_authority": "jane.sme@company.com",
    "raw_ddl": "CREATE TABLE finance.global_revenue_agg_v1 (
      id SERIAL PRIMARY KEY,
      region VARCHAR(64) NOT NULL,
      currency CHAR(3) NOT NULL,
      revenue_usd NUMERIC(18,4) NOT NULL,
      reporting_date DATE NOT NULL,
      created_at TIMESTAMPTZ DEFAULT now()
    );"
  }' | jq .
```

### Option B — Bulk ingest from DDL files

```bash
# Place DDL files in ddl-inputs/ (one file = one table)
# Then trigger ingestion for each:
for f in ddl-inputs/*.sql; do
  TABLE=$(basename "$f" .sql)
  DDL=$(cat "$f")
  curl -s -X POST http://localhost:8000/assets \
    -H "Content-Type: application/json" \
    -d "{\"asset_name\": \"finance.$TABLE\", \"asset_type\": \"table\",
         \"source_system\": \"postgres\", \"context_authority\": \"sme@company.com\",
         \"raw_ddl\": $(jq -Rs . <<< \"$DDL\")}" | jq '.id'
done
```

---

## 6. Trigger AI Drafting

```bash
# Enqueue the drafting task for a registered asset
# (replace ASSET_ID with the UUID returned by step 5)
python -c "
from metadata_architect.workers.tasks import draft_asset_metadata
draft_asset_metadata.delay('ASSET_ID')
print('Task queued.')
"

# Watch Celery logs — the pipeline will:
# 1. Parse DDL
# 2. Draft SoI with Claude
# 3. Run jargon scrub
# 4. Compute TDK score
# 5. Send Verification Pulse email + Slack to SME
```

---

## 7. SME Review

The SME receives a Verification Pulse notification containing a one-time review link:

```
https://YOUR_PORTAL_BASE_URL/workflows/WORKFLOW_ID/review?token=JWT_TOKEN
```

The SME clicks the link and takes one of three actions:

| Action | Endpoint | Result |
|---|---|---|
| Approve | `POST /workflows/{id}/approve` | Status → SME_APPROVED, YAML policy emitted |
| Edit + Approve | `POST /workflows/{id}/edit` | Corrected SoI certified, edit diff stored |
| Reject | `POST /workflows/{id}/reject` | Status → SME_REJECTED, governance notified |

Check review status:
```bash
curl http://localhost:8000/workflows?status=AWAITING_SME_AUDIT | jq '.items | length'
```

---

## 8. CI/CD Gate Integration

### GitHub Actions

Add to your data pipeline repository's workflow:

```yaml
jobs:
  deploy-finance-tables:
    needs: metadata-check
    # ... your deployment steps

  metadata-check:
    uses: mokumron1/metadata-architect/.github/workflows/metadata-gates.yml@main
    with:
      asset_name: "finance.global_revenue_agg_v1"
      source_system: "postgres"
    secrets:
      gate_api_key: ${{ secrets.METADATA_GATE_API_KEY }}
      metadata_api_url: ${{ secrets.METADATA_API_URL }}
```

### GitLab CI

```yaml
include:
  - project: 'your-group/metadata-architect'
    file: '.gitlab/metadata-gates.gitlab-ci.yml'

check-revenue-table:
  extends: .metadata-gate-context-first
  variables:
    ASSET_NAME: "finance.global_revenue_agg_v1"
    SOURCE_SYSTEM: "postgres"
```

---

## 9. Monitoring & Observability

### Health check

```bash
curl http://localhost:8000/health
```

### SLA breach monitoring

```bash
# Assets overdue for SME review
curl "http://localhost:8000/workflows?status=AWAITING_SME_AUDIT" | \
  jq '[.items[] | select(.sla_deadline_at < now | todate)] | length'

# Orphaned assets (missed SLA)
curl "http://localhost:8000/workflows?status=ORPHANED" | jq '.items | length'
```

### TDK score distribution

```bash
psql $DATABASE_URL -c "
  SELECT
    ROUND(composite_score::numeric, 1) as score_bucket,
    COUNT(*) as assets
  FROM tdk_scores
  WHERE event_type IN ('SME_APPROVED', 'SME_EDITED')
  GROUP BY 1 ORDER BY 1 DESC;
"
```

### OpenTelemetry (optional)

Set `OTEL_EXPORTER_OTLP_ENDPOINT=http://your-collector:4317` in `.env` to export
traces to Jaeger, Tempo, or any OTLP-compatible backend.

---

## 10. Pilot Success Criteria

| Metric | Target | How to measure |
|---|---|---|
| Assets registered | 50+ | `GET /assets` → `total` |
| SME response rate | ≥ 80% within SLA | Workflows in SME_APPROVED / total non-orphaned |
| Avg TDK score at approval | ≥ 0.70 | Query `tdk_scores` on SME_APPROVED events |
| AI draft acceptance rate | ≥ 60% approved without edit | `SME_APPROVED` / (`SME_APPROVED` + `SME_EDITED`) |
| Gate blocks (false positives) | 0 | Gate returns passed=False on registered+approved asset |
| Orphan rate | < 10% | `ORPHANED` / total workflows |

---

## 11. Rollback

```bash
# Roll back to previous migration
alembic downgrade 0001

# Stop services
docker compose down

# Re-tag to previous release
git checkout v0.1.0
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Celery tasks not processing | Redis not reachable | `docker compose ps redis` |
| SME email not received | SendGrid key not set | Check `.env` + SendGrid activity feed |
| Gate returns 401 | Wrong `GATE_API_KEY` | Confirm key matches `.env` |
| YAML not in MinIO | MinIO unreachable | `docker compose ps minio`; check `minio_*` settings |
| TDK score 0.0 | DDL parse failed silently | `GET /assets/{id}` → check `column_metadata` field |
| OTel spans not appearing | Collector not running | Set `OTEL_EXPORTER_OTLP_ENDPOINT` or leave unset for no-op |
