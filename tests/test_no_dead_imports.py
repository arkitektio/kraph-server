"""Every module in the project must import.

This repo has repeatedly accumulated modules that reference deleted siblings — an
entire `graph_engine/insights/` tree importing `core.age` / `core.types` /
`core.renderers`, a `core/manager.py` shadowing `core/managers.py`, and several
call sites of a `graph_engine.base_models` that no longer exists. None of it failed
CI, because nothing imported it and no test asserted that everything imports.

This test is the guard. It needs no database and no docker stack.
"""

import importlib
import pkgutil

import pytest

# First-party packages. `tests` is excluded because pytest imports it anyway, and
# `core-backup-do-not-delete` is not a valid package name so pkgutil never sees it.
PACKAGES = ["api", "core", "datalayer", "graph_engine", "kraph_server", "rekuest_core", "stats"]


def _iter_modules() -> list[str]:
    names: list[str] = []
    for package_name in PACKAGES:
        package = importlib.import_module(package_name)
        names.append(package_name)
        for module in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
            # Migrations are imported by Django itself and are generated code.
            if ".migrations." in module.name:
                continue
            names.append(module.name)
    return names


@pytest.mark.parametrize("module_name", _iter_modules())
def test_module_imports(module_name: str) -> None:
    """Importing the module must not raise."""
    importlib.import_module(module_name)


def test_graph_engine_base_models_is_gone() -> None:
    """`graph_engine.base_models` was deleted; nothing may reference it again.

    Note this is specifically the graph_engine one. `datalayer.base_models` and
    `authentikate.base_models` are real modules and are unaffected.
    """
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("graph_engine.base_models")
