"""Aggregate all API routers."""

from fastapi import APIRouter

from melo.api.routes import (
    agents,
    auth,
    conversations,
    settings,
    studio,
    studio_ws,
    voices,
    ws,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(agents.router)
api_router.include_router(conversations.router)
api_router.include_router(voices.router)
api_router.include_router(studio.router)
api_router.include_router(settings.router)
api_router.include_router(ws.router)
api_router.include_router(studio_ws.router)
