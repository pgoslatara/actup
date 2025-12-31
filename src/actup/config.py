import yaml
from pydantic import BaseModel


class Config(BaseModel):
    """Configuration settings for the application."""

    duckdb_file: str
    exclude_repo_paths: list[str]
    exclude_repos: list[str]
    github_api_base_url: str
    pat_github_env_var: str
    popular_actions_limit: int
    popular_repos_limit: int
    temp_dir: str

    @classmethod
    def load(cls, path: str = "config.yaml") -> "Config":
        """Load configuration from a YAML file."""
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        return cls(**data)


settings = Config.load()
