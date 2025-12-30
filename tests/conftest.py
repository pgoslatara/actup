import os

import pytest

from actup.database import Database


@pytest.fixture
def test_db():
    """Create a test database fixture."""
    test_db_file = "test_db.duckdb"
    if os.path.exists(test_db_file):
        os.remove(test_db_file)

    db = Database(test_db_file)
    yield db
    db.close()
    if os.path.exists(test_db_file):
        os.remove(test_db_file)
