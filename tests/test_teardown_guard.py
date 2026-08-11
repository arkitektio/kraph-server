"""The AGE teardown guard must refuse to run against a non-disposable database.

`tests/conftest.py::_drop_all_age_graphs` drops *every* graph in `ag_catalog.ag_graph`,
not only the ones a test created. That is correct against the throwaway compose stack
and catastrophic against a real database. Nothing structurally stops someone running
the suite with `DJANGO_SETTINGS_MODULE` pointed elsewhere, so the guard is the only
thing standing between a misconfigured run and data loss — which makes it worth a test.

Needs no database and no docker stack.
"""

from unittest.mock import patch

import pytest

from tests.conftest import _assert_disposable_database

TEST_STACK = {"host": "localhost", "port": "5555", "dbname": "test_testdb"}

UNSAFE = [
    pytest.param({**TEST_STACK, "host": "db"}, id="production-host"),
    pytest.param({**TEST_STACK, "port": "5432"}, id="default-postgres-port"),
    pytest.param({**TEST_STACK, "dbname": "kraph_db"}, id="non-test-database"),
    pytest.param({"host": "", "port": "", "dbname": ""}, id="unknown-connection"),
]


def test_guard_allows_the_disposable_test_stack() -> None:
    """The real test stack must pass, or the whole suite is blocked."""
    with patch("tests.conftest.connections") as connections:
        connections.__getitem__.return_value.get_connection_params.return_value = TEST_STACK
        _assert_disposable_database()


@pytest.mark.parametrize("params", UNSAFE)
def test_guard_refuses_anything_else(params: dict) -> None:
    """Any deviation from the disposable stack must raise before dropping anything."""
    with patch("tests.conftest.connections") as connections:
        connections.__getitem__.return_value.get_connection_params.return_value = params
        with pytest.raises(RuntimeError, match="Refusing to drop AGE graphs"):
            _assert_disposable_database()
