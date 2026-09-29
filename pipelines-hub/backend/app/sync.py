"""Poller en segundo plano: mantiene repos, ejecuciones y despliegues al día.

Estrategia para no quemar el rate limit (Bitbucket da ~1.000 req/h por usuario):
- La lista de repos de cada org/workspace se pide cada `repo_list_interval` (1 request,
  y con ETag en GitHub). Si un repo muestra actividad nueva, se consulta de inmediato.
- Cada repo seguido tiene su propio `next_poll_at`: caliente (15 s) mientras tenga
  ejecuciones activas, tibio (60 s) si tuvo algo en la última hora, frío (10 min) si no.
- Los despliegues se refrescan cuando termina una ejecución del repo, o cada 30 min.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
from dataclasses import asdict
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import Account, Deployment, PullRequest, Repo, Run, SessionLocal, Source, utcnow
from app.providers import provider_for
from app.providers.base import (
    ACTIVE_STATUSES,
    IN_PROGRESS_STATUSES,
    AuthError,
    PRInfo,
    ProviderError,
    RateLimited,
    RunInfo,
)

log = logging.getLogger("pipelines_hub.sync")


def matches_filter(name: str, full_name: str, repo_filter: str | None) -> bool:
    if not repo_filter or not repo_filter.strip():
        return True
    patterns = [p.strip() for p in repo_filter.split(",") if p.strip()]
    include = [p for p in patterns if not p.startswith("!")]
    exclude = [p[1:] for p in patterns if p.startswith("!")]

    def hit(ps):
        return any(fnmatch.fnmatch(name.lower(), p.lower())
                   or fnmatch.fnmatch(full_name.lower(), p.lower()) for p in ps)

    if exclude and hit(exclude):
        return False
    return hit(include) if include else True


def apply_run(run: Run, info: RunInfo) -> None:
    for field in ("number", "attempt", "workflow", "title", "status", "raw_status", "branch",
                  "sha", "actor", "actor_avatar", "event", "url", "created_at", "started_at",
                  "finished_at", "duration_s"):
        setattr(run, field, getattr(info, field))
    run.updated_at = utcnow()


def apply_pr(pr: PullRequest, info: PRInfo) -> None:
    for field in ("title", "state", "draft", "author", "author_id", "author_avatar",
                  "source_branch", "target_branch", "head_sha", "url", "created_at",
                  "updated_at", "closed_at", "task_count"):
        setattr(pr, field, getattr(info, field))
    if info.comment_count is not None:
        pr.comment_count = info.comment_count


def dump_reviewers(reviewers) -> str:
    return json.dumps([asdict(r) for r in reviewers or []])


def _record_rate(account: Account, provider) -> None:
    api = provider.api
    if api.rate_remaining is not None:
        account.rate_remaining = api.rate_remaining
    if api.rate_limit is not None:
        account.rate_limit = api.rate_limit


def _record_error(account: Account, e: Exception) -> str:
    if isinstance(e, AuthError):
        account.status, account.status_detail = "error", e.message
    elif isinstance(e, RateLimited):
        account.backoff_until = utcnow() + timedelta(seconds=e.retry_after or 60)
        account.status_detail = e.message
    return getattr(e, "message", None) or f"{e.__class__.__name__}: {e}"


class Syncer:
    def __init__(self):
        self.settings = get_settings()
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._sem = asyncio.Semaphore(self.settings.concurrency)
        self._inflight: set[str] = set()
        self.last_tick_at = None
        self.last_error: str | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="syncer")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def wake(self) -> None:
        self._wake.set()

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as e:  # el loop nunca debe morir
                log.exception("tick falló")
                self.last_error = str(e)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.settings.tick_seconds)
            except TimeoutError:
                pass

    async def _guarded(self, key: str, coro_fn, *args) -> None:
        if key in self._inflight:
            return
        self._inflight.add(key)
        try:
            async with self._sem:
                await coro_fn(*args)
        except Exception:
            log.exception("%s falló", key)
        finally:
            self._inflight.discard(key)

    async def tick(self) -> None:
        now = utcnow()
        self.last_tick_at = now
        st = self.settings
        async with SessionLocal() as s:
            sources = (await s.execute(
                select(Source).join(Account)
                .where(Source.enabled.is_(True), Account.status == "ok")
                .where((Account.backoff_until.is_(None)) | (Account.backoff_until < now))
            )).scalars().all()
            due_sources = [
                src.id for src in sources
                if not src.last_synced_at
                or src.last_synced_at <= now - timedelta(seconds=st.repo_list_interval)
            ]
            active_source_ids = [src.id for src in sources]
            repos = (await s.execute(
                select(Repo).where(
                    Repo.tracked.is_(True), Repo.muted.is_(False),
                    Repo.source_id.in_(active_source_ids),
                )
            )).scalars().all() if active_source_ids else []

        await asyncio.gather(*(self._guarded(f"src:{i}", self.sync_source, i)
                               for i in due_sources))

        due_repos = [r.id for r in repos if not r.next_poll_at or r.next_poll_at <= now]
        due_prs = [r.id for r in repos if not r.prs_next_poll_at or r.prs_next_poll_at <= now]
        due_deploys = [
            r.id for r in repos
            if not r.deployments_synced_at
            or r.deployments_synced_at <= now - timedelta(seconds=st.deployments_interval)
        ]
        await asyncio.gather(
            *(self._guarded(f"repo:{i}", self.poll_repo, i) for i in due_repos),
            *(self._guarded(f"dep:{i}", self.sync_deployments, i) for i in due_deploys),
            *(self._guarded(f"pr:{i}", self.poll_prs, i) for i in due_prs),
        )

    # ------------------------------------------------------------------------------
    async def sync_source(self, source_id: int) -> None:
        st = self.settings
        async with SessionLocal() as s:
            src = await s.get(Source, source_id, options=[selectinload(Source.account),
                                                           selectinload(Source.repos)])
            if not src:
                return
            account = src.account
            provider = provider_for(account)
            try:
                infos, etag = await provider.list_repos(src.kind, src.slug, src.repos_etag)
                src.last_error = None
            except ProviderError as e:
                src.last_error = _record_error(account, e)
                src.last_synced_at = utcnow()
                _record_rate(account, provider)
                await s.commit()
                return
            _record_rate(account, provider)
            now = utcnow()
            src.last_synced_at = now
            existing = {r.full_name: r for r in src.repos}
            if infos is not None:
                src.repos_etag = etag
                for info in infos:
                    repo = existing.get(info.full_name)
                    if repo is None:
                        repo = Repo(source=src, full_name=info.full_name, name=info.name)
                        s.add(repo)
                        existing[info.full_name] = repo
                    elif info.activity_at and (
                        not repo.activity_at or info.activity_at > repo.activity_at
                    ):
                        repo.next_poll_at = now  # hubo push: mirar ya
                        repo.prs_next_poll_at = now
                    repo.name = info.name
                    repo.html_url = info.html_url
                    repo.default_branch = info.default_branch
                    repo.private = info.private
                    repo.activity_at = info.activity_at
                    if info.git_url:
                        repo.git_url = info.git_url

            # Qué repos se siguen: fijados + los N más activos que calzan con el filtro
            cutoff = now - timedelta(days=src.active_days or st.default_active_days)
            candidates = sorted(
                (r for r in existing.values()
                 if matches_filter(r.name, r.full_name, src.repo_filter)),
                key=lambda r: r.activity_at or now.replace(year=1970),
                reverse=True,
            )
            auto = {
                r.full_name for r in candidates[: src.max_repos or st.default_max_repos]
                if r.activity_at and r.activity_at >= cutoff
            }
            for r in existing.values():
                tracked = r.pinned or r.full_name in auto
                if tracked and not r.tracked:
                    r.next_poll_at = now
                r.tracked = tracked
            await s.commit()

    async def poll_repo(self, repo_id: int) -> None:
        st = self.settings
        async with SessionLocal() as s:
            repo = await s.get(Repo, repo_id, options=[
                selectinload(Repo.source).selectinload(Source.account)
            ])
            if not repo:
                return
            account = repo.source.account
            provider = provider_for(account)
            now = utcnow()
            try:
                infos, etag = await provider.list_runs(repo.full_name, repo.runs_etag,
                                                       st.runs_per_repo)
                repo.last_error = None
            except ProviderError as e:
                repo.last_error = _record_error(account, e)
                repo.next_poll_at = now + timedelta(seconds=st.cold_poll_interval)
                _record_rate(account, provider)
                await s.commit()
                return
            _record_rate(account, provider)
            repo.last_polled_at = now

            if infos is not None:
                repo.runs_etag = etag
                ids = [i.external_id for i in infos]
                current = {
                    r.external_id: r for r in (await s.execute(
                        select(Run).where(Run.repo_id == repo.id, Run.external_id.in_(ids))
                    )).scalars()
                } if ids else {}
                for info in infos:
                    run = current.get(info.external_id)
                    if run is None:
                        run = Run(repo_id=repo.id, external_id=info.external_id)
                        s.add(run)
                    elif run.status in ACTIVE_STATUSES and info.status not in ACTIVE_STATUSES:
                        repo.deployments_synced_at = None  # terminó algo: refrescar entornos
                    apply_run(run, info)
                await s.flush()
                await self._prune(s, repo.id)

            # Solo lo que corre de verdad deja el repo "caliente". Un pipeline en pausa
            # (esperando un step manual) puede quedar así días: basta con mirarlo tibio.
            active = (await s.execute(
                select(Run.id).where(
                    Run.repo_id == repo.id, Run.status.in_(IN_PROGRESS_STATUSES),
                    Run.created_at >= now - timedelta(days=1),
                ).limit(1)
            )).first()
            paused = (await s.execute(
                select(Run.id).where(
                    Run.repo_id == repo.id, Run.status == "waiting",
                    Run.created_at >= now - timedelta(days=7),
                ).limit(1)
            )).first()
            newest = (await s.execute(
                select(Run.created_at).where(Run.repo_id == repo.id)
                .order_by(Run.created_at.desc()).limit(1)
            )).scalar()
            recent = now - timedelta(hours=1)
            if active:
                wait = st.hot_poll_interval
            elif paused or (newest and newest >= recent) or (
                repo.activity_at and repo.activity_at >= recent
            ):
                wait = st.warm_poll_interval
            else:
                wait = st.cold_poll_interval
            repo.next_poll_at = now + timedelta(seconds=wait)
            await s.commit()

    async def poll_prs(self, repo_id: int) -> None:
        st = self.settings
        async with SessionLocal() as s:
            repo = await s.get(Repo, repo_id, options=[
                selectinload(Repo.source).selectinload(Source.account)
            ])
            if not repo:
                return
            account = repo.source.account
            provider = provider_for(account)
            now = utcnow()
            interval = (st.github_pr_interval if account.provider == "github"
                        else st.bitbucket_pr_interval)
            repo.prs_next_poll_at = now + timedelta(seconds=interval)
            try:
                infos, etag = await provider.list_prs(repo.full_name, repo.prs_etag)
            except ProviderError as e:
                repo.last_error = _record_error(account, e)
                _record_rate(account, provider)
                await s.commit()
                return
            if infos is not None:
                repo.prs_etag = etag
                current = {
                    p.number: p for p in (await s.execute(
                        select(PullRequest).where(PullRequest.repo_id == repo.id)
                    )).scalars()
                }
                for info in infos:
                    pr = current.get(info.number)
                    if pr is None:
                        pr = PullRequest(repo_id=repo.id, number=info.number, reviewers_json="[]")
                        s.add(pr)
                    apply_pr(pr, info)
                    stamp = info.updated_at.isoformat()
                    if account.provider == "bitbucket":
                        pr.reviewers_json = dump_reviewers(info.reviewers)
                    elif info.state == "open" and pr.reviews_for != stamp:
                        # GitHub: las aprobaciones vienen aparte; solo si el PR cambió
                        try:
                            reviewers = await provider.pr_reviewers(repo.full_name, info)
                            pr.reviewers_json = dump_reviewers(reviewers)
                            pr.reviews_for = stamp
                        except ProviderError:
                            pr.reviewers_json = dump_reviewers(info.reviewers)
                cutoff = now - timedelta(days=st.closed_pr_days)
                await s.execute(delete(PullRequest).where(
                    PullRequest.repo_id == repo.id, PullRequest.state != "open",
                    PullRequest.updated_at < cutoff,
                ))
            _record_rate(account, provider)
            await s.commit()

    async def _prune(self, s, repo_id: int) -> None:
        keep = self.settings.runs_per_repo * 2
        old = (await s.execute(
            select(Run.id).where(Run.repo_id == repo_id)
            .order_by(Run.created_at.desc()).offset(keep)
        )).scalars().all()
        if old:
            await s.execute(delete(Run).where(Run.id.in_(old)))

    async def sync_deployments(self, repo_id: int) -> None:
        async with SessionLocal() as s:
            repo = await s.get(Repo, repo_id, options=[
                selectinload(Repo.source).selectinload(Source.account)
            ])
            if not repo:
                return
            account = repo.source.account
            provider = provider_for(account)
            try:
                infos = await provider.list_deployments(repo.full_name)
            except ProviderError as e:
                _record_error(account, e)
                _record_rate(account, provider)
                repo.deployments_synced_at = utcnow()
                await s.commit()
                return
            _record_rate(account, provider)
            current = {
                d.environment: d for d in (await s.execute(
                    select(Deployment).where(Deployment.repo_id == repo.id)
                )).scalars()
            }
            seen = set()
            for info in infos:
                seen.add(info.environment)
                d = current.get(info.environment) or Deployment(
                    repo_id=repo.id, environment=info.environment
                )
                for field in ("env_type", "rank", "status", "sha", "ref", "actor",
                              "deployed_at", "url", "run_external_id"):
                    setattr(d, field, getattr(info, field))
                s.add(d)
            for env, d in current.items():
                if env not in seen:
                    await s.delete(d)
            repo.deployments_synced_at = utcnow()
            await s.commit()

    async def force(self, source_id: int | None = None) -> None:
        """Marca todo (o una fuente) para sincronizar en el próximo tick."""
        async with SessionLocal() as s:
            q = select(Source)
            if source_id:
                q = q.where(Source.id == source_id)
            for src in (await s.execute(q.options(selectinload(Source.repos)))).scalars():
                src.last_synced_at = None
                src.repos_etag = None
                for r in src.repos:
                    r.next_poll_at = None
                    r.runs_etag = None
                    r.deployments_synced_at = None
                    r.prs_next_poll_at = None
                    r.prs_etag = None
            await s.commit()
        self.wake()


syncer = Syncer()
