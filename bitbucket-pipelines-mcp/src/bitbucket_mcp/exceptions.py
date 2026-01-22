"""Custom exceptions for Bitbucket MCP server."""


class BitbucketError(Exception):
    """Base exception for Bitbucket API errors."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class AuthenticationError(BitbucketError):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication failed. Check your credentials."):
        super().__init__(message, status_code=401)


class NotFoundError(BitbucketError):
    """Raised when a resource is not found."""

    def __init__(self, resource: str, identifier: str):
        message = f"{resource} not found: {identifier}"
        super().__init__(message, status_code=404)


class RateLimitError(BitbucketError):
    """Raised when rate limit is exceeded."""

    def __init__(self, retry_after: int | None = None):
        message = "Rate limit exceeded."
        if retry_after:
            message += f" Retry after {retry_after} seconds."
        super().__init__(message, status_code=429)
        self.retry_after = retry_after


class ValidationError(BitbucketError):
    """Raised when request validation fails."""

    def __init__(self, message: str):
        super().__init__(message, status_code=400)


class PermissionError(BitbucketError):
    """Raised when user lacks required permissions."""

    def __init__(self, action: str):
        message = f"Permission denied for action: {action}"
        super().__init__(message, status_code=403)


class ConflictError(BitbucketError):
    """Raised when there's a conflict (e.g., merge conflict)."""

    def __init__(self, message: str):
        super().__init__(message, status_code=409)
