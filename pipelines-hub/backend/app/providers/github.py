"""GitHub Actions (REST v3)."""

from __future__ import annotations

import asyncio
import re

from app.providers.base import (
    APPROVED,
    CANCELLED,
    CHANGES,
    COMMENTED,
    FAILED,
    PENDING,
    QUEUED,
    RUNNING,
    SKIPPED,
    SUCCESS,
    WAITING,
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
    SubStep,
    parse_dt,
)

_CONCLUSION = {
    "success": SUCCESS,
    "failure": FAILED,
    "timed_out": FAILED,
    "startup_failure": FAILED,
    "cancelled": CANCELLED,
    "skipped": SKIPPED,
    "neutral": SKIPPED,
    "stale": SKIPPED,
    "action_required": WAITING,
}
_RUN_ID_IN_URL = re.compile(r"/actions/runs/(\d+)")


def map_status(status: str | None, conclusion: str | None) -> str:
    if status == "completed":
        return _CONCLUSION.get(conclusion or "", FAILED)
    if status == "in_progress":
        return RUNNING
    if status == "waiting":
        return WAITING
    return QUEUED


def _deploy_state(state: str | None) -> str:
    return {
        "success": SUCCESS,
        "inactive": SUCCESS,  # reemplazado por uno más nuevo: igual quedó desplegado
        "failure": FAILED,
        "error": FAILED,
        "in_progress": RUNNING,
        "queued": QUEUED,
        "pending": QUEUED,
        "waiting": WAITING,
    }.get(state or "", QUEUED)


class GitHubProvider:
    kind = "github"

    def __init__(self, token: str, api_url: str | None = None, login: str | None = None,
                 timeout: float = 30):
        self.login = login
        self.api = HttpApi(
            (api_url or "https://api.github.com").rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "pipelines-hub",
            },
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self.api.aclose()

    # --- identidad y organizaciones -------------------------------------------------
    async def whoami(self) -> Identity:
        u = await self.api.get_json("/user")
        return Identity(login=u["login"], name=u.get("name"), avatar_url=u.get("avatar_url"),
                        id=u["login"].lower())

    async def discover_sources(self) -> list[SourceInfo]:
        me = await self.whoami()
        out = [SourceInfo("user", me.login, me.name or me.login, me.avatar_url)]
        orgs = await self.api.get_json("/user/orgs", params={"per_page": 100})
        out += [SourceInfo("org", o["login"], o["login"], o.get("avatar_url")) for o in orgs]
        return out

    async def list_repos(self, kind: str, slug: str, etag: str | None = None
                         ) -> tuple[list[RepoInfo] | None, str | None]:
        params = {"per_page": 100, "sort": "pushed", "direction": "desc"}
        if kind == "org":
            path = f"/orgs/{slug}/repos"
            params["type"] = "all"
        elif self.login and slug.lower() == self.login.lower():
            path = "/user/repos"
            params["affiliation"] = "owner"
        else:
            path = f"/users/{slug}/repos"
        headers = {"If-None-Match": etag} if etag else {}
        r = await self.api.request("GET", path, params=params, headers=headers)
        if r.status_code == 304:
            return None, etag
        repos = [
            RepoInfo(
                full_name=x["full_name"],
                name=x["name"],
                html_url=x.get("html_url"),
                default_branch=x.get("default_branch"),
                activity_at=parse_dt(x.get("pushed_at") or x.get("updated_at")),
                private=bool(x.get("private")),
            )
            for x in r.json()
            if not x.get("archived")
        ]
        return repos, r.headers.get("etag")

    # --- ejecuciones ------------------------------------------------------------------
    @staticmethod
    def _run(x: dict) -> RunInfo:
        started = parse_dt(x.get("run_started_at"))
        status = map_status(x.get("status"), x.get("conclusion"))
        finished = parse_dt(x.get("updated_at")) if x.get("status") == "completed" else None
        actor = x.get("triggering_actor") or x.get("actor") or {}
        return RunInfo(
            external_id=str(x["id"]),
            number=x.get("run_number"),
            attempt=x.get("run_attempt"),
            workflow=x.get("name"),
            title=(x.get("display_title") or (x.get("head_commit") or {}).get("message") or "")
            .split("\n")[0],
            status=status,
            raw_status=f"{x.get('status')}/{x.get('conclusion')}" if x.get("conclusion")
            else x.get("status"),
            branch=x.get("head_branch"),
            sha=x.get("head_sha"),
            actor=actor.get("login"),
            actor_avatar=actor.get("avatar_url"),
            event=x.get("event"),
            url=x.get("html_url"),
            created_at=parse_dt(x["created_at"]),
            started_at=started,
            finished_at=finished,
            duration_s=int((finished - started).total_seconds()) if finished and started else None,
        )

    async def list_runs(self, full_name: str, etag: str | None = None, limit: int = 30
                        ) -> tuple[list[RunInfo] | None, str | None]:
        headers = {"If-None-Match": etag} if etag else {}
        try:
            r = await self.api.request(
                "GET", f"/repos/{full_name}/actions/runs",
                params={"per_page": limit}, headers=headers,
            )
        except NotFound:
            return [], None
        if r.status_code == 304:
            return None, etag
        return [self._run(x) for x in r.json().get("workflow_runs", [])], r.headers.get("etag")

    async def get_run(self, full_name: str, external_id: str) -> RunInfo:
        return self._run(await self.api.get_json(f"/repos/{full_name}/actions/runs/{external_id}"))

    async def get_steps(self, full_name: str, external_id: str) -> list[StepInfo]:
        jobs: list[dict] = []
        page = 1
        while True:
            data = await self.api.get_json(
                f"/repos/{full_name}/actions/runs/{external_id}/jobs",
                params={"per_page": 100, "page": page, "filter": "latest"},
            )
            jobs += data.get("jobs", [])
            if len(jobs) >= data.get("total_count", 0) or not data.get("jobs"):
                break
            page += 1
        out = []
        for j in jobs:
            started, finished = parse_dt(j.get("started_at")), parse_dt(j.get("completed_at"))
            status = map_status(j.get("status"), j.get("conclusion"))
            out.append(StepInfo(
                id=str(j["id"]),
                name=j.get("name") or f"job {j['id']}",
                status=status,
                started_at=started,
                finished_at=finished,
                duration_s=int((finished - started).total_seconds())
                if started and finished and status not in (QUEUED, RUNNING) else None,
                url=j.get("html_url"),
                substeps=[
                    SubStep(
                        number=s.get("number"),
                        name=s.get("name", ""),
                        status=map_status(s.get("status"), s.get("conclusion")),
                        started_at=parse_dt(s.get("started_at")),
                        finished_at=parse_dt(s.get("completed_at")),
                    )
                    for s in j.get("steps") or []
                ],
            ))
        return out

    async def get_log(self, full_name: str, external_id: str, step_id: str, offset: int = 0
                      ) -> LogChunk:
        try:
            r = await self.api.request("GET", f"/repos/{full_name}/actions/jobs/{step_id}/logs")
        except NotFound:
            return LogChunk("", offset, complete=False, available=False,
                            message="GitHub publica el log de un job cuando termina.")
        data = r.content
        return LogChunk(data[offset:].decode("utf-8", "replace"), len(data), complete=True)

    async def cancel(self, full_name: str, external_id: str) -> None:
        await self.api.request("POST", f"/repos/{full_name}/actions/runs/{external_id}/cancel")

    async def rerun(self, full_name: str, external_id: str, failed_only: bool = False) -> None:
        action = "rerun-failed-jobs" if failed_only else "rerun"
        await self.api.request("POST", f"/repos/{full_name}/actions/runs/{external_id}/{action}")

    # --- pull requests ------------------------------------------------------------------
    async def list_prs(self, full_name: str, etag: str | None = None, limit: int = 50
                       ) -> tuple[list[PRInfo] | None, str | None]:
        headers = {"If-None-Match": etag} if etag else {}
        try:
            r = await self.api.request(
                "GET", f"/repos/{full_name}/pulls",
                params={"state": "all", "sort": "updated", "direction": "desc",
                        "per_page": limit},
                headers=headers,
            )
        except NotFound:
            return [], None
        if r.status_code == 304:
            return None, etag
        return [_pr(x) for x in r.json()], r.headers.get("etag")

    async def pr_reviewers(self, full_name: str, pr: PRInfo) -> list[Reviewer]:
        reviews = await self.api.get_json(
            f"/repos/{full_name}/pulls/{pr.number}/reviews", params={"per_page": 100}
        )
        return merge_reviewers(pr.reviewers or [], reviews, pr.author_id)

    async def get_pr(self, full_name: str, number: int) -> PRDetail:
        base = f"/repos/{full_name}"
        x = await self.api.get_json(f"{base}/pulls/{number}")
        info = _pr(x)
        sha = info.head_sha

        async def paged(path, pages=3):
            out = []
            for page in range(1, pages + 1):
                data = await self.api.get_json(path, params={"per_page": 100, "page": page})
                out += data
                if len(data) < 100:
                    break
            return out

        async def checks():
            if not sha:
                return []
            out = []
            try:
                cr = await self.api.get_json(f"{base}/commits/{sha}/check-runs",
                                             params={"per_page": 100})
                for c in cr.get("check_runs", []):
                    out.append(PRCheck(c.get("name", ""), map_status(c.get("status"),
                                       c.get("conclusion")), c.get("html_url"),
                                       (c.get("app") or {}).get("name")))
            except ProviderError:
                pass
            try:
                st = await self.api.get_json(f"{base}/commits/{sha}/status")
                legacy = {"success": SUCCESS, "failure": FAILED, "error": FAILED,
                          "pending": RUNNING}
                for c in st.get("statuses", []):
                    out.append(PRCheck(c.get("context", ""), legacy.get(c.get("state"), QUEUED),
                                       c.get("target_url"), "status"))
            except ProviderError:
                pass
            return out

        reviews, files, issue_comments, review_comments, check_list, commits = (
            await asyncio.gather(
                paged(f"{base}/pulls/{number}/reviews", 1),
                paged(f"{base}/pulls/{number}/files"),
                paged(f"{base}/issues/{number}/comments", 2),
                paged(f"{base}/pulls/{number}/comments", 2),
                checks(),
                paged(f"{base}/pulls/{number}/commits", 1),
            )
        )
        comments = [
            PRComment(str(c["id"]), (c.get("user") or {}).get("login"),
                      (c.get("user") or {}).get("avatar_url"), c.get("body") or "",
                      parse_dt(c.get("created_at")), url=c.get("html_url"))
            for c in issue_comments
        ] + [
            PRComment(str(c["id"]), (c.get("user") or {}).get("login"),
                      (c.get("user") or {}).get("avatar_url"), c.get("body") or "",
                      parse_dt(c.get("created_at")), path=c.get("path"),
                      line=c.get("line") or c.get("original_line"), url=c.get("html_url"))
            for c in review_comments
        ] + [
            PRComment(f"r{rv['id']}", (rv.get("user") or {}).get("login"),
                      (rv.get("user") or {}).get("avatar_url"),
                      rv.get("body") or "", parse_dt(rv.get("submitted_at")),
                      url=rv.get("html_url"))
            for rv in reviews if rv.get("body")
        ]
        comments.sort(key=lambda c: c.created_at.isoformat() if c.created_at else "")
        status_map = {"added": "added", "removed": "removed", "renamed": "renamed"}
        return PRDetail(
            info=info,
            body=x.get("body") or "",
            reviewers=merge_reviewers(info.reviewers or [], reviews, info.author_id),
            files=[
                PRFile(f["filename"], f.get("previous_filename"),
                       status_map.get(f.get("status"), "modified"),
                       f.get("additions", 0), f.get("deletions", 0), f.get("patch"))
                for f in files
            ],
            comments=comments,
            checks=check_list,
            commits=[
                PRCommit(c["sha"], (c.get("commit") or {}).get("message", ""),
                         (c.get("author") or {}).get("login")
                         or ((c.get("commit") or {}).get("author") or {}).get("name"),
                         parse_dt(((c.get("commit") or {}).get("author") or {}).get("date")))
                for c in commits
            ],
            mergeable=x.get("mergeable"),
            merge_state=x.get("mergeable_state"),
            additions=x.get("additions"),
            deletions=x.get("deletions"),
            merged_by=(x.get("merged_by") or {}).get("login"),
        )

    async def pr_action(self, full_name: str, number: int, action: str,
                        body: str | None = None, strategy: str | None = None,
                        close_source_branch: bool = False) -> None:
        base = f"/repos/{full_name}"
        if action == "approve":
            await self.api.request("POST", f"{base}/pulls/{number}/reviews",
                                   json={"event": "APPROVE", "body": body or ""})
        elif action == "request_changes":
            if not body:
                raise ProviderError("GitHub exige un comentario para pedir cambios", 422)
            await self.api.request("POST", f"{base}/pulls/{number}/reviews",
                                   json={"event": "REQUEST_CHANGES", "body": body})
        elif action == "unapprove":
            raise ProviderError("GitHub no permite retirar una aprobación por API; "
                                "hay que pedir cambios o descartar la review en GitHub", 422)
        elif action == "comment":
            await self.api.request("POST", f"{base}/issues/{number}/comments",
                                   json={"body": body or ""})
        elif action == "merge":
            payload = {"merge_method": _MERGE_METHOD.get(strategy or "merge", "merge")}
            if body:
                payload["commit_title"] = body
            await self.api.request("PUT", f"{base}/pulls/{number}/merge", json=payload)
            if close_source_branch:
                pr = await self.api.get_json(f"{base}/pulls/{number}")
                head = pr.get("head") or {}
                if (head.get("repo") or {}).get("full_name") == full_name:
                    await self.api.request("DELETE", f"{base}/git/refs/heads/{head['ref']}")
        elif action == "decline":
            await self.api.request("PATCH", f"{base}/pulls/{number}", json={"state": "closed"})
        else:
            raise ProviderError(f"Acción desconocida: {action}", 422)

    # --- despliegues ------------------------------------------------------------------
    async def list_deployments(self, full_name: str) -> list[DeploymentInfo]:
        try:
            envs = (await self.api.get_json(
                f"/repos/{full_name}/environments", params={"per_page": 100}
            )).get("environments", [])
        except (NotFound, ProviderError) as e:
            if isinstance(e, NotFound) or e.status_code in (403, 404):
                return []
            raise
        out = []
        for rank, env in enumerate(envs):
            name = env["name"]
            deps = await self.api.get_json(
                f"/repos/{full_name}/deployments", params={"environment": name, "per_page": 1}
            )
            if not deps:
                continue
            d = deps[0]
            statuses = await self.api.get_json(
                f"/repos/{full_name}/deployments/{d['id']}/statuses", params={"per_page": 1}
            )
            st = statuses[0] if statuses else {}
            link = st.get("log_url") or st.get("target_url") or ""
            m = _RUN_ID_IN_URL.search(link)
            out.append(DeploymentInfo(
                environment=name,
                env_type=_guess_env_type(name),
                rank=rank,
                status=_deploy_state(st.get("state")) if st else QUEUED,
                sha=d.get("sha"),
                ref=d.get("ref"),
                actor=(d.get("creator") or {}).get("login"),
                deployed_at=parse_dt(st.get("created_at") or d.get("created_at")),
                url=link or None,
                run_external_id=m.group(1) if m else None,
            ))
        return out


_REVIEW_STATE = {"APPROVED": APPROVED, "CHANGES_REQUESTED": CHANGES, "COMMENTED": COMMENTED}
_MERGE_METHOD = {"merge": "merge", "squash": "squash", "rebase": "rebase"}


def _pr(x: dict) -> PRInfo:
    state = "open" if x.get("state") == "open" else ("merged" if x.get("merged_at") else "closed")
    user = x.get("user") or {}
    requested = [
        Reviewer(r["login"].lower(), r["login"], r.get("avatar_url"), PENDING)
        for r in x.get("requested_reviewers") or []
    ]
    return PRInfo(
        number=x["number"],
        title=x.get("title") or "",
        state=state,
        draft=bool(x.get("draft")),
        author=user.get("login"),
        author_id=(user.get("login") or "").lower() or None,
        author_avatar=user.get("avatar_url"),
        source_branch=(x.get("head") or {}).get("ref"),
        target_branch=(x.get("base") or {}).get("ref"),
        head_sha=(x.get("head") or {}).get("sha"),
        url=x.get("html_url"),
        created_at=parse_dt(x["created_at"]),
        updated_at=parse_dt(x["updated_at"]),
        closed_at=parse_dt(x.get("merged_at") or x.get("closed_at")),
        comment_count=(x.get("comments") or 0) + (x.get("review_comments") or 0)
        if "comments" in x else None,
        reviewers=requested,  # se completan con las reviews aparte
    )


def merge_reviewers(requested: list[Reviewer], reviews: list[dict],
                    author_id: str | None) -> list[Reviewer]:
    """Estado vigente por persona: la última review que no sea solo comentario manda,
    y quien fue (re)pedido como revisor queda pendiente."""
    out: dict[str, Reviewer] = {}
    for rv in sorted(reviews, key=lambda r: r.get("submitted_at") or ""):
        user = rv.get("user") or {}
        login = (user.get("login") or "").lower()
        state = _REVIEW_STATE.get(rv.get("state"))
        if not login or login == author_id or not state:
            continue
        prev = out.get(login)
        if prev and state == COMMENTED and prev.state in (APPROVED, CHANGES):
            continue
        out[login] = Reviewer(login, user.get("login"), user.get("avatar_url"), state,
                              required=False)
    for r in requested:
        prev = out.get(r.id)
        out[r.id] = Reviewer(r.id, r.name, r.avatar or (prev.avatar if prev else None), PENDING)
    return list(out.values())


def _guess_env_type(name: str) -> str | None:
    n = name.lower()
    if any(k in n for k in ("prod", "live", "stable")):
        return "Production"
    if any(k in n for k in ("stag", "pre", "uat", "qa")):
        return "Staging"
    if any(k in n for k in ("test", "dev", "preview")):
        return "Test"
    return None
