"""Pydantic models for Bitbucket branches."""

from datetime import datetime

from pydantic import BaseModel, Field


class BranchTarget(BaseModel):
    """Branch target (commit)."""

    hash: str
    date: datetime | None = None
    message: str | None = None
    author: dict | None = None


class BranchLinks(BaseModel):
    """Branch links."""

    html: dict[str, str] | None = None
    commits: dict[str, str] | None = None


class Branch(BaseModel):
    """Bitbucket branch model."""

    name: str
    target: BranchTarget | None = None
    links: BranchLinks | None = None
    type: str = "branch"
    default_merge_strategy: str | None = None
    merge_strategies: list[str] | None = None


class BranchList(BaseModel):
    """Paginated list of branches."""

    values: list[Branch] = Field(default_factory=list)
    pagelen: int = 10
    size: int | None = None
    page: int = 1
    next: str | None = None
    previous: str | None = None
