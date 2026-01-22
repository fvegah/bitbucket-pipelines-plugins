"""Pydantic models for Bitbucket pipelines."""

from datetime import datetime

from pydantic import BaseModel, Field


class PipelineSelector(BaseModel):
    """Pipeline selector for custom pipelines."""

    type: str = "custom"
    pattern: str | None = None


class PipelineRefTarget(BaseModel):
    """Reference target (branch/tag)."""

    ref_type: str = Field(alias="type", default="branch")
    ref_name: str | None = None


class PipelineCommit(BaseModel):
    """Commit information in a pipeline."""

    hash: str
    message: str | None = None


class PipelineTarget(BaseModel):
    """Pipeline target configuration."""

    type: str = "pipeline_ref_target"
    ref_type: str | None = None
    ref_name: str | None = None
    commit: PipelineCommit | None = None
    selector: PipelineSelector | None = None


class PipelineState(BaseModel):
    """Pipeline state information."""

    name: str
    type: str | None = None
    result: dict | None = None


class PipelineCreator(BaseModel):
    """Pipeline creator information."""

    display_name: str | None = None
    uuid: str | None = None
    account_id: str | None = None


class Pipeline(BaseModel):
    """Bitbucket pipeline model."""

    uuid: str
    build_number: int
    created_on: datetime | None = None
    completed_on: datetime | None = None
    state: PipelineState | None = None
    target: PipelineTarget | None = None
    trigger: dict | None = None
    creator: PipelineCreator | None = None
    repository: dict | None = None
    duration_in_seconds: int | None = None


class PipelineList(BaseModel):
    """Paginated list of pipelines."""

    values: list[Pipeline] = Field(default_factory=list)
    pagelen: int = 10
    size: int | None = None
    page: int = 1
    next: str | None = None
    previous: str | None = None


class PipelineStepState(BaseModel):
    """Pipeline step state."""

    name: str
    type: str | None = None
    result: dict | None = None


class PipelineStep(BaseModel):
    """Pipeline step model."""

    uuid: str
    name: str | None = None
    started_on: datetime | None = None
    completed_on: datetime | None = None
    state: PipelineStepState | None = None
    duration_in_seconds: int | None = None
    run_number: int | None = None
    image: dict | None = None
    script_commands: list[dict] | None = None


class PipelineStepList(BaseModel):
    """Paginated list of pipeline steps."""

    values: list[PipelineStep] = Field(default_factory=list)
    pagelen: int = 10
    size: int | None = None
    page: int = 1
    next: str | None = None
    previous: str | None = None
