"""Pydantic models for Bitbucket repositories."""

from datetime import datetime

from pydantic import BaseModel, Field


class RepositoryLinks(BaseModel):
    """Repository links."""

    html: dict[str, str] | None = None
    clone: list[dict[str, str]] | None = None


class Project(BaseModel):
    """Project model."""

    key: str
    name: str
    uuid: str | None = None


class Owner(BaseModel):
    """Repository owner."""

    display_name: str
    uuid: str | None = None
    account_id: str | None = None
    type: str = "user"


class Repository(BaseModel):
    """Bitbucket repository model."""

    uuid: str
    name: str
    full_name: str
    slug: str
    description: str | None = None
    is_private: bool = True
    scm: str = "git"
    created_on: datetime | None = None
    updated_on: datetime | None = None
    size: int | None = None
    language: str | None = None
    has_issues: bool = False
    has_wiki: bool = False
    fork_policy: str | None = None
    project: Project | None = None
    owner: Owner | None = None
    links: RepositoryLinks | None = None
    mainbranch: dict[str, str] | None = None


class RepositoryList(BaseModel):
    """Paginated list of repositories."""

    values: list[Repository] = Field(default_factory=list)
    pagelen: int = 10
    size: int | None = None
    page: int = 1
    next: str | None = None
    previous: str | None = None
