"""Configuration management using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Bitbucket MCP Server settings.

    Configuration is loaded from environment variables.
    Uses API tokens (app passwords are deprecated as of 2025).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Required credentials - API token authentication
    # Use your Atlassian account email (not Bitbucket username)
    bitbucket_email: str
    bitbucket_api_token: str

    # Optional defaults
    default_workspace: str | None = None

    # API configuration
    api_base_url: str = "https://api.bitbucket.org/2.0"
    timeout: float = 30.0

    @property
    def auth(self) -> tuple[str, str]:
        """Return auth tuple for httpx (email + API token)."""
        return (self.bitbucket_email, self.bitbucket_api_token)


def get_settings() -> Settings:
    """Get settings instance."""
    return Settings()
