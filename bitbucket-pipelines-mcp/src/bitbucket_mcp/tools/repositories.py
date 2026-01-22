"""Repository tools for Bitbucket MCP server."""

from typing import Any

from fastmcp import FastMCP
from fastmcp.server.context import Context
from fastmcp.server.dependencies import CurrentContext

from bitbucket_mcp.client import BitbucketClient


def get_client(ctx: Context) -> BitbucketClient:
    """Get the Bitbucket client from context."""
    return ctx.lifespan_context["client"]


def register_repository_tools(mcp: FastMCP) -> None:
    """Register repository-related tools."""

    @mcp.tool
    async def list_repositories(
        workspace: str,
        page: int = 1,
        pagelen: int = 10,
        ctx: Context = CurrentContext(),
    ) -> dict[str, Any]:
        """List repositories in a Bitbucket workspace.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            page: Page number for pagination (default: 1).
            pagelen: Number of results per page (default: 10, max: 100).

        Returns:
            Paginated list of repositories with their details.
        """
        client = get_client(ctx)
        return await client.list_repositories(
            workspace=workspace,
            page=page,
            pagelen=pagelen,
        )

    @mcp.tool
    async def get_repository(
        workspace: str,
        repo_slug: str,
        ctx: Context = CurrentContext(),
    ) -> dict[str, Any]:
        """Get details of a specific repository.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            repo_slug: The repository slug.

        Returns:
            Repository details including name, description, owner, and settings.
        """
        client = get_client(ctx)
        return await client.get_repository(
            workspace=workspace,
            repo_slug=repo_slug,
        )
