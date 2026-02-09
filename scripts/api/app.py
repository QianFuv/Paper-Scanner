"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from scripts.shared.constants import API_PREFIX


class CacheControlMiddleware(BaseHTTPMiddleware):
    """
    Add cache control headers to API responses.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        is_articles = request.url.path.startswith(f"{API_PREFIX}/articles")
        is_meta = request.url.path.startswith(f"{API_PREFIX}/meta")
        if is_articles or is_meta:
            response.headers["Cache-Control"] = (
                "public, max-age=300, stale-while-revalidate=600"
            )
        return response


def build_app() -> FastAPI:
    """
    Build and configure the FastAPI application.

    Returns:
        Configured FastAPI application.
    """
    application = FastAPI(title="Paper Scanner API", version="1.0.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(CacheControlMiddleware)
    return application


app = build_app()
