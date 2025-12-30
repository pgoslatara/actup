import logging, os

from rich.logging import RichHandler


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Set up the application logger."""
    logging.basicConfig(level=level, format="%(message)s", datefmt="[%X]", handlers=[RichHandler(rich_tracebacks=True)])
    return logging.getLogger("actup")


logger = setup_logging()
