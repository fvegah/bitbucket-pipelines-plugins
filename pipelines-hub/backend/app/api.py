"""API REST consumida por el front."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app import service
from app.config import get_settings
from app.crypto import encrypt
from app.db import Account, Repo, SessionLocal, Source
from app.providers import PROVIDERS, build_provider, drop_provider, provider_for
from app.providers.base import ProviderError
from app.service import iso
from app.sync import syncer

router = APIRouter(prefix="/api")


# --- esquemas ---------------------------------------------------------------------------
class CredentialsIn(BaseModel):
    provider: Literal["github", "bitbucket", "cloudflare"]
    token: str = Field(min_length=1)
    username: str | None = None  # email de Atlassian para API tokens de Bitbucket
    api_url: str | None = None


class AccountIn(CredentialsIn):
    name: str = Field(min_length=1, max_length=100)


class AccountPatch(BaseModel):
    name: str | None = None
    token: str | None = None
    username: str | None = None
    api_url: str | None = None


class SourceIn(BaseModel):
    kind: Literal["org", "user", "workspace", "account"]
    slug: str = Field(min_length=1, max_length=200)
    display_name: str | None = None
    avatar_url: str | None = None
    repo_filter: str | None = None
    max_repos: int | None = Field(default=None, ge=1, le=100)
    active_days: int | None = Field(default=None, ge=1, le=3650)


class SourcePatch(BaseModel):
    enabled: bool | None = None
    repo_filter: str | None = None
    max_repos: int | None = Field(default=None, ge=1, le=100)
    active_days: int | None = Field(default=None, ge=1, le=3650)


class RepoPatch(BaseModel):
    pinned: bool | None = None
    muted: bool | None = None


class RerunIn(BaseModel):
    failed_only: bool = False


class ViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scope: Literal["runs", "prs", "deployments"] = "runs"
    filter: dict = Field(default_factory=dict)
    position: int | None = None


class PRActionIn(BaseModel):
    body: str | None = None
    strategy: Literal["merge", "squash", "rebase"] | None = None
    close_source_branch: bool = False


def _account_dict(a: Account) -> dict:
    return {
        "id": a.id,
        "provider": a.provider,
        "name": a.name,
        "username": a.username,
        "api_url": a.api_url,
        "login": a.login,
        "avatar_url": a.avatar_url,
        "status": a.status,
        "status_detail": a.status_detail,
        "rate_remaining": a.rate_remaining,
        "rate_limit": a.rate_limit,
        "backoff_until": iso(a.backoff_until),
        "created_at": iso(a.created_at),
        "sources": [_source_dict(s) for s in a.sources],
    }


def _source_dict(s: Source) -> dict:
    repos = s.repos if "repos" in s.__dict__ else []
    return {
        "id": s.id,
        "account_id": s.account_id,
        "kind": s.kind,
        "slug": s.slug,
        "display_name": s.display_name,
        "avatar_url": s.avatar_url,
        "enabled": s.enabled,
        "repo_filter": s.repo_filter,
        "max_repos": s.max_repos,
        "active_days": s.active_days,
        "last_synced_at": iso(s.last_synced_at),
        "last_error": s.last_error,
        "repo_count": len(repos),
        "tracked_count": sum(1 for r in repos if r.tracked),
    }


def _err(e: Exception) -> HTTPException:
    if isinstance(e, service.ServiceError):
        return HTTPException(e.status_code, e.message)
    if isinstance(e, ProviderError):
        code = e.status_code if e.status_code in (400, 401, 403, 404, 409, 422, 429) else 502
        return HTTPException(code, e.message)
    return HTTPException(500, str(e))


async def _validate(provider: str, token: str, username: str | None, api_url: str | None):
    p = build_provider(provider, token, username, api_url)
    try:
        return await p.whoami()
    except ProviderError as e:
        raise _err(e) from e
    finally:
        await p.aclose()


_ACCOUNT_OPTS = [selectinload(Account.sources).selectinload(Source.repos)]


# --- cuentas -----------------------------------------------------------------------------
@router.get("/accounts")
async def list_accounts():
    async with SessionLocal() as s:
        rows = (await s.execute(select(Account).options(*_ACCOUNT_OPTS)
                                .order_by(Account.id))).scalars()
        return [_account_dict(a) for a in rows]


@router.post("/accounts/test")
async def test_account(body: CredentialsIn):
    ident = await _validate(body.provider, body.token, body.username, body.api_url)
    return asdict(ident)


@router.post("/accounts", status_code=201)
async def create_account(body: AccountIn):
    ident = await _validate(body.provider, body.token, body.username, body.api_url)
    async with SessionLocal() as s:
        a = Account(
            provider=body.provider, name=body.name.strip(),
            username=(body.username or "").strip() or None,
            api_url=(body.api_url or "").strip() or None,
            secret_enc=encrypt(body.token.strip()),
            login=ident.login, avatar_url=ident.avatar_url, status="ok", user_id=ident.id,
        )
        s.add(a)
        await s.commit()
        a = await s.get(Account, a.id, options=_ACCOUNT_OPTS, populate_existing=True)
        return _account_dict(a)


@router.patch("/accounts/{account_id}")
async def update_account(account_id: int, body: AccountPatch):
    async with SessionLocal() as s:
        a = await s.get(Account, account_id, options=_ACCOUNT_OPTS)
        if not a:
            raise HTTPException(404, "Cuenta no encontrada")
        if body.name is not None:
            a.name = body.name.strip()
        if body.username is not None:
            a.username = body.username.strip() or None
        if body.api_url is not None:
            a.api_url = body.api_url.strip() or None
        if body.token:
            a.secret_enc = encrypt(body.token.strip())
        if body.token or body.username is not None or body.api_url is not None:
            await drop_provider(a.id)
            try:
                ident = await provider_for(a).whoami()
            except ProviderError as e:
                raise _err(e) from e
            a.login, a.avatar_url, a.user_id = ident.login, ident.avatar_url, ident.id
            a.status, a.status_detail, a.backoff_until = "ok", None, None
        await s.commit()
        a = await s.get(Account, account_id, options=_ACCOUNT_OPTS, populate_existing=True)
        return _account_dict(a)


@router.post("/accounts/{account_id}/revalidate")
async def revalidate_account(account_id: int):
    async with SessionLocal() as s:
        a = await s.get(Account, account_id, options=_ACCOUNT_OPTS)
        if not a:
            raise HTTPException(404, "Cuenta no encontrada")
        try:
            ident = await provider_for(a).whoami()
            a.login, a.avatar_url, a.user_id = ident.login, ident.avatar_url, ident.id
            a.status, a.status_detail, a.backoff_until = "ok", None, None
        except ProviderError as e:
            a.status, a.status_detail = "error", e.message
        await s.commit()
        syncer.wake()
        return _account_dict(a)


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(account_id: int):
    async with SessionLocal() as s:
        a = await s.get(Account, account_id)
        if not a:
            raise HTTPException(404, "Cuenta no encontrada")
        await s.delete(a)
        await s.commit()
    await drop_provider(account_id)


@router.get("/accounts/{account_id}/discover")
async def discover(account_id: int):
    async with SessionLocal() as s:
        a = await s.get(Account, account_id, options=[selectinload(Account.sources)])
        if not a:
            raise HTTPException(404, "Cuenta no encontrada")
        added = {src.slug.lower() for src in a.sources}
        try:
            found = await provider_for(a).discover_sources()
        except ProviderError as e:
            raise _err(e) from e
    return [{**asdict(f), "added": f.slug.lower() in added} for f in found]


# --- organizaciones / workspaces ---------------------------------------------------------
@router.post("/accounts/{account_id}/sources", status_code=201)
async def add_source(account_id: int, body: SourceIn):
    st = get_settings()
    async with SessionLocal() as s:
        a = await s.get(Account, account_id)
        if not a:
            raise HTTPException(404, "Cuenta no encontrada")
        expected = {"bitbucket": {"workspace"}, "github": {"org", "user"},
                    "cloudflare": {"account"}}[a.provider]
        if body.kind not in expected:
            raise HTTPException(422, f"Para {a.provider} se agregan: {', '.join(expected)}")
        src = Source(
            account_id=a.id, kind=body.kind, slug=body.slug.strip(),
            display_name=body.display_name or body.slug.strip(), avatar_url=body.avatar_url,
            repo_filter=(body.repo_filter or "").strip() or None,
            max_repos=body.max_repos or st.default_max_repos,
            active_days=body.active_days or st.default_active_days,
        )
        s.add(src)
        try:
            await s.commit()
        except IntegrityError as e:
            raise HTTPException(409, f"{body.slug} ya está agregada en esta cuenta") from e
        src_id = src.id
    syncer.wake()
    async with SessionLocal() as s:
        src = await s.get(Source, src_id, options=[selectinload(Source.repos)])
        return _source_dict(src)


@router.patch("/sources/{source_id}")
async def update_source(source_id: int, body: SourcePatch):
    async with SessionLocal() as s:
        src = await s.get(Source, source_id, options=[selectinload(Source.repos)])
        if not src:
            raise HTTPException(404, "Organización no encontrada")
        for field, value in body.model_dump(exclude_unset=True).items():
            if field == "repo_filter":
                value = (value or "").strip() or None
            setattr(src, field, value)
        src.last_synced_at = None  # recalcular qué repos se siguen
        await s.commit()
        data = _source_dict(src)
    syncer.wake()
    return data


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: int):
    async with SessionLocal() as s:
        src = await s.get(Source, source_id)
        if not src:
            raise HTTPException(404, "Organización no encontrada")
        await s.delete(src)
        await s.commit()


@router.get("/sources/{source_id}/repos")
async def source_repos(source_id: int):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(Repo).where(Repo.source_id == source_id)
            .options(selectinload(Repo.source).selectinload(Source.account))
            .order_by(Repo.tracked.desc(), Repo.activity_at.desc())
        )).scalars()
        return [service.repo_dict(r) for r in rows]


@router.patch("/repos/{repo_id}")
async def update_repo(repo_id: int, body: RepoPatch):
    async with SessionLocal() as s:
        r = await s.get(Repo, repo_id, options=[selectinload(Repo.source)
                                                 .selectinload(Source.account)])
        if not r:
            raise HTTPException(404, "Repo no encontrado")
        if body.pinned is not None:
            r.pinned = body.pinned
            r.tracked = r.tracked or body.pinned
            r.source.last_synced_at = None
            r.next_poll_at = None
        if body.muted is not None:
            r.muted = body.muted
        await s.commit()
        data = service.repo_dict(r)
    syncer.wake()
    return data


@router.get("/repos")
async def list_repos(tracked: bool = True):
    async with SessionLocal() as s:
        q = select(Repo).options(selectinload(Repo.source).selectinload(Source.account))
        if tracked:
            q = q.where(Repo.tracked.is_(True))
        rows = (await s.execute(q.order_by(Repo.full_name))).scalars()
        return [service.repo_dict(r) for r in rows]


# --- ejecuciones ----------------------------------------------------------------------------
@router.get("/overview")
async def overview():
    return await service.overview()


@router.get("/runs")
async def runs(provider: str | None = None, account_id: int | None = None,
               source_id: int | None = None, repo_id: int | None = None,
               repo: str | None = None, branch: str | None = None, status: str | None = None,
               q: str | None = None, limit: int = 100, before_id: int | None = None,
               filter: str | None = None, view: str | None = None):
    if provider and provider not in PROVIDERS:
        raise HTTPException(422, "provider inválido")
    try:
        return await service.list_runs(
            provider=provider, account_id=account_id, source_id=source_id, repo_id=repo_id,
            repo=repo, branch=branch, status=status, q=q, limit=limit, before_id=before_id,
            filter=filter, view=view,
        )
    except (service.ServiceError, ValueError) as e:
        raise _err(e if isinstance(e, service.ServiceError)
                   else service.ServiceError(f"filter inválido: {e}", 422)) from e


@router.get("/runs/stats")
async def runs_stats(filter: str | None = None, q: str | None = None):
    try:
        return await service.run_stats(filter, q)
    except (service.ServiceError, ValueError) as e:
        raise _err(e if isinstance(e, service.ServiceError)
                   else service.ServiceError(f"filter inválido: {e}", 422)) from e


@router.get("/runs/facets")
async def runs_facets(filter: str | None = None, days: int = 30):
    try:
        return await service.run_facets(filter, days)
    except (service.ServiceError, ValueError) as e:
        raise _err(e if isinstance(e, service.ServiceError)
                   else service.ServiceError(f"filter inválido: {e}", 422)) from e


def _bad_filter(e: Exception) -> HTTPException:
    return _err(e if isinstance(e, service.ServiceError)
                else service.ServiceError(f"filter inválido: {e}", 422))


@router.get("/views")
async def views(scope: str = "runs"):
    return await service.list_views(scope)


@router.post("/views", status_code=201)
async def create_view(body: ViewIn):
    try:
        return await service.save_view(body.name, body.filter, position=body.position,
                                       scope=body.scope)
    except service.ServiceError as e:
        raise _err(e) from e


@router.put("/views/{view_id}")
async def update_view(view_id: int, body: ViewIn):
    try:
        return await service.save_view(body.name, body.filter, view_id, body.position,
                                       scope=body.scope)
    except service.ServiceError as e:
        raise _err(e) from e


@router.delete("/views/{view_id}", status_code=204)
async def remove_view(view_id: int):
    try:
        await service.delete_view(view_id)
    except service.ServiceError as e:
        raise _err(e) from e


@router.get("/runs/{run_id}")
async def run_detail(run_id: int):
    try:
        return await service.get_run_detail(run_id)
    except service.ServiceError as e:
        raise _err(e) from e


@router.get("/runs/{run_id}/steps/{step_id}/log")
async def step_log(run_id: int, step_id: str, offset: int = 0):
    try:
        return await service.get_step_log(run_id, step_id, max(offset, 0))
    except service.ServiceError as e:
        raise _err(e) from e


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: int):
    try:
        return await service.cancel_run(run_id)
    except service.ServiceError as e:
        raise _err(e) from e


@router.post("/runs/{run_id}/rerun")
async def rerun(run_id: int, body: RerunIn | None = None):
    try:
        return await service.rerun_run(run_id, (body or RerunIn()).failed_only)
    except service.ServiceError as e:
        raise _err(e) from e


@router.get("/deployments")
async def deployments(repo: str | None = None, provider: str | None = None,
                      filter: str | None = None, view: str | None = None, q: str | None = None):
    try:
        return await service.list_deployments(repo=repo, provider=provider, filter=filter,
                                              view=view, q=q)
    except (service.ServiceError, ValueError) as e:
        raise _bad_filter(e) from e


@router.get("/deployments/facets")
async def deployments_facets(filter: str | None = None, days: int = 90):
    try:
        return await service.facets("deployments", filter, days)
    except (service.ServiceError, ValueError) as e:
        raise _bad_filter(e) from e


@router.get("/prs")
async def prs(view: str = "open", provider: str | None = None, repo: str | None = None,
              q: str | None = None, filter: str | None = None, saved_view: str | None = None):
    if view not in service.PR_VIEWS:
        raise HTTPException(422, "view inválida")
    try:
        return await service.list_prs(view, provider=provider, repo=repo, q=q, filter=filter,
                                      saved_view=saved_view)
    except (service.ServiceError, ValueError) as e:
        raise _bad_filter(e) from e


@router.get("/prs/facets")
async def prs_facets(filter: str | None = None):
    try:
        return await service.facets("prs", filter)
    except (service.ServiceError, ValueError) as e:
        raise _bad_filter(e) from e


@router.get("/prs/{pr_id}")
async def pr_detail(pr_id: int):
    try:
        return await service.get_pr_detail(pr_id)
    except service.ServiceError as e:
        raise _err(e) from e


@router.post("/prs/{pr_id}/{action}")
async def pr_action(pr_id: int, action: str, body: PRActionIn | None = None):
    b = body or PRActionIn()
    try:
        return await service.pr_action(pr_id, action.replace("-", "_"), b.body, b.strategy,
                                       b.close_source_branch)
    except service.ServiceError as e:
        raise _err(e) from e


@router.post("/sync")
async def force_sync(source_id: int | None = None):
    await syncer.force(source_id)
    return {"ok": True}
