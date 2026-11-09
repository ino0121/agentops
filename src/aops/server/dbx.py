"""Connects API routes to the dbx lifecycle when the server is configured for a workspace.

Without AOPS_REGISTRY and AOPS_WAREHOUSE_ID the routes keep returning 501 (contract only).
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Request

from ..dbx.service import Caller, Config, Service
from .common import NotImplementedYet


@lru_cache(maxsize=1)
def _service() -> Service | None:
    config = Config.from_env()
    return Service(config) if config else None


def service_for(command: str | None) -> Service:
    svc = _service()
    if svc is None:
        raise NotImplementedYet(command)
    return svc


def caller_of(request: Request, svc: Service) -> Caller:
    """Databricks Apps forwards the user's email and token; elsewhere the bearer token tells who it is."""
    token = request.headers.get("x-forwarded-access-token")
    if not token:
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else None
    return svc.identify(token, request.headers.get("x-forwarded-email"))
