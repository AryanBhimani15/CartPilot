from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.catalog import router as catalog_router
from app.catalog.search import refresh_catalog_embeddings
from app.config import get_settings
from app.db.session import get_db_session, get_session_factory


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    get_settings()
    async with get_session_factory()() as session:
        await refresh_catalog_embeddings(session)
        await session.commit()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="CartPilot API", version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )
    application.include_router(catalog_router)

    @application.get("/api/v1/health", tags=["health"])
    async def health(db: AsyncSession = Depends(get_db_session)) -> dict[str, str]:
        await db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok"}

    return application


app = create_app()
