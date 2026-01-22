"""Pipeline tools for Bitbucket MCP server."""

from typing import Any

from fastmcp import FastMCP
from fastmcp.server.context import Context
from fastmcp.server.dependencies import CurrentContext

from bitbucket_mcp.client import BitbucketClient


def get_client(ctx: Context) -> BitbucketClient:
    """Get the Bitbucket client from context."""
    return ctx.lifespan_context["client"]


def register_pipeline_tools(mcp: FastMCP) -> None:
    """Register pipeline-related tools."""

    @mcp.tool
    async def list_pipelines(
        workspace: str,
        repo_slug: str,
        page: int = 1,
        pagelen: int = 10,
        sort: str = "-created_on",
        ctx: Context = CurrentContext(),
    ) -> dict[str, Any]:
        """List pipelines for a Bitbucket repository.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            repo_slug: The repository slug.
            page: Page number for pagination (default: 1).
            pagelen: Number of results per page (default: 10, max: 100).
            sort: Sort order. Use '-created_on' for newest first (default).

        Returns:
            Paginated list of pipelines with their status and details.
        """
        client = get_client(ctx)
        return await client.list_pipelines(
            workspace=workspace,
            repo_slug=repo_slug,
            page=page,
            pagelen=pagelen,
            sort=sort,
        )

    @mcp.tool
    async def get_pipeline(
        workspace: str,
        repo_slug: str,
        pipeline_uuid: str,
        ctx: Context = CurrentContext(),
    ) -> dict[str, Any]:
        """Get details of a specific pipeline.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            repo_slug: The repository slug.
            pipeline_uuid: The UUID of the pipeline (with or without braces).

        Returns:
            Pipeline details including state, target, duration, and creator.
        """
        client = get_client(ctx)
        # Ensure UUID is wrapped in braces if not already
        if not pipeline_uuid.startswith("{"):
            pipeline_uuid = f"{{{pipeline_uuid}}}"
        return await client.get_pipeline(
            workspace=workspace,
            repo_slug=repo_slug,
            pipeline_uuid=pipeline_uuid,
        )

    @mcp.tool
    async def trigger_pipeline(
        workspace: str,
        repo_slug: str,
        ref_type: str = "branch",
        ref_name: str = "main",
        custom_pipeline: str | None = None,
        variables: list[dict[str, str]] | None = None,
        ctx: Context = CurrentContext(),
    ) -> dict[str, Any]:
        """Trigger a new pipeline run.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            repo_slug: The repository slug.
            ref_type: Type of reference - 'branch' or 'tag' (default: 'branch').
            ref_name: Name of the branch or tag (default: 'main').
            custom_pipeline: Name of custom pipeline to run (optional).
            variables: List of pipeline variables [{"key": "name", "value": "val"}].

        Returns:
            The created pipeline details including UUID and initial state.
        """
        client = get_client(ctx)

        target: dict[str, Any] = {
            "type": "pipeline_ref_target",
            "ref_type": ref_type,
            "ref_name": ref_name,
        }

        if custom_pipeline:
            target["selector"] = {
                "type": "custom",
                "pattern": custom_pipeline,
            }

        if variables:
            target["variables"] = variables

        return await client.trigger_pipeline(
            workspace=workspace,
            repo_slug=repo_slug,
            target=target,
        )

    @mcp.tool
    async def stop_pipeline(
        workspace: str,
        repo_slug: str,
        pipeline_uuid: str,
        ctx: Context = CurrentContext(),
    ) -> dict[str, Any]:
        """Stop a running pipeline.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            repo_slug: The repository slug.
            pipeline_uuid: The UUID of the pipeline to stop.

        Returns:
            Empty dict on success.
        """
        client = get_client(ctx)
        if not pipeline_uuid.startswith("{"):
            pipeline_uuid = f"{{{pipeline_uuid}}}"
        return await client.stop_pipeline(
            workspace=workspace,
            repo_slug=repo_slug,
            pipeline_uuid=pipeline_uuid,
        )

    @mcp.tool
    async def get_pipeline_step_log(
        workspace: str,
        repo_slug: str,
        pipeline_uuid: str,
        step_uuid: str,
        ctx: Context = CurrentContext(),
    ) -> str:
        """Get the log output of a pipeline step.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            repo_slug: The repository slug.
            pipeline_uuid: The UUID of the pipeline.
            step_uuid: The UUID of the step.

        Returns:
            The log output as plain text.
        """
        client = get_client(ctx)
        if not pipeline_uuid.startswith("{"):
            pipeline_uuid = f"{{{pipeline_uuid}}}"
        if not step_uuid.startswith("{"):
            step_uuid = f"{{{step_uuid}}}"
        return await client.get_pipeline_step_log(
            workspace=workspace,
            repo_slug=repo_slug,
            pipeline_uuid=pipeline_uuid,
            step_uuid=step_uuid,
        )
