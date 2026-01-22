"""HTTP client for Bitbucket API."""

from typing import Any

import httpx

from bitbucket_mcp.config import Settings
from bitbucket_mcp.exceptions import (
    AuthenticationError,
    BitbucketError,
    ConflictError,
    NotFoundError,
    PermissionError,
    RateLimitError,
    ValidationError,
)


class BitbucketClient:
    """Async HTTP client for Bitbucket Cloud API."""

    def __init__(self, settings: Settings):
        """Initialize the client with settings."""
        self.settings = settings
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "BitbucketClient":
        """Enter async context."""
        self._client = httpx.AsyncClient(
            base_url=self.settings.api_base_url,
            auth=self.settings.auth,
            timeout=self.settings.timeout,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get the HTTP client, raising if not initialized."""
        if self._client is None:
            raise RuntimeError("Client not initialized. Use async context manager.")
        return self._client

    def _handle_error(self, response: httpx.Response) -> None:
        """Handle HTTP error responses."""
        status_code = response.status_code

        try:
            error_data = response.json()
            error_message = error_data.get("error", {}).get("message", response.text)
        except Exception:
            error_message = response.text

        if status_code == 401:
            raise AuthenticationError()
        elif status_code == 403:
            raise PermissionError(error_message)
        elif status_code == 404:
            raise NotFoundError("Resource", error_message)
        elif status_code == 409:
            raise ConflictError(error_message)
        elif status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimitError(int(retry_after) if retry_after else None)
        elif status_code == 400:
            raise ValidationError(error_message)
        else:
            raise BitbucketError(error_message, status_code)

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a GET request."""
        response = await self.client.get(path, params=params)
        if not response.is_success:
            self._handle_error(response)
        return response.json()

    async def post(
        self, path: str, json: dict[str, Any] | None = None, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make a POST request."""
        response = await self.client.post(path, json=json, params=params)
        if not response.is_success:
            self._handle_error(response)
        # Some endpoints return empty response on success
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    async def put(
        self, path: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make a PUT request."""
        response = await self.client.put(path, json=json)
        if not response.is_success:
            self._handle_error(response)
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    async def delete(self, path: str) -> dict[str, Any]:
        """Make a DELETE request."""
        response = await self.client.delete(path)
        if not response.is_success:
            self._handle_error(response)
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    # Repository methods
    async def list_repositories(
        self, workspace: str, page: int = 1, pagelen: int = 10
    ) -> dict[str, Any]:
        """List repositories in a workspace."""
        return await self.get(
            f"/repositories/{workspace}",
            params={"page": page, "pagelen": pagelen},
        )

    async def get_repository(self, workspace: str, repo_slug: str) -> dict[str, Any]:
        """Get a specific repository."""
        return await self.get(f"/repositories/{workspace}/{repo_slug}")

    # Pipeline methods
    async def list_pipelines(
        self,
        workspace: str,
        repo_slug: str,
        page: int = 1,
        pagelen: int = 10,
        sort: str = "-created_on",
    ) -> dict[str, Any]:
        """List pipelines for a repository."""
        return await self.get(
            f"/repositories/{workspace}/{repo_slug}/pipelines",
            params={"page": page, "pagelen": pagelen, "sort": sort},
        )

    async def get_pipeline(
        self, workspace: str, repo_slug: str, pipeline_uuid: str
    ) -> dict[str, Any]:
        """Get a specific pipeline."""
        return await self.get(
            f"/repositories/{workspace}/{repo_slug}/pipelines/{pipeline_uuid}"
        )

    async def trigger_pipeline(
        self, workspace: str, repo_slug: str, target: dict[str, Any]
    ) -> dict[str, Any]:
        """Trigger a new pipeline."""
        return await self.post(
            f"/repositories/{workspace}/{repo_slug}/pipelines",
            json={"target": target},
        )

    async def stop_pipeline(
        self, workspace: str, repo_slug: str, pipeline_uuid: str
    ) -> dict[str, Any]:
        """Stop a running pipeline."""
        return await self.post(
            f"/repositories/{workspace}/{repo_slug}/pipelines/{pipeline_uuid}/stopPipeline"
        )

    async def get_pipeline_steps(
        self, workspace: str, repo_slug: str, pipeline_uuid: str
    ) -> dict[str, Any]:
        """Get steps for a pipeline."""
        return await self.get(
            f"/repositories/{workspace}/{repo_slug}/pipelines/{pipeline_uuid}/steps"
        )

    async def get_pipeline_step_log(
        self, workspace: str, repo_slug: str, pipeline_uuid: str, step_uuid: str
    ) -> str:
        """Get log for a pipeline step."""
        response = await self.client.get(
            f"/repositories/{workspace}/{repo_slug}/pipelines/{pipeline_uuid}/steps/{step_uuid}/log",
            headers={"Accept": "application/octet-stream"},
        )
        if not response.is_success:
            self._handle_error(response)
        return response.text

    # Pull Request methods
    async def list_pull_requests(
        self,
        workspace: str,
        repo_slug: str,
        state: str = "OPEN",
        page: int = 1,
        pagelen: int = 10,
    ) -> dict[str, Any]:
        """List pull requests for a repository."""
        return await self.get(
            f"/repositories/{workspace}/{repo_slug}/pullrequests",
            params={"state": state, "page": page, "pagelen": pagelen},
        )

    async def get_pull_request(
        self, workspace: str, repo_slug: str, pr_id: int
    ) -> dict[str, Any]:
        """Get a specific pull request."""
        return await self.get(f"/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}")

    async def create_pull_request(
        self, workspace: str, repo_slug: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a new pull request."""
        return await self.post(
            f"/repositories/{workspace}/{repo_slug}/pullrequests",
            json=data,
        )

    async def approve_pull_request(
        self, workspace: str, repo_slug: str, pr_id: int
    ) -> dict[str, Any]:
        """Approve a pull request."""
        return await self.post(
            f"/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/approve"
        )

    async def merge_pull_request(
        self,
        workspace: str,
        repo_slug: str,
        pr_id: int,
        merge_strategy: str = "merge_commit",
        close_source_branch: bool = False,
        message: str | None = None,
    ) -> dict[str, Any]:
        """Merge a pull request."""
        data: dict[str, Any] = {
            "merge_strategy": merge_strategy,
            "close_source_branch": close_source_branch,
        }
        if message:
            data["message"] = message
        return await self.post(
            f"/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/merge",
            json=data,
        )

    async def decline_pull_request(
        self, workspace: str, repo_slug: str, pr_id: int
    ) -> dict[str, Any]:
        """Decline a pull request."""
        return await self.post(
            f"/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/decline"
        )

    # Branch methods
    async def list_branches(
        self,
        workspace: str,
        repo_slug: str,
        query: str | None = None,
        page: int = 1,
        pagelen: int = 10,
    ) -> dict[str, Any]:
        """List branches for a repository."""
        params: dict[str, Any] = {"page": page, "pagelen": pagelen}
        if query:
            params["q"] = f'name ~ "{query}"'
        return await self.get(
            f"/repositories/{workspace}/{repo_slug}/refs/branches",
            params=params,
        )

    async def create_branch(
        self, workspace: str, repo_slug: str, name: str, target: str
    ) -> dict[str, Any]:
        """Create a new branch."""
        return await self.post(
            f"/repositories/{workspace}/{repo_slug}/refs/branches",
            json={"name": name, "target": {"hash": target}},
        )

    async def delete_branch(
        self, workspace: str, repo_slug: str, name: str
    ) -> dict[str, Any]:
        """Delete a branch."""
        return await self.delete(
            f"/repositories/{workspace}/{repo_slug}/refs/branches/{name}"
        )
