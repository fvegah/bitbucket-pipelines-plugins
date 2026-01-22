# Bitbucket Pipelines Plugins

A collection of plugins and integrations for Bitbucket Pipelines.

## Plugins

| Plugin | Description |
|--------|-------------|
| [bitbucket-pipelines-mcp](./bitbucket-pipelines-mcp) | MCP server for AI assistants to manage Bitbucket Cloud |

## Overview

This monorepo contains tools that extend Bitbucket Pipelines functionality, with a focus on AI-assisted DevOps workflows.

### bitbucket-pipelines-mcp

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that enables AI assistants like Claude to interact with Bitbucket Cloud. It provides tools to:

- **Manage Pipelines**: List, trigger, stop, and get logs
- **Handle Pull Requests**: Create, review, approve, merge, and decline
- **Work with Branches**: List, create, and delete
- **Access Repositories**: List and get details

## Quick Start

```bash
# Clone the repository
git clone git@github.com:fvegah/bitbucket-pipelines-plugins.git
cd bitbucket-pipelines-plugins

# Navigate to the MCP server
cd bitbucket-pipelines-mcp

# Install dependencies
poetry install

# Configure credentials
cp .env.example .env
# Edit .env with your Bitbucket API token

# Run the server
poetry run bitbucket-mcp
```

## Architecture

```
bitbucket-pipelines-plugins/
├── bitbucket-pipelines-mcp/     # MCP server for Bitbucket Cloud
│   ├── src/
│   │   └── bitbucket_mcp/
│   │       ├── server.py        # FastMCP server setup
│   │       ├── client.py        # Async HTTP client for Bitbucket API
│   │       ├── config.py        # Environment configuration
│   │       ├── exceptions.py    # Custom exceptions
│   │       ├── tools/           # MCP tools by domain
│   │       └── models/          # Pydantic response models
│   ├── pyproject.toml
│   └── README.md
└── CLAUDE.md                    # AI assistant instructions
```

## Workflow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   AI Assistant  │────▶│   MCP Server    │────▶│ Bitbucket Cloud │
│ (Claude, etc.)  │◀────│ (bitbucket-mcp) │◀────│    API v2.0     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │
        │    MCP Protocol       │    HTTPS + Basic Auth
        │    (JSON-RPC)         │    (API Token)
```

1. **AI Assistant** sends tool requests via MCP protocol
2. **MCP Server** translates requests to Bitbucket API calls
3. **Bitbucket Cloud** executes operations and returns results
4. Results flow back through the chain to the AI assistant

## Configuration

### Bitbucket API Token

1. Go to [Atlassian Account Settings](https://id.atlassian.com/manage-profile/security) > **Security**
2. Click **Create and manage API tokens** > **Create API token with scopes**
3. Select **Bitbucket** as the app and add scopes:
   - **Repositories**: Read, Write
   - **Pull requests**: Read, Write
   - **Pipelines**: Read, Write

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BITBUCKET_EMAIL` | Yes | Your Atlassian account email |
| `BITBUCKET_API_TOKEN` | Yes | API token (starts with `ATAT`) |
| `DEFAULT_WORKSPACE` | No | Default workspace slug |

## Integration with Claude

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bitbucket": {
      "command": "poetry",
      "args": ["--directory", "/path/to/bitbucket-pipelines-mcp", "run", "bitbucket-mcp"],
      "env": {
        "BITBUCKET_EMAIL": "your-email@example.com",
        "BITBUCKET_API_TOKEN": "ATAT..."
      }
    }
  }
}
```

### Claude Code

Add to your MCP settings (`.claude/settings.json` or `~/.claude.json`):

```json
{
  "mcpServers": {
    "bitbucket": {
      "command": "poetry",
      "args": ["--directory", "/path/to/bitbucket-pipelines-mcp", "run", "bitbucket-mcp"],
      "env": {
        "BITBUCKET_EMAIL": "your-email@example.com",
        "BITBUCKET_API_TOKEN": "ATAT..."
      }
    }
  }
}
```

## Development

```bash
cd bitbucket-pipelines-mcp

# Install dependencies
poetry install

# Lint
poetry run ruff check src/

# Format
poetry run ruff format src/
```

## License

MIT
