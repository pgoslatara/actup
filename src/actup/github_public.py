from multiprocessing import Pool

import requests
from retry import retry
from tqdm import tqdm

from actup.logger import logger


class GitHubPublicClient:
    """A client for interacting with GitHub public APIs."""

    def __init__(
        self,
    ):
        """Initialize the GitHubClient."""
        self.session = requests.session()

    @retry(delay=5, tries=5)
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
                headers={"accept": "application/json"}, url=f"https://github.com/marketplace/actions/{i['slug']}"
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
        page_numbers = list(range(1, int(limit / 20) + 2))

        with Pool(processes=3) as pool:  # Unable to max out as requests will be blocked
            for result in tqdm(
                pool.imap_unordered(self._search_popular_actions, page_numbers),
                total=len(page_numbers),
                desc="Finding Actions",
            ):
                actions.extend(result)

        return actions[:limit]
