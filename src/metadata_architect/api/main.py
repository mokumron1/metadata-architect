import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from metadata_architect.api.routers import assets, batch, gates, workflows
from metadata_architect.middleware.request_id import RequestIDMiddleware
from metadata_architect.observability.logging import configure_logging
from metadata_architect.observability.tracing import setup_tracing

# Initialise logging and tracing before the app handles any requests
configure_logging()
setup_tracing()

log = structlog.get_logger()

app = FastAPI(
    title="Metadata Architect API",
    description="AI-powered metadata generation and governance agent",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production via ALLOWED_ORIGINS env var
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(assets.router)
app.include_router(workflows.router)
app.include_router(gates.router)
app.include_router(batch.router)


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok"}
