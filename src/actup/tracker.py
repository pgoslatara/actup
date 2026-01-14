import re
from pathlib import Path
from typing import TYPE_CHECKING

from actup.logger import logger
from actup.models import PullRequestRecord

if TYPE_CHECKING:
    from actup.github_api import GitHubAPIClient

TRACKER_FILE = "PR_TRACKER.md"


def update_tracker(pr: PullRequestRecord):
    """Update the pull request tracker file."""
    path = Path(TRACKER_FILE)
    if not path.exists():
        with open(path, "w") as f:
            f.write("# Pull Request Tracker\n\n| Date | Repo | PR | Status |\n|---|---|---|---|\n")

    with open(path, "a") as f:
        date_str = pr.created_at.strftime("%Y-%m-%d")
        f.write(f"| {date_str} | {pr.repo_full_name} | [{pr.pr_url}]({pr.pr_url}) | {pr.status} |\n")


def update_pr_statuses(client: "GitHubAPIClient"):
    """Update the status of all PRs in the tracker file."""
    path = Path(TRACKER_FILE)
    if not path.exists():
        logger.warning(f"{TRACKER_FILE} does not exist.")
        return

    logger.info(f"Reading {TRACKER_FILE}...")
    with open(path, "r") as f:
        lines = f.readlines()

    new_lines = []
    updated_count = 0

    # Regex to find PR link: [url](url)
    # And specifically https://github.com/owner/repo/pull/number
    pr_pattern = re.compile(r"\[.*?\]\((https://github\.com/([^/]+)/([^/]+)/pull/(\d+))\)")

    for line in lines:
        if line.strip().startswith("|") and "github.com" in line:
            match = pr_pattern.search(line)
            if match:
                full_url, owner, repo, number = match.groups()
                logger.info(f"Checking status for PR: {full_url}")

                try:
                    pr_details = client.get_pull_request_details(owner, repo, int(number))

                    if pr_details.get("merged"):
                        status = "merged"
                    else:
                        status = pr_details.get("state", "unknown")

                    # Update line
                    # Assuming format | Date | Repo | PR | Status |
                    parts = line.split("|")
                    if len(parts) >= 5:
                        current_status = parts[4].strip()
                        if current_status != status:
                            # Preserve padding if possible, or just space it
                            parts[4] = f" {status} "
                            line = "|".join(parts)
                            updated_count += 1
                            logger.info(f"Updated status for {owner}/{repo}#{number}: {current_status} -> {status}")
                        else:
                            logger.info(f"Status unchanged for {owner}/{repo}#{number}: {status}")
                except Exception as e:
                    logger.error(f"Failed to check status for {full_url}: {e}")

        new_lines.append(line)

    if updated_count > 0:
        with open(path, "w") as f:
            f.writelines(new_lines)
        logger.info(f"Updated {updated_count} PR statuses in {TRACKER_FILE}.")
    else:
        logger.info("No statuses needed updating.")
