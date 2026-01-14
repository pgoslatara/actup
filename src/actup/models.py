from datetime import datetime

from pydantic import BaseModel


class GitHubAction(BaseModel):
    """Model representing a GitHub Action."""

    name: str
    owner: str
    repo: str
    stars: int
    latest_version: str | None
    latest_major_version: str | None
    checked_at: datetime | None = None


class GitHubRepo(BaseModel):
    """Model representing a GitHub Repository."""

    repo_full_name: str
    clone_url: str
    stars: int
    archived: bool
    pushed_at: datetime
    fork: bool
    size: int
    checked_at: datetime | None = None


class GitHubUsedAction(BaseModel):
    """Model representing a used GitHub Action."""

    action_raw: str
    file_path: str
    repo_full_name: str
    action_name: str
    action_version: str
    line_number: int
    checked_at: datetime | None = None


class RepositoryMention(BaseModel):
    """Model representing an action mention in a repository."""

    repo_full_name: str
    file_path: str
    line_number: int
    action_name: str
    detected_version: str
    latest_version: str
    stars: int
    is_outdated: bool


class PullRequestRecord(BaseModel):
    """Model representing a pull request record."""

    repo_full_name: str
    pr_url: str
    branch_name: str
    created_at: datetime
    status: str
