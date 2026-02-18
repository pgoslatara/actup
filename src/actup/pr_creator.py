import shutil
import time
from datetime import datetime
from enum import Enum
from pathlib import Path

from git import Repo

from actup.config import settings
from actup.database import Database
from actup.github_api import GitHubAPIClient
from actup.logger import logger
from actup.models import PullRequestRecord, RepositoryMention
from actup.tracker import update_tracker
from actup.utils import (
    git_clone_shallow,
    merge_pr_body_into_template,
    replace_action_version_in_content,
)


class UpdateMode(str, Enum):
    """Mode for updating GitHub Actions in PRs."""

    LATEST_VERSION = "latest_version"
    PIN_TO_SHA = "pin_to_sha"


class PullRequestCreator:
    """A modular class for creating pull requests to update GitHub Actions."""

    def __init__(
        self,
        client: GitHubAPIClient | None = None,
        temp_dir: str | None = None,
        pin_to_sha: bool = False,
    ):
        """Initialize the PullRequestCreator.

        Args:
            client: Optional GitHub API client. If not provided, a new one will be created.
            temp_dir: Optional temp directory path. Defaults to settings.temp_dir/pr.
            pin_to_sha: Whether to pin actions to commit SHAs instead of version tags.

        """
        self.client = client or GitHubAPIClient()
        self.temp_dir = Path(temp_dir or settings.temp_dir) / "pr"
        self.current_user = None
        self.pin_to_sha = pin_to_sha
        self.mode = UpdateMode.PIN_TO_SHA if pin_to_sha else UpdateMode.LATEST_VERSION

    def prepare_fork(self, owner: str, repo_name: str) -> str:
        """Fork and sync the repository.

        Args:
            owner: The owner of the original repository.
            repo_name: The name of the repository.

        Returns:
            The username of the authenticated user (fork owner).

        """
        if self.current_user is None:
            self.current_user = self.client.get_current_user()

        target_repo_info = self.client.get_repo(owner, repo_name)
        default_branch = target_repo_info.get("default_branch", "main")

        logger.info("Forking...")
        try:
            self.client.create_fork(owner, repo_name)
            time.sleep(5)
        except Exception:
            logger.info("Fork already exists (or failed), proceeding...")

        try:
            self.client.sync_fork(self.current_user, repo_name, default_branch)
            logger.info("Fork synced with upstream.")
        except Exception as e:
            logger.warning(f"Could not sync fork: {e}")

        return self.current_user

    def clone_repository(self, owner: str, repo_name: str, current_user: str) -> tuple[Repo, Path]:
        """Clone the forked repository.

        Args:
            owner: The owner of the original repository.
            repo_name: The name of the repository.
            current_user: The username of the fork owner.

        Returns:
            A tuple of (Repo object, path to the cloned directory).

        """
        fork_url = f"https://github.com/{current_user}/{repo_name}.git"
        repo_full_name = f"{owner}/{repo_name}"
        repo_dir = self.temp_dir / repo_full_name.replace("/", "_")

        if repo_dir.exists():
            shutil.rmtree(repo_dir)

        logger.info(f"Cloning fork {fork_url}...")
        auth_url = fork_url.replace("https://", f"https://{self.client.token}@")
        repo = git_clone_shallow(auth_url, str(repo_dir))

        return repo, repo_dir

    def create_branch(self, repo: Repo, prefix: str = "actup/update-actions") -> str:
        """Create a new branch.

        Args:
            repo: The Git repository object.
            prefix: The prefix for the branch name.

        Returns:
            The name of the created branch.

        """
        branch_name = f"{prefix}-{int(datetime.now().timestamp())}"
        repo.git.checkout("-b", branch_name)
        return branch_name

    def update_workflow_files(self, mentions: list[RepositoryMention], repo_dir: Path) -> set[str]:
        """Update workflow files with new action versions.

        Args:
            mentions: List of RepositoryMention objects representing outdated actions.
            repo_dir: Path to the cloned repository.

        Returns:
            Set of modified file paths.

        """
        modified_files = set()
        for m in mentions:
            m.file_path = m.file_path.replace("/cloned_repos/", "/pr/")
            full_path = m.file_path
            with open(full_path, "r") as f:
                content = f.read()

            if self.pin_to_sha and m.commit_sha:
                new_content = self._replace_with_sha_comment(content, m.action_name, m.detected_version, m.commit_sha)
            elif m.latest_version:
                new_content = replace_action_version_in_content(
                    content, m.action_name, m.detected_version, m.latest_version
                )

            if new_content != content:
                with open(full_path, "w") as f:
                    f.write(new_content)
                modified_files.add(m.file_path)

        return modified_files

    def _replace_with_sha_comment(self, content: str, action_name: str, old_version: str, commit_sha: str) -> str:
        """Replace version with commit SHA and add a comment with the original version.

        Args:
            content: The file content.
            action_name: The action name (e.g., 'actions/checkout').
            old_version: The old version tag (e.g., 'v4.0.1').
            commit_sha: The commit SHA to pin to.

        Returns:
            The updated content with SHA pinning and comment.

        """
        old_ref = f"uses: {action_name}@{old_version}"
        new_ref = f"uses: {action_name}@{commit_sha} #{old_version}"

        if old_ref in content:
            return content.replace(old_ref, new_ref)
        return content

    def commit_and_push(self, repo: Repo, branch_name: str, modified_files: list[str]) -> None:
        """Commit and push changes to the remote repository.

        Args:
            repo: The Git repository object.
            branch_name: The name of the branch to push.
            modified_files: List of modified file paths to commit.

        """
        repo.index.add(["/".join(m.split("/")[3:]) for m in modified_files])
        if self.pin_to_sha:
            commit_message = "chore: Pin GitHub Actions to commit SHAs"
        else:
            commit_message = "chore: Update outdated GitHub Actions versions"
        repo.index.commit(commit_message)
        logger.info(f"Pushing `{branch_name}`...")
        repo.remote().push(branch_name)

    def check_existing_prs(self, repo_full_name: str) -> list[dict]:
        """Check for existing workflow-related PRs.

        Args:
            repo_full_name: The full name of the repository (owner/repo).

        Returns:
            List of existing PRs that modify workflow files.

        """
        return self.client.find_workflow_yaml_prs(repo_full_name=repo_full_name)

    def should_create_pr(self, existing_prs: list[dict]) -> bool:
        """Determine if a new PR should be created based on existing PRs.

        Args:
            existing_prs: List of existing workflow-related PRs.

        Returns:
            True if a new PR should be created, False otherwise.

        """
        if not existing_prs:
            return True

        for pr in existing_prs:
            title_lower = pr["title"].strip().lower()
            if self.pin_to_sha:
                if (
                    title_lower.find("pin") >= 0
                    and title_lower.find("sha") >= 0
                    or title_lower.find("commit sha") >= 0
                    or pr.get("author") == "pgoslatara"
                ):
                    logger.info(
                        f"PR {pr['number']} already pins GitHub Actions to SHAs "
                        "or is created by me so not creating any PR."
                    )
                    return False
            else:
                if (
                    title_lower.find("(deps): bump actions/") >= 0
                    or title_lower.find("build: bump ") >= 0
                    or title_lower.find("bump ") >= 0
                    or title_lower.find("bump the github-actions group") == 0
                    or title_lower.find("chore(deps): bump ") >= 0
                    or title_lower.find("chore(deps): update ") >= 0
                    or title_lower.find("ci: bump ") >= 0
                    or pr.get("author") == "pgoslatara"
                ):
                    logger.info(
                        f"PR {pr['number']} already updates GitHub Actions or is created by me so not creating any PR."
                    )
                    return False

        return True

    def build_pr_details(self, mentions: list[RepositoryMention], modified_files: set[str]) -> tuple[str, str]:
        """Build the PR title and body.

        Args:
            mentions: List of RepositoryMention objects.
            modified_files: Set of modified file paths.

        Returns:
            A tuple of (title, body).

        """
        if self.pin_to_sha:
            if len(mentions) > 1:
                pr_title = "chore: Pin GitHub Actions to commit SHAs"
            else:
                pr_title = "chore: Pin GitHub Action to commit SHA"

            pr_body = "This PR pins GitHub Actions to exact commit SHAs for more reproducible builds.\n\n"
            for m in mentions:
                sha_short = m.commit_sha[:7] if m.commit_sha else "unknown"
                pr_body += (
                    f"- Pinned `{m.action_name}` from `{m.detected_version}` to `{sha_short}` "
                    f"in `{'/'.join(m.file_path.split('/')[3:])}`\n"
                )
        else:
            if len(mentions) > 1:
                pr_title = "chore: Update outdated GitHub Actions versions"
            else:
                pr_title = "chore: Update outdated GitHub Actions version"

            pr_body = "This PR updates outdated GitHub Action versions.\n\n"
            for m in mentions:
                pr_body += (
                    f"- Updated `{m.action_name}` from `{m.detected_version}` to "
                    f"`{m.latest_version}` in `{'/'.join(m.file_path.split('/')[3:])}`\n"
                )

        return pr_title, pr_body

    def get_pr_template_content(self, repo_dir: Path) -> str | None:
        """Check for and read PR template if it exists.

        Args:
            repo_dir: Path to the cloned repository.

        Returns:
            The PR template content, or None if not found.

        """
        dot_github_dir = repo_dir / ".github"
        if not dot_github_dir.exists():
            return None

        for f in dot_github_dir.iterdir():
            if f.is_file() and f.name.lower() == "pull_request_template.md":
                with open(f, "r") as fp:
                    return fp.read()

        return None

    def merge_with_template(self, pr_body: str, template_content: str) -> str:
        """Merge PR body with template using LLM.

        Args:
            pr_body: The generated PR body.
            template_content: The PR template content.

        Returns:
            The merged PR body.

        """
        logger.info("Found PR template file, merging changes into template...")
        merged_body = merge_pr_body_into_template(pr_body=pr_body, pull_request_template_body=template_content)
        logger.info(f"See below the PR body that will be used: \n{merged_body}")
        return merged_body

    def create_pr(
        self,
        owner: str,
        repo_name: str,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> dict:
        """Create a pull request via the GitHub API.

        Args:
            owner: The owner of the repository.
            repo_name: The name of the repository.
            title: The PR title.
            body: The PR body.
            head: The branch name (format: username:branch).
            base: The target branch.

        Returns:
            The created PR object from GitHub API.

        """
        return self.client.create_pull_request(
            owner=owner,
            repo=repo_name,
            title=title,
            body=body,
            head=head,
            base=base,
        )

    def record_pr(self, repo_full_name: str, pr_url: str, branch_name: str, pr_state: str) -> None:
        """Record the created PR in the database and tracker.

        Args:
            repo_full_name: The full name of the repository.
            pr_url: The URL of the created PR.
            branch_name: The branch name used for the PR.
            pr_state: The state of the PR (e.g., 'open').

        """
        record = PullRequestRecord(
            repo_full_name=repo_full_name,
            pr_url=pr_url,
            branch_name=branch_name,
            created_at=datetime.now(),
            status=pr_state,
        )
        db = Database()
        db.save_pr_record(record)
        db.add_repo_to_pr_exclusions(repo_full_name)
        db.close()
        update_tracker(record)

    def mark_repo_excluded(self, repo_full_name: str) -> None:
        """Mark a repository as excluded from PR creation.

        Args:
            repo_full_name: The full name of the repository.

        """
        db = Database()
        db.add_repo_to_pr_exclusions(repo_full_name)
        db.close()

    def create_pr_for_repo(
        self,
        repo_full_name: str,
        mentions: list[RepositoryMention],
        interactive: bool = True,
        pin_to_sha: bool | None = None,
    ) -> PullRequestRecord | None:
        """Create a PR for a single repository.

        This is a convenience method that orchestrates all the steps.

        Args:
            repo_full_name: The full name of the repository (owner/repo).
            mentions: List of RepositoryMention objects for this repo.
            interactive: Whether to prompt for confirmation before creating PR.
            pin_to_sha: Override the instance pin_to_sha setting.

        Returns:
            The created PullRequestRecord, or None if PR was not created.

        """
        if pin_to_sha is not None:
            old_pin_to_sha = self.pin_to_sha
            self.pin_to_sha = pin_to_sha
            self.mode = UpdateMode.PIN_TO_SHA if pin_to_sha else UpdateMode.LATEST_VERSION

        try:
            owner, repo_name = repo_full_name.split("/")
            logger.info(f"Processing updates for {repo_full_name}...")

            current_user = self.prepare_fork(owner, repo_name)
            repo, repo_dir = self.clone_repository(owner, repo_name, current_user)

            target_repo_info = self.client.get_repo(owner, repo_name)
            default_branch = target_repo_info.get("default_branch", "main")

            if self.pin_to_sha:
                branch_name = self.create_branch(repo, prefix="actup/pin-actions-to-sha")
            else:
                branch_name = self.create_branch(repo)

            modified_files = self.update_workflow_files(mentions, repo_dir)

            if not modified_files:
                logger.info("No files changed.")
                self.mark_repo_excluded(repo_full_name)
                shutil.rmtree(repo_dir)
                return None

            self.commit_and_push(repo, branch_name, list(modified_files))

            pr_title, pr_body = self.build_pr_details(mentions, modified_files)

            wip_pr_url = (
                f"https://github.com/{repo_full_name}/compare/{default_branch}...{current_user}:"
                f"{repo_name}:{branch_name}?expand=1"
            )
            logger.info(f"Visit {wip_pr_url} to check PR before creation")

            existing_prs = self.check_existing_prs(repo_full_name)
            if existing_prs:
                logger.info(
                    "The following PRs relate to `.github/workflows`, please take a look prior to creating a PR:"
                )
                for pr in existing_prs:
                    logger.info(f"{pr['html_url']}: {pr['title']}")

            if not self.should_create_pr(existing_prs):
                self.mark_repo_excluded(repo_full_name)
                shutil.rmtree(repo_dir)
                return None

            template_content = self.get_pr_template_content(repo_dir)
            if template_content:
                pr_body = self.merge_with_template(pr_body, template_content)

            if interactive:
                confirmation = input("Happy for PR to be created (Y/N)?")
                if confirmation.lower() != "y":
                    self.mark_repo_excluded(repo_full_name)
                    shutil.rmtree(repo_dir)
                    return None

            pr = self.create_pr(
                owner=owner,
                repo_name=repo_name,
                title=pr_title,
                body=pr_body,
                head=f"{current_user}:{branch_name}",
                base=default_branch,
            )

            logger.info("\n")
            logger.info(">>>>>>>>>>>>>>>>>>>>>>.")
            logger.info(f"Draft PR created: {pr['html_url']}")
            logger.info(">>>>>>>>>>>>>>>>>>>>>>.")
            logger.info("\n")

            self.record_pr(repo_full_name, pr["html_url"], branch_name, pr["state"])
            shutil.rmtree(repo_dir)

            return PullRequestRecord(
                repo_full_name=repo_full_name,
                pr_url=pr["html_url"],
                branch_name=branch_name,
                created_at=datetime.now(),
                status=pr["state"],
            )
        finally:
            if pin_to_sha is not None:
                self.pin_to_sha = old_pin_to_sha
                self.mode = UpdateMode.PIN_TO_SHA if old_pin_to_sha else UpdateMode.LATEST_VERSION

    def create_prs(
        self,
        mentions: list[RepositoryMention],
        interactive: bool = True,
        pin_to_sha: bool | None = None,
    ) -> list[PullRequestRecord]:
        """Create PRs for all outdated actions grouped by repository.

        Args:
            mentions: List of all RepositoryMention objects.
            interactive: Whether to prompt for confirmation before creating each PR.
            pin_to_sha: Whether to pin actions to commit SHAs instead of version tags.

        Returns:
            List of created PullRequestRecord objects.

        """
        if pin_to_sha is not None:
            self.pin_to_sha = pin_to_sha
            self.mode = UpdateMode.PIN_TO_SHA if pin_to_sha else UpdateMode.LATEST_VERSION

        from collections import defaultdict

        repo_updates = defaultdict(list)
        for mention in mentions:
            repo_updates[mention.repo_full_name].append(mention)

        results = []
        for repo_full_name, repo_mentions in repo_updates.items():
            result = self.create_pr_for_repo(repo_full_name, repo_mentions, interactive)
            if result:
                results.append(result)

        return results
