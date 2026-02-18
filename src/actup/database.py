from datetime import datetime
from functools import cache
from pathlib import Path

import duckdb

from actup.config import settings
from actup.logger import logger
from actup.models import GitHubAction, GitHubRepo, PullRequestRecord, RepositoryMention
from actup.utils import is_major_version_outdated


class Database:
    """A wrapper for the DuckDB database."""

    def __init__(self, db_file: str | None = None):
        """Initialize the database connection."""
        self.db_file = "./actup.duckdb"
        self.con = duckdb.connect(self.db_file)
        self.init_db()

    def add_repo_to_pr_exclusions(self, repo_full_name: str) -> None:
        """Add a repo to the pr_exclusions table."""
        self.con.execute(
            """
            INSERT OR REPLACE INTO pull_request_exclusions VALUES (?)
        """,
            (repo_full_name,),
        )

    def close(self):
        """Close the database connection."""
        self.con.close()

    def find_outdated_actions(self) -> None:
        """Save outdated actions."""
        actions = self.con.query("""
            SELECT DISTINCT
                au.repo_full_name,
                au.action_name,
                au.action_version,
                au.filepath,
                au.line_number,
                pa.latest_major_version
            FROM action_usage au
            LEFT JOIN popular_actions pa ON CONCAT(pa.owner, '/', pa.repo) = au.action_name
            WHERE
                SUBSTRING(au.action_version, 1, 1) = 'v'
                AND au.line_number <> -1 -- Denotes unknowns
        """).fetchall()

        for i in range(len(actions)):
            actions[i] = actions[i] + (
                is_major_version_outdated(detected_version=actions[i][2], latest_version=actions[i][5]),
            )

        self.con.execute("DROP TABLE IF EXISTS outdated_actions;")
        self.con.execute("""
            CREATE TABLE outdated_actions (
                repo_full_name VARCHAR,
                action_name VARCHAR,
                action_version VARCHAR,
                filepath VARCHAR,
                line_number INTEGER,
                latest_major_version VARCHAR,
                is_outdated BOOLEAN,
                PRIMARY KEY (repo_full_name, filepath, line_number)
            );
        """)
        self.con.executemany("INSERT INTO outdated_actions VALUES (?, ?, ?, ?, ?, ?, ?);", actions)
        num_action_usages = self.con.execute(
            "SELECT COUNT(*) FROM outdated_actions WHERE is_outdated IS TRUE"
        ).fetchall()[0][0]
        logger.info(f"Found {num_action_usages} outdated actions. Saved to `outdated_actions`.")

    def get_outdated_mentions(self) -> list[RepositoryMention]:
        """Get all outdated action mentions."""
        res = self.con.execute("""
            SELECT
                oa.repo_full_name,
                oa.action_name,
                oa.action_version,
                oa.filepath,
                oa.line_number,
                pa.latest_version,
                oa.is_outdated,
                pr.stars,
                tag.commit_sha
            FROM outdated_actions oa
            LEFT JOIN popular_repositories pr ON pr.repo_full_name = oa.repo_full_name
            LEFT JOIN popular_actions pa ON CONCAT(pa.owner, '/', pa.repo) = oa.action_name
            LEFT JOIN action_tags tag ON tag.action_name = oa.action_name AND tag.tag = oa.action_version
            LEFT JOIN pull_request_exclusions pre ON pre.repo_full_name = oa.repo_full_name
            WHERE
                oa.is_outdated IS TRUE
                AND pre.repo_full_name IS NULL -- i.e. Do not include excluded repos
                AND oa.repo_full_name NOT IN (
                    -- Updates locked to maintainers
                    'ant-design/ant-design',
                    'expo/expo',
                    'tldraw/tldraw',

                    -- unable to open PRs
                    'gorhill/uBlock',

                    -- Autoclosed PRs
                    'AUTOMATIC1111/stable-diffusion-webui',

                    -- unfriendly to automated improvements
                    'alacritty/alacritty',
                    'pocketbase/pocketbase',
                    'RVC-Boss/GPT-SoVITS',
                    'Significant-Gravitas/AutoGPT'
                )
                AND oa.action_name != 'actions/labeler' -- Contains breaking change in v5
            ORDER BY pr.stars asc -- desc
        """).fetchall()
        return [
            RepositoryMention(
                repo_full_name=r[0],
                action_name=r[1],
                detected_version=r[2],
                file_path=r[3],
                line_number=r[4],
                latest_version=r[5],
                is_outdated=r[6],
                stars=r[7],
                commit_sha=r[8] if len(r) > 8 else None,
            )
            for r in res
        ]

    @cache
    def get_popular_actions(self) -> list[GitHubAction]:
        """Get all popular actions."""
        res = self.con.execute(
            "SELECT * FROM popular_actions WHERE latest_major_version IS NOT NULL ORDER BY stars DESC"
        ).fetchall()
        logger.info(f"Retrieved {len(res)} actions.")
        return [
            GitHubAction(
                name=r[0],
                owner=r[1],
                repo=r[2],
                stars=int(r[3]),
                latest_version=r[4],
                latest_major_version=r[5],
                commit_sha=r[6] if len(r) > 6 else None,
                checked_at=r[7] if len(r) > 7 else None,
            )
            for r in res
        ]

    @cache
    def get_popular_repos(self) -> list[GitHubRepo]:
        """Get all popular repos."""
        res = self.con.execute(
            "SELECT * FROM popular_repositories WHERE repo_full_name "
            f"NOT IN ('{"', '".join(settings.exclude_repos)}') "
            "AND archived IS False "
            "AND fork IS FALSE "
            "AND pushed_at >= CURRENT_DATE - INTERVAL '6 months' "
            "ORDER BY stars DESC",
        ).fetchall()
        logger.info(f"Retrieved {len(res)} repos.")
        return [
            GitHubRepo(
                repo_full_name=r[0],
                clone_url=r[1],
                stars=int(r[2]),
                archived=r[3],
                pushed_at=r[4],
                fork=r[5],
                size=r[6],
                checked_at=r[7],
            )
            for r in res
        ]

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
                commit_sha VARCHAR,
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
                commit_sha VARCHAR,
                checked_at TIMESTAMP
            );
        """)

        try:
            self.con.execute("ALTER TABLE popular_actions ADD COLUMN commit_sha VARCHAR")
        except Exception:
            pass

        try:
            self.con.execute("ALTER TABLE action_mentions ADD COLUMN commit_sha VARCHAR")
        except Exception:
            pass

        self.con.execute("""
            CREATE TABLE IF NOT EXISTS action_tags (
                action_name VARCHAR,
                tag VARCHAR,
                commit_sha VARCHAR,
                PRIMARY KEY (action_name, tag)
            );
        """)

        self.con.execute("""
            CREATE TABLE IF NOT EXISTS popular_repositories (
                repo_full_name VARCHAR PRIMARY KEY,
                clone_url VARCHAR,
                stars INTEGER,
                archived BOOLEAN,
                pushed_at TIMESTAMP,
                fork BOOLEAN,
                size INTEGER,
                checked_at TIMESTAMP
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
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS pull_request_exclusions (
                repo_full_name VARCHAR PRIMARY KEY
            );
        """)

    def save_popular_action(self, action: GitHubAction):
        """Save a popular action."""
        self.con.execute(
            """
            INSERT OR REPLACE INTO popular_actions
            (name, owner, repo, stars, latest_version, latest_major_version, commit_sha, checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                action.name,
                action.owner,
                action.repo,
                action.stars,
                action.latest_version,
                action.latest_major_version,
                action.commit_sha,
                datetime.now(),
            ),
        )

    def save_popular_repo(self, repo: GitHubRepo):
        """Save a popular repos."""
        self.con.execute(
            """
            INSERT OR REPLACE INTO popular_repositories VALUES (?, ?, ?, ?,?, ?, ?, ?)
        """,
            (
                repo.repo_full_name,
                repo.clone_url,
                repo.stars,
                repo.archived,
                repo.pushed_at,
                repo.fork,
                repo.size,
                datetime.now(),
            ),
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
            INSERT OR REPLACE INTO action_mentions VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                mention.repo_full_name,
                mention.file_path,
                mention.line_number,
                mention.action_name,
                mention.detected_version,
                mention.latest_version,
                mention.is_outdated,
                mention.commit_sha,
            ),
        )

    def save_used_actions(
        self,
    ):
        """Save used actions."""
        self.con.execute(f"""
            CREATE OR REPLACE TABLE action_usage AS
            SELECT
                DISTINCT *
            FROM read_json_auto('{Path(settings.temp_dir) / "action_usage"}')
        """)
        num_action_usages = self.con.execute("SELECT COUNT(*) FROM action_usage").fetchall()[0][0]
        logger.info(f"Saved {num_action_usages} used actions to `action_usage`.")

    def save_action_tag(self, action_name: str, tag: str, commit_sha: str) -> None:
        """Save an action tag and its commit SHA."""
        self.con.execute(
            """
            INSERT OR REPLACE INTO action_tags (action_name, tag, commit_sha) VALUES (?, ?, ?)
        """,
            (action_name, tag, commit_sha),
        )

    def get_action_tag_sha(self, action_name: str, tag: str) -> str | None:
        """Get the commit SHA for a specific action tag."""
        result = self.con.execute(
            "SELECT commit_sha FROM action_tags WHERE action_name = ? AND tag = ?",
            (action_name, tag),
        ).fetchone()
        return result[0] if result else None

    def has_action_tags(self, action_name: str) -> bool:
        """Check if an action already has tags stored in the database."""
        result = self.con.execute(
            "SELECT 1 FROM action_tags WHERE action_name = ? LIMIT 1",
            (action_name,),
        ).fetchone()
        return result is not None

    def truncate_actions(self):
        """Truncate the popular_actions table."""
        self.con.execute("TRUNCATE TABLE popular_actions")

    def truncate_repositories(self):
        """Truncate the popular_repositories table."""
        self.con.execute("TRUNCATE TABLE popular_repositories")
