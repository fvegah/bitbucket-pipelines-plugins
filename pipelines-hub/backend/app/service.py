"""Operaciones de negocio compartidas por la API REST y el servidor MCP."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.db import (
    Account,
    Deployment,
    PullRequest,
    Repo,
    Run,
    SavedView,
    SessionLocal,
    Source,
    utcnow,
)
from app.providers import provider_for
from app.providers.base import ACTIVE_STATUSES, IN_PROGRESS_STATUSES, ProviderError
from app.sync import apply_pr, apply_run, dump_reviewers, syncer


class ServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def repo_dict(repo: Repo) -> dict[str, Any]:
    src = repo.source
    return {
        "id": repo.id,
        "full_name": repo.full_name,
        "name": repo.name,
        "html_url": repo.html_url,
        "git_url": repo.git_url,
        "default_branch": repo.default_branch,
        "provider": src.account.provider,
        "account_id": src.account_id,
        "account_name": src.account.name,
        "source_id": src.id,
        "source_slug": src.slug,
        "tracked": repo.tracked,
        "pinned": repo.pinned,
        "muted": repo.muted,
        "private": repo.private,
        "activity_at": iso(repo.activity_at),
        "last_polled_at": iso(repo.last_polled_at),
        "next_poll_at": iso(repo.next_poll_at),
        "last_error": repo.last_error,
    }


def run_dict(run: Run) -> dict[str, Any]:
    repo = run.repo
    return {
        "id": run.id,
        "external_id": run.external_id,
        "number": run.number,
        "attempt": run.attempt,
        "workflow": run.workflow,
        "title": run.title,
        "status": run.status,
        "raw_status": run.raw_status,
        "branch": run.branch,
        "sha": run.sha,
        "actor": run.actor,
        "actor_avatar": run.actor_avatar,
        "event": run.event,
        "url": run.url,
        "created_at": iso(run.created_at),
        "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at),
        "duration_s": run.duration_s,
        "provider": repo.source.account.provider,
        "repo": {
            "id": repo.id,
            "full_name": repo.full_name,
            "name": repo.name,
            "html_url": repo.html_url,
            "git_url": repo.git_url,
            "source_slug": repo.source.slug,
            "account_name": repo.source.account.name,
        },
    }


def _jsonable(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    return obj


_RUN_OPTS = [selectinload(Run.repo).selectinload(Repo.source).selectinload(Source.account)]


# --- filtros dinámicos y vistas ------------------------------------------------------------
# Un filtro es {"include": {campo: [valores]}, "exclude": {campo: [valores]}, "since_hours": N}.
# Los valores con * son comodines (deploy*, *-legacy). Cada pantalla (scope) tiene sus campos:
# "org" es la organización de GitHub, el workspace de Bitbucket o la cuenta de Cloudflare.
_COMMON = {
    "provider": Account.provider,
    "account": Account.name,
    "org": Source.slug,
    "repo": Repo.full_name,
}
SCOPES: dict[str, dict[str, Any]] = {
    "runs": {
        "fields": {**_COMMON, "branch": Run.branch, "workflow": Run.workflow,
                   "actor": Run.actor, "event": Run.event, "status": Run.status},
        "time": Run.created_at,
    },
    "prs": {
        "fields": {**_COMMON, "author": PullRequest.author, "target": PullRequest.target_branch,
                   "source": PullRequest.source_branch, "state": PullRequest.state},
        "time": PullRequest.updated_at,
    },
    "deployments": {
        "fields": {**_COMMON, "environment": Deployment.environment,
                   "status": Deployment.status, "actor": Deployment.actor},
        "time": Deployment.deployed_at,
    },
}
FILTER_FIELDS = SCOPES["runs"]["fields"]  # compatibilidad


def _cond(field: str, values: list[str], scope: str = "runs"):
    col = SCOPES[scope]["fields"][field]
    conds = []
    exact = []
    for v in values:
        v = str(v).strip()
        if not v:
            continue
        if scope == "runs" and field == "status" and v == "active":
            conds.append(and_(Run.status.in_(IN_PROGRESS_STATUSES),
                              Run.created_at >= utcnow() - timedelta(days=1)))
        elif scope == "prs" and field == "state" and v == "draft":
            conds.append(and_(PullRequest.state == "open", PullRequest.draft.is_(True)))
        elif "*" in v:
            conds.append(func.lower(col).like(v.lower().replace("*", "%")))
        else:
            exact.append(v.lower())
    if exact:
        conds.append(func.lower(col).in_(exact))
    return or_(*conds) if conds else None


def parse_filter(raw: str | dict | None, scope: str = "runs") -> dict[str, Any]:
    if not raw:
        return {}
    f = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(f, dict):
        raise ServiceError("filter debe ser un objeto JSON", 422)
    for part in ("include", "exclude"):
        for field in (f.get(part) or {}):
            if field not in SCOPES[scope]["fields"]:
                raise ServiceError(f"Campo de filtro desconocido: {field}", 422)
    return f


def apply_filter(stmt, f: dict[str, Any], skip: str | None = None, scope: str = "runs"):
    fields = SCOPES[scope]["fields"]
    for field, values in (f.get("include") or {}).items():
        if field != skip and values:
            c = _cond(field, values, scope)
            if c is not None:
                stmt = stmt.where(c)
    for field, values in (f.get("exclude") or {}).items():
        if field != skip and values:
            c = _cond(field, values, scope)
            if c is not None:
                stmt = stmt.where(or_(~c, fields[field].is_(None)))
    if f.get("since_hours"):
        stmt = stmt.where(SCOPES[scope]["time"]
                          >= utcnow() - timedelta(hours=float(f["since_hours"])))
    return stmt


def _search(stmt, q: str | None):
    if not q:
        return stmt
    like = f"%{q}%"
    return stmt.where(or_(Run.title.ilike(like), Run.workflow.ilike(like),
                          Run.branch.ilike(like), Run.actor.ilike(like),
                          Repo.full_name.ilike(like), Run.sha.ilike(f"{q}%")))


def _runs_base(columns=None):
    base = select(*columns) if columns is not None else select(Run)
    return (base.select_from(Run).join(Run.repo).join(Repo.source).join(Source.account)
            .where(Repo.muted.is_(False)))


def _prs_base(columns=None):
    base = select(*columns) if columns is not None else select(PullRequest)
    return (base.select_from(PullRequest).join(PullRequest.repo).join(Repo.source)
            .join(Source.account).where(Repo.muted.is_(False), Repo.tracked.is_(True)))


def _deps_base(columns=None):
    base = select(*columns) if columns is not None else select(Deployment)
    return (base.select_from(Deployment).join(Deployment.repo).join(Repo.source)
            .join(Source.account).where(Repo.muted.is_(False)))


_BASES = {"runs": _runs_base, "prs": _prs_base, "deployments": _deps_base}


async def _resolve_view(view: str | int | None, scope: str = "runs") -> dict[str, Any]:
    if view in (None, ""):
        return {}
    async with SessionLocal() as s:
        q = select(SavedView)
        q = q.where(SavedView.id == int(view)) if str(view).isdigit() else \
            q.where(func.lower(SavedView.name) == str(view).lower())
        v = (await s.execute(q)).scalar()
    if not v or (v.scope or "runs") != scope:
        raise ServiceError(f"Vista no encontrada: {view}", 404)
    return json.loads(v.filter_json or "{}")


def _merge(a: dict, b: dict) -> dict:
    since = b.get("since_hours") or a.get("since_hours")
    out = {"include": {}, "exclude": {}, "since_hours": since}
    for part in ("include", "exclude"):
        for src in (a, b):
            for k, v in (src.get(part) or {}).items():
                out[part].setdefault(k, [])
                out[part][k] += [x for x in v if x not in out[part][k]]
    return out


async def facets(scope: str, filter: str | dict | None = None, days: int = 30
                 ) -> dict[str, Any]:
    """Valores posibles de cada campo con su cantidad, según el resto del filtro activo."""
    if scope not in SCOPES:
        raise ServiceError("scope inválido", 422)
    f = parse_filter(filter, scope)
    spec = SCOPES[scope]
    since = utcnow() - timedelta(days=days)
    out: dict[str, list] = {}
    async with SessionLocal() as s:
        for field, col in spec["fields"].items():
            stmt = apply_filter(_BASES[scope]([col, func.count()]), f, skip=field, scope=scope)
            if scope != "prs":  # los PR abiertos pueden ser antiguos: no se recortan
                stmt = stmt.where(spec["time"] >= since)
            rows = (await s.execute(
                stmt.where(col.is_not(None)).group_by(col)
                .order_by(func.count().desc()).limit(300)
            )).all()
            out[field] = [{"value": v, "count": c} for v, c in rows]
    return out


async def list_runs(
    *, provider: str | None = None, account_id: int | None = None, source_id: int | None = None,
    repo_id: int | None = None, repo: str | None = None, branch: str | None = None,
    status: str | None = None, q: str | None = None, limit: int = 100,
    before_id: int | None = None, filter: str | dict | None = None,
    view: str | int | None = None,
) -> list[dict[str, Any]]:
    f = _merge(await _resolve_view(view), parse_filter(filter))
    stmt = apply_filter(_runs_base().options(*_RUN_OPTS), f)
    if provider:
        stmt = stmt.where(Account.provider == provider)
    if account_id:
        stmt = stmt.where(Source.account_id == account_id)
    if source_id:
        stmt = stmt.where(Repo.source_id == source_id)
    if repo_id:
        stmt = stmt.where(Run.repo_id == repo_id)
    if repo:
        stmt = stmt.where(Repo.full_name.ilike(f"%{repo}%"))
    if branch:
        stmt = stmt.where(Run.branch == branch)
    if status:
        stmt = stmt.where(_cond("status", status.split(",")))
    stmt = _search(stmt, q)
    if before_id:
        stmt = stmt.where(Run.id < before_id)
    stmt = stmt.order_by(Run.created_at.desc(), Run.id.desc()).limit(min(limit, 500))
    async with SessionLocal() as s:
        return [run_dict(r) for r in (await s.execute(stmt)).scalars()]


async def run_stats(filter: str | dict | None = None, q: str | None = None) -> dict[str, Any]:
    """Resumen (en curso + últimas 24 h) de lo que calza con el filtro."""
    f = parse_filter(filter)
    f24 = {**f, "since_hours": min(float(f.get("since_hours") or 24), 24)}
    async with SessionLocal() as s:
        by_status = dict((await s.execute(
            _search(apply_filter(_runs_base([Run.status, func.count()]), f24), q)
            .group_by(Run.status)
        )).all())
        active = (await s.execute(
            _search(apply_filter(_runs_base([func.count()]), f), q)
            .where(Run.status.in_(IN_PROGRESS_STATUSES),
                   Run.created_at >= utcnow() - timedelta(days=1))
        )).scalar()
        # en pausa (step manual pendiente): mismo criterio que filtrar por estado "En pausa"
        waiting = (await s.execute(
            _search(apply_filter(_runs_base([func.count()]), f), q)
            .where(Run.status == "waiting")
        )).scalar()
        repos = (await s.execute(
            _search(apply_filter(_runs_base([func.count(func.distinct(Run.repo_id))]), f), q)
        )).scalar()
    return {"last_24h": by_status, "active": active, "waiting": waiting, "repos": repos}


async def run_facets(filter: str | dict | None = None, days: int = 30) -> dict[str, Any]:
    return await facets("runs", filter, days)


# --- vistas guardadas ------------------------------------------------------------------------
def view_dict(v: SavedView) -> dict[str, Any]:
    return {"id": v.id, "name": v.name, "scope": v.scope or "runs",
            "filter": json.loads(v.filter_json or "{}"), "position": v.position}


async def list_views(scope: str | None = "runs") -> list[dict[str, Any]]:
    async with SessionLocal() as s:
        q = select(SavedView).order_by(SavedView.position, SavedView.id)
        rows = [view_dict(v) for v in (await s.execute(q)).scalars()]
    return [v for v in rows if not scope or v["scope"] == scope]


async def save_view(name: str, filter: dict, view_id: int | None = None,
                    position: int | None = None, scope: str = "runs") -> dict[str, Any]:
    if scope not in SCOPES:
        raise ServiceError("scope inválido", 422)
    parse_filter(filter, scope)
    async with SessionLocal() as s:
        if view_id:
            v = await s.get(SavedView, view_id)
            if not v:
                raise ServiceError("Vista no encontrada", 404)
        else:
            count = (await s.execute(select(func.count()).select_from(SavedView))).scalar()
            v = SavedView(position=count, scope=scope)
            s.add(v)
        v.name = name.strip()
        v.filter_json = json.dumps(filter)
        if position is not None:
            v.position = position
        try:
            await s.commit()
        except IntegrityError as e:
            raise ServiceError(f"Ya existe una vista llamada {name}", 409) from e
        return view_dict(v)


async def delete_view(view_id: int) -> None:
    async with SessionLocal() as s:
        v = await s.get(SavedView, view_id)
        if not v:
            raise ServiceError("Vista no encontrada", 404)
        await s.delete(v)
        await s.commit()


async def overview() -> dict[str, Any]:
    now = utcnow()
    day = now - timedelta(hours=24)
    async with SessionLocal() as s:
        by_status = dict((await s.execute(
            select(Run.status, func.count()).join(Run.repo)
            .where(Repo.muted.is_(False), Run.created_at >= day).group_by(Run.status)
        )).all())
        active = (await s.execute(
            select(func.count()).select_from(Run).join(Run.repo)
            .where(Repo.muted.is_(False), Run.status.in_(IN_PROGRESS_STATUSES),
                   Run.created_at >= now - timedelta(days=1))
        )).scalar()
        tracked = (await s.execute(
            select(func.count()).select_from(Repo).where(Repo.tracked.is_(True))
        )).scalar()
        accounts = (await s.execute(select(func.count()).select_from(Account))).scalar()
    return {
        "prs": await pr_counts(),
        "last_24h": by_status,
        "active": active,
        "tracked_repos": tracked,
        "accounts": accounts,
        "syncer": {
            "last_tick_at": iso(syncer.last_tick_at),
            "last_error": syncer.last_error,
        },
    }


async def _load_run(s, run_id: int) -> Run:
    run = await s.get(Run, run_id, options=_RUN_OPTS)
    if not run:
        raise ServiceError("Ejecución no encontrada", 404)
    return run


async def get_run_detail(run_id: int) -> dict[str, Any]:
    async with SessionLocal() as s:
        run = await _load_run(s, run_id)
        account = run.repo.source.account
        provider = provider_for(account)
        try:
            info, steps = await asyncio.gather(
                provider.get_run(run.repo.full_name, run.external_id),
                provider.get_steps(run.repo.full_name, run.external_id),
            )
        except ProviderError as e:
            data = run_dict(run)
            data.update(steps=[], error=e.message)
            return data
        was_active = run.status in ACTIVE_STATUSES
        apply_run(run, info)
        if was_active and run.status not in ACTIVE_STATUSES:
            run.repo.deployments_synced_at = None
        await s.commit()
        data = run_dict(run)
        data["steps"] = [_jsonable(asdict(st)) for st in steps]
        return data


async def get_step_log(run_id: int, step_id: str, offset: int = 0) -> dict[str, Any]:
    async with SessionLocal() as s:
        run = await _load_run(s, run_id)
        provider = provider_for(run.repo.source.account)
    try:
        chunk = await provider.get_log(run.repo.full_name, run.external_id, step_id, offset)
    except ProviderError as e:
        raise ServiceError(e.message, e.status_code or 502) from e
    return asdict(chunk)


async def _run_action(run_id: int, action: str, failed_only: bool = False) -> dict[str, Any]:
    async with SessionLocal() as s:
        run = await _load_run(s, run_id)
        provider = provider_for(run.repo.source.account)
        try:
            if action == "cancel":
                await provider.cancel(run.repo.full_name, run.external_id)
            else:
                await provider.rerun(run.repo.full_name, run.external_id, failed_only)
        except ProviderError as e:
            raise ServiceError(e.message, e.status_code or 502) from e
        run.repo.next_poll_at = None
        run.repo.runs_etag = None
        await s.commit()
    syncer.wake()
    return {"ok": True}


async def cancel_run(run_id: int) -> dict[str, Any]:
    return await _run_action(run_id, "cancel")


async def rerun_run(run_id: int, failed_only: bool = False) -> dict[str, Any]:
    return await _run_action(run_id, "rerun", failed_only)


async def list_deployments(repo: str | None = None, provider: str | None = None,
                           filter: str | dict | None = None, view: str | int | None = None,
                           q: str | None = None) -> list[dict[str, Any]]:
    f = _merge(await _resolve_view(view, "deployments"), parse_filter(filter, "deployments"))
    stmt = apply_filter(_deps_base().options(
        selectinload(Deployment.repo).selectinload(Repo.source).selectinload(Source.account)
    ), f, scope="deployments")
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Repo.full_name.ilike(like), Deployment.environment.ilike(like),
                              Deployment.actor.ilike(like), Deployment.sha.ilike(f"{q}%")))
    if repo:
        stmt = stmt.where(Repo.full_name.ilike(f"%{repo}%"))
    if provider:
        stmt = stmt.where(Account.provider == provider)
    async with SessionLocal() as s:
        deps = (await s.execute(stmt)).scalars().all()
        run_ids = {(d.repo_id, d.run_external_id) for d in deps if d.run_external_id}
        runs = {}
        if run_ids:
            rows = (await s.execute(
                select(Run).where(Run.external_id.in_([r for _, r in run_ids]))
            )).scalars()
            runs = {(r.repo_id, r.external_id): r for r in rows}
        grouped: dict[int, dict[str, Any]] = {}
        for d in deps:
            g = grouped.setdefault(d.repo_id, {"repo": repo_dict(d.repo), "environments": []})
            run = runs.get((d.repo_id, d.run_external_id))
            g["environments"].append({
                "environment": d.environment,
                "env_type": d.env_type,
                "rank": d.rank,
                "status": d.status,
                "sha": d.sha,
                "ref": d.ref or (run.branch if run else None),
                "actor": d.actor,
                "deployed_at": iso(d.deployed_at),
                "url": d.url or (run.url if run else None),
                "run_id": run.id if run else None,
                "run_number": run.number if run else None,
                "title": run.title if run else None,
            })
    out = list(grouped.values())
    for g in out:
        g["environments"].sort(key=lambda e: (e["rank"], e["environment"]))
    out.sort(key=lambda g: max((e["deployed_at"] or "") for e in g["environments"]),
             reverse=True)
    return out


# --- pull requests -------------------------------------------------------------------------
_PR_OPTS = [selectinload(PullRequest.repo).selectinload(Repo.source).selectinload(Source.account)]
PR_VIEWS = ("review", "mine", "open", "closed")


def me_of(account: Account) -> str | None:
    """Identificador del dueño de la cuenta tal como aparece en autores y revisores."""
    if account.user_id:
        return account.user_id
    return account.login.lower() if account.provider == "github" and account.login else None


def _ci_summary(runs: list[Run]) -> dict[str, Any] | None:
    if not runs:
        return None
    latest: dict[str, Run] = {}
    for r in sorted(runs, key=lambda r: r.created_at):
        latest[r.workflow or "?"] = r  # la última de cada workflow manda
    items = list(latest.values())
    statuses = {r.status for r in items}
    if "failed" in statuses:
        status = "failed"
    elif statuses & IN_PROGRESS_STATUSES:
        status = "running"
    elif "waiting" in statuses:
        status = "waiting"
    elif statuses <= {"success", "skipped"}:
        status = "success"
    else:
        status = "cancelled"
    return {
        "status": status,
        "runs": [{"id": r.id, "workflow": r.workflow, "status": r.status, "number": r.number}
                 for r in sorted(items, key=lambda r: r.workflow or "")],
    }


async def _runs_for_prs(s, prs: list[PullRequest]) -> dict[tuple[int, str], list[Run]]:
    """Ejecuciones del commit de cada PR: las del mismo repo y las de despliegues que
    construyen ese repo (p. ej. Workers/Pages de Cloudflare conectados a GitHub)."""
    keys = {(p.repo_id, p.head_sha[:12]) for p in prs if p.head_sha}
    if not keys:
        return {}
    pr_repos = {p.repo_id: p.repo for p in prs}
    by_url = {(r.html_url or "").lower().rstrip("/"): rid for rid, r in pr_repos.items()
              if r.html_url}
    linked = (await s.execute(
        select(Repo.id, Repo.git_url).where(func.lower(Repo.git_url).in_(list(by_url)))
    )).all() if by_url else []
    alias = {rid: by_url[(url or "").lower().rstrip("/")] for rid, url in linked}
    repo_ids = {k[0] for k in keys} | set(alias)
    rows = (await s.execute(
        select(Run).where(Run.repo_id.in_(repo_ids),
                          Run.created_at >= utcnow() - timedelta(days=60))
    )).scalars()
    out: dict[tuple[int, str], list[Run]] = {}
    for r in rows:
        if not r.sha:
            continue
        key = (alias.get(r.repo_id, r.repo_id), r.sha[:12])
        if key in keys:
            out.setdefault(key, []).append(r)
    return out


def pr_dict(pr: PullRequest, runs: list[Run] | None = None) -> dict[str, Any]:
    account = pr.repo.source.account
    me = me_of(account)
    reviewers = json.loads(pr.reviewers_json or "[]")
    mine = bool(me and pr.author_id == me)
    my_review = next((r["state"] for r in reviewers if me and r["id"] == me), None)
    approvals = sum(1 for r in reviewers if r["state"] == "approved")
    changes = sum(1 for r in reviewers if r["state"] == "changes_requested")
    ci = _ci_summary(runs or [])
    return {
        "id": pr.id,
        "number": pr.number,
        "title": pr.title,
        "state": pr.state,
        "draft": pr.draft,
        "author": pr.author,
        "author_avatar": pr.author_avatar,
        "source_branch": pr.source_branch,
        "target_branch": pr.target_branch,
        "head_sha": pr.head_sha,
        "url": pr.url,
        "created_at": iso(pr.created_at),
        "updated_at": iso(pr.updated_at),
        "closed_at": iso(pr.closed_at),
        "comment_count": pr.comment_count,
        "task_count": pr.task_count,
        "reviewers": reviewers,
        "approvals": approvals,
        "changes_requested": changes,
        "is_mine": mine,
        "my_review": my_review,
        "review_requested": pr.state == "open" and not pr.draft and not mine
        and my_review == "pending",
        "ready": pr.state == "open" and not pr.draft and approvals > 0 and changes == 0
        and (ci is None or ci["status"] == "success"),
        "ci": ci,
        "provider": account.provider,
        "repo": {
            "id": pr.repo.id,
            "full_name": pr.repo.full_name,
            "name": pr.repo.name,
            "html_url": pr.repo.html_url,
            "account_name": account.name,
        },
    }


async def list_prs(view: str = "open", *, provider: str | None = None, repo: str | None = None,
                   q: str | None = None, limit: int = 300, filter: str | dict | None = None,
                   saved_view: str | int | None = None) -> dict[str, Any]:
    f = _merge(await _resolve_view(saved_view, "prs"), parse_filter(filter, "prs"))
    stmt = apply_filter(_prs_base().options(*_PR_OPTS), f, scope="prs")
    if provider:
        stmt = stmt.where(Account.provider == provider)
    if repo:
        stmt = stmt.where(Repo.full_name.ilike(f"%{repo}%"))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(PullRequest.title.ilike(like), PullRequest.author.ilike(like),
                              PullRequest.source_branch.ilike(like),
                              Repo.full_name.ilike(like)))
    closed_cutoff = utcnow() - timedelta(days=7)
    stmt = stmt.where(or_(PullRequest.state == "open", PullRequest.closed_at >= closed_cutoff))
    stmt = stmt.order_by(PullRequest.updated_at.desc())
    async with SessionLocal() as s:
        prs = (await s.execute(stmt)).scalars().all()
        runs = await _runs_for_prs(s, [p for p in prs if p.state == "open"])
        items = [pr_dict(p, runs.get((p.repo_id, (p.head_sha or "")[:12]))) for p in prs]
    buckets = {
        "review": [i for i in items if i["review_requested"]],
        "mine": [i for i in items if i["is_mine"] and i["state"] == "open"],
        "open": [i for i in items if i["state"] == "open"],
        "closed": [i for i in items if i["state"] != "open"],
    }
    return {
        "counts": {k: len(v) for k, v in buckets.items()},
        "items": buckets.get(view, buckets["open"])[:limit],
    }


async def pr_counts() -> dict[str, int]:
    data = await list_prs("review")
    return {"review": data["counts"]["review"], "mine": data["counts"]["mine"]}


async def _load_pr(s, pr_id: int) -> PullRequest:
    pr = await s.get(PullRequest, pr_id, options=_PR_OPTS)
    if not pr:
        raise ServiceError("Pull request no encontrado", 404)
    return pr


async def get_pr_detail(pr_id: int) -> dict[str, Any]:
    async with SessionLocal() as s:
        pr = await _load_pr(s, pr_id)
        provider = provider_for(pr.repo.source.account)
        try:
            detail = await provider.get_pr(pr.repo.full_name, pr.number)
        except ProviderError as e:
            runs = await _runs_for_prs(s, [pr])
            data = pr_dict(pr, runs.get((pr.repo_id, (pr.head_sha or "")[:12])))
            data.update(error=e.message, body="", files=[], comments=[], checks=[], commits=[])
            return data
        apply_pr(pr, detail.info)
        pr.reviewers_json = dump_reviewers(detail.reviewers)
        pr.reviews_for = detail.info.updated_at.isoformat()
        await s.commit()
        runs = await _runs_for_prs(s, [pr])
        data = pr_dict(pr, runs.get((pr.repo_id, (pr.head_sha or "")[:12])))
        data.update(
            body=detail.body,
            files=[asdict(f) for f in detail.files],
            comments=_jsonable([asdict(c) for c in detail.comments]),
            checks=[asdict(c) for c in detail.checks],
            commits=_jsonable([asdict(c) for c in detail.commits]),
            mergeable=detail.mergeable,
            merge_state=detail.merge_state,
            additions=detail.additions,
            deletions=detail.deletions,
            merged_by=detail.merged_by,
            me=me_of(pr.repo.source.account),
        )
        return data


PR_ACTIONS = ("approve", "unapprove", "request_changes", "comment", "merge", "decline")


async def pr_action(pr_id: int, action: str, body: str | None = None,
                    strategy: str | None = None, close_source_branch: bool = False
                    ) -> dict[str, Any]:
    if action not in PR_ACTIONS:
        raise ServiceError(f"Acción inválida: {action}", 422)
    async with SessionLocal() as s:
        pr = await _load_pr(s, pr_id)
        provider = provider_for(pr.repo.source.account)
        try:
            await provider.pr_action(pr.repo.full_name, pr.number, action, body, strategy,
                                     close_source_branch)
        except ProviderError as e:
            raise ServiceError(e.message, e.status_code or 502) from e
        pr.repo.prs_next_poll_at = None
        pr.repo.prs_etag = None
        if action == "merge":
            pr.repo.next_poll_at = None  # el merge suele disparar un pipeline
            pr.repo.runs_etag = None
        await s.commit()
    syncer.wake()
    return {"ok": True}
