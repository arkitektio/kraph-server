"""A graph's Apache AGE handle is random, internal, and not how a graph is addressed.

`Graph.age_name` used to be `{name}_{org_slug}` — derived from user input, checked
for collisions per organization against a globally unique column, interpolated
unescaped into `cypher('…')`, and accepted by `get_accessible_graph` as the
`graph:` argument, so a projection detail was the public address of a view. It is
`g` + 32 hex now (`core.models.new_projection_handle`), assigned by the model
default, and `graph:` is a primary key and nothing else.
"""

import re

import pytest
from asgiref.sync import sync_to_async

from core import models as core_models
from tests import writes

HANDLE = re.compile(r"^g[0-9a-f]{32}$")

NODE = """
    query GetNode($id: ID!, $graph: ID!) {
        node(id: $id, graph: $graph) { id }
    }
"""


def test_two_graphs_with_one_name_get_distinct_random_handles(transactional_db, table_projector, minimal_schema, authenticated_context) -> None:
    """Same name, same organization, twice — two handles, neither derived from the name."""
    from graph_engine.materialize import materialize

    request = authenticated_context.request
    kwargs = dict(user=request._user, organization=request._organization, membership=request.membership, name="Twins")

    first = materialize(minimal_schema, table_projector, **kwargs)
    second = materialize(minimal_schema, table_projector, **kwargs)

    assert first.pk != second.pk
    assert first.age_name != second.age_name
    for graph in (first, second):
        assert HANDLE.match(graph.age_name), f"{graph.age_name!r} is not an opaque handle"
        assert "twins" not in graph.age_name.lower(), "the handle must not be derived from the name"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_graph_argument_is_a_primary_key_not_the_handle(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """`graph: "<age_name>"` is refused; the same read by id succeeds."""
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS")

    by_handle = await api_schema.execute(NODE, variable_values={"id": entity_id, "graph": str(test_graph.age_name)}, context_value=simple_api_context)
    assert by_handle.errors, "the AGE handle must not address a graph"
    assert "by its id" in str(by_handle.errors[0]), f"Refused for the wrong reason: {by_handle.errors[0]}"

    by_id = await api_schema.execute(NODE, variable_values={"id": entity_id, "graph": str(test_graph.pk)}, context_value=simple_api_context)
    assert by_id.errors is None, f"GraphQL errors: {by_id.errors}"
    assert by_id.data["node"]["id"] == entity_id


@pytest.mark.django_db(transaction=True)
def test_a_graph_row_needs_no_handle_to_be_created(test_graph: core_models.Graph) -> None:
    """The default supplies it, so fixtures and callers never invent one."""
    graph = core_models.Graph.objects.create(
        name="Handle-less",
        user=test_graph.user,
        membership=test_graph.membership,
        organization=test_graph.organization,
    )
    assert HANDLE.match(graph.age_name)
