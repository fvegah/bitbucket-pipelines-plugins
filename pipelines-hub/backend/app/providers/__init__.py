"""Fábrica de proveedores a partir de una cuenta guardada."""

from typing import Protocol

from app.config import get_settings
from app.crypto import decrypt
from app.providers.base import (
    DeploymentInfo,
    Identity,
    LogChunk,
    PRDetail,
    PRInfo,
    RepoInfo,
    Reviewer,
    RunInfo,
    SourceInfo,
    StepInfo,
)
from app.providers.bitbucket import BitbucketProvider
from app.providers.cloudflare import CloudflareProvider
from app.providers.github import GitHubProvider

PROVIDERS = ("github", "bitbucket", "cloudflare")


class Provider(Protocol):
    kind: str
    api: object

    async def aclose(self) -> None: ...
    async def whoami(self) -> Identity: ...
    async def discover_sources(self) -> list[SourceInfo]: ...
    async def list_repos(self, kind: str, slug: str, etag: str | None = None
                         ) -> tuple[list[RepoInfo] | None, str | None]: ...
    async def list_runs(self, full_name: str, etag: str | None = None, limit: int = 30
                        ) -> tuple[list[RunInfo] | None, str | None]: ...
    async def get_run(self, full_name: str, external_id: str) -> RunInfo: ...
    async def get_steps(self, full_name: str, external_id: str) -> list[StepInfo]: ...
    async def get_log(self, full_name: str, external_id: str, step_id: str, offset: int = 0
                      ) -> LogChunk: ...
    async def cancel(self, full_name: str, external_id: str) -> None: ...
    async def rerun(self, full_name: str, external_id: str, failed_only: bool = False
                    ) -> None: ...
    async def list_deployments(self, full_name: str) -> list[DeploymentInfo]: ...
    async def list_prs(self, full_name: str, etag: str | None = None, limit: int = 50
                       ) -> tuple[list[PRInfo] | None, str | None]: ...
    async def pr_reviewers(self, full_name: str, pr: PRInfo) -> list[Reviewer]: ...
    async def get_pr(self, full_name: str, number: int) -> PRDetail: ...
    async def pr_action(self, full_name: str, number: int, action: str,
                        body: str | None = None, strategy: str | None = None,
                        close_source_branch: bool = False) -> None: ...


def build_provider(provider: str, secret: str, username: str | None = None,
                   api_url: str | None = None, login: str | None = None) -> Provider:
    timeout = get_settings().http_timeout
    if provider == "github":
        return GitHubProvider(secret, api_url=api_url, login=login, timeout=timeout)
    if provider == "bitbucket":
        return BitbucketProvider(secret, username=username or None, api_url=api_url,
                                 login=login, timeout=timeout)
    if provider == "cloudflare":
        return CloudflareProvider(secret, api_url=api_url, login=login, timeout=timeout)
    raise ValueError(f"Proveedor desconocido: {provider}")


_cache: dict[int, tuple[str, Provider]] = {}


def provider_for(account) -> Provider:
    """Un cliente por cuenta, reutilizado mientras la credencial no cambie."""
    key = f"{account.secret_enc}|{account.username}|{account.api_url}|{account.login}"
    hit = _cache.get(account.id)
    if hit and hit[0] == key:
        return hit[1]
    p = build_provider(account.provider, decrypt(account.secret_enc), account.username,
                       account.api_url, account.login)
    _cache[account.id] = (key, p)
    return p


async def drop_provider(account_id: int) -> None:
    hit = _cache.pop(account_id, None)
    if hit:
        await hit[1].aclose()


async def close_all() -> None:
    for _, p in list(_cache.values()):
        await p.aclose()
    _cache.clear()
