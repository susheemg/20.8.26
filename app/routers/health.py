"""Health, readiness and version endpoints — the reference extracted router.

These have no business-logic dependencies beyond the DB session, which makes
them the safe first extraction that proves the injection pattern without
touching the 480-test green path.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from .deps import RouterDeps


def build_health_router(deps: RouterDeps) -> APIRouter:
    r = APIRouter(tags=["health"])

    @r.get("/api/v1/health")
    def health():
        return {"status": "ok", "version": "4.0-unified", "ai": "local-deterministic"}

    @r.get("/healthz")
    def healthz():
        return {"status": "ok", "version": deps.platform_version()}

    @r.get("/readyz")
    def readyz(s: Session = Depends(deps.db)):
        s.execute(text("SELECT 1"))
        return {"status": "ready"}

    return r
