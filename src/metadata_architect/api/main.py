import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from metadata_architect.api.routers import assets, gates, workflows

log = structlog.get_logger()

app = FastAPI(
    title="Metadata Architect API",
    description="AI-powered metadata generation and governance agent",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(assets.router)
app.include_router(workflows.router)
app.include_router(gates.router)


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok"}
