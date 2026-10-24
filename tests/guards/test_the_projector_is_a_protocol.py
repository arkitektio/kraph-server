"""The projection seam is a named protocol, and the projector speaks no query language (A7).

`graph_engine/projection/protocol.py::Projector` is what the controller and
`graph_engine.projector` draw through; `TableProjector` is the Postgres-table
implementation and the only place the drawing's rows are read or written. These
tests pin the facts that make a second projection kind possible — and that keep
the drawing a *projection*: the implementation satisfies the protocol, the
module that decides *what* to draw contains no trace of *how* it is stored, and
no module outside `projection/table.py` touches the drawing's tables.
"""

import ast
import re
from pathlib import Path

from graph_engine.projection import Projector, TableProjector

REPO = Path(__file__).resolve().parents[2]


def test_table_projector_satisfies_the_protocol() -> None:
    assert isinstance(TableProjector(), Projector)


def _code_only(path: Path) -> str:
    """The module's code with comments and docstrings stripped — prose may name what code may not."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
            body.pop(0)
    return ast.unparse(tree)


def test_projector_module_names_no_storage_and_no_query_language() -> None:
    """`graph_engine/projector.py` decides what to draw; it never says how."""
    code = _code_only(REPO / "graph_engine" / "projector.py")
    assert ".engine" not in code, "projector.py reaches for an engine; route through controller.projector"
    assert "_validate_property_key" not in code, "key validation belongs to the projector implementation"
    for keyword in ("MATCH (", "MERGE (", "DETACH DELETE", "CREATE (", "SELECT ", "INSERT ", "ProjectionVertex", "ProjectionLabel", "ProjectionMember", "ProjectionEdge"):
        assert keyword not in code, f"storage vocabulary ({keyword!r}) in projector.py; it belongs in graph_engine/projection/table.py"


def test_controller_executes_no_queries_itself() -> None:
    """Every query the controller used to run directly is a `Projector` method now."""
    code = _code_only(REPO / "graph_engine" / "controller.py")
    assert "self.engine" not in code
    assert not re.search(r"engine\.execute\(", code), "the controller must not execute queries; it draws through self.projector"
    for keyword in ("ProjectionVertex", "ProjectionLabel", "ProjectionMember", "ProjectionEdge"):
        assert keyword not in code, f"{keyword} in controller.py; the drawing's rows belong to graph_engine/projection/table.py"


def test_namespace_module_names_no_storage_and_no_ddl() -> None:
    """`graph_engine/namespace.py` decides what a namespace declares; never how.

    It reads `core.Category` rows and produces a spec. The DDL that spells the
    spec — schemas, views, the property graph — is `table.py`'s alone, the same
    what/how split `projector.py` keeps for the drawing itself.
    """
    code = _code_only(REPO / "graph_engine" / "namespace.py")
    for keyword in ("SELECT ", "INSERT ", "CREATE ", "DROP ", "GRAPH_TABLE", "ProjectionVertex", "ProjectionLabel", "ProjectionMember", "ProjectionEdge"):
        assert keyword not in code, f"storage vocabulary ({keyword!r}) in namespace.py; DDL belongs in graph_engine/projection/table.py"
