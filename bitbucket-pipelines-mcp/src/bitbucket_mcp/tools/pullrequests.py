"""Pull request tools for Bitbucket MCP server."""

from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.server.context import Context
from fastmcp.server.dependencies import CurrentContext

from bitbucket_mcp.client import BitbucketClient


def get_client(ctx: Context) -> BitbucketClient:
    """Get the Bitbucket client from context."""
    return ctx.lifespan_context["client"]


def register_pullrequest_tools(mcp: FastMCP) -> None:
    """Register pull request-related tools."""

    @mcp.tool
    async def list_pull_requests(
        workspace: str,
        repo_slug: str,
        state: Literal["OPEN", "MERGED", "DECLINED", "SUPERSEDED"] = "OPEN",
        page: int = 1,
        pagelen: int = 10,
        ctx: Context = CurrentContext(),
    ) -> dict[str, Any]:
        """List pull requests for a Bitbucket repository.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            repo_slug: The repository slug.
            state: Filter by PR state - OPEN, MERGED, DECLINED, or SUPERSEDED (default: OPEN).
            page: Page number for pagination (default: 1).
            pagelen: Number of results per page (default: 10, max: 50).

        Returns:
            Paginated list of pull requests with their details.
        """
        client = get_client(ctx)
        return await client.list_pull_requests(
            workspace=workspace,
            repo_slug=repo_slug,
            state=state,
            page=page,
            pagelen=pagelen,
        )

    @mcp.tool
    async def get_pull_request(
        workspace: str,
        repo_slug: str,
        pr_id: int,
        ctx: Context = CurrentContext(),
    ) -> dict[str, Any]:
        """Get details of a specific pull request.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            repo_slug: The repository slug.
            pr_id: The pull request ID (numeric).

        Returns:
            Pull request details including title, description, author, reviewers, and state.
        """
        client = get_client(ctx)
        return await client.get_pull_request(
            workspace=workspace,
            repo_slug=repo_slug,
            pr_id=pr_id,
        )

    @mcp.tool
    async def create_pull_request(
        workspace: str,
        repo_slug: str,
        title: str,
        source_branch: str,
        destination_branch: str = "main",
        description: str | None = None,
        close_source_branch: bool = False,
        reviewers: list[str] | None = None,
        ctx: Context = CurrentContext(),
    ) -> dict[str, Any]:
        """Create a new pull request.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            repo_slug: The repository slug.
            title: Title of the pull request.
            source_branch: Source branch name.
            destination_branch: Destination branch name (default: 'main').
            description: Description/body of the PR (optional).
            close_source_branch: Whether to close source branch after merge (default: False).
            reviewers: List of reviewer account UUIDs (optional).

        Returns:
            The created pull request details.
        """
        client = get_client(ctx)

        data: dict[str, Any] = {
            "title": title,
            "source": {"branch": {"name": source_branch}},
            "destination": {"branch": {"name": destination_branch}},
            "close_source_branch": close_source_branch,
        }

        if description:
            data["description"] = description

        if reviewers:
            data["reviewers"] = [{"uuid": uuid} for uuid in reviewers]

        return await client.create_pull_request(
            workspace=workspace,
            repo_slug=repo_slug,
            data=data,
        )

    @mcp.tool
    async def approve_pull_request(
        workspace: str,
        repo_slug: str,
        pr_id: int,
        ctx: Context = CurrentContext(),
    ) -> dict[str, Any]:
        """Approve a pull request.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            repo_slug: The repository slug.
            pr_id: The pull request ID (numeric).

        Returns:
            The approval details.
        """
        client = get_client(ctx)
        return await client.approve_pull_request(
            workspace=workspace,
            repo_slug=repo_slug,
            pr_id=pr_id,
        )

    @mcp.tool
    async def merge_pull_request(
        workspace: str,
        repo_slug: str,
        pr_id: int,
        merge_strategy: Literal["merge_commit", "squash", "fast_forward"] = "merge_commit",
        close_source_branch: bool = False,
        message: str | None = None,
        ctx: Context = CurrentContext(),
    ) -> dict[str, Any]:
        """Merge a pull request.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            repo_slug: The repository slug.
            pr_id: The pull request ID (numeric).
            merge_strategy: Strategy for merge - merge_commit, squash, or fast_forward (default: merge_commit).
            close_source_branch: Whether to close the source branch (default: False).
            message: Custom merge commit message (optional).

        Returns:
            The merge details including the resulting commit.
        """
        client = get_client(ctx)
        return await client.merge_pull_request(
            workspace=workspace,
            repo_slug=repo_slug,
            pr_id=pr_id,
            merge_strategy=merge_strategy,
            close_source_branch=close_source_branch,
            message=message,
        )

    @mcp.tool
    async def decline_pull_request(
        workspace: str,
        repo_slug: str,
        pr_id: int,
        ctx: Context = CurrentContext(),
    ) -> dict[str, Any]:
        """Decline (reject) a pull request.

        Args:
            workspace: The Bitbucket workspace slug or UUID.
            repo_slug: The repository slug.
            pr_id: The pull request ID (numeric).

        Returns:
            The declined pull request details.
        """
        client = get_client(ctx)
        return await client.decline_pull_request(
            workspace=workspace,
            repo_slug=repo_slug,
            pr_id=pr_id,
        )
