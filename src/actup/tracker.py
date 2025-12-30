from pathlib import Path

from actup.models import PullRequestRecord

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
