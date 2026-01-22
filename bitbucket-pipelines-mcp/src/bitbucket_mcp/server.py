"""FastMCP server for Bitbucket Cloud."""

from collections.abc import AsyncIterator

from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

from bitbucket_mcp.client import BitbucketClient
from bitbucket_mcp.config import get_settings


@lifespan
async def bitbucket_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Manage Bitbucket client lifecycle."""
    settings = get_settings()
    client = BitbucketClient(settings)
    async with client:
        yield {"client": client, "settings": settings}


# Create the FastMCP server
mcp = FastMCP(
    name="bitbucket-mcp",
    instructions="""
    Bitbucket Cloud MCP Server - Manage pipelines, pull requests, branches and repositories.

    This server provides tools to interact with Bitbucket Cloud:
    - Pipelines: List, trigger, stop pipelines and get logs
    - Pull Requests: List, create, approve, merge, decline PRs
    - Branches: List, create, delete branches
    - Repositories: List and get repository details

    All tools require workspace and repo_slug parameters to identify the repository.
    """,
    lifespan=bitbucket_lifespan,
)

# Import and register all tools
from bitbucket_mcp.tools import (
    register_branch_tools,
    register_pipeline_tools,
    register_pullrequest_tools,
    register_repository_tools,
)

register_repository_tools(mcp)
register_pipeline_tools(mcp)
register_pullrequest_tools(mcp)
register_branch_tools(mcp)


def main():
    """Run the MCP server."""
    mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
