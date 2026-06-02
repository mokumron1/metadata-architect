import structlog
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()
from fastapi.middleware.cors import CORSMiddleware

from metadata_architect.api.routers import assets, batch, gates, soi_studio, workflows
from metadata_architect.database import Base, engine
from metadata_architect.middleware.request_id import RequestIDMiddleware
from metadata_architect.observability.logging import configure_logging
from metadata_architect.observability.tracing import setup_tracing

# Ensure all models are imported so their tables are registered with Base.metadata
import metadata_architect.models.asset_registry  # noqa: F401
import metadata_architect.models.soi_studio       # noqa: F401

configure_logging()
setup_tracing()

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables that don't yet exist (safe to run on every startup)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="Metadata Architect API",
    description="AI-powered metadata generation and governance agent",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
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
app.include_router(soi_studio.router)


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok"}
