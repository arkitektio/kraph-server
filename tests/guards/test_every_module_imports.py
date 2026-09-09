"""Every module in the project imports.

No database, no docker stack.

History: the repo repeatedly accumulated modules referencing deleted siblings —
an `insights/` tree importing `core.age`, a `core/manager.py` shadowing
`core/managers.py`, call sites of a `graph_engine.base_models` that no longer
existed — and none of it failed CI, because nothing imported it.
"""

import importlib
import pkgutil

import pytest

# First-party packages. `tests` is excluded because pytest imports it anyway, and
# `core-backup-do-not-delete` is not a valid package name so pkgutil never sees it.
PACKAGES = ["api", "core", "datalayer", "evidence", "graph_engine", "kraph_server", "stats"]


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


# Accessors that defer their imports into the function body. Walking modules cannot
# see inside these, which is exactly how `get_retrieved_types` kept naming two
# functions deleted in M0 and `get_rollup_utils` outlived the module it loaded.
LAZY_ACCESSORS = [
    ("graph_engine", "get_controller"),
    ("graph_engine", "get_retrieved_types"),
    ("graph_engine", "get_aggregations"),
]


@pytest.mark.parametrize(("module_name", "accessor"), LAZY_ACCESSORS)
def test_lazy_accessor_resolves(module_name: str, accessor: str) -> None:
    """Calling the accessor must not raise ImportError."""
    module = importlib.import_module(module_name)
    getattr(module, accessor)()


@pytest.mark.parametrize("package_name", PACKAGES)
def test_all_names_exist(package_name: str) -> None:
    """Every name a package advertises in `__all__` must actually be there.

    `graph_engine.__all__` listed six names — GraphOperation, NodeChangeModel,
    get_migration_controller and friends — that had no definition anywhere, so
    `from graph_engine import *` would have failed while every targeted import
    kept working.
    """
    package = importlib.import_module(package_name)
    missing = [name for name in getattr(package, "__all__", []) if not hasattr(package, name)]
    assert not missing, f"{package_name}.__all__ advertises names that do not exist: {missing}"
