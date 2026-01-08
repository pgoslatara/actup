import os
import re
import time
from typing import Any

import httpx
from retry import retry

from actup.config import settings
from actup.logger import logger


class GitHubAPIClient:
    """A client for interacting with the GitHub API."""

    def __init__(
        self,
    ):
        """Initialize the GitHubClient."""
        self.token = os.environ.get(settings.pat_github_env_var)
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.client = httpx.Client(base_url=settings.github_api_base_url, headers=self.headers, timeout=30.0)

    def _extract_major_version(self, tag: str) -> str | None:
        match = re.match(r"^v?(\d+)(\.\d+)*$", tag)
        return f"v{match[1]}" if match else None

    @retry(delay=10, tries=3)
    def _make_request(self, method: str, path: str, params: dict | None = None, json: dict | None = None) -> Any:
        logger.debug(f"Request: {method} {path}")
        response = self.client.request(method, path, params=params, json=json)
        response.raise_for_status()
        r = response.json()
        logger.debug(f"{r=}")
        return r

    def create_fork(self, owner: str, repo: str) -> dict:
        """Create a fork of the repository."""
        return self._make_request("POST", f"/repos/{owner}/{repo}/forks")

    def create_pull_request(self, owner: str, repo: str, title: str, body: str, head: str, base: str) -> dict:
        """Create a pull request."""
        data = {"title": title, "body": body, "head": head, "base": base, "draft": True}
        return self._make_request("POST", f"/repos/{owner}/{repo}/pulls", json=data)

    def get_current_user(self) -> str:
        """Get the authenticated user's login."""
        user = self._make_request("GET", "/user")
        return user["login"]

    def get_repo(self, owner: str, repo: str) -> dict:
        """Get repository information."""
        return self._make_request("GET", f"/repos/{owner}/{repo}")

    def search_popular_repositories(self, limit) -> list[dict]:
        """Search for popular repositories."""
        repos = []
        max_stars_count = 1_000_000_000
        while len(repos) < limit:
            page = 1
            while True:
                params = {"q": f"stars:1..{max_stars_count} sort:stars", "page": page, "per_page": 100}
                data = self._make_request("GET", "/search/repositories", params=params)
                if not data.get("items", []):
                    break
                repos.extend(data.get("items", []))
                if len(repos) > limit:
                    break
                page += 1
                if page == 10:  # Not sure why page 10 is getting 403 codes, but it is
                    max_stars_count = int(repos[-1]["stargazers_count"])
                    logger.info(f"Resetting max_stars_count to {max_stars_count}.")
                    time.sleep(45)  # To avoid GitHub returning 403 codes
                    break

        return repos[:limit]

    def sync_fork(self, owner: str, repo: str, branch: str) -> dict:
        """Sync a fork with the upstream repository."""
        data = {"branch": branch}
        return self._make_request("POST", f"/repos/{owner}/{repo}/merge-upstream", json=data)
