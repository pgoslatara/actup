import os
import re
import time
from typing import Any

import httpx
from retry import retry

from actup.logger import logger


class GitHubAPIClient:
    """A client for interacting with the GitHub API."""

    def __init__(
        self,
    ):
        """Initialize the GitHubClient."""
        self.token = os.environ.get("PAT_GITHUB")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.client = httpx.Client(base_url="https://api.github.com", headers=self.headers, timeout=30.0)

    def _extract_major_version(self, tag: str) -> str | None:
        match = re.match(r"^v?(\d+)(\.\d+)*$", tag)
        return f"v{match[1]}" if match else None

    @retry(delay=10, tries=5)
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

    def find_workflow_yaml_prs(self, repo_full_name: str) -> list[dict]:
        """Identify relevant pull requests.

        Only looks at PRs that modify YAML files in the .github/workflows directory.
        """
        modified_prs_info = []
        params = {"state": "open", "per_page": 100}
        all_prs = []
        page = 1
        while True:
            paged_params = {**params, "page": page}
            response = self._make_request(method="get", path=f"repos/{repo_full_name}/pulls", params=paged_params)
            if not response:
                break
            all_prs.extend(response)
            page += 1

        if not all_prs:
            logger.info(f"No open pull requests found for {repo_full_name}.")
            return []
        else:
            logger.info(f"Found {len(all_prs)} open pull requests for {repo_full_name}.")

        for pr in all_prs:
            pr_number = pr["number"]
            pr_title = pr["title"]
            pr_html_url = pr["html_url"]
            files_params = {"per_page": 100}
            pr_files = []
            files_page = 1
            while True:
                paged_files_params = {**files_params, "page": files_page}
                files_response = self._make_request(
                    method="get", path=f"repos/{repo_full_name}/pulls/{pr_number}/files", params=paged_files_params
                )
                if not files_response:
                    break
                pr_files.extend(files_response)
                files_page += 1

            for file in pr_files:
                file_name = file.get("filename")
                if (
                    file_name
                    and file_name.startswith(".github/workflows/")
                    and (file_name.endswith(".yml") or file_name.endswith(".yaml"))
                ):
                    modified_prs_info.append(
                        {
                            "number": pr_number,
                            "title": pr_title,
                            "html_url": pr_html_url,
                            "file_modified": file_name,
                            "author": pr["user"]["login"],
                        }
                    )

        logger.info("\n")
        logger.info(
            f"Found {len({i['number'] for i in modified_prs_info})} open pull requests"
            f" for {repo_full_name} that modify `.github/workflows` files."
        )
        return modified_prs_info

    def get_current_user(self) -> str:
        """Get the authenticated user's login."""
        user = self._make_request("GET", "/user")
        return user["login"]

    def get_repo(self, owner: str, repo: str) -> dict:
        """Get repository information."""
        return self._make_request("GET", f"/repos/{owner}/{repo}")

    def get_pull_request_details(self, owner: str, repo: str, number: int) -> dict:
        """Get pull request details."""
        return self._make_request("GET", f"/repos/{owner}/{repo}/pulls/{number}")

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
                if page == 11:  # Not sure why page 10 is getting 403 codes, but it is
                    max_stars_count = int(repos[-1]["stargazers_count"])
                    logger.info(f"Retrieved {len(repos)} repositories...")
                    logger.info(f"Resetting max_stars_count to {max_stars_count}.")
                    time.sleep(60)  # To avoid GitHub returning 403 codes
                    break

        return repos[:limit]

    def sync_fork(self, owner: str, repo: str, branch: str) -> dict:
        """Sync a fork with the upstream repository."""
        data = {"branch": branch}
        return self._make_request("POST", f"/repos/{owner}/{repo}/merge-upstream", json=data)
