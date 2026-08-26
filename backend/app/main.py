from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers.exceptions import router as exceptions_router
from .routers.health import router as health_router
from .routers.imports import router as imports_router
from .routers.reconciliation import router as reconciliation_router
from .routers.webhooks import router as webhooks_router


def create_app() -> FastAPI:
    app = FastAPI(title="Reco.ai Backend", version="0.1.0")

    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            *settings.cors_origin_list(),
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(imports_router)
    app.include_router(reconciliation_router)
    app.include_router(webhooks_router)
    app.include_router(exceptions_router)
    return app


app = create_app()
