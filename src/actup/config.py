import yaml
from pydantic import BaseModel


class Config(BaseModel):
    """Configuration settings for the application."""

    exclude_repos: list[str] = []
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
