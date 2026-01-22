"""Branch tools for Bitbucket MCP server."""

from typing import Any

from fastmcp import FastMCP
from fastmcp.server.context import Context
from fastmcp.server.dependencies import CurrentContext

from bitbucket_mcp.client import BitbucketClient


def get_client(ctx: Context) -> BitbucketClient:
    """Get the Bitbucket client from context."""
    return ctx.lifespan_context["client"]


def register_branch_tools(mcp: FastMCP) -> None:
    """Register branch-related tools."""

    @mcp.tool
    async def list_branches(
        workspace: str,
        repo_slug: str,
        query: str | None = None,
        page: int = 1,
        pagelen: int = 10,
        ctx: Context = CurrentContext(),
    ) -> dict[str, Any]:
        """List branches for a Bitbucket repository.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            repo_slug: The repository slug.
            query: Filter branches by name (partial match, optional).
            page: Page number for pagination (default: 1).
            pagelen: Number of results per page (default: 10, max: 100).

        Returns:
            Paginated list of branches with their target commits.
        """
        client = get_client(ctx)
        return await client.list_branches(
            workspace=workspace,
            repo_slug=repo_slug,
            query=query,
            page=page,
            pagelen=pagelen,
        )

    @mcp.tool
    async def create_branch(
        workspace: str,
        repo_slug: str,
        name: str,
        target: str,
        ctx: Context = CurrentContext(),
    ) -> dict[str, Any]:
        """Create a new branch in a repository.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            repo_slug: The repository slug.
            name: Name for the new branch.
            target: Commit hash or branch name to create from.

        Returns:
            The created branch details.
        """
        client = get_client(ctx)
        return await client.create_branch(
            workspace=workspace,
            repo_slug=repo_slug,
            name=name,
            target=target,
        )

    @mcp.tool
    async def delete_branch(
        workspace: str,
        repo_slug: str,
        name: str,
        ctx: Context = CurrentContext(),
    ) -> dict[str, Any]:
        """Delete a branch from a repository.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            repo_slug: The repository slug.
            name: Name of the branch to delete.

        Returns:
            Empty dict on success.
        """
        client = get_client(ctx)
        return await client.delete_branch(
            workspace=workspace,
            repo_slug=repo_slug,
            name=name,
        )
