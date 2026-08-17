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
