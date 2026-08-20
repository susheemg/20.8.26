"""Auto-extracted admin routes (RouterDeps pattern). See app/routers/deps.py.

Behaviour is byte-identical to the pre-split monolith; per-instance deps are bound
as locals (multi-app isolation), invariant models/imports come from bro_app globals.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import (PlainTextResponse, StreamingResponse,
    HTMLResponse, JSONResponse, FileResponse, RedirectResponse)

from .deps import RouterDeps
from ._shared import bind_shared


def build_admin_router(deps: RouterDeps) -> APIRouter:
    import app.bro_app as _M
    globals().update({k: v for k, v in vars(_M).items() if not k.startswith("__")})
    r = APIRouter()
    app = r
    db = deps.db
    actor = deps.actor
    require = deps.require
    audit = deps.audit
    notify = deps.notify
    _fb_guidance = deps.fb_guidance
    _ai_live = deps.ai_live
    AI_HOLDING = deps.ai_holding
    engine = deps.engine
    _platform_version = deps.platform_version
    SessionFactory = deps.session_factory
    _sh = bind_shared(deps)
    _monitor_interval = _sh["_monitor_interval"]
    _rmd_row = _sh["_rmd_row"]
    _file_monitoring_report = _sh["_file_monitoring_report"]
    _ai_research = _sh["_ai_research"]
    # --- build-level imports replicated from the pre-split factory ---
    from app.features.admin import identity as IDP
    from app.features.domain.models_db import hash_password as _hash_pw
    import secrets as _secrets
    from app.features.intelligence import sanctions as SANC
    from app.features.domain.registry_models import SanctionsScreening, WatchlistEntry, VendorPerson
    from app.features.lifecycle import monitoring as MON
    from fastapi.responses import PlainTextResponse
    import csv as _csv, io as _io
    from datetime import datetime as _dt2
    from app.features.assessment import agents as _A
    from app.features.assessment import agent_engine as _AE
    from app.features.domain.models_feature import AgentLearning, BackgroundInsight
    from app.features.domain import registry_service as RS
    from app.features.intelligence import financial as FIN
    from app.features.domain.registry_models import (
        IndustryMaster, MaterialGroupMaster, VendorGroup, VendorRecord,
        VendorIndustry, ContactRecord, EngagementRecord, AssessmentRecord,
        FindingRecord, RemediationRecord, FourthPartyRecord, FourthPartyVendor,
        ArtefactRecord, IssueRecord,
    )
    import json as _json2, os as _os2
    from app.features.lifecycle import performance_service as PERF
    from app.features.platform import platform_docs as PDOCS
    from app.features.assessment import learnings as LEARN
    from app.features.admin import integrations as INTEG
    from app.features.admin import content as CONTENT
    from app.features.admin import layout as LAYOUT


    @app.post("/api/v1/login")
    def login(body: LoginIn, request: Request, s: Session = Depends(db)):
        ip = request.client.host if (request and request.client) else "?"
        if not SEC.check_rate(f"login:{ip}"):
            SEC.log_json("login.rate_limited", ip=ip)
            raise HTTPException(429, "too many login attempts — please slow down")
        rem = SEC.login_locked(body.username)
        if rem:
            raise HTTPException(423, f"account temporarily locked — retry in {rem}s")
        u = s.scalars(select(User).where(User.username == body.username)).first()
        if not u or not verify_password(body.password, u.password_hash):
            SEC.record_login_failure(body.username)
            raise HTTPException(401, "invalid credentials")
        SEC.record_login_success(body.username)
        token = issue_token(u.username, u.role.key)
        import app.features.admin.rbac as _RBAC
        return {"token": token, "token_type": "bearer",
                "username": u.username, "role": u.role.key,
                "permissions": [p.key for p in u.role.permissions],
                "nav_denied": _RBAC.denied_navs(s, u),
                "vendor_id": getattr(u, "vendor_id", None),
                "is_backup": bool(getattr(u, "is_backup", False))}

    # ===== SSO (OIDC) + SCIM provisioning =====
    from app.features.admin import identity as IDP
    from app.features.domain.models_db import hash_password as _hash_pw
    import secrets as _secrets

    def _resolve_role(s: Session, key: Optional[str]) -> Role:
        """Map a role key to a Role row; fall back to least-privilege, never None."""
        for k in (key, "vendor"):
            if k:
                r = s.scalars(select(Role).where(Role.key == k)).first()
                if r:
                    return r
        r = s.scalars(select(Role)).first()
        if not r:
            raise HTTPException(500, "no roles configured")
        return r

    def _upsert_sso_user(s: Session, ident: dict) -> User:
        u = s.scalars(select(User).where(User.username == ident["username"])).first()
        role = _resolve_role(s, ident["role"])
        if not u:
            u = User(username=ident["username"], full_name=ident.get("full_name") or ident["username"],
                     email=ident.get("email"), password_hash=_hash_pw(_secrets.token_hex(24)),
                     role_id=role.id, is_active=True)
            s.add(u); s.flush()
            audit(s, "sso.user_provisioned", ident["username"], {"role": role.key})
        else:
            if u.role_id != role.id:
                u.role_id = role.id
            u.is_active = True
            if ident.get("full_name"):
                u.full_name = ident["full_name"]
        return u

    def _sso_success_page(token: str):
        from fastapi.responses import HTMLResponse
        # Hand the session token to the SPA (held in sessionStorage) and redirect in.
        return HTMLResponse(
            "<!doctype html><meta charset=utf-8><script>"
            f"sessionStorage.setItem('bro_tok',{json.dumps(token)});"
            "location.replace('/');</script>Signing you in…")

    def _complete_sso(s: Session, code: str, provider: str):
        tokens = IDP.exchange_code(code, provider)
        claims = IDP.verify_id_token(tokens["id_token"], provider)
        ident = IDP.claims_to_identity(claims, provider)
        u = _upsert_sso_user(s, ident)
        s.commit()
        return _sso_success_page(issue_token(u.username, u.role.key))

    @app.get("/auth/oidc/login")
    def oidc_login(provider: str = "enterprise"):
        provider = (provider or "enterprise").lower()
        if provider not in IDP.PROVIDERS:
            raise HTTPException(400, "unknown SSO provider")
        if not IDP.oidc_enabled(provider):
            raise HTTPException(404, f"SSO provider '{provider}' is not configured")
        from fastapi.responses import RedirectResponse
        return RedirectResponse(IDP.auth_url(IDP.new_state(provider), provider))

    @app.get("/auth/oidc/callback")
    def oidc_callback(code: str = None, state: str = None, s: Session = Depends(db)):
        # Google / Enterprise return via GET. Provider is recovered from the
        # signed state token so it can't be spoofed via the query string.
        if not code:
            raise HTTPException(400, "missing authorization code")
        try:
            provider = (IDP.read_state(state).get("p") if state else "enterprise") or "enterprise"
        except Exception:
            raise HTTPException(400, "invalid or expired SSO state")
        if not IDP.oidc_enabled(provider):
            raise HTTPException(404, f"SSO provider '{provider}' is not configured")
        try:
            return _complete_sso(s, code, provider)
        except Exception as e:
            raise HTTPException(401, f"SSO sign-in failed: {e}")

    @app.post("/auth/oidc/apple/callback")
    async def apple_callback(request: Request, s: Session = Depends(db)):
        # Sign in with Apple posts the result as form fields (response_mode=form_post).
        form = await request.form()
        code = form.get("code")
        state = form.get("state")
        if not code:
            raise HTTPException(400, "missing authorization code")
        try:
            prov = (IDP.read_state(state).get("p") if state else "apple") or "apple"
        except Exception:
            raise HTTPException(400, "invalid or expired SSO state")
        if prov != "apple" or not IDP.oidc_enabled("apple"):
            raise HTTPException(404, "Apple SSO is not configured")
        try:
            return _complete_sso(s, code, "apple")
        except Exception as e:
            raise HTTPException(401, f"Apple sign-in failed: {e}")

    @app.get("/api/v1/auth/sso-status")
    def sso_status():
        provs = {p: IDP.oidc_enabled(p) for p in IDP.PROVIDERS}
        return {"oidc_enabled": IDP.any_oidc_enabled(),
                "providers": provs,
                "scim_enabled": IDP.scim_enabled()}

    # ---- SCIM 2.0 (RFC 7644): IdP-driven user provisioning ----
    def _scim_guard(authorization: str = Header(default=None)):
        if not IDP.scim_enabled():
            raise HTTPException(404, "SCIM is not enabled")
        if not IDP.scim_token_ok(authorization):
            raise HTTPException(401, "invalid SCIM token")

    @app.get("/scim/v2/Users")
    def scim_list_users(filter: str = None, s: Session = Depends(db),
                        authorization: str = Header(default=None)):
        _scim_guard(authorization)
        rows = s.scalars(select(User)).all()
        if filter and "userName eq " in filter:
            want = filter.split("userName eq ", 1)[1].strip().strip('"')
            rows = [u for u in rows if u.username == want]
        return IDP.scim_list_response([IDP.user_to_scim(u) for u in rows])

    @app.get("/scim/v2/Users/{uid}")
    def scim_get_user(uid: int, s: Session = Depends(db),
                      authorization: str = Header(default=None)):
        _scim_guard(authorization)
        u = s.get(User, uid)
        if not u:
            raise HTTPException(404, "not found")
        return IDP.user_to_scim(u)

    @app.post("/scim/v2/Users", status_code=201)
    def scim_create_user(body: dict = Body(...), s: Session = Depends(db),
                         authorization: str = Header(default=None)):
        _scim_guard(authorization)
        data = IDP.scim_extract(body)
        if not data["username"]:
            raise HTTPException(400, "userName required")
        existing = s.scalars(select(User).where(User.username == data["username"])).first()
        if existing:
            return IDP.user_to_scim(existing)
        role_key = data["role_hint"] or IDP.map_groups_to_role([])
        role = _resolve_role(s, role_key)
        u = User(username=data["username"], full_name=data["full_name"], email=data["email"],
                 password_hash=_hash_pw(_secrets.token_hex(24)),
                 role_id=role.id, is_active=bool(data["active"]))
        s.add(u); s.flush()
        audit(s, "scim.user_created", data["username"], {"role": role.key})
        s.commit()
        return IDP.user_to_scim(u)

    @app.patch("/scim/v2/Users/{uid}")
    @app.put("/scim/v2/Users/{uid}")
    def scim_update_user(uid: int, body: dict = Body(...), s: Session = Depends(db),
                         authorization: str = Header(default=None)):
        _scim_guard(authorization)
        u = s.get(User, uid)
        if not u:
            raise HTTPException(404, "not found")
        # Support both PUT (full resource) and PATCH (Operations) for active/profile.
        if "active" in body:
            u.is_active = bool(body["active"])
        for op in body.get("Operations", []):
            if (op.get("path") == "active") or ("active" in str(op.get("value"))):
                v = op.get("value")
                u.is_active = (v.get("active") if isinstance(v, dict) else bool(v))
        d = IDP.scim_extract(body) if "userName" in body else None
        if d and d.get("full_name"):
            u.full_name = d["full_name"]
        audit(s, "scim.user_updated", u.username, {"active": u.is_active})
        s.commit()
        return IDP.user_to_scim(u)

    @app.delete("/scim/v2/Users/{uid}", status_code=204)
    def scim_delete_user(uid: int, s: Session = Depends(db),
                         authorization: str = Header(default=None)):
        _scim_guard(authorization)
        u = s.get(User, uid)
        if u:
            u.is_active = False  # SCIM delete = deactivate (preserve audit trail)
            audit(s, "scim.user_deactivated", u.username, {})
            s.commit()
        return Response(status_code=204)

    @app.get("/scim/v2/Groups")
    def scim_list_groups(s: Session = Depends(db), authorization: str = Header(default=None)):
        _scim_guard(authorization)
        groups = [{"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
                   "id": str(r.id), "displayName": r.key}
                  for r in s.scalars(select(Role)).all()]
        return IDP.scim_list_response(groups)

    # ===== vendors =====
    @app.get("/api/v1/notifications")
    def notifications(s: Session = Depends(db), u: User = Depends(require("notify.view"))):
        rows = s.scalars(select(Notification).order_by(Notification.id.desc())).all()
        unread = s.scalar(select(func.count()).select_from(Notification)
                          .where(Notification.is_read == False))  # noqa: E712
        return {"unread": unread,
                "items": [{"id": n.id, "event": n.event, "audience": n.audience,
                           "read": n.is_read} for n in rows[:50]]}

    # ===== methodology versioning =====

    @app.post("/api/v1/me/password")
    def change_password(b: PasswordIn, s: Session = Depends(db), u: User = Depends(actor)):
        from app.features.domain.models_db import hash_password
        if not verify_password(b.current_password, u.password_hash):
            raise HTTPException(403, "current password incorrect")
        if len(b.new_password) < 6:
            raise HTTPException(400, "new password too short")
        u.password_hash = hash_password(b.new_password)
        audit(s, "user.password_changed", u.username, {"username": u.username})
        s.commit()
        return {"changed": True}

    # ---- Supplier users (backup users) — managed by Assessors & Controllers ----
    @app.get("/api/v1/supplier-users")
    def list_supplier_users(vendor_id: Optional[str] = None, s: Session = Depends(db),
                            u: User = Depends(require("supplier.manage"))):
        from app.features.domain.models_db import Role
        vrole = s.scalars(select(Role).where(Role.key == "vendor")).first()
        q = select(User).where(User.role_id == vrole.id) if vrole else select(User).where(False)
        if vendor_id:
            q = q.where(User.vendor_id == vendor_id)
        return [{"id": x.id, "username": x.username, "full_name": x.full_name,
                 "email": x.email, "vendor_id": x.vendor_id, "is_backup": bool(x.is_backup),
                 "is_active": x.is_active, "managed_by": x.managed_by}
                for x in s.scalars(q).all()]

    @app.post("/api/v1/supplier-users")
    def create_supplier_user(b: SupplierUserIn, s: Session = Depends(db),
                             u: User = Depends(require("supplier.manage"))):
        from app.features.domain.models_db import hash_password, Role
        if not b.email or "@" not in b.email:
            raise HTTPException(400, "a valid email is required")
        if s.scalars(select(User).where(User.username == b.username)).first():
            raise HTTPException(409, "username already exists")
        if s.scalars(select(User).where(User.email == b.email)).first():
            raise HTTPException(409, "a user with that email already exists")
        vrole = s.scalars(select(Role).where(Role.key == "vendor")).first()
        if not vrole:
            raise HTTPException(500, "vendor role missing")
        # a primary must exist before a backup, and only one backup per vendor
        if b.is_backup:
            has_primary = s.scalars(select(User).where(User.vendor_id == b.vendor_id,
                                    User.role_id == vrole.id, User.is_backup == False)).first()
            if not has_primary:
                raise HTTPException(400, "create the primary supplier user before a backup")
            has_backup = s.scalars(select(User).where(User.vendor_id == b.vendor_id,
                                   User.role_id == vrole.id, User.is_backup == True)).first()
            if has_backup:
                raise HTTPException(409, "a backup user already exists for this vendor")
        row = User(username=b.username, full_name=b.full_name, email=b.email,
                   password_hash=hash_password(b.password), role_id=vrole.id,
                   vendor_id=b.vendor_id, is_backup=bool(b.is_backup),
                   managed_by=u.username, is_active=True)
        s.add(row); s.flush()
        audit(s, "supplier_user.created", u.username,
              {"username": b.username, "vendor_id": b.vendor_id, "backup": bool(b.is_backup)})
        s.commit()
        return {"id": row.id, "username": row.username, "is_backup": row.is_backup}

    @app.patch("/api/v1/supplier-users/{uid}")
    def update_supplier_user(uid: int, b: SupplierUserUpdateIn, s: Session = Depends(db),
                             u: User = Depends(require("supplier.manage"))):
        from app.features.domain.models_db import Role, hash_password
        row = s.get(User, uid)
        vrole = s.scalars(select(Role).where(Role.key == "vendor")).first()
        if not row or not vrole or row.role_id != vrole.id:
            raise HTTPException(404, "supplier user not found")
        d = b.model_dump(exclude_none=True)
        if "password" in d:
            row.password_hash = hash_password(d.pop("password"))
        for f, val in d.items():
            setattr(row, f, val)
        audit(s, "supplier_user.updated", u.username, {"username": row.username})
        s.commit()
        return {"updated": True, "username": row.username, "is_active": row.is_active,
                "is_backup": bool(row.is_backup)}

    @app.post("/api/v1/supplier-users/{uid}/enable")
    def enable_supplier_user(uid: int, s: Session = Depends(db),
                             u: User = Depends(require("supplier.manage"))):
        return _toggle_supplier_user(s, uid, True, u)

    @app.post("/api/v1/supplier-users/{uid}/disable")
    def disable_supplier_user(uid: int, s: Session = Depends(db),
                              u: User = Depends(require("supplier.manage"))):
        return _toggle_supplier_user(s, uid, False, u)

    def _toggle_supplier_user(s, uid, active, u):
        from app.features.domain.models_db import Role
        row = s.get(User, uid)
        vrole = s.scalars(select(Role).where(Role.key == "vendor")).first()
        if not row or not vrole or row.role_id != vrole.id:
            raise HTTPException(404, "supplier user not found")
        row.is_active = active
        audit(s, "supplier_user." + ("enabled" if active else "disabled"), u.username,
              {"username": row.username})
        s.commit()
        return {"username": row.username, "is_active": active}

    @app.get("/api/v1/me")
    def my_profile(s: Session = Depends(db), u: User = Depends(actor)):
        import app.features.admin.rbac as RBAC
        ctx = {}
        vid = getattr(u, "vendor_id", None)
        rk = u.role.key if u.role else None
        # non-editable: supplier name for supplier users
        if vid:
            try:
                vr = s.scalars(select(VendorRecord).where(VendorRecord.vendor_id == vid)).first()
                ctx["supplier_name"] = vr.legal_name if vr else None
                ctx["supplier_id"] = vid
            except Exception:
                pass
        # non-editable: business units for business users (buyers)
        if rk == "buyer":
            try:
                bus = set()
                for e in s.scalars(select(EngagementRecord).where(EngagementRecord.owner_user == u.username)).all():
                    if getattr(e, "business_unit", None):
                        bus.add(e.business_unit)
                ctx["business_units"] = sorted(bus)
            except Exception:
                pass
        return {"username": u.username, "full_name": u.full_name,
                "email": u.email, "role": rk,
                "phone": getattr(u, "phone", None),
                "secondary_email": getattr(u, "secondary_email", None),
                "timezone": getattr(u, "timezone", None),
                "created_at": u.created_at.isoformat() if getattr(u, "created_at", None) else None,
                "last_login": u.last_login.isoformat() if getattr(u, "last_login", None) else None,
                "vendor_id": vid,
                "is_backup": bool(getattr(u, "is_backup", False)),
                "profile_context": ctx,
                "permissions": RBAC.user_permissions(s, u),
                "nav_denied": RBAC.denied_navs(s, u)}

    @app.get("/api/v1/me/activity")
    def my_activity(limit: int = 200, s: Session = Depends(db), u: User = Depends(actor)):
        rows = s.scalars(select(AuditLog).where(AuditLog.actor == u.username)
                         .order_by(AuditLog.seq.desc()).limit(min(max(limit, 1), 500))).all()
        return [{"seq": r.seq, "action": r.action, "detail": r.detail,
                 "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]

    @app.patch("/api/v1/me")
    def update_profile(b: ProfileIn, s: Session = Depends(db), u: User = Depends(actor)):
        for f, val in b.model_dump(exclude_none=True).items():
            setattr(u, f, val)
        audit(s, "user.profile_updated", u.username, {"username": u.username})
        s.commit()
        return {"updated": True}

    # ---- Admin: users ----
    @app.get("/api/v1/privacy/data-map")
    def privacy_data_map(u: User = Depends(require("admin.config"))):
        """The personal-data map for DPO review (DB-03)."""
        from app.features.admin import privacy as _P
        return _P.data_flow_report()

    @app.get("/api/v1/privacy/erasure-plan")
    def privacy_erasure_plan(subject: str, s: Session = Depends(db),
                             u: User = Depends(require("admin.config"))):
        """Report-only: what an erasure request for this subject would do, table by
        table, including what would be retained and on what basis."""
        from app.features.admin import privacy as _P
        return _P.erasure_plan(s, subject)

    @app.post("/api/v1/privacy/erasure")
    def privacy_erasure(subject: str, confirm: bool = False, s: Session = Depends(db),
                        u: User = Depends(require("admin.config"))):
        """Execute an erasure. Defaults to a dry run — erasure is irreversible and must
        not be one accidental call away. Blocked until the map is signed by Legal/DPO."""
        from app.features.admin import privacy as _P
        return _P.execute_erasure(s, subject, actor=u.username, dry_run=not confirm,
                                  audit_fn=audit)

    @app.get("/api/v1/admin/users")
    def list_users(q: Optional[str] = None, s: Session = Depends(db),
                   u: User = Depends(require("admin.users"))):
        rows = s.scalars(select(User)).all()
        if q:
            ql = q.strip().lower()
            rows = [x for x in rows if ql in (x.username or "").lower()
                    or ql in (x.full_name or "").lower()
                    or ql in (x.email or "").lower()
                    or ql in (x.role.key if x.role else "").lower()]
        return [{"id": x.id, "username": x.username, "full_name": x.full_name,
                 "email": x.email, "role": x.role.key if x.role else None,
                 "is_active": x.is_active,
                 "last_login": x.last_login.isoformat() if x.last_login else None}
                for x in rows]

    @app.post("/api/v1/admin/users")
    def create_user(b: UserIn, s: Session = Depends(db), u: User = Depends(require("admin.users"))):
        from app.features.domain.models_db import hash_password
        if not b.email or "@" not in b.email or "." not in b.email.split("@")[-1]:
            raise HTTPException(400, "a valid email address is required for every user "
                                     "(notifications are triggered to it)")
        if s.scalars(select(User).where(User.username == b.username)).first():
            raise HTTPException(409, "username exists")
        if s.scalars(select(User).where(User.email == b.email)).first():
            raise HTTPException(409, "a user with that email already exists")
        role = s.scalars(select(Role).where(Role.key == b.role_key)).first()
        if not role:
            raise HTTPException(400, "unknown role")
        row = User(username=b.username, full_name=b.full_name, email=b.email,
                   password_hash=hash_password(b.password), role_id=role.id)
        s.add(row); s.flush()
        audit(s, "user.created", u.username, {"username": b.username, "role": b.role_key})
        s.commit()
        return {"id": row.id, "username": row.username}

    @app.patch("/api/v1/admin/users/{uid}")
    def update_user(uid: int, b: UserUpdateIn, s: Session = Depends(db),
                    u: User = Depends(require("admin.users"))):
        target = s.get(User, uid)
        if not target:
            raise HTTPException(404, "user not found")
        data = b.model_dump(exclude_none=True)
        if "role_key" in data:
            role = s.scalars(select(Role).where(Role.key == data.pop("role_key"))).first()
            if not role:
                raise HTTPException(400, "unknown role")
            target.role_id = role.id
        for f, val in data.items():
            setattr(target, f, val)
        audit(s, "user.updated", u.username, {"user_id": uid})
        s.commit()
        return {"user_id": uid, "updated": True}

    @app.delete("/api/v1/admin/users/{uid}")
    def deactivate_user(uid: int, s: Session = Depends(db), u: User = Depends(require("admin.users"))):
        target = s.get(User, uid)
        if not target:
            raise HTTPException(404, "user not found")
        if target.username == "admin":
            raise HTTPException(400, "cannot deactivate the seed admin")
        target.is_active = False
        audit(s, "user.deactivated", u.username, {"user_id": uid})
        s.commit()
        return {"user_id": uid, "is_active": False}

    # ---- Admin: roles & permissions ----
    @app.get("/api/v1/admin/roles")
    def list_roles(s: Session = Depends(db), u: User = Depends(require("admin.roles"))):
        return [{"key": r.key, "label": r.label, "is_system": r.is_system,
                 "permissions": [p.key for p in r.permissions]}
                for r in s.scalars(select(Role)).all()]

    @app.get("/api/v1/admin/permissions")
    def list_permissions(s: Session = Depends(db), u: User = Depends(require("admin.roles"))):
        from app.features.domain.models_db import Permission
        return [{"key": p.key, "label": p.label, "category": p.category}
                for p in s.scalars(select(Permission)).all()]

    @app.put("/api/v1/admin/roles/{rkey}/permissions")
    def set_role_perms(rkey: str, b: RolePermsIn, s: Session = Depends(db),
                       u: User = Depends(require("admin.roles"))):
        from app.features.domain.models_db import Permission
        role = s.scalars(select(Role).where(Role.key == rkey)).first()
        if not role:
            raise HTTPException(404, "role not found")
        perms = s.scalars(select(Permission).where(Permission.key.in_(b.permission_keys))).all()
        role.permissions = list(perms)
        audit(s, "role.permissions_set", u.username, {"role": rkey, "count": len(perms)})
        s.commit()
        return {"role": rkey, "permissions": [p.key for p in perms]}

    @app.get("/api/v1/admin/rbac/matrix")
    def rbac_matrix(s: Session = Depends(db), u: User = Depends(require("admin.roles"))):
        """Broad role x permission grid with graded access (read/write/modify/denied)."""
        from app.features.domain.models_db import Permission
        import app.features.admin.rbac as RBAC
        roles = [{"key": r.key, "label": r.label, "color": r.color,
                  "is_system": r.is_system, "all": (r.key == "admin")}
                 for r in s.scalars(select(Role).order_by(Role.id)).all()]
        perms = [{"key": p.key, "label": p.label, "category": p.category}
                 for p in s.scalars(select(Permission)).all()]
        # stable category order
        cats = []
        for p in perms:
            if p["category"] not in cats:
                cats.append(p["category"])
        return {"roles": roles, "permissions": perms, "categories": cats,
                "levels": RBAC.ACCESS_LEVELS, "grants": RBAC.access_matrix(s)}

    @app.put("/api/v1/admin/rbac/cell")
    def rbac_set_cell(b: RbacCellIn, s: Session = Depends(db),
                      u: User = Depends(require("admin.roles"))):
        import app.features.admin.rbac as RBAC
        if b.role_key == "admin":
            raise HTTPException(400, "the Administrator role has full access and cannot be edited")
        try:
            r = RBAC.set_access(s, b.role_key, b.perm_key, b.access, actor=u.username)
        except KeyError:
            raise HTTPException(404, "unknown role or permission")
        except ValueError as e:
            raise HTTPException(400, str(e))
        audit(s, "rbac.cell_set", u.username,
              {"role": b.role_key, "perm": b.perm_key, "access": b.access})
        s.commit()
        return r

    # ---- Admin: webhooks ----
    @app.get("/api/v1/admin/webhooks")
    def list_webhooks(s: Session = Depends(db), u: User = Depends(require("admin.webhooks"))):
        return [{"id": w.id, "url": w.url, "event": w.event, "active": w.active}
                for w in s.scalars(select(Webhook)).all()]

    @app.post("/api/v1/admin/webhooks")
    def add_webhook(b: WebhookIn, s: Session = Depends(db), u: User = Depends(require("admin.webhooks"))):
        row = Webhook(url=b.url, event=b.event); s.add(row); s.flush()
        audit(s, "webhook.added", u.username, {"id": row.id, "url": b.url})
        s.commit()
        return {"webhook_id": row.id}

    @app.delete("/api/v1/admin/webhooks/{wid}")
    def del_webhook(wid: int, s: Session = Depends(db), u: User = Depends(require("admin.webhooks"))):
        w = s.get(Webhook, wid)
        if not w:
            raise HTTPException(404, "webhook not found")
        s.delete(w); audit(s, "webhook.deleted", u.username, {"id": wid}); s.commit()
        return {"deleted": True}

    # ---- Notifications: mark read ----
    @app.post("/api/v1/notifications/{nid}/read")
    def mark_read(nid: int, s: Session = Depends(db), u: User = Depends(require("notify.view"))):
        n = s.get(Notification, nid)
        if not n:
            raise HTTPException(404, "notification not found")
        n.is_read = True; s.commit()
        return {"id": nid, "read": True}

    @app.post("/api/v1/notifications/read-all")
    def mark_all_read(s: Session = Depends(db), u: User = Depends(require("notify.view"))):
        rows = s.scalars(select(Notification).where(Notification.is_read == False)).all()  # noqa: E712
        for n in rows:
            n.is_read = True
        s.commit()
        return {"marked": len(rows)}

    # ---- Email: send (real SMTP or simulation outbox) ----
    @app.post("/api/v1/email/send")
    def email_send(b: EmailIn, s: Session = Depends(db), u: User = Depends(require("admin.email"))):
        from app.features.admin import email_service
        sent = False
        try:
            sent = email_service.send_email(b.to_addr, b.subject, b.body)
        except Exception as e:  # SMTP failure -> fall back to outbox
            audit(s, "email.send_failed", u.username, {"to": b.to_addr, "error": str(e)[:120]})
        s.add(EmailOutbox(to_addr=b.to_addr, subject=b.subject, body=b.body, sent=sent))
        audit(s, "email.queued" if not sent else "email.sent", u.username, {"to": b.to_addr})
        s.commit()
        return {"to": b.to_addr, "sent": sent, "mode": "smtp" if sent else "simulation"}

    @app.get("/api/v1/email/outbox")
    def email_outbox(s: Session = Depends(db), u: User = Depends(require("admin.email"))):
        return [{"id": e.id, "to": e.to_addr, "subject": e.subject, "sent": e.sent}
                for e in s.scalars(select(EmailOutbox).order_by(EmailOutbox.id.desc())).all()]

    # ---- Evidence renewal chase (uses email path) ----
    @app.get("/api/v1/notifications/catalogue")
    def notif_catalogue(s: Session = Depends(db), u: User = Depends(require("admin.integrations"))):
        from app.features.admin import notifications as NOTIF
        return {"catalogue": NOTIF.CATALOGUE, "settings": NOTIF.get_settings(s), "audiences": NOTIF.AUDIENCES}

    @app.post("/api/v1/notifications/settings")
    def notif_settings(body: dict = Body(default={}), s: Session = Depends(db),
                       u: User = Depends(require("admin.integrations"))):
        from app.features.admin import notifications as NOTIF
        out = NOTIF.set_settings(s, body.get("settings") or {})
        audit(s, "notifications.settings", u.username, {"enabled": [k for k, v in out.items() if v["enabled"]]})
        return {"settings": out}

    @app.get("/api/v1/notifications/inbox")
    def notif_inbox(s: Session = Depends(db), u: User = Depends(require("vendor.view"))):
        from app.features.admin import notifications as NOTIF
        return {"items": NOTIF.inbox(s, 50), "unread": NOTIF.unread_count(s)}

    @app.post("/api/v1/notifications/read")
    def notif_read(body: dict = Body(default={}), s: Session = Depends(db),
                   u: User = Depends(require("vendor.view"))):
        from app.features.admin import notifications as NOTIF
        NOTIF.mark_read(s, body.get("id")); return {"unread": NOTIF.unread_count(s)}

    # ---- Notification templates (admin-authored, multi-group, editable) ----
    @app.get("/api/v1/notifications/groups")
    def notif_groups(s: Session = Depends(db), u: User = Depends(require("admin.email"))):
        """Selectable user groups = roles, with a live member/emailable count."""
        from app.features.admin import notifications as NOTIF
        out = []
        for r in s.scalars(select(Role).order_by(Role.id)).all():
            members = s.scalars(select(User).where(User.role_id == r.id,
                                                   User.is_active == True)).all()
            out.append({"key": r.key, "label": r.label, "color": r.color,
                        "members": len(members),
                        "emailable": sum(1 for m in members if m.email)})
        return {"groups": out}

    @app.get("/api/v1/notifications/templates")
    def notif_tpl_list(s: Session = Depends(db), u: User = Depends(require("admin.email"))):
        from app.features.admin import notifications as NOTIF
        return {"templates": NOTIF.list_templates(s)}

    @app.post("/api/v1/notifications/templates")
    def notif_tpl_create(b: NotifTemplateIn, s: Session = Depends(db),
                         u: User = Depends(require("admin.email"))):
        from app.features.admin import notifications as NOTIF
        t = NOTIF.create_template(s, b.name, b.subject or "", b.body or "",
                                  b.groups or [], actor=u.username)
        audit(s, "notif.template_created", u.username, {"name": b.name})
        return t

    @app.put("/api/v1/notifications/templates/{tid}")
    def notif_tpl_update(tid: int, b: NotifTemplateUpdateIn, s: Session = Depends(db),
                         u: User = Depends(require("admin.email"))):
        from app.features.admin import notifications as NOTIF
        t = NOTIF.update_template(s, tid, b.model_dump(exclude_none=True), actor=u.username)
        if not t:
            raise HTTPException(404, "template not found")
        audit(s, "notif.template_updated", u.username, {"id": tid})
        return t

    @app.delete("/api/v1/notifications/templates/{tid}")
    def notif_tpl_delete(tid: int, s: Session = Depends(db),
                         u: User = Depends(require("admin.email"))):
        from app.features.admin import notifications as NOTIF
        NOTIF.delete_template(s, tid)
        audit(s, "notif.template_deleted", u.username, {"id": tid})
        return {"deleted": tid}

    @app.post("/api/v1/notifications/templates/{tid}/trigger")
    def notif_tpl_trigger(tid: int, s: Session = Depends(db),
                          u: User = Depends(require("admin.email"))):
        from app.features.admin import notifications as NOTIF
        r = NOTIF.trigger_template(s, tid, actor=u.username)
        if r.get("error"):
            raise HTTPException(404, "template not found")
        audit(s, "notif.template_triggered", u.username,
              {"id": tid, "recipients": r.get("recipients")})
        return r

    @app.get("/api/v2/i18n/languages")
    def v2_i18n_languages(u: User = Depends(actor)):
        from app.features.admin import i18n as I18N
        return {"languages": I18N.LANGUAGES}

    @app.post("/api/v2/i18n/translate")
    def v2_i18n_translate(b: I18nTranslateIn, u: User = Depends(actor)):
        from app.features.admin import i18n as I18N
        res = I18N.translate_strings(b.strings or [], b.lang)
        if isinstance(res, dict) and "_map" in res:
            return {"translations": res["_map"], "ai": res["_ai"], "lang": b.lang}
        return {"translations": res or {}, "ai": False, "lang": b.lang}

    @app.post("/api/v2/i18n/normalize")
    def v2_i18n_normalize(b: I18nTextIn, s: Session = Depends(db), u: User = Depends(actor)):
        from app.features.admin import i18n as I18N
        res = I18N.to_english(b.text or "", b.lang)
        audit(s, "v2.i18n_normalize", u.username,
              {"detected": res.get("detected_language"), "chars": len(b.text or "")})
        s.commit()
        return res

    @app.post("/api/v2/i18n/document")
    def v2_i18n_document(b: I18nTextIn, s: Session = Depends(db), u: User = Depends(actor)):
        from app.features.admin import i18n as I18N
        res = I18N.translate_document(b.text or "")
        audit(s, "v2.i18n_document", u.username,
              {"detected": res.get("detected_language"), "chars": len(b.text or "")})
        s.commit()
        return res

    # ===== Critical Vendor Modelling (transparency) =====
    @app.post("/api/v2/artefacts/email-intake")
    def v2_email_intake(b: EmailIntakeIn, s: Session = Depends(db),
                        u: User = Depends(require("lifecycle.documents"))):
        from app.features.admin import email_intake as EI
        result = EI.process_inbound_email(
            s, sender=b.sender, subject=b.subject or "",
            attachment_name=b.attachment_name or "", attachment_b64=b.attachment_b64,
            body_text=b.body_text or "", vendor_id=b.vendor_id)
        audit(s, "v2.email_intake", u.username,
              {"status": result["status"], "artefact_id": result.get("artefact_id")})
        s.commit()
        return result

    # ---- analysis-section support: sectors, peers, research, monitoring ----
    @app.get("/api/v2/integrations/catalog")
    def v2_integrations_catalog(u: User = Depends(require("admin.integrations"))):
        """The catalogue of available external connectors (no secrets)."""
        return {"connectors": INTEG.catalog()}

    @app.get("/api/v2/integrations")
    def v2_integrations_list(s: Session = Depends(db),
                             u: User = Depends(require("admin.integrations"))):
        return {"connectors": [INTEG.config_row(s, c.key) for c in
                               [INTEG._CONNECTORS[k]() for k in INTEG._CONNECTORS]]}

    @app.get("/api/v2/integrations/{key}")
    def v2_integration_get(key: str, s: Session = Depends(db),
                           u: User = Depends(require("admin.integrations"))):
        if key not in INTEG._CONNECTORS:
            raise HTTPException(404, "unknown connector")
        return INTEG.config_row(s, key)

    @app.put("/api/v2/integrations/{key}")
    def v2_integration_config(key: str, b: ConnectorConfigIn, s: Session = Depends(db),
                              u: User = Depends(require("admin.integrations"))):
        try:
            row = INTEG.upsert_config(s, key, enabled=b.enabled, base_url=b.base_url,
                                      secret_name=b.secret_name, config=b.config, actor=u.username)
        except KeyError:
            raise HTTPException(404, "unknown connector")
        audit(s, "v2.connector_configured", u.username, {"connector": key, "enabled": b.enabled})
        s.commit()
        return row

    @app.post("/api/v2/integrations/{key}/test")
    def v2_integration_test(key: str, s: Session = Depends(db),
                            u: User = Depends(require("admin.integrations"))):
        conn = INTEG.get_connector(s, key)
        if not conn:
            raise HTTPException(404, "unknown connector")
        res = conn.test_connection()
        audit(s, "v2.connector_test", u.username, {"connector": key, "mode": res.get("mode")})
        return res

    @app.post("/api/v2/integrations/{key}/sync")
    def v2_integration_sync(key: str, b: ConnectorSyncIn, s: Session = Depends(db),
                            u: User = Depends(require("admin.integrations"))):
        if key not in INTEG._CONNECTORS:
            raise HTTPException(404, "unknown connector")
        if b.vendor_id:
            res = INTEG.sync_vendor(s, key, b.vendor_id, actor=u.username)
            audit(s, "v2.connector_sync", u.username, {"connector": key, "vendor_id": b.vendor_id})
            s.commit()
            return res
        # all (or an explicit set) — capped for safety
        from app.features.domain.registry_models import VendorRecord
        vids = b.vendor_ids or [v.vendor_id for v in
                                s.scalars(select(VendorRecord).limit(200)).all()]
        res = INTEG.sync_all_vendors(s, key, vids, actor=u.username)
        audit(s, "v2.connector_sync_all", u.username, {"connector": key, "vendors": len(vids)})
        s.commit()
        return res

    @app.get("/api/v2/integrations/{key}/logs")
    def v2_integration_logs(key: str, s: Session = Depends(db),
                            u: User = Depends(require("admin.integrations"))):
        if key not in INTEG._CONNECTORS:
            raise HTTPException(404, "unknown connector")
        return {"logs": INTEG.recent_logs(s, key)}

    # ================= CONTENT STUDIO ("Admin Change") =================
    from app.features.admin import content as CONTENT

    @app.get("/api/v2/content/overrides")
    def v2_content_overrides(s: Session = Depends(db)):
        """Public: the effective default->override map the client applies. No
        sensitive data — only custom UI copy — so the login screen localises too."""
        return {"overrides": CONTENT.overrides_map(s)}

    @app.get("/api/v2/content/registry")
    def v2_content_registry(s: Session = Depends(db),
                            u: User = Depends(require("admin.content"))):
        return CONTENT.registry_rows(s)

    @app.put("/api/v2/content/item/{key:path}")
    def v2_content_set(key: str, b: ContentSetIn, s: Session = Depends(db),
                       u: User = Depends(require("admin.content"))):
        try:
            r = CONTENT.set_override(s, key, b.value, actor=u.username)
        except KeyError:
            raise HTTPException(404, "unknown content key")
        audit(s, "v2.content_set", u.username, {"key": key})
        s.commit()
        return r

    @app.post("/api/v2/content/item/{key:path}/reset")
    def v2_content_reset(key: str, s: Session = Depends(db),
                         u: User = Depends(require("admin.content"))):
        r = CONTENT.reset(s, key)
        audit(s, "v2.content_reset", u.username, {"key": key})
        s.commit()
        return r

    @app.post("/api/v2/content/custom")
    def v2_content_custom(b: ContentCustomIn, s: Session = Depends(db),
                          u: User = Depends(require("admin.content"))):
        try:
            r = CONTENT.add_custom(s, b.source_text, b.value, actor=u.username)
        except ValueError as e:
            raise HTTPException(400, str(e))
        audit(s, "v2.content_custom", u.username, {"source": b.source_text[:60]})
        s.commit()
        return r

    @app.post("/api/v2/content/reset-all")
    def v2_content_reset_all(s: Session = Depends(db),
                             u: User = Depends(require("admin.content"))):
        r = CONTENT.reset_all(s)
        audit(s, "v2.content_reset_all", u.username, r)
        s.commit()
        return r

    @app.get("/api/v2/content/export")
    def v2_content_export(s: Session = Depends(db),
                          u: User = Depends(require("admin.content"))):
        return CONTENT.export_all(s)

    @app.post("/api/v2/content/import")
    def v2_content_import(b: ContentImportIn, s: Session = Depends(db),
                          u: User = Depends(require("admin.content"))):
        r = CONTENT.import_all(s, b.data, actor=u.username)
        audit(s, "v2.content_import", u.username, r)
        s.commit()
        return r

    # ================= NAV & LAYOUT CONFIG (structural) =================
    from app.features.admin import layout as LAYOUT

    @app.get("/api/v2/layout/config")
    def v2_layout_config(s: Session = Depends(db)):
        """Public: the nav show/hide + order map the client applies to the shell."""
        return LAYOUT.layout_config(s)

    @app.get("/api/v2/layout/catalog")
    def v2_layout_catalog(s: Session = Depends(db),
                          u: User = Depends(require("admin.content"))):
        return LAYOUT.catalog(s)

    @app.put("/api/v2/layout/item/{datav}")
    def v2_layout_item(datav: str, b: LayoutItemIn, s: Session = Depends(db),
                       u: User = Depends(require("admin.content"))):
        try:
            r = LAYOUT.set_item(s, datav, hidden=b.hidden, sort_order=b.order, actor=u.username)
        except KeyError:
            raise HTTPException(404, "unknown nav item")
        except ValueError as e:
            raise HTTPException(400, str(e))
        audit(s, "v2.layout_item", u.username, {"item": datav})
        s.commit()
        return r

    @app.put("/api/v2/layout/group/{slug}")
    def v2_layout_group(slug: str, b: LayoutItemIn, s: Session = Depends(db),
                        u: User = Depends(require("admin.content"))):
        try:
            r = LAYOUT.set_group(s, slug, hidden=b.hidden, sort_order=b.order, actor=u.username)
        except KeyError:
            raise HTTPException(404, "unknown group")
        audit(s, "v2.layout_group", u.username, {"group": slug})
        s.commit()
        return r

    @app.post("/api/v2/layout/reorder")
    def v2_layout_reorder(b: LayoutReorderIn, s: Session = Depends(db),
                          u: User = Depends(require("admin.content"))):
        r = LAYOUT.reorder_group(s, b.slug, b.order, actor=u.username)
        audit(s, "v2.layout_reorder", u.username, {"group": b.slug})
        s.commit()
        return r

    @app.post("/api/v2/layout/reset-all")
    def v2_layout_reset(s: Session = Depends(db),
                        u: User = Depends(require("admin.content"))):
        r = LAYOUT.reset_all(s)
        audit(s, "v2.layout_reset", u.username, r)
        s.commit()
        return r

    # ================= ENGAGEMENT ASSESSMENT REPORT (Vendor 360) =================

    return r
