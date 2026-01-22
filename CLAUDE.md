# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a monorepo containing plugins for Bitbucket Pipelines. Currently contains:

- **bitbucket-pipelines-mcp**: A Model Context Protocol (MCP) server for Bitbucket Cloud that enables AI assistants to manage pipelines, pull requests, branches, and repositories.

## Commands

All commands should be run from the `bitbucket-pipelines-mcp` directory:

```bash
cd bitbucket-pipelines-mcp

# Install dependencies
poetry install

# Run the MCP server
poetry run bitbucket-mcp

# Lint
poetry run ruff check src/

# Format
poetry run ruff format src/
```

## Architecture

### bitbucket-pipelines-mcp

Built with FastMCP and uses httpx for async HTTP requests to Bitbucket Cloud API v2.0.

**Key Components:**

- `server.py` - FastMCP server setup with lifespan management for the HTTP client
- `client.py` - `BitbucketClient` async HTTP client wrapping all Bitbucket API calls
- `config.py` - Pydantic Settings for configuration via environment variables
- `exceptions.py` - Custom exception hierarchy for API errors (auth, rate limit, not found, etc.)
- `tools/` - MCP tools organized by domain (pipelines, pullrequests, branches, repositories)
- `models/` - Pydantic models for API responses (currently unused but available for typed responses)

**Tool Registration Pattern:**

Each tool module exports a `register_*_tools(mcp)` function that decorates async functions with `@mcp.tool`. Tools access the shared `BitbucketClient` via `ctx.lifespan_context["client"]`.

**Configuration:**

Required environment variables:
- `BITBUCKET_EMAIL` - Your Atlassian account email (not Bitbucket username)
- `BITBUCKET_API_TOKEN` - API token with scopes (starts with ATAT)

Optional:
- `DEFAULT_WORKSPACE`

## Bitbucket API Notes

- Pipeline and step UUIDs must be wrapped in braces (e.g., `{uuid}`) - the tools handle this automatically
- API base URL: `https://api.bitbucket.org/2.0`
- Uses Basic Auth with API tokens (app passwords deprecated since 2025)
