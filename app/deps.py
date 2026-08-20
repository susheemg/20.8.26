"""Shared FastAPI dependencies for extracted routers.

The route logic historically lived as closures inside create_app(), capturing the
per-app SessionFactory. To move routes into per-package APIRouter modules without
changing behaviour, we expose the same primitives here, bound to app.state at
startup. Routers depend on these instead of closure-captured locals.
"""
from __future__ import annotations
import os as _os
from typing import Optional
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.domain.models_db import User
from app.features.admin.rbac import has_permission
from app.features.admin import security as SEC
from app.features.admin.auth import bearer_subject, TokenError


def _session_factory(request: Request):
    return request.app.state.session_factory


def get_db(request: Request) -> Session:
    s = request.app.state.session_factory()
    try:
        yield s
    finally:
        s.close()


def actor(request: Request,
          authorization: str = Header(default=None),
          x_user: str = Header(default=None),
          s: Session = Depends(get_db)) -> User:
    username: Optional[str] = None
    if authorization:
        try:
            username = bearer_subject(authorization)
        except TokenError as e:
            raise HTTPException(401, str(e))
    elif _os.environ.get("BRO_TRUST_HEADER") == "1" and x_user and not SEC.is_production():
        username = x_user
    if not username:
        raise HTTPException(401, "authentication required")
    u = s.scalars(select(User).where(User.username == username)).first()
    if not u or not u.is_active:
        raise HTTPException(401, "unknown or inactive user")
    return u


def require(perm: str):
    def dep(u: User = Depends(actor)):
        if not has_permission(u, perm):
            raise HTTPException(403, f"missing permission: {perm}")
        return u
    return dep
