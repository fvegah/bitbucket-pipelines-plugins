"""Tipos normalizados y cliente HTTP común a los proveedores."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

# Estados normalizados de una ejecución o paso
QUEUED, RUNNING, WAITING = "queued", "running", "waiting"
SUCCESS, FAILED, CANCELLED, SKIPPED = "success", "failed", "cancelled", "skipped"
ACTIVE_STATUSES = {QUEUED, RUNNING, WAITING}  # todavía no terminan
IN_PROGRESS_STATUSES = {QUEUED, RUNNING}  # corriendo de verdad (sin los en pausa)


class ProviderError(Exception):
    def __init__(
        self, message: str, status_code: int | None = None, retry_after: int | None = None
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after


class AuthError(ProviderError):
    pass


class NotFound(ProviderError):
    pass


class RateLimited(ProviderError):
    pass


@dataclass
class Identity:
    login: str
    name: str | None = None
    avatar_url: str | None = None
    id: str | None = None  # con qué se compara "yo" en autores y revisores


# Estados de revisión normalizados
APPROVED, CHANGES, COMMENTED, PENDING = "approved", "changes_requested", "commented", "pending"


@dataclass
class Reviewer:
    id: str
    name: str
    avatar: str | None
    state: str  # approved | changes_requested | commented | pending
    required: bool = True  # pedido explícitamente como revisor


@dataclass
class PRInfo:
    number: int
    title: str
    state: str  # open | merged | closed
    draft: bool
    author: str | None
    author_id: str | None
    author_avatar: str | None
    source_branch: str | None
    target_branch: str | None
    head_sha: str | None
    url: str | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    comment_count: int | None = None
    task_count: int | None = None
    reviewers: list[Reviewer] | None = None  # None = hay que pedirlos aparte (GitHub)


@dataclass
class PRFile:
    path: str
    old_path: str | None
    status: str  # added | removed | modified | renamed | conflict
    additions: int
    deletions: int
    patch: str | None = None


@dataclass
class PRComment:
    id: str
    author: str | None
    author_avatar: str | None
    body: str
    created_at: datetime | None
    path: str | None = None
    line: int | None = None
    url: str | None = None


@dataclass
class PRCheck:
    name: str
    status: str  # estados normalizados de ejecución
    url: str | None = None
    source: str | None = None


@dataclass
class PRCommit:
    sha: str
    message: str
    author: str | None
    date: datetime | None


@dataclass
class PRDetail:
    info: PRInfo
    body: str
    reviewers: list[Reviewer]
    files: list[PRFile]
    comments: list[PRComment]
    checks: list[PRCheck]
    commits: list[PRCommit]
    mergeable: bool | None = None  # None = desconocido
    merge_state: str | None = None
    additions: int | None = None
    deletions: int | None = None
    merged_by: str | None = None


@dataclass
class SourceInfo:
    kind: str
    slug: str
    name: str | None = None
    avatar_url: str | None = None


@dataclass
class RepoInfo:
    full_name: str
    name: str
    html_url: str | None
    default_branch: str | None
    activity_at: datetime | None
    private: bool = True
    git_url: str | None = None  # repo de GitHub/GitLab que despliega (Cloudflare)


@dataclass
class RunInfo:
    external_id: str
    number: int | None
    workflow: str | None
    title: str | None
    status: str
    raw_status: str | None
    branch: str | None
    sha: str | None
    actor: str | None
    actor_avatar: str | None
    event: str | None
    url: str | None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_s: int | None = None
    attempt: int | None = None


@dataclass
class SubStep:
    number: int | None
    name: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass
class StepInfo:
    """Un job de GitHub Actions o un step de Bitbucket Pipelines (lo que tiene log)."""

    id: str
    name: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_s: int | None = None
    environment: str | None = None
    manual: bool = False
    url: str | None = None
    substeps: list[SubStep] = field(default_factory=list)


@dataclass
class LogChunk:
    text: str
    next_offset: int
    complete: bool  # True cuando el paso terminó y no llegará más log
    available: bool = True
    message: str | None = None


@dataclass
class DeploymentInfo:
    environment: str
    env_type: str | None
    rank: int
    status: str
    sha: str | None
    ref: str | None
    actor: str | None
    deployed_at: datetime | None
    url: str | None
    run_external_id: str | None


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.replace("Z", "+00:00")
    # Bitbucket manda nanosegundos: Python acepta hasta microsegundos
    if "." in v:
        head, _, tail = v.partition(".")
        digits = "".join(ch for ch in tail if ch.isdigit())
        tz = tail[len(digits):]
        v = f"{head}.{digits[:6]}{tz}"
    dt = datetime.fromisoformat(v)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class HttpApi:
    """Cliente httpx con traducción de errores y registro de rate limit."""

    def __init__(self, base_url: str, *, auth=None, headers: dict | None = None, timeout=30):
        self.client = httpx.AsyncClient(
            base_url=base_url,
            auth=auth,
            headers=headers or {},
            timeout=timeout,
            follow_redirects=True,
        )
        self.rate_remaining: int | None = None
        self.rate_limit: int | None = None

    async def aclose(self) -> None:
        await self.client.aclose()

    def _track(self, r: httpx.Response) -> None:
        rem = r.headers.get("x-ratelimit-remaining")
        lim = r.headers.get("x-ratelimit-limit")
        if rem and rem.isdigit():
            self.rate_remaining = int(rem)
        if lim and lim.isdigit():
            self.rate_limit = int(lim)

    @staticmethod
    def _error_message(r: httpx.Response) -> str:
        try:
            data = r.json()
        except Exception:
            return r.text[:300] or r.reason_phrase
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                return err.get("message") or str(err)
            return data.get("message") or str(data)[:300]
        return str(data)[:300]

    def raise_for(self, r: httpx.Response) -> None:
        if r.is_success or r.status_code == 304:
            return
        msg = self._error_message(r)
        code = r.status_code
        if code == 401:
            raise AuthError(f"Credenciales rechazadas: {msg}", code)
        if code == 429 or (code == 403 and self.rate_remaining == 0):
            ra = r.headers.get("retry-after")
            raise RateLimited(f"Límite de API alcanzado: {msg}", code, int(ra) if ra else 60)
        if code == 404:
            raise NotFound(msg, code)
        raise ProviderError(f"HTTP {code}: {msg}", code)

    async def request(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            r = await self.client.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise ProviderError(f"Error de red: {e.__class__.__name__}: {e}") from e
        self._track(r)
        self.raise_for(r)
        return r

    async def get_json(self, path: str, **kw) -> Any:
        return (await self.request("GET", path, **kw)).json()
