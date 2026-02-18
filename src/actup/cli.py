import logging
from multiprocessing import Pool, cpu_count
from pathlib import Path

import typer
from retry import retry
from tqdm import tqdm

from actup.config import settings
from actup.database import Database
from actup.github_api import GitHubAPIClient
from actup.github_public import GitHubPublicClient
from actup.logger import logger
from actup.models import GitHubAction, GitHubRepo
from actup.pr_creator import PullRequestCreator
from actup.tracker import update_pr_statuses
from actup.utils import git_clone_sparse, search_and_extract_actions

app = typer.Typer()
client_api = GitHubAPIClient()
client_public = GitHubPublicClient()


@app.command()
def create_prs(
    pin_to_sha: bool = typer.Option(False, "--pin-to-sha", help="Pin actions to commit SHAs instead of version tags."),
):
    """Create Pull Requests for outdated actions."""
    db = Database()
    outdated = db.get_outdated_mentions()
    db.close()

    if not outdated:
        logger.info("No outdated actions found. Did you run find-outdated-actions?")
        return

    if pin_to_sha:
        logger.info("Mode: Pinning actions to commit SHAs")

    creator = PullRequestCreator(client=client_api)
    creator.create_prs(outdated, pin_to_sha=pin_to_sha)


@retry(delay=3, tries=2)
def _fetch_repo_contents(repo_data):
    repo_full_name = repo_data.repo_full_name
    repo_url = repo_data.clone_url
    repo_dir = Path(settings.temp_dir) / "cloned_repos" / repo_full_name.replace("/", "_")
    logger.info(f"Cloning {repo_url}...")
    git_clone_sparse(repo_url=repo_url, final_target_dir=str(repo_dir))


@app.command()
def fetch_repos():
    """Fetch popular repositories contents."""
    db = Database()
    known_repos = db.get_popular_repos()
    db.close()
    if not known_repos:
        raise RuntimeError("No known repos found. Run find-repos first.")

    with Pool(processes=cpu_count()) as pool:
        for _ in tqdm(
            pool.imap_unordered(_fetch_repo_contents, known_repos), total=len(known_repos), desc="Fetching Repos"
        ):
            pass


@app.command()
def find_actions(limit: int = settings.popular_actions_limit):
    """Fetch popular GitHub Actions and their latest major versions."""
    logger.info(f"Searching for top {limit} popular actions...")
    actions = client_public.search_popular_actions(limit)
    db = Database()
    db.truncate_actions()

    for i, repo_data in enumerate(actions, start=1):
        name = repo_data["name"]
        owner = repo_data["owner"]
        repo_name = repo_data["repo"]
        stars = repo_data["stars"]
        latest_version = repo_data["latest_version"]
        latest_major = client_api._extract_major_version(latest_version)
        action = GitHubAction(
            name=name,
            owner=owner,
            repo=repo_name,
            stars=stars,
            latest_version=latest_version,
            latest_major_version=latest_major,
        )
        db.save_popular_action(action)
    db.close()


@app.command()
def find_outdated_actions():
    """Find outdated actions."""
    db = Database()
    db.find_outdated_actions()
    db.close()


@app.command()
def find_action_shas():
    """Resolve action version tags to commit SHAs for ALL releases."""
    db = Database()
    actions = db.get_popular_actions()
    db.close()

    if not actions:
        logger.info("No popular actions found. Run find-actions first.")
        return

    db = Database()
    actions_to_process = []
    skipped = 0

    for action in actions:
        action_key = f"{action.owner}/{action.repo}"
        if db.has_action_tags(action_key):
            skipped += 1
            logger.debug(f"Skipping {action_key} - already processed")
        else:
            actions_to_process.append(action)

    db.close()

    logger.info(f"Resolving commit SHAs for {len(actions_to_process)} actions ({skipped} already processed)...")

    if not actions_to_process:
        logger.info("All actions already processed.")
        return

    db = Database()

    for action in tqdm(actions_to_process, desc="Resolving SHAs"):
        tags = client_api.get_tags(action.owner, action.repo)
        action_key = f"{action.owner}/{action.repo}"
        for tag in tags:
            tag_name = tag.get("name")
            tag_sha = tag.get("commit", {}).get("sha")
            if tag_name and tag_sha:
                db.save_action_tag(action_key, tag_name, tag_sha)
                logger.debug(f"Resolved {action.name}@{tag_name} -> {tag_sha[:7]}")

    db.close()
    logger.info("Done resolving commit SHAs for all releases.")


@app.command()
def find_repos(limit: int = settings.popular_repos_limit):
    """Find popular repositories."""
    logger.info(f"Searching for top {limit} popular repositories...")
    repos = client_api.search_popular_repositories(limit)
    db = Database()
    db.truncate_repositories()

    for repo_data in repos:
        repo_full_name = repo_data["full_name"]
        clone_url = repo_data["clone_url"]
        stars = repo_data["stargazers_count"]
        archived = repo_data["archived"]
        pushed_at = repo_data["pushed_at"]
        fork = repo_data["fork"]
        size = repo_data["size"]

        action = GitHubRepo(
            repo_full_name=repo_full_name,
            clone_url=clone_url,
            stars=stars,
            archived=archived,
            pushed_at=pushed_at,
            fork=fork,
            size=size,
        )
        db.save_popular_repo(action)
    db.close()


@app.command()
def init_db():
    """Initialize the DuckDB database schema."""
    db = Database()
    db.close()
    logger.info(f"Database initialized at {db.db_file}")


@app.callback()
def main(verbose: bool = typer.Option(False, "-v", "--verbose", help="Enable verbose logging.")):
    """ActUp: A tool to analyze GitHub Action usage."""
    if verbose:
        logger.setLevel(logging.DEBUG)


@app.command()
def report():
    """Update the list of created PRs with their status."""
    update_pr_statuses(client_api)


@app.command()
def scan_repos():
    """Scan popular repositories for outdated action usage."""
    db = Database()
    known_actions = {a.name: a.latest_major_version for a in db.get_popular_actions()}
    known_repos = db.get_popular_repos()
    db.close()
    if not known_actions:
        raise RuntimeError("No known actions found. Run find-actions first.")
    if not known_repos:
        raise RuntimeError("No known repos found. Run find-repos first.")
    if not (Path(settings.temp_dir) / "cloned_repos").exists():
        raise RuntimeError("No cloned repos found. Run fetch-repos first.")

    with Pool(processes=cpu_count()) as pool:
        for _ in tqdm(
            pool.imap_unordered(search_and_extract_actions, known_repos), total=len(known_repos), desc="Scanning Repos"
        ):
            pass

    db = Database()
    db.save_used_actions()
    db.close()


if __name__ == "__main__":
    app()
