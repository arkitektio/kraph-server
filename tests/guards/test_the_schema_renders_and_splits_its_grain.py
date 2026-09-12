"""The GraphQL schema builds, renders, and keeps the log's grain apart from the view's (C4).

Every member of `NodeSubtype` / `EdgeSubtype` is registered, so an abstract
type always resolves; `Structure` and `Metric` implement neither interface,
because they are claim rows with no drawing. No database required.
"""

import pathlib
import typing

from api import types
from api.schema import schema

SNAPSHOT = pathlib.Path(__file__).resolve().parents[2] / "test.graphql"


def test_print_schema():
    sdl = str(schema)
    print(sdl)  # visible with `pytest -s`
    assert sdl.strip(), "Schema SDL should not be empty"


def test_the_committed_sdl_is_the_live_schema():
    """`test.graphql` is the schema, not a hand dump.

    It is the one artifact that shows a breaking change whole, so a schema change
    that does not regenerate it is a schema change nobody read.

    History: the file was "a hand-dumped SDL snapshot, not asserted by any test",
    regenerated from memory after some changes and not others.
    """
    assert SNAPSHOT.exists(), "test.graphql is missing; regenerate with `uv run python manage.py print_schema > test.graphql`"
    assert SNAPSHOT.read_text().strip() == str(schema).strip(), "test.graphql is stale; regenerate with `uv run python manage.py print_schema > test.graphql` and read the diff"


def test_every_castable_subtype_is_registered_in_the_schema():
    """A type the cast can produce must exist in the schema, or the query fails at runtime.

    `cast_edge_to_graphql_type` and `cast_node_to_graphql_type` dispatch onto the
    members of `EdgeSubtype` and `NodeSubtype`. Several are reachable only through
    the `Edge` or `Node` *interface* — `connections`, `retractLinks` — so nothing
    names them concretely and strawberry does not register them unless
    `create_schema` lists them explicitly.

    Leaving one out is not a build error. It fails as
    "Abstract type 'Edge' was resolved to a type 'X' that does not exist inside
    the schema", on the one query that happens to produce that kind — which is
    exactly the sort of silence a schema test can close cheaply and nothing else
    will.
    """
    sdl = str(schema)

    for union in (types.EdgeSubtype, types.NodeSubtype):
        for member in typing.get_args(union):
            name = member.__name__
            assert f"type {name} " in sdl or f"type {name}\n" in sdl, f"{name} is castable but not in the schema; add it to `create_schema(types=[...])`"


def test_the_grain_split_is_visible_in_the_sdl():
    """Claim types stay off the projection interface, and the edge shape is honest.

    Each line here pins one half of a conflation the SDL used to carry:
    - `Structure` and `Metric` are claim rows with no drawing, so they must not
      implement `Node` — that interface's `label` is "the label as recently
      drawn", which for them was a hard-coded constant.
    - Every edge the API can build is row-backed (`RetrievedEdge.from_link`), so
      `Edge.assertion` is non-null; the nullable form documented a projection
      branch nothing can produce.
    - A node or edge id is the same uuid `Instance.id`/`Link.id` serve as `ID!`,
      so the drawing types must not hand it out as a different scalar.
    """
    sdl = str(schema)

    assert "type Structure implements" not in sdl, "A structure is a claim; no view ever draws one"
    assert "type Metric implements" not in sdl, "A metric is a claim; its value folds into vertices, it is never one"
    assert "type Structure {" in sdl and "type Metric {" in sdl

    assert "Null for an edge read out of a projection" not in sdl, "The projection-built edge is extinct; the description must not resurrect it"
    assert "assertion: Assertion!" in sdl, "Every edge is built from a Link row, which cannot exist without its assertion"

    node_block = sdl.split("interface Node {")[1].split("\n}")[0]
    edge_block = sdl.split("interface Edge {")[1].split("\n}")[0]
    for block, name in ((node_block, "Node"), (edge_block, "Edge")):
        assert "id: ID!" in block, f"{name}.id must be the same ID scalar the claim types use"
        assert "id: String!" not in block, f"{name} must not hand the uuid out as a String"


def test_every_write_payload_implements_the_asserted_interface():
    """A write payload is reachable by name, and says so in the schema.

    `Asserted` carries the two questions every write answers the same way —
    `pending` and `assertion` — so a client can select them across any write
    result. The fifteen payload types are named concretely by their mutations'
    return annotations, so unlike the `Edge` and `Node` subtypes above none of
    them needs listing in `create_schema(types=[...])`; this asserts that the
    reachability actually holds rather than assuming it, because a type reachable
    only through an interface fails at **runtime** and never at build.

    It also holds the interface itself honest: a payload class that stops
    inheriting `Asserted` still builds, still serves, and quietly drops two fields
    from its contract.
    """
    sdl = str(schema)

    implementors = [name for name in dir(types) if name.startswith("Asserted") and isinstance(getattr(types, name), type) and issubclass(getattr(types, name), types.Asserted) and getattr(types, name) is not types.Asserted]
    assert len(implementors) == 15, f"expected the fifteen write payloads, found {sorted(implementors)}"

    for name in implementors:
        assert f"type {name} implements Asserted " in sdl, f"{name} subclasses Asserted but the schema does not say so"
