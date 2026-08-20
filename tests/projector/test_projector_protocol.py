"""The projection seam is a named protocol, and the projector speaks no query language.

`graph_engine/projection/protocol.py::Projector` is what the controller and
`graph_engine.projector` draw through; `CypherProjector` is the Apache AGE
implementation and the only place a drawing's Cypher lives. These tests pin the
two facts that make a second projection kind possible: the implementation
satisfies the protocol, and the module that decides *what* to draw contains no
trace of *how* AGE draws it.
"""

import ast
import re
from pathlib import Path

from graph_engine.engine.testing.mock_cypher_engine import MockCypherEngine
from graph_engine.projection import CypherProjector, Projector

REPO = Path(__file__).resolve().parents[2]


def test_cypher_projector_satisfies_the_protocol() -> None:
    assert isinstance(CypherProjector(MockCypherEngine()), Projector)


def _code_only(path: Path) -> str:
    """The module's code with comments and docstrings stripped — prose may name what code may not."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
            body.pop(0)
    return ast.unparse(tree)


def test_projector_module_names_no_engine_and_no_cypher() -> None:
    """`graph_engine/projector.py` decides what to draw; it never says how."""
    code = _code_only(REPO / "graph_engine" / "projector.py")
    assert ".engine" not in code, "projector.py reaches for an engine; route through controller.projector"
    assert "_validate_property_key" not in code, "key validation belongs to the projector implementation"
    for keyword in ("MATCH (", "MERGE (", "DETACH DELETE", "CREATE ("):
        assert keyword not in code, f"Cypher ({keyword!r}) in projector.py; it belongs in graph_engine/projection/cypher.py"


def test_controller_executes_no_cypher_itself() -> None:
    """Every query the controller used to run directly is a `Projector` method now."""
    code = _code_only(REPO / "graph_engine" / "controller.py")
    assert "self.engine" not in code
    assert not re.search(r"engine\.execute\(", code), "the controller must not execute queries; it draws through self.projector"
