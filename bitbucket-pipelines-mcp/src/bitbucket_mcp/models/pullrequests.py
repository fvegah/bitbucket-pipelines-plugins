"""Pydantic models for Bitbucket pull requests."""

from datetime import datetime

from pydantic import BaseModel, Field


class PRUser(BaseModel):
    """Pull request user."""

    display_name: str
    uuid: str | None = None
    account_id: str | None = None


class PRBranch(BaseModel):
    """Pull request branch reference."""

    name: str
    repository: dict | None = None


class PRSource(BaseModel):
    """Pull request source."""

    branch: PRBranch
    commit: dict | None = None


class PRDestination(BaseModel):
    """Pull request destination."""

    branch: PRBranch
    commit: dict | None = None


class PRLinks(BaseModel):
    """Pull request links."""

    html: dict[str, str] | None = None
    diff: dict[str, str] | None = None
    commits: dict[str, str] | None = None
    approve: dict[str, str] | None = None
    merge: dict[str, str] | None = None
    decline: dict[str, str] | None = None


class PRParticipant(BaseModel):
    """Pull request participant."""

    user: PRUser
    role: str  # PARTICIPANT, REVIEWER
    approved: bool = False
    state: str | None = None  # approved, changes_requested, null


class PullRequest(BaseModel):
    """Bitbucket pull request model."""

    id: int
    title: str
    description: str | None = None
    state: str  # OPEN, MERGED, DECLINED, SUPERSEDED
    author: PRUser | None = None
    source: PRSource
    destination: PRDestination
    close_source_branch: bool = False
    created_on: datetime | None = None
    updated_on: datetime | None = None
    merge_commit: dict | None = None
    closed_by: PRUser | None = None
    reason: str | None = None
    comment_count: int = 0
    task_count: int = 0
    links: PRLinks | None = None
    participants: list[PRParticipant] = Field(default_factory=list)
    reviewers: list[PRUser] = Field(default_factory=list)


class PullRequestList(BaseModel):
    """Paginated list of pull requests."""

    values: list[PullRequest] = Field(default_factory=list)
    pagelen: int = 10
    size: int | None = None
    page: int = 1
    next: str | None = None
    previous: str | None = None
