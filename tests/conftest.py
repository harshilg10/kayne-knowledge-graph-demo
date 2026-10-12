"""Shared fixtures. Graph tests run against the built demo graph and never modify it."""
from __future__ import annotations

import os

import pytest

from kgdemo import neo4j_client as db


def _graph_ready() -> bool:
    try:
        db.ping()
        return db.run("MATCH (d:Document) RETURN count(d) AS n")[0]["n"] > 0
    except Exception:
        return False


@pytest.fixture(scope="session")
def graph():
    """The built graph (python -m kgdemo.build). Skips graph tests when it is not available."""
    if not _graph_ready():
        pytest.skip("Neo4j demo graph not available - run scripts/neo4j_start.sh and python -m kgdemo.build")
    return db


def pytest_collection_modifyitems(config, items):
    if os.getenv("KG_DESTRUCTIVE_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="resets the database; set KG_DESTRUCTIVE_TESTS=1 (then rebuild with kgdemo.build)")
    for item in items:
        if "destructive" in item.keywords:
            item.add_marker(skip)


def pytest_configure(config):
    config.addinivalue_line("markers", "destructive: test resets the Neo4j database")
