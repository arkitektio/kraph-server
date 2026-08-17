"""Smoke test: the GraphQL schema must build and render to a non-empty SDL string.

No database required — this only imports and stringifies the schema.
"""

import typing

from api import types
from api.schema import schema


def test_print_schema():
    sdl = str(schema)
    print(sdl)  # visible with `pytest -s`
    assert sdl.strip(), "Schema SDL should not be empty"


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
    - `Structure` and `Metric` are evidence rows with no AGE presence, so they
      must not implement `Node` — that interface's `label` is "the AGE graph
      label as recently materialized", which for them was a hard-coded constant.
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
