import logging
import time
from collections import defaultdict
from datetime import datetime
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
from actup.models import GitHubAction, GitHubRepo, PullRequestRecord
from actup.tracker import update_pr_statuses, update_tracker
from actup.utils import (
    git_clone_shallow,
    git_clone_sparse,
    replace_action_version_in_content,
    search_and_extract_actions,
)

app = typer.Typer()
client_api = GitHubAPIClient()
client_public = GitHubPublicClient()


@app.command()
def create_prs():
    """Create Pull Requests for outdated actions."""
    db = Database()
    outdated = db.get_outdated_mentions()
    db.close()

    if not outdated:
        logger.info("No outdated actions found. Did you run find-outdated-actions?")
        return

    repo_updates = defaultdict(list)
    for mention in outdated:
        repo_updates[mention.repo_full_name].append(mention)

    current_user = client_api.get_current_user()
    temp_dir = Path(settings.temp_dir) / "pr"

    for repo_full_name, mentions in repo_updates.items():
        owner, repo_name = repo_full_name.split("/")
        logger.info(f"Processing updates for {repo_full_name}...")

        target_repo_info = client_api.get_repo(owner, repo_name)
        default_branch = target_repo_info.get("default_branch", "main")
        logger.info("Forking...")
        try:
            client_api.create_fork(owner, repo_name)
            time.sleep(5)
        except Exception:
            logger.info("Fork already exists (or failed), proceeding...")

        try:
            client_api.sync_fork(current_user, repo_name, default_branch)
            logger.info("Fork synced with upstream.")
        except Exception as e:
            logger.warning(f"Could not sync fork: {e}")

        fork_url = f"https://github.com/{current_user}/{repo_name}.git"
        repo_dir = temp_dir / repo_full_name.replace("/", "_")

        logger.info(f"Cloning fork {fork_url}...")
        auth_url = fork_url.replace("https://", f"https://{client_api.token}@")

        repo = git_clone_shallow(auth_url, str(repo_dir))

        branch_name = f"actup/update-actions-{int(datetime.now().timestamp())}"
        repo.git.checkout("-b", branch_name)

        modified_files = set()
        for m in mentions:
            m.file_path = m.file_path.replace("/cloned_repos/", "/pr/")
            full_path = m.file_path
            with open(full_path, "r") as f:
                content = f.read()

            new_content = replace_action_version_in_content(
                content, m.action_name, m.detected_version, m.latest_version
            )

            if new_content != content:
                with open(full_path, "w") as f:
                    f.write(new_content)
                modified_files.add(m.file_path)

        if not modified_files:
            logger.info("No files changed.")
            continue

        if len(mentions) > 1:
            pr_title = commit_message = "docs: Update outdated GitHub Actions versions"
            pr_body = "This PR updates outdated GitHub Action versions.\n\n"
        else:
            pr_title = commit_message = "docs: Update outdated GitHub Actions version"
            pr_body = "This PR updates an outdated GitHub Action version.\n\n"

        repo.index.add(["/".join(m.split("/")[3:]) for m in modified_files])
        repo.index.commit(commit_message)
        logger.info(f"Pushing `{branch_name}`...")
        repo.remote().push(branch_name)

        logger.info("Creating PR...")
        pr_title = pr_title
        pr_body = pr_body
        for m in mentions:
            pr_body += (
                f"- Updated `{m.action_name}` from `{m.detected_version}` to "
                f"`{m.latest_version}` in `{'/'.join(m.file_path.split('/')[3:])}`\n"
            )

        logger.info(
            f"Visit https://github.com/{repo_full_name}/compare/{default_branch}...{current_user}:"
            f"{repo_full_name.split('/')[1]}:{branch_name}?expand=1 to check PR before creation"
        )
        confirmation = input("Happy to proceed (Y/N)?")
        if confirmation.lower() == "y":
            pr = client_api.create_pull_request(
                owner,
                repo_name,
                title=pr_title,
                body=pr_body,
                head=f"{current_user}:{branch_name}",
                base=default_branch,
            )

            logger.info("\n\n")
            logger.info(f"Draft PR created: {pr['html_url']}")
            logger.info("\n\n")

            record = PullRequestRecord(
                repo_full_name=repo_full_name,
                pr_url=pr["html_url"],
                branch_name=branch_name,
                created_at=datetime.now(),
                status=pr["state"],
            )
            db = Database()
            db.save_pr_record(record)
            db.close()
            update_tracker(record)

        # Log to database so we don't re-create PRs
        db = Database()
        db.add_repo_to_pr_exclusions(repo_full_name)
        db.close()


@retry(delay=3, tries=2)
def _fetch_repo_contents(repo_data):
    repo_full_name = repo_data.repo_full_name
    repo_url = repo_data.clone_url
    repo_dir = Path(settings.temp_dir) / "cloned_repos" / repo_full_name.replace("/", "_")
    logger.info(f"Cloning https://www.github.com/{repo_full_name}...")
    git_clone_sparse(repo_url, str(repo_dir))


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
