# Bitbucket MCP Server

A Model Context Protocol (MCP) server for Bitbucket Cloud that enables AI assistants to manage pipelines, pull requests, branches, and repositories.

## Features

- **Pipelines**: List, trigger, stop pipelines and get step logs
- **Pull Requests**: List, create, approve, merge, decline PRs
- **Branches**: List, create, delete branches
- **Repositories**: List and get repository details

## Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/)
- Bitbucket Cloud account with App Password

## Installation

```bash
cd bitbucket-pipelines-mcp

# Install dependencies
poetry install
```

## Configuration

### Create Bitbucket API Token

> **Note**: App passwords are deprecated. Use API tokens instead.

1. Go to **Bitbucket Settings** > **Atlassian account settings** > **Security**
2. Select **Create and manage API tokens** > **Create API token with scopes**
3. Name the token, set an expiry date, and select **Bitbucket** as the app
4. Add the following scopes:
   - **Repositories**: Read, Write
   - **Pull requests**: Read, Write
   - **Pipelines**: Read, Write

### Environment Variables

Create a `.env` file or set environment variables:

```bash
BITBUCKET_EMAIL=your-email@example.com  # Atlassian account email
BITBUCKET_API_TOKEN=ATAT...your-token   # API token (starts with ATAT)
DEFAULT_WORKSPACE=your-workspace        # Optional
```

## Usage

### Running the Server

```bash
poetry run bitbucket-mcp
```

### Claude Desktop Configuration

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "bitbucket": {
      "command": "poetry",
      "args": ["--directory", "/path/to/bitbucket-pipelines-mcp", "run", "bitbucket-mcp"],
      "env": {
        "BITBUCKET_EMAIL": "your-email@example.com",
        "BITBUCKET_API_TOKEN": "ATAT...your-token"
      }
    }
  }
}
```

### Claude Code Configuration

Add to your Claude Code MCP settings:

```json
{
  "mcpServers": {
    "bitbucket": {
      "command": "poetry",
      "args": ["--directory", "/path/to/bitbucket-pipelines-mcp", "run", "bitbucket-mcp"],
      "env": {
        "BITBUCKET_EMAIL": "your-email@example.com",
        "BITBUCKET_API_TOKEN": "ATAT...your-token"
      }
    }
  }
}
```

## Available Tools

### Repositories

| Tool | Description |
|------|-------------|
| `list_repositories` | List repositories in a workspace |
| `get_repository` | Get details of a specific repository |

### Pipelines

| Tool | Description |
|------|-------------|
| `list_pipelines` | List pipelines for a repository |
| `get_pipeline` | Get details of a specific pipeline |
| `trigger_pipeline` | Trigger a new pipeline run |
| `stop_pipeline` | Stop a running pipeline |
| `get_pipeline_step_log` | Get logs from a pipeline step |

### Pull Requests

| Tool | Description |
|------|-------------|
| `list_pull_requests` | List PRs filtered by state |
| `get_pull_request` | Get details of a specific PR |
| `create_pull_request` | Create a new PR |
| `approve_pull_request` | Approve a PR |
| `merge_pull_request` | Merge a PR |
| `decline_pull_request` | Decline a PR |

### Branches

| Tool | Description |
|------|-------------|
| `list_branches` | List branches in a repository |
| `create_branch` | Create a new branch |
| `delete_branch` | Delete a branch |

## Examples

### List repositories in a workspace

```
list_repositories(workspace="my-workspace")
```

### Trigger a pipeline

```
trigger_pipeline(
    workspace="my-workspace",
    repo_slug="my-repo",
    ref_name="main",
    custom_pipeline="deploy-staging"
)
```

### Create a pull request

```
create_pull_request(
    workspace="my-workspace",
    repo_slug="my-repo",
    title="Add new feature",
    source_branch="feature/new-feature",
    destination_branch="main",
    description="This PR adds a new feature"
)
```

## Development

```bash
# Install with dev dependencies
poetry install

# Run linting
poetry run ruff check src/

# Run formatting
poetry run ruff format src/
```

## License

MIT
