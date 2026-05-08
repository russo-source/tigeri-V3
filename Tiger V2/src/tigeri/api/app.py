from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tigeri.agent_card.registry import get_registry
from tigeri.api.middleware import (
    CsrfOriginMiddleware,
    MustChangePasswordMiddleware,
    RequestIdMiddleware,
)
from tigeri.api.routes import (
    actions,
    activation,
    admin,
    agents,
    audit,
    auth,
    chat,
    health,
    integrations,
    invoices,
)
from tigeri.core.config import get_settings
from tigeri.core.logging import configure_logging
from tigeri.graph.tracing import configure_langsmith


@asynccontextmanager
async def _lifespan(app: FastAPI):
    configure_logging()
    configure_langsmith()
    get_registry()  # eager-load Agent Cards
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    is_local = settings.env == "local"

    app = FastAPI(
        title="Tigeri.ai",
        version="0.1.0",
        description="Slice 1 — Scaffold + Invoice Agent end-to-end",
        lifespan=_lifespan,
        # Lock down auto-generated docs in non-local environments — they
        # otherwise enumerate every route + schema to anonymous attackers.
        docs_url="/docs" if is_local else None,
        redoc_url="/redoc" if is_local else None,
        openapi_url="/openapi.json" if is_local else None,
    )

    # Order matters: middleware added LAST runs FIRST per Starlette's stack.
    # We want RequestId outermost (so even CSRF rejections carry an id),
    # then CSRF, then CORS innermost.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "https://100-48-88-95.sslip.io",
            "http://ec2-100-48-88-95.compute-1.amazonaws.com",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # MustChangePasswordMiddleware sits BETWEEN CSRF and the route handler so
    # CSRF still runs first (no point checking password state if Origin is
    # bad), but before any route logic sees an authed user.
    app.add_middleware(MustChangePasswordMiddleware)
    app.add_middleware(CsrfOriginMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(activation.router)
    app.include_router(agents.router)
    app.include_router(invoices.router)
    app.include_router(audit.router)
    app.include_router(integrations.router)
    app.include_router(chat.router)
    app.include_router(actions.router)
    app.include_router(admin.router)
    return app
