"""Interface-typed fields must resolve concrete fragments.

These are the queries that crashed while the category and query hierarchies were
multi-table inheritance under django-polymorphic. The strawberry-django optimizer
built django-polymorphic's *filter*-path syntax (``core__graphnodesquery___graph``)
and handed it to ``select_related()``, which django-polymorphic never translates, so
Django raised ``FieldError: Invalid field name(s) given in select_related: 'core'``.

The trigger is narrow enough to be easy to lose again: an interface-typed field whose
concrete inline fragment selects a foreign key. Nothing in the suite covered it.

Each test asserts the ``__typename`` as well as the data, because that is what proves
type resolution still works now that it dispatches on a ``kind`` column instead of on
django-polymorphic downcasting the row on the way out.
"""

import kante
import pytest
from asgiref.sync import sync_to_async
from django.test.utils import CaptureQueriesContext
from django.db import connection
from kante.context import HttpContext

from core import models as core_models


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_node_categories_interface_resolves_fragments(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`Graph.nodeCategories` is typed as an interface and its fragments select FKs."""
    query = """
        query NodeCategories($graph: ID!) {
            graph(id: $graph) {
                nodeCategories {
                    __typename
                    id
                    label
                    ... on EntityCategory {
                        instanceKind
                        graph { id }
                    }
                    ... on NaturalEventCategory {
                        graph { id }
                    }
                }
            }
        }
    """

    result = await api_schema.execute(
        query,
        variable_values={"graph": str(test_graph.id)},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None

    categories = result.data["graph"]["nodeCategories"]
    assert categories, "the bio graph schema defines node categories"

    typenames = {category["__typename"] for category in categories}
    assert typenames <= {"EntityCategory", "NaturalEventCategory", "ProtocolEventCategory"}
    assert "EntityCategory" in typenames

    # No edge category may leak into a node-category field.
    assert not typenames & {"RelationCategory", "MeasurementCategory", "StructureRelationCategory"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_edge_categories_interface_resolves_fragments(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The edge side of the same question, including the descriptor resolvers.

    `sourceDescriptor` reads `source_definition_model`, which only the per-kind proxy
    defines -- so this also covers `Category.as_kind()`.
    """
    query = """
        query EdgeCategories($graph: ID!) {
            graph(id: $graph) {
                edgeCategories {
                    __typename
                    id
                    label
                    ... on RelationCategory {
                        sourceDescriptor { keys }
                        targetDescriptor { keys }
                    }
                    ... on MeasurementCategory {
                        targetDescriptor { keys }
                    }
                }
            }
        }
    """

    result = await api_schema.execute(
        query,
        variable_values={"graph": str(test_graph.id)},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None

    categories = result.data["graph"]["edgeCategories"]
    assert categories, "the bio graph schema defines edge categories"

    typenames = {category["__typename"] for category in categories}
    assert typenames <= {"RelationCategory", "MeasurementCategory", "StructureRelationCategory"}
    assert not typenames & {"EntityCategory"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_graph_queries_interface_resolves_fragments(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The exact shape from the bug report: `graphQueries` with a fragment on a FK."""
    await core_models.GraphTableQuery.objects.acreate(
        graph=test_graph,
        key="interface_fragment_table",
        label="Interface Fragment Table",
        query="MATCH (n) RETURN n",
        columns=[],
    )
    await core_models.GraphTableQuery.objects.acreate(
        graph=test_graph,
        key="interface_fragment_nodes",
        label="Interface Fragment Nodes",
        query="MATCH (n) RETURN n",
        columns=[],
    )

    query = """
        query GraphQueries {
            graphQueries {
                __typename
                id
                label
                ... on GraphTableQuery {
                    graph { id }
                    columns { key }
                }
            }
        }
    """

    result = await api_schema.execute(query, context_value=simple_api_context)

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None

    by_label = {row["label"]: row for row in result.data["graphQueries"]}
    assert by_label["Interface Fragment Table"]["__typename"] == "GraphTableQuery"
    assert by_label["Interface Fragment Nodes"]["__typename"] == "GraphTableQuery"
    assert by_label["Interface Fragment Nodes"]["graph"]["id"] == str(test_graph.id)


# `test_concrete_query_field_is_scoped_to_its_kind` used to sit here, contrasting a
# table query with a nodes query under one interface. Only the table kind exists
# now, so there is no second kind to be scoped against.


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_interface_fragment_does_not_fan_out_into_queries(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The list costs a bounded number of queries, not one per row.

    Binding the concrete types to a proxy model instead of the concrete one still
    *works*, but the optimizer quietly gives up and every fragment field costs a round
    trip -- measured at 21 queries for 5 rows against 1 when bound correctly. That
    failure is invisible without a count, so pin it.
    """
    rows = 5
    for index in range(rows):
        await core_models.GraphTableQuery.objects.acreate(
            graph=test_graph,
            key=f"count_table_{index}",
            label=f"Count Table {index}",
            query="MATCH (n) RETURN n",
            columns=[],
        )

    query = """
        query GraphQueries {
            graphQueries {
                __typename
                id
                label
                ... on GraphTableQuery { graph { id } }
            }
        }
    """

    # `CaptureQueriesContext` touches the connection on entry, which Django forbids
    # directly inside an async test, so enter and leave it on the ORM's thread.
    captured = CaptureQueriesContext(connection)
    await sync_to_async(captured.__enter__)()
    try:
        result = await api_schema.execute(query, context_value=simple_api_context)
    finally:
        await sync_to_async(captured.__exit__)(None, None, None)

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert len(result.data["graphQueries"]) == rows

    selects = [q["sql"] for q in captured.captured_queries if q["sql"].lstrip().upper().startswith("SELECT")]
    # Generous, because auth and permission checks share the connection. The point is
    # that it does not scale with `rows`.
    assert len(selects) < rows, f"the list fanned out into per-row queries: {[sql[:120] for sql in selects]}"
