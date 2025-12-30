from datetime import datetime

import duckdb

from actup.config import settings
from actup.models import GitHubAction, GitHubRepo, PullRequestRecord, RepositoryMention


class Database:
    """A wrapper for the DuckDB database."""

    def __init__(self):
        """Initialize the database connection."""
        self.con = duckdb.connect(settings.duckdb_file)
        self.init_db()

    def close(self):
        """Close the database connection."""
        self.con.close()

    def get_outdated_mentions(self) -> list[RepositoryMention]:
        """Get all outdated action mentions."""
        res = self.con.execute("SELECT * FROM action_mentions WHERE is_outdated = true").fetchall()
        return [
            RepositoryMention(
                repo_full_name=r[0],
                file_path=r[1],
                line_number=r[2],
                action_name=r[3],
                detected_version=r[4],
                latest_version=r[5],
                is_outdated=r[6],
            )
            for r in res
        ]

    def get_popular_actions(self) -> list[GitHubAction]:
        """Get all popular actions."""
        res = self.con.execute(
            "SELECT * FROM popular_actions WHERE latest_major_version IS NOT NULL ORDER BY stars DESC"
        ).fetchall()
        return [
            GitHubAction(
                name=r[0],
                owner=r[1],
                repo=r[2],
                stars=int(r[3]),
                latest_version=r[4],
                latest_major_version=r[5],
                checked_at=r[6],
            )
            for r in res
        ]

    def get_popular_repos(self) -> list[GitHubRepo]:
        """Get all popular repos."""
        res = self.con.execute("SELECT * FROM popular_repositories ORDER BY stars DESC").fetchall()
        return [GitHubRepo(repo_full_name=r[0], clone_url=r[1], stars=int(r[2]), checked_at=r[3]) for r in res]

    def init_db(self):
        """Initialise the database tables."""
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS action_mentions (
                repo_full_name VARCHAR,
                file_path VARCHAR,
                line_number INTEGER,
                action_name VARCHAR,
                detected_version VARCHAR,
                latest_version VARCHAR,
                is_outdated BOOLEAN,
                PRIMARY KEY (repo_full_name, file_path, line_number)
            );
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS popular_actions (
                name VARCHAR PRIMARY KEY,
                owner VARCHAR,
                repo VARCHAR,
                stars INTEGER,
                latest_version VARCHAR,
                latest_major_version VARCHAR,
                checked_at TIMESTAMP
            );
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS popular_repositories (
                repo_full_name VARCHAR PRIMARY KEY,
                clone_url VARCHAR,
                stars INTEGER,
                checked_at TIMESTAMP
            );
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS scanned_repositories (
                full_name VARCHAR PRIMARY KEY,
                scanned_at TIMESTAMP
            );
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS pull_requests (
                repo_full_name VARCHAR,
                pr_url VARCHAR PRIMARY KEY,
                branch_name VARCHAR,
                created_at TIMESTAMP,
                status VARCHAR
            );
        """)

    def save_popular_action(self, action: GitHubAction):
        """Save a popular action."""
        self.con.execute(
            """
            INSERT OR REPLACE INTO popular_actions VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                action.name,
                action.owner,
                action.repo,
                action.stars,
                action.latest_version,
                action.latest_major_version,
                datetime.now(),
            ),
        )

    def save_popular_repo(self, repo: GitHubRepo):
        """Save a popular repos."""
        self.con.execute(
            """
            INSERT OR REPLACE INTO popular_repositories VALUES (?, ?, ?, ?)
        """,
            (repo.repo_full_name, repo.clone_url, repo.stars, datetime.now()),
        )

    def save_pr_record(self, pr: PullRequestRecord):
        """Save a pull request record."""
        self.con.execute(
            """
            INSERT OR REPLACE INTO pull_requests VALUES (?, ?, ?, ?, ?)
        """,
            (pr.repo_full_name, pr.pr_url, pr.branch_name, pr.created_at, pr.status),
        )

    def save_repo_mention(self, mention: RepositoryMention):
        """Save a repository mention."""
        self.con.execute(
            """
            INSERT OR REPLACE INTO action_mentions VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                mention.repo_full_name,
                mention.file_path,
                mention.line_number,
                mention.action_name,
                mention.detected_version,
                mention.latest_version,
                mention.is_outdated,
            ),
        )

    def truncate_actions(self):
        """Truncate the popular_actions table."""
        self.con.execute("TRUNCATE TABLE popular_actions")

    def truncate_repositories(self):
        """Truncate the popular_repositories table."""
        self.con.execute("TRUNCATE TABLE popular_repositories")
