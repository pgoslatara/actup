import os
from multiprocessing import Pool, cpu_count

import requests
from retry import retry
from tqdm import tqdm

from actup.logger import logger


class GitHubPublicClient:
    """A client for interacting with GitHub public APIs.

    Authenticating via a GitHub token increases the number of requests that are tolerated.
    """

    def __init__(
        self,
    ):
        """Initialize the GitHubClient."""
        self.session = requests.session()
        self.token = os.environ.get("PAT_GITHUB")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @retry(delay=10, tries=3)
    def _call_url(self, headers: dict[str, str], url: str) -> dict[str, str]:
        r = self.session.get(headers=headers, url=url)
        return r.json()

    def _search_popular_actions(self, page_num) -> list[dict]:
        actions = []
        url = f"https://github.com/marketplace?page={page_num}&type=actions"
        logger.debug(f"Fetching from {url}")
        marketplace_data = self._call_url(headers={"accept": "application/json"}, url=url)
        for i in marketplace_data["results"]:
            action_data = self._call_url(
                headers=self.headers, url=f"https://github.com/marketplace/actions/{i['slug']}"
            )
            if "error" in action_data:
                logger.warning(f"Unable to fetch info for {i}.")
            else:
                actions.append(
                    {
                        "name": i["name"],
                        "owner": action_data["payload"]["repository"]["owner"],
                        "repo": action_data["payload"]["repository"]["name"],
                        "stars": action_data["payload"]["action"]["stars"],
                        "latest_version": action_data["payload"]["releaseData"]["latestRelease"]["tagName"],
                    }
                )

        return actions

    def search_popular_actions(self, limit) -> list[dict]:
        """Search for popular GitHub Actions."""
        actions = []
        page_numbers = [item for item in list(range(1, int(limit / 20) + 2)) if item <= 500]

        with Pool(processes=min(4, cpu_count())) as pool:  # Unable to max out as requests will be blocked
            for result in tqdm(
                pool.imap_unordered(self._search_popular_actions, page_numbers),
                total=len(page_numbers),
                desc="Finding Actions",
            ):
                actions.extend(result)

        return actions[:limit]
