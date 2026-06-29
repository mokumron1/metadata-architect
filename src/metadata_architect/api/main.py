import structlog
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

# Inject Windows system cert store so Anthropic SDK SSL works without certifi bundle gaps
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass
from fastapi.middleware.cors import CORSMiddleware

_STATIC_DIR = Path(__file__).parent.parent / "static"

from metadata_architect.api.routers import assets, audit, batch, gates, onboarding, soi_studio, workflows
from metadata_architect.config import get_settings
from metadata_architect.database import Base, engine
from metadata_architect.middleware.request_id import RequestIDMiddleware
from metadata_architect.observability.logging import configure_logging
from metadata_architect.observability.tracing import setup_tracing

# Ensure all models are imported so their tables are registered with Base.metadata
import metadata_architect.models.asset_registry  # noqa: F401
import metadata_architect.models.soi_studio       # noqa: F401
import metadata_architect.models.onboarding      # noqa: F401
import metadata_architect.models.audit           # noqa: F401

configure_logging()
setup_tracing()

log = structlog.get_logger()

_settings = get_settings()
_allowed_origins = _settings.get_allowed_origins()

# When an explicit origin list is provided use it with credentials support.
# When no list is configured, fall back to a restrictive wildcard *without*
# credentials so the combination is valid (browsers block wildcard + credentials).
if _allowed_origins:
    _cors_kwargs = {
        "allow_origins": _allowed_origins,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }
else:
    _cors_kwargs = {
        "allow_origins": ["*"],
        "allow_credentials": False,
        "allow_methods": ["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "X-Gate-API-Key", "X-Request-ID", "Authorization"],
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate production secrets at startup so misconfigured deployments fail loudly.
    get_settings().validate_production_secrets()
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
app.add_middleware(CORSMiddleware, **_cors_kwargs)

app.include_router(assets.router)
app.include_router(workflows.router)
app.include_router(gates.router)
app.include_router(batch.router)
app.include_router(soi_studio.router)
app.include_router(onboarding.router)
app.include_router(audit.router)

if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(_STATIC_DIR / "metadata-drafter.html")

@app.get("/audit-viewer", include_in_schema=False)
async def audit_viewer():
    return FileResponse(_STATIC_DIR / "audit-viewer.html")

@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok"}
