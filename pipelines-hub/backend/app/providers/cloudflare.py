"""Cloudflare: Workers Builds (Workers conectados a Git) y Pages.

Mapeo al modelo del panel:
- una cuenta de Cloudflare (las "organizaciones" del dashboard) = Source (kind "account")
- un Worker o un proyecto de Pages = Repo (full_name "<cuenta>/<nombre>")
- un build de Workers Builds / un deployment de Pages = Run
- Workers sin Workers Builds (deploy con wrangler desde otro CI): sus deployments = Run

La API de Workers Builds identifica al Worker por su *tag* y exige un token de usuario
(no de cuenta), así que el proveedor mantiene un índice nombre → (cuenta, tag).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from app.providers.base import (
    CANCELLED,
    FAILED,
    QUEUED,
    RUNNING,
    SKIPPED,
    SUCCESS,
    AuthError,
    DeploymentInfo,
    HttpApi,
    Identity,
    LogChunk,
    NotFound,
    PRDetail,
    PRInfo,
    ProviderError,
    RepoInfo,
    Reviewer,
    RunInfo,
    SourceInfo,
    StepInfo,
    SubStep,
    parse_dt,
)

DASH = "https://dash.cloudflare.com"
_OUTCOME = {"success": SUCCESS, "fail": FAILED, "failure": FAILED, "cancelled": CANCELLED,
            "terminated": CANCELLED, "skipped": SKIPPED}
_STAGE = {"success": SUCCESS, "failure": FAILED, "canceled": CANCELLED, "cancelled": CANCELLED,
          "skipped": SKIPPED, "active": RUNNING, "idle": QUEUED}
_EVENT = {"github:push": "push", "gitlab:push": "push", "ad_hoc": "manual",
          "deploy_hook": "deploy_hook"}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "cuenta"


def _git_url(provider_type: str | None, owner: str | None, repo: str | None) -> str | None:
    if not owner or not repo:
        return None
    host = {"github": "github.com", "gitlab": "gitlab.com"}.get(provider_type or "github")
    return f"https://{host}/{owner}/{repo}" if host else None


def _ts_line(ts, line: str) -> str:
    """Prefija la hora en formato ISO, igual que los logs de GitHub (el visor la entiende)."""
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts, UTC)
        else:
            dt = parse_dt(str(ts))
        return f"{dt.strftime('%Y-%m-%dT%H:%M:%S.%f')}Z {line}"
    except Exception:
        return line


class CloudflareProvider:
    kind = "cloudflare"

    def __init__(self, token: str, api_url: str | None = None, login: str | None = None,
                 timeout: float = 30):
        self.login = login
        self.api = HttpApi(
            (api_url or "https://api.cloudflare.com/client/v4").rstrip("/"),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                     "User-Agent": "pipelines-hub"},
            timeout=timeout,
        )
        self._accounts: dict[str, dict] = {}  # slug -> {id, name}
        self._repos: dict[str, dict] = {}  # full_name -> {type, account_id, name, tag, ...}
        self._git: dict[str, str] = {}  # tag de Worker -> url del repo (sale de los builds)

    async def aclose(self) -> None:
        await self.api.aclose()

    # --- HTTP con el sobre {success, errors, result, result_info} ------------------------
    async def _call(self, method: str, path: str, **kw):
        try:
            r = await self.api.request(method, path, **kw)
        except ProviderError as e:
            raise e.__class__(self._cf_message(e.message), e.status_code, e.retry_after) from e
        if not r.content:
            return None, {}
        data = r.json()
        if isinstance(data, dict) and data.get("success") is False:
            raise ProviderError(self._errors(data), r.status_code)
        if isinstance(data, dict) and "result" in data:
            return data["result"], data.get("result_info") or {}
        return data, {}

    @staticmethod
    def _errors(data: dict) -> str:
        errs = data.get("errors") or []
        return "; ".join(f"{e.get('message')} ({e.get('code')})" for e in errs) or str(data)[:200]

    @staticmethod
    def _cf_message(msg: str) -> str:
        m = re.search(r"'message': '([^']+)'", msg)
        return m.group(1) if m else msg

    async def _get(self, path: str, **params):
        result, _ = await self._call("GET", path, params=params or None)
        return result

    async def _paged(self, path: str, per_page: int = 50, max_pages: int = 10, **params):
        out = []
        for page in range(1, max_pages + 1):
            result, info = await self._call("GET", path,
                                            params={**params, "page": page, "per_page": per_page})
            out += result or []
            if not info or page >= (info.get("total_pages") or 1) or not result:
                break
        return out

    # --- identidad y cuentas -----------------------------------------------------------
    async def whoami(self) -> Identity:
        try:
            tok = await self._get("/user/tokens/verify")
        except AuthError as e:
            raise AuthError(
                "Cloudflare rechazó el token. Tiene que ser un token de *usuario* (My Profile → "
                "API Tokens), no de cuenta: la API de Workers Builds no acepta tokens de cuenta.",
                e.status_code,
            ) from e
        if (tok or {}).get("status") != "active":
            raise AuthError(f"El token está {tok.get('status')}", 401)
        login, name = f"token {tok.get('id', '')[:8]}", None
        try:
            user = await self._get("/user")
            login, name = user.get("email") or login, user.get("first_name")
        except ProviderError:
            pass  # sin permiso "User Details: Read": no es necesario
        return Identity(login=login, name=name, id=login.lower())

    async def _load_accounts(self) -> None:
        accounts = await self._paged("/accounts", per_page=50)
        self._accounts = {}
        for a in accounts:
            slug = slugify(a["name"])
            if slug in self._accounts:
                slug = f"{slug}-{a['id'][:6]}"
            self._accounts[slug] = {"id": a["id"], "name": a["name"]}

    async def _account(self, slug: str) -> dict:
        if slug not in self._accounts:
            await self._load_accounts()
        acc = self._accounts.get(slug) or next(
            (a for a in self._accounts.values() if a["id"] == slug), None)
        if not acc:
            raise NotFound(f"El token no tiene acceso a la cuenta de Cloudflare '{slug}'", 404)
        return acc

    async def discover_sources(self) -> list[SourceInfo]:
        await self._load_accounts()
        return [SourceInfo("account", slug, a["name"]) for slug, a in self._accounts.items()]

    # --- "repos": Workers y proyectos de Pages ------------------------------------------
    async def list_repos(self, kind: str, slug: str, etag: str | None = None
                         ) -> tuple[list[RepoInfo] | None, str | None]:
        acc = await self._account(slug)
        aid = acc["id"]
        out: list[RepoInfo] = []
        names: set[str] = set()
        scripts = await self._get(f"/accounts/{aid}/workers/scripts") or []
        for sc in scripts:
            name = sc["id"]
            full = f"{slug}/{name}"
            names.add(name)
            self._repos[full] = {"type": "worker", "account_id": aid, "name": name,
                                 "tag": sc.get("tag")}
            out.append(RepoInfo(
                full_name=full, name=name,
                html_url=f"{DASH}/{aid}/workers/services/view/{name}/production",
                default_branch=None, activity_at=parse_dt(sc.get("modified_on")),
                git_url=self._git.get(sc.get("tag") or ""),
            ))
        try:
            projects = await self._paged(f"/accounts/{aid}/pages/projects", per_page=10,
                                         max_pages=20)
        except ProviderError as e:
            if e.status_code not in (403, 404):
                raise
            projects = []  # token sin permiso de Pages
        for pj in projects:
            name = pj["name"]
            full = f"{slug}/{name}" if name not in names else f"{slug}/{name}-pages"
            cfg = ((pj.get("source") or {}).get("config") or {})
            git = _git_url((pj.get("source") or {}).get("type"), cfg.get("owner"),
                           cfg.get("repo_name"))
            self._repos[full] = {"type": "pages", "account_id": aid, "name": name,
                                 "subdomain": pj.get("subdomain"), "git_url": git}
            latest = pj.get("latest_deployment") or {}
            out.append(RepoInfo(
                full_name=full, name=name if full.endswith(name) else f"{name} (pages)",
                html_url=f"{DASH}/{aid}/pages/view/{name}",
                default_branch=pj.get("production_branch"),
                activity_at=parse_dt(latest.get("created_on") or pj.get("created_on")),
                git_url=git,
            ))
        return out, None

    async def _repo(self, full_name: str) -> dict:
        if full_name not in self._repos:
            slug = full_name.split("/", 1)[0]
            await self.list_repos("account", slug)
        info = self._repos.get(full_name)
        if not info:
            raise NotFound(f"No existe {full_name} en Cloudflare", 404)
        return info

    # --- ejecuciones ---------------------------------------------------------------------
    def _build_run(self, r: dict, b: dict) -> RunInfo:
        meta = b.get("build_trigger_metadata") or {}
        trig = b.get("trigger") or {}
        st = b.get("status")
        if st == "stopped":
            status = _OUTCOME.get(b.get("build_outcome") or "", FAILED)
        elif st == "running":
            status = RUNNING
        else:
            status = QUEUED
        created = parse_dt(b.get("created_on"))
        started = parse_dt(b.get("running_on") or b.get("initializing_on"))
        finished = parse_dt(b.get("stopped_on")) if st == "stopped" else None
        git = _git_url(meta.get("provider_type"), meta.get("provider_account_name"),
                       meta.get("repo_name"))
        if git and r.get("tag"):
            self._git[r["tag"]] = git
        return RunInfo(
            external_id=b["build_uuid"],
            number=None,
            workflow=f"Workers Builds · {trig.get('trigger_name') or 'build'}",
            title=(meta.get("commit_message") or "").split("\n")[0] or None,
            status=status,
            raw_status=f"{st}/{b.get('build_outcome')}" if b.get("build_outcome") else st,
            branch=meta.get("branch"),
            sha=meta.get("commit_hash"),
            actor=meta.get("author"),
            actor_avatar=None,
            event=meta.get("build_trigger_source"),
            url=f"{DASH}/{r['account_id']}/workers/services/view/{r['name']}/production/builds/"
            f"{b['build_uuid']}",
            created_at=created,
            started_at=started or created,
            finished_at=finished,
            duration_s=int((finished - (started or created)).total_seconds())
            if finished and (started or created) else None,
        )

    def _deploy_run(self, r: dict, d: dict) -> RunInfo:
        """Deployment de un Worker que no usa Workers Builds (wrangler, dashboard, API)."""
        ann = d.get("annotations") or {}
        created = parse_dt(d.get("created_on"))
        return RunInfo(
            external_id=f"deploy:{d['id']}",
            number=None,
            workflow=f"Deploy · {d.get('source') or 'wrangler'}",
            title=ann.get("workers/message") or None,
            status=SUCCESS,
            raw_status="deployed",
            branch=None,
            sha=None,
            actor=d.get("author_email"),
            actor_avatar=None,
            event=ann.get("workers/triggered_by") or d.get("source"),
            url=f"{DASH}/{r['account_id']}/workers/services/view/{r['name']}/production/"
            "deployments",
            created_at=created,
            started_at=created,
            finished_at=created,
            duration_s=None,
        )

    @staticmethod
    def _pages_status(d: dict) -> str:
        if d.get("is_skipped"):
            return SKIPPED
        stage = d.get("latest_stage") or {}
        st = _STAGE.get(stage.get("status") or "", QUEUED)
        if st == SUCCESS and stage.get("name") != "deploy":
            return RUNNING  # terminó una etapa intermedia
        if st == RUNNING and stage.get("name") == "queued":
            return QUEUED
        return st

    def _pages_run(self, r: dict, d: dict) -> RunInfo:
        meta = (d.get("deployment_trigger") or {}).get("metadata") or {}
        stages = d.get("stages") or []
        status = self._pages_status(d)
        created = parse_dt(d.get("created_on"))
        started = next((parse_dt(s.get("started_on")) for s in stages
                        if s.get("name") != "queued" and s.get("started_on")), None) or created
        finished = parse_dt((d.get("latest_stage") or {}).get("ended_on")) \
            if status not in (QUEUED, RUNNING) else None
        return RunInfo(
            external_id=d["id"],
            number=None,
            workflow=f"Pages · {d.get('environment') or 'deploy'}",
            title=(meta.get("commit_message") or "").split("\n")[0] or None,
            status=status,
            raw_status=f"{(d.get('latest_stage') or {}).get('name')}/"
            f"{(d.get('latest_stage') or {}).get('status')}",
            branch=meta.get("branch"),
            sha=meta.get("commit_hash"),
            actor=None,
            actor_avatar=None,
            event=_EVENT.get((d.get("deployment_trigger") or {}).get("type"), "push"),
            url=f"{DASH}/{r['account_id']}/pages/view/{r['name']}/{d['id']}",
            created_at=created,
            started_at=started,
            finished_at=finished,
            duration_s=int((finished - started).total_seconds()) if finished and started else None,
        )

    async def list_runs(self, full_name: str, etag: str | None = None, limit: int = 30
                        ) -> tuple[list[RunInfo] | None, str | None]:
        r = await self._repo(full_name)
        aid = r["account_id"]
        if r["type"] == "pages":
            deps, _ = await self._call(
                "GET", f"/accounts/{aid}/pages/projects/{r['name']}/deployments",
                params={"per_page": min(limit, 25)},
            )
            return [self._pages_run(r, d) for d in deps or []], None
        builds: list = []
        if r.get("tag"):
            try:
                builds, _ = await self._call(
                    "GET", f"/accounts/{aid}/builds/workers/{r['tag']}/builds",
                    params={"per_page": min(limit, 50)},
                )
            except ProviderError as e:
                if e.status_code not in (403, 404):
                    raise
        if builds:
            return [self._build_run(r, b) for b in builds], None
        try:
            data = await self._get(f"/accounts/{aid}/workers/scripts/{r['name']}/deployments")
        except ProviderError:
            return [], None
        deps = (data or {}).get("deployments", []) if isinstance(data, dict) else data or []
        return [self._deploy_run(r, d) for d in deps[:limit]], None

    async def get_run(self, full_name: str, external_id: str) -> RunInfo:
        r = await self._repo(full_name)
        aid = r["account_id"]
        if r["type"] == "pages":
            d = await self._get(
                f"/accounts/{aid}/pages/projects/{r['name']}/deployments/{external_id}")
            return self._pages_run(r, d)
        if external_id.startswith("deploy:"):
            runs, _ = await self.list_runs(full_name)
            hit = next((x for x in runs or [] if x.external_id == external_id), None)
            if not hit:
                raise NotFound("Deployment no encontrado", 404)
            return hit
        return self._build_run(r, await self._get(f"/accounts/{aid}/builds/builds/{external_id}"))

    async def get_steps(self, full_name: str, external_id: str) -> list[StepInfo]:
        run = await self.get_run(full_name, external_id)
        r = await self._repo(full_name)
        substeps: list[SubStep] = []
        if r["type"] == "pages":
            d = await self._get(
                f"/accounts/{r['account_id']}/pages/projects/{r['name']}/deployments/"
                f"{external_id}")
            substeps = [
                SubStep(i, s.get("name", ""), _STAGE.get(s.get("status") or "", QUEUED),
                        parse_dt(s.get("started_on")), parse_dt(s.get("ended_on")))
                for i, s in enumerate(d.get("stages") or [], start=1)
            ]
        if external_id.startswith("deploy:"):
            name = "Deploy (sin log: se hizo fuera de Workers Builds)"
        else:
            name = "Build y deploy" if r["type"] == "worker" else "Deployment de Pages"
        return [StepInfo(
            id=external_id, name=name, status=run.status, started_at=run.started_at,
            finished_at=run.finished_at, duration_s=run.duration_s,
            environment=(run.workflow or "").split(" · ")[-1] if r["type"] == "pages" else None,
            url=run.url, substeps=substeps,
        )]

    async def get_log(self, full_name: str, external_id: str, step_id: str, offset: int = 0
                      ) -> LogChunk:
        r = await self._repo(full_name)
        aid = r["account_id"]
        if external_id.startswith("deploy:"):
            return LogChunk("", offset, complete=True, available=False,
                            message="Este deploy se hizo con wrangler/API fuera de Workers "
                                    "Builds: Cloudflare no guarda log.")
        lines: list[str] = []
        try:
            if r["type"] == "pages":
                data = await self._get(
                    f"/accounts/{aid}/pages/projects/{r['name']}/deployments/{external_id}"
                    "/history/logs")
                lines = [_ts_line(x.get("ts"), x.get("line", "")) for x in
                         (data or {}).get("data", [])]
            else:
                cursor = None
                for _ in range(50):  # hasta ~50 páginas
                    params = {"cursor": cursor} if cursor else {}
                    data = await self._get(f"/accounts/{aid}/builds/builds/{external_id}/logs",
                                           **params)
                    chunk = (data or {}).get("lines") or []
                    lines += [_ts_line(ts, msg) for ts, msg in chunk]
                    cursor = (data or {}).get("cursor")
                    if not cursor or not chunk or not (data or {}).get("truncated", True):
                        break
        except NotFound:
            return LogChunk("", offset, complete=False, available=False,
                            message="Todavía no hay log para este build.")
        text = "\n".join(lines) + ("\n" if lines else "")
        data_b = text.encode()
        return LogChunk(data_b[offset:].decode("utf-8", "replace"), len(data_b), complete=False)

    async def cancel(self, full_name: str, external_id: str) -> None:
        r = await self._repo(full_name)
        if r["type"] == "pages" or external_id.startswith("deploy:"):
            raise ProviderError("Cloudflare no permite cancelar un deployment de Pages por API",
                                422)
        await self._call("PUT", f"/accounts/{r['account_id']}/builds/builds/{external_id}/cancel")

    async def rerun(self, full_name: str, external_id: str, failed_only: bool = False) -> None:
        r = await self._repo(full_name)
        aid = r["account_id"]
        if external_id.startswith("deploy:"):
            raise ProviderError("Este deploy no vino de Workers Builds: no hay build que "
                                "re-lanzar", 422)
        if r["type"] == "pages":
            await self._call("POST", f"/accounts/{aid}/pages/projects/{r['name']}/deployments/"
                                     f"{external_id}/retry")
            return
        b = await self._get(f"/accounts/{aid}/builds/builds/{external_id}")
        trig = (b.get("trigger") or {}).get("trigger_uuid")
        meta = b.get("build_trigger_metadata") or {}
        if not trig:
            raise ProviderError("El build no tiene trigger asociado", 422)
        body = {k: v for k, v in {"branch": meta.get("branch"),
                                  "commit_hash": meta.get("commit_hash")}.items() if v}
        await self._call("POST", f"/accounts/{aid}/builds/triggers/{trig}/builds", json=body)

    # --- entornos ------------------------------------------------------------------------
    async def list_deployments(self, full_name: str) -> list[DeploymentInfo]:
        r = await self._repo(full_name)
        aid = r["account_id"]
        out: list[DeploymentInfo] = []
        if r["type"] == "pages":
            for rank, env in enumerate(("production", "preview")):
                deps, _ = await self._call(
                    "GET", f"/accounts/{aid}/pages/projects/{r['name']}/deployments",
                    params={"env": env, "per_page": 1},
                )
                if not deps:
                    continue
                run = self._pages_run(r, deps[0])
                out.append(DeploymentInfo(
                    environment=env, env_type="Production" if env == "production" else "Test",
                    rank=rank, status=run.status, sha=run.sha, ref=run.branch, actor=None,
                    deployed_at=run.finished_at or run.created_at,
                    url=deps[0].get("url") or run.url, run_external_id=run.external_id,
                ))
            return out
        try:
            data = await self._get(f"/accounts/{aid}/workers/scripts/{r['name']}/deployments")
        except ProviderError:
            return []
        deps = (data or {}).get("deployments", []) if isinstance(data, dict) else data or []
        if not deps:
            return []
        d = deps[0]
        sha = ref = run_id = None
        version = next((v.get("version_id") for v in d.get("versions") or []), None)
        if version:
            try:
                builds = await self._get(f"/accounts/{aid}/builds/builds",
                                         version_ids=version)
                b = (builds or {}).get(version) if isinstance(builds, dict) else \
                    next(iter(builds or []), None)
                if b:
                    meta = b.get("build_trigger_metadata") or {}
                    sha, ref, run_id = meta.get("commit_hash"), meta.get("branch"), \
                        b.get("build_uuid")
            except ProviderError:
                pass
        out.append(DeploymentInfo(
            environment="production", env_type="Production", rank=0, status=SUCCESS,
            sha=sha, ref=ref, actor=d.get("author_email"),
            deployed_at=parse_dt(d.get("created_on")),
            url=f"{DASH}/{aid}/workers/services/view/{r['name']}/production/deployments",
            run_external_id=run_id or f"deploy:{d['id']}",
        ))
        return out

    # --- Cloudflare no tiene pull requests ---------------------------------------------
    async def list_prs(self, full_name: str, etag: str | None = None, limit: int = 50
                       ) -> tuple[list[PRInfo] | None, str | None]:
        return [], None

    async def pr_reviewers(self, full_name: str, pr: PRInfo) -> list[Reviewer]:
        return []

    async def get_pr(self, full_name: str, number: int) -> PRDetail:
        raise ProviderError("Cloudflare no tiene pull requests", 404)

    async def pr_action(self, full_name: str, number: int, action: str, body=None,
                        strategy=None, close_source_branch: bool = False) -> None:
        raise ProviderError("Cloudflare no tiene pull requests", 404)
