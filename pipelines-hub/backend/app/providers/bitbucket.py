"""Bitbucket Cloud Pipelines (API 2.0)."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import quote

import httpx

from app.providers.base import (
    APPROVED,
    CANCELLED,
    CHANGES,
    FAILED,
    PENDING,
    QUEUED,
    RUNNING,
    SKIPPED,
    SUCCESS,
    WAITING,
    AuthError,
    DeploymentInfo,
    HttpApi,
    Identity,
    LogChunk,
    NotFound,
    PRCheck,
    PRComment,
    PRCommit,
    PRDetail,
    PRFile,
    PRInfo,
    ProviderError,
    RepoInfo,
    Reviewer,
    RunInfo,
    SourceInfo,
    StepInfo,
    parse_dt,
)

_RESULT = {
    "SUCCESSFUL": SUCCESS,
    "FAILED": FAILED,
    "ERROR": FAILED,
    "STOPPED": CANCELLED,
    "EXPIRED": CANCELLED,
    "NOT_RUN": SKIPPED,
    "SKIPPED": SKIPPED,
}


def map_state(state: dict | None) -> tuple[str, str]:
    """Estado normalizado + estado crudo legible."""
    state = state or {}
    name = state.get("name") or "PENDING"
    result = (state.get("result") or {}).get("name")
    stage = (state.get("stage") or {}).get("name")
    if name == "COMPLETED":
        return _RESULT.get(result or "", FAILED), f"{name}/{result}"
    if name == "IN_PROGRESS":
        if stage in ("PAUSED", "HALTED"):
            return WAITING, f"{name}/{stage}"
        return RUNNING, name
    if name in ("PAUSED", "HALTED"):
        return WAITING, name
    return QUEUED, name


def _uuid(value: str) -> str:
    value = value.strip()
    return value if value.startswith("{") else f"{{{value}}}"


def _q(value: str) -> str:
    return quote(_uuid(value), safe="")


def _link(obj: dict | None, rel: str) -> str | None:
    return (((obj or {}).get("links") or {}).get(rel) or {}).get("href")


def _workflow(target: dict) -> str:
    sel = target.get("selector") or {}
    kind, pattern = sel.get("type"), sel.get("pattern")
    if kind == "custom":
        return f"custom: {pattern}"
    if kind in ("branches", "tags", "bookmarks"):
        return f"{kind}: {pattern}"
    if kind == "pull-requests":
        return f"pull-requests: {pattern}"
    return "default"


_PR_STATE = {"OPEN": "open", "MERGED": "merged", "DECLINED": "closed", "SUPERSEDED": "closed"}
_STATUS = {"SUCCESSFUL": SUCCESS, "FAILED": FAILED, "INPROGRESS": RUNNING, "STOPPED": CANCELLED}
_MERGE_STRATEGY = {"merge": "merge_commit", "squash": "squash", "rebase": "fast_forward"}
_PR_FIELDS = "+values.participants,+values.draft,-values.description,-values.summary"


def _user_id(u: dict | None) -> str | None:
    u = u or {}
    return u.get("account_id") or u.get("uuid")


def _pr(full_name: str, x: dict) -> PRInfo:
    author = x.get("author") or {}
    reviewers = []
    for p in x.get("participants") or []:
        u = p.get("user") or {}
        state = p.get("state")
        if p.get("approved") or state == "approved":
            st = APPROVED
        elif state == "changes_requested":
            st = CHANGES
        elif p.get("role") == "REVIEWER":
            st = PENDING
        else:
            continue  # solo comentó: no cuenta como revisor
        reviewers.append(Reviewer(_user_id(u) or "?", u.get("display_name") or "?",
                                  _link(u, "avatar"), st, required=p.get("role") == "REVIEWER"))
    return PRInfo(
        number=x["id"],
        title=x.get("title") or "",
        state=_PR_STATE.get(x.get("state"), "closed"),
        draft=bool(x.get("draft")),
        author=author.get("display_name") or author.get("nickname"),
        author_id=_user_id(author),
        author_avatar=_link(author, "avatar"),
        source_branch=((x.get("source") or {}).get("branch") or {}).get("name"),
        target_branch=((x.get("destination") or {}).get("branch") or {}).get("name"),
        head_sha=((x.get("source") or {}).get("commit") or {}).get("hash"),
        url=_link(x, "html") or f"https://bitbucket.org/{full_name}/pull-requests/{x['id']}",
        created_at=parse_dt(x["created_on"]),
        updated_at=parse_dt(x["updated_on"]),
        closed_at=parse_dt(x.get("closed_on")) if x.get("state") != "OPEN" else None,
        comment_count=x.get("comment_count"),
        task_count=x.get("task_count"),
        reviewers=reviewers,
    )


_DIFF_SPLIT = re.compile(r"^diff --git a/(.*?) b/(.*)$", re.M)


def split_diff(raw: str) -> dict[str, str]:
    """Separa un diff unificado por archivo (clave: ruta nueva) y deja solo los hunks."""
    out: dict[str, str] = {}
    matches = list(_DIFF_SPLIT.finditer(raw))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        chunk = raw[m.end():end]
        hunk = chunk.find("\n@@")
        out[m.group(2)] = chunk[hunk + 1:].rstrip("\n") if hunk >= 0 else ""
    return out


class BitbucketProvider:
    kind = "bitbucket"

    def __init__(self, token: str, username: str | None = None, api_url: str | None = None,
                 login: str | None = None, timeout: float = 30):
        # API token de Atlassian (email + token) o access token de workspace/repo (Bearer)
        auth = httpx.BasicAuth(username, token) if username else None
        headers = {"Accept": "application/json", "User-Agent": "pipelines-hub"}
        if not username:
            headers["Authorization"] = f"Bearer {token}"
        self.login = login
        self.api = HttpApi(
            (api_url or "https://api.bitbucket.org/2.0").rstrip("/"),
            auth=auth, headers=headers, timeout=timeout,
        )

    async def aclose(self) -> None:
        await self.api.aclose()

    async def whoami(self) -> Identity:
        try:
            u = await self.api.get_json("/user")
        except AuthError as e:
            if "scope" in e.message.lower():
                raise AuthError(
                    "El token no tiene scopes de Bitbucket. Se creó con \"Create API token\" "
                    "(sin scopes) o para otra app. Crea uno nuevo con \"Create API token with "
                    "scopes\", elige la app Bitbucket y marca read:user, read:workspace, "
                    "read:repository, read:pipeline y read:pullrequest (+ write:pipeline y "
                    "write:pullrequest para actuar).", e.status_code,
                ) from e
            raise
        return Identity(
            login=u.get("username") or u.get("nickname") or u.get("account_id") or "?",
            name=u.get("display_name"),
            avatar_url=_link(u, "avatar"),
            id=u.get("account_id") or u.get("uuid"),
        )

    async def discover_sources(self) -> list[SourceInfo]:
        # /user/workspaces es el endpoint vigente; los otros quedan por compatibilidad
        for path in ("/user/workspaces", "/user/permissions/workspaces", "/workspaces"):
            try:
                data = await self.api.get_json(path, params={"pagelen": 100})
            except (NotFound, ProviderError) as e:
                if isinstance(e, NotFound) or e.status_code in (403, 404, 410):
                    continue
                raise
            out = []
            for v in data.get("values", []):
                ws = v.get("workspace") or v
                if ws.get("slug"):
                    out.append(SourceInfo("workspace", ws["slug"], ws.get("name"),
                                          _link(ws, "avatar")))
            return out
        return []

    async def list_repos(self, kind: str, slug: str, etag: str | None = None
                         ) -> tuple[list[RepoInfo] | None, str | None]:
        data = await self.api.get_json(
            f"/repositories/{slug}",
            params={
                "sort": "-updated_on",
                "pagelen": 100,
                "fields": "values.slug,values.name,values.links.html.href,"
                "values.mainbranch.name,values.updated_on,values.is_private",
            },
        )
        repos = [
            RepoInfo(
                full_name=f"{slug}/{x['slug']}",
                name=x.get("name") or x["slug"],
                html_url=_link(x, "html"),
                default_branch=(x.get("mainbranch") or {}).get("name"),
                activity_at=parse_dt(x.get("updated_on")),
                private=bool(x.get("is_private", True)),
            )
            for x in data.get("values", [])
        ]
        return repos, None

    # --- ejecuciones ------------------------------------------------------------------
    @staticmethod
    def _run(full_name: str, x: dict) -> RunInfo:
        target = x.get("target") or {}
        commit = target.get("commit") or {}
        status, raw = map_state(x.get("state"))
        created = parse_dt(x["created_on"])
        finished = parse_dt(x.get("completed_on"))
        branch = target.get("ref_name") or target.get("source")
        creator = x.get("creator") or {}
        return RunInfo(
            external_id=x["uuid"],
            number=x.get("build_number"),
            attempt=x.get("run_number"),
            workflow=_workflow(target),
            title=(commit.get("message") or "").split("\n")[0] or None,
            status=status,
            raw_status=raw,
            branch=branch,
            sha=commit.get("hash"),
            actor=creator.get("display_name") or creator.get("nickname"),
            actor_avatar=_link(creator, "avatar"),
            event=((x.get("trigger") or {}).get("name") or "").lower() or None,
            url=f"https://bitbucket.org/{full_name}/pipelines/results/{x.get('build_number')}",
            created_at=created,
            started_at=created,
            finished_at=finished,
            duration_s=x.get("duration_in_seconds"),
        )

    async def list_runs(self, full_name: str, etag: str | None = None, limit: int = 30
                        ) -> tuple[list[RunInfo] | None, str | None]:
        try:
            data = await self.api.get_json(
                f"/repositories/{full_name}/pipelines/",
                params={
                    "sort": "-created_on",
                    "pagelen": min(limit, 100),
                    "fields": "+values.target.commit.message",
                },
            )
        except NotFound:
            return [], None
        return [self._run(full_name, x) for x in data.get("values", [])], None

    async def get_run(self, full_name: str, external_id: str) -> RunInfo:
        x = await self.api.get_json(
            f"/repositories/{full_name}/pipelines/{_q(external_id)}",
            params={"fields": "+target.commit.message"},
        )
        return self._run(full_name, x)

    async def get_steps(self, full_name: str, external_id: str) -> list[StepInfo]:
        data = await self.api.get_json(
            f"/repositories/{full_name}/pipelines/{_q(external_id)}/steps/",
            params={"pagelen": 100},
        )
        out = []
        for i, s in enumerate(data.get("values", []), start=1):
            status, _ = map_state(s.get("state"))
            env = s.get("deployment_environment") or s.get("environment") or {}
            out.append(StepInfo(
                id=s["uuid"],
                name=s.get("name") or f"Step {i}",
                status=status,
                started_at=parse_dt(s.get("started_on")),
                finished_at=parse_dt(s.get("completed_on")),
                duration_s=s.get("duration_in_seconds"),
                environment=env.get("name") if isinstance(env, dict) else None,
                manual=(s.get("trigger") or {}).get("type") == "pipeline_step_trigger_manual",
            ))
        return out

    async def get_log(self, full_name: str, external_id: str, step_id: str, offset: int = 0
                      ) -> LogChunk:
        path = f"/repositories/{full_name}/pipelines/{_q(external_id)}/steps/{_q(step_id)}/log"
        headers = {"Accept": "application/octet-stream"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            r = await self.api.client.get(path, headers=headers)
        except httpx.HTTPError as e:
            raise ProviderError(f"Error de red: {e}") from e
        self.api._track(r)
        if r.status_code == 416:  # nada nuevo desde offset
            return LogChunk("", offset, complete=False)
        if r.status_code == 404:
            return LogChunk("", offset, complete=False, available=False,
                            message="El step todavía no tiene log (o ya expiró en Bitbucket).")
        self.api.raise_for(r)
        data = r.content
        if r.status_code == 200 and offset:
            data = data[offset:]  # el servidor ignoró el Range
        # no cortar un carácter UTF-8 multibyte a la mitad
        cut = len(data)
        for back in range(1, 4):
            if cut - back < 0:
                break
            b = data[cut - back]
            if b & 0xC0 == 0x80:
                continue
            if b >= 0xC0:
                need = 2 if b < 0xE0 else 3 if b < 0xF0 else 4
                if back < need:
                    cut -= back
            break
        return LogChunk(data[:cut].decode("utf-8", "replace"), offset + cut, complete=False)

    async def cancel(self, full_name: str, external_id: str) -> None:
        await self.api.request(
            "POST", f"/repositories/{full_name}/pipelines/{_q(external_id)}/stopPipeline"
        )

    async def rerun(self, full_name: str, external_id: str, failed_only: bool = False) -> None:
        if failed_only:
            raise ProviderError("Bitbucket no permite re-ejecutar solo los steps fallidos por API")
        x = await self.api.get_json(f"/repositories/{full_name}/pipelines/{_q(external_id)}")
        t = x.get("target") or {}
        target: dict = {"type": t.get("type", "pipeline_ref_target")}
        for key in ("ref_type", "ref_name", "selector", "source", "destination"):
            if t.get(key):
                target[key] = t[key]
        if (t.get("commit") or {}).get("hash"):
            target["commit"] = {"type": "commit", "hash": t["commit"]["hash"]}
        await self.api.request(
            "POST", f"/repositories/{full_name}/pipelines/", json={"target": target}
        )

    # --- pull requests ------------------------------------------------------------------
    async def list_prs(self, full_name: str, etag: str | None = None, limit: int = 50
                       ) -> tuple[list[PRInfo] | None, str | None]:
        try:
            data = await self.api.get_json(
                f"/repositories/{full_name}/pullrequests",
                params=[("state", "OPEN"), ("state", "MERGED"), ("state", "DECLINED"),
                        ("sort", "-updated_on"), ("pagelen", min(limit, 50)),
                        ("fields", _PR_FIELDS)],
            )
        except NotFound:
            return [], None
        return [_pr(full_name, x) for x in data.get("values", [])], None

    async def pr_reviewers(self, full_name: str, pr: PRInfo) -> list[Reviewer]:
        return pr.reviewers or []

    async def get_pr(self, full_name: str, number: int) -> PRDetail:
        base = f"/repositories/{full_name}/pullrequests/{number}"

        async def safe(coro, default):
            try:
                return await coro
            except ProviderError:
                return default

        async def diff_text():
            r = await self.api.request("GET", f"{base}/diff")
            return r.text[:3_000_000]

        x, diffstat, raw_diff, comments, statuses, commits = await asyncio.gather(
            self.api.get_json(base),
            safe(self.api.get_json(f"{base}/diffstat", params={"pagelen": 500}), {}),
            safe(diff_text(), ""),
            safe(self.api.get_json(f"{base}/comments", params={"pagelen": 100}), {}),
            safe(self.api.get_json(f"{base}/statuses", params={"pagelen": 50}), {}),
            safe(self.api.get_json(f"{base}/commits", params={"pagelen": 50}), {}),
        )
        info = _pr(full_name, x)
        patches = split_diff(raw_diff)
        files = []
        conflict = False
        for d in diffstat.get("values", []):
            new, old = (d.get("new") or {}).get("path"), (d.get("old") or {}).get("path")
            status = d.get("status") or "modified"
            if "conflict" in status:
                conflict, status = True, "conflict"
            path = new or old or "?"
            files.append(PRFile(path, old if old != new else None, status,
                                d.get("lines_added") or 0, d.get("lines_removed") or 0,
                                patches.get(path)))
        return PRDetail(
            info=info,
            body=x.get("description") or "",
            reviewers=info.reviewers or [],
            files=files,
            comments=[
                PRComment(str(c["id"]), (c.get("user") or {}).get("display_name"),
                          _link(c.get("user"), "avatar"), (c.get("content") or {}).get("raw", ""),
                          parse_dt(c.get("created_on")),
                          path=(c.get("inline") or {}).get("path"),
                          line=(c.get("inline") or {}).get("to")
                          or (c.get("inline") or {}).get("from"),
                          url=_link(c, "html"))
                for c in comments.get("values", []) if not c.get("deleted")
            ],
            checks=[
                PRCheck(s.get("name") or s.get("key") or "", _STATUS.get(s.get("state"), QUEUED),
                        s.get("url"), s.get("type"))
                for s in statuses.get("values", [])
            ],
            commits=[
                PRCommit(c["hash"], c.get("message", ""),
                         ((c.get("author") or {}).get("user") or {}).get("display_name")
                         or (c.get("author") or {}).get("raw"), parse_dt(c.get("date")))
                for c in commits.get("values", [])
            ],
            mergeable=False if conflict else None,
            merge_state="dirty" if conflict else None,
            additions=sum(f.additions for f in files),
            deletions=sum(f.deletions for f in files),
            merged_by=((x.get("closed_by") or {}).get("display_name")
                       if x.get("state") == "MERGED" else None),
        )

    async def pr_action(self, full_name: str, number: int, action: str,
                        body: str | None = None, strategy: str | None = None,
                        close_source_branch: bool = False) -> None:
        base = f"/repositories/{full_name}/pullrequests/{number}"
        if action == "approve":
            await self.api.request("POST", f"{base}/approve")
        elif action == "unapprove":
            await self.api.request("DELETE", f"{base}/approve")
        elif action == "request_changes":
            await self.api.request("POST", f"{base}/request-changes")
            if body:
                await self.api.request("POST", f"{base}/comments", json={"content": {"raw": body}})
        elif action == "comment":
            await self.api.request("POST", f"{base}/comments",
                                   json={"content": {"raw": body or ""}})
        elif action == "merge":
            payload = {
                "type": "pullrequest",
                "merge_strategy": _MERGE_STRATEGY.get(strategy or "merge", "merge_commit"),
                "close_source_branch": close_source_branch,
            }
            if body:
                payload["message"] = body
            await self.api.request("POST", f"{base}/merge", json=payload)
        elif action == "decline":
            await self.api.request("POST", f"{base}/decline")
        else:
            raise ProviderError(f"Acción desconocida: {action}", 422)

    # --- despliegues ------------------------------------------------------------------
    async def list_deployments(self, full_name: str) -> list[DeploymentInfo]:
        try:
            envs = (await self.api.get_json(
                f"/repositories/{full_name}/environments/", params={"pagelen": 100}
            )).get("values", [])
        except NotFound:
            return []
        if not envs:
            return []
        params = {"pagelen": 100, "sort": "-state.started_on"}
        try:
            deps = (await self.api.get_json(
                f"/repositories/{full_name}/deployments/", params=params
            )).get("values", [])
        except ProviderError as e:
            if e.status_code != 400:
                raise
            params.pop("sort")
            deps = (await self.api.get_json(
                f"/repositories/{full_name}/deployments/", params=params
            )).get("values", [])

        latest: dict[str, dict] = {}
        for d in deps:
            env_uuid = (d.get("environment") or {}).get("uuid")
            state = d.get("state") or {}
            when = state.get("started_on") or state.get("completed_on") or ""
            if env_uuid and when > ((latest.get(env_uuid) or {}).get("_when") or ""):
                latest[env_uuid] = {**d, "_when": when}

        out = []
        for env in envs:
            d = latest.get(env["uuid"])
            if not d:
                continue
            state = d.get("state") or {}
            name = state.get("name")
            result = (state.get("status") or {}).get("name")
            if name == "IN_PROGRESS":
                status = RUNNING
            elif name == "UNDEPLOYED":
                status = SUCCESS
            else:
                status = _RESULT.get(result or "", SUCCESS if name == "COMPLETED" else QUEUED)
            release = d.get("release") or {}
            deployable = d.get("deployable") or {}
            commit = release.get("commit") or deployable.get("commit") or {}
            pipeline = release.get("pipeline") or deployable.get("pipeline") or {}
            deployer = state.get("deployer") or {}
            out.append(DeploymentInfo(
                environment=env.get("name") or env.get("slug"),
                env_type=(env.get("environment_type") or {}).get("name"),
                rank=(env.get("environment_type") or {}).get("rank", 0) * 100 + env.get("rank", 0),
                status=status,
                sha=commit.get("hash"),
                ref=None,
                actor=deployer.get("display_name"),
                deployed_at=parse_dt(state.get("completed_on") or state.get("started_on")),
                url=state.get("url") or release.get("url") or None,
                run_external_id=pipeline.get("uuid"),
            ))
        return out
