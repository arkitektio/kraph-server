"""Categories and views are listable, and a view's presentation is inert (C4, C7)."""

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from api.schema import schema
from core import models as core_models
from core.models import Graph
from graph_engine import input_models
from tests.support import writes
from tests.support.reads import (
    ADMITTING_RELATIONS,
    ADMITTING_RELATIONS_BETWEEN_CLAIMS,
    SCATTER_PLOTS_OF,
)
from tests.support.writes import execute


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_entity_category_search(
    test_graph: Graph, authenticated_context: HttpContext
) -> None:
    await core_models.EntityCategory.objects.acreate_from_entity_definition(
        graph=test_graph,
        definition=input_models.EntityDefinitionInput(
            key="Neuron",
            label="Neuron",
            instance_kind="neuron",
        ),
    )
    await core_models.EntityCategory.objects.acreate_from_entity_definition(
        graph=test_graph,
        definition=input_models.EntityDefinitionInput(
            key="Astrocyte",
            label="Astrocyte",
            instance_kind="astrocyte",
        ),
    )

    query: str = """
        query SearchEntityCategories($label: String!) {
            entityCategories(filters: {label: $label}) {
                id
                label
            }
        }
    """

    result = await schema.execute(
        query,
        variable_values={"label": "Neuron"},
        context_value=authenticated_context,
    )

    assert result.errors is None, result.errors
    assert result.data, result.errors

    labels: set[str] = {item["label"] for item in result.data["entityCategories"]}

    assert "Neuron" in labels
    assert "Astrocyte" not in labels


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_relation_category_filter_by_label(
    test_graph: Graph, authenticated_context: HttpContext
) -> None:
    await core_models.RelationCategory.objects.acreate_from_relation_definition(
        graph=test_graph,
        definition=input_models.RelationDefinitionInput(
            key="CONNECTED_TO_TEST",
            source=input_models.EntityDescriptorInput(),
            target=input_models.EntityDescriptorInput(),
        ),
    )
    await core_models.RelationCategory.objects.acreate_from_relation_definition(
        graph=test_graph,
        definition=input_models.RelationDefinitionInput(
            key="PART_OF_TEST",
            source=input_models.EntityDescriptorInput(),
            target=input_models.EntityDescriptorInput(),
        ),
    )

    query: str = """
        query SearchRelationCategories($label: String!) {
            relationCategories(filters: {label: $label}) {
                id
                label
            }
        }
    """

    result = await schema.execute(
        query,
        variable_values={"label": "CONNECTED_TO_TEST"},
        context_value=authenticated_context,
    )

    assert result.errors is None, result.errors
    assert result.data, result.errors

    labels: set[str] = {item["label"] for item in result.data["relationCategories"]}

    assert "CONNECTED_TO_TEST" in labels
    assert "PART_OF_TEST" not in labels


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_graph(db: object, authenticated_context: HttpContext) -> None:
    graph: Graph = await Graph.objects.acreate(
        name="Test Model",
        description="This is a test model",
        user=authenticated_context.request.user,
        organization=authenticated_context.request.organization,
        membership=authenticated_context.request.membership,
    )

    query: str = f"""
        query {{
            graph(id: {graph.pk}) {{
                id
                name
            }}
        }}
    """

    sub = await schema.execute(
        query,
        context_value=authenticated_context,
    )

    assert sub.data, sub.errors

    assert sub.data["graph"]["name"] == "Test Model"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_pair_of_entity_categories_lists_the_relations_that_admit_it(
    api_schema: kante.Schema, test_graph: Graph, authenticated_context: HttpContext
) -> None:
    """`RelationCategoryFilter.admits`: the descriptors the namespace draws with, asked from the two ends in one query."""

    def ids() -> dict[str, str]:
        return {
            category.key: str(category.pk)
            for category in core_models.EntityCategory.objects.filter(graph=test_graph)
        }

    by_key = await sync_to_async(ids)()

    async def admitting(source: str, target: str) -> list[str]:
        data = await execute(
            api_schema,
            authenticated_context,
            ADMITTING_RELATIONS,
            {"source": by_key[source], "target": by_key[target]},
        )
        return sorted(row["label"] for row in data["relationCategories"])

    assert await admitting("AIS", "Cell") == ["PART_OF"]
    assert await admitting("Cell", "Cell") == ["IS_CONNECTED_TO"]
    assert await admitting("Cell", "AIS") == [], (
        "Direction matters: PART_OF runs from the part to the cell"
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_two_claims_list_the_relations_that_could_connect_them(
    api_schema: kante.Schema, test_graph: Graph, authenticated_context: HttpContext
) -> None:
    """`RelationCategoryFilter.admitsInstances`: `admits`, asked in every view that draws both claims.

    History: the app found the categories each claim was drawn under itself, took the
    first view drawing both, and asked `admits` for that view only.
    """
    ais = await writes.create_entity(api_schema, authenticated_context, "AIS")
    cell = await writes.create_entity(api_schema, authenticated_context, "Cell")
    other_cell = await writes.create_entity(api_schema, authenticated_context, "Cell")

    async def admitting(source: str, target: str) -> list[tuple[str, str]]:
        data = await execute(
            api_schema,
            authenticated_context,
            ADMITTING_RELATIONS_BETWEEN_CLAIMS,
            {"source": source, "target": target},
        )
        return sorted(
            (row["label"], row["graph"]["id"]) for row in data["relationCategories"]
        )

    assert await admitting(ais, cell) == [("PART_OF", str(test_graph.pk))]
    assert await admitting(cell, other_cell) == [
        ("IS_CONNECTED_TO", str(test_graph.pk))
    ]
    assert await admitting(cell, ais) == [], (
        "Direction matters, as it does for `admits`"
    )
    assert await admitting(ais, "00000000-0000-0000-0000-000000000000") == [], (
        "A claim nobody made admits nothing"
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_view_lists_only_the_plots_drawn_from_its_queries(
    api_schema: kante.Schema, test_graph: Graph, authenticated_context: HttpContext
) -> None:
    """`ScatterPlotFilter.graph` and `.query`: a graph's page lists its own plots, not the organization's.

    History: the graph page's Plots tab listed every plot there was.
    """

    def plots() -> tuple[str, str, str, str]:
        request = authenticated_context.request
        user = request._user
        other_graph = Graph.objects.create(
            name="other_view",
            user=user,
            membership=request.membership,
            organization=request._organization,
        )
        mine = core_models.GraphTableQuery.objects.create(
            graph=test_graph, key="mine", label="Mine", query="MATCH (n) RETURN n"
        )
        second = core_models.GraphTableQuery.objects.create(
            graph=test_graph, key="second", label="Second", query="MATCH (n) RETURN n"
        )
        theirs = core_models.GraphTableQuery.objects.create(
            graph=other_graph, key="theirs", label="Theirs", query="MATCH (n) RETURN n"
        )
        here = core_models.ScatterPlot.objects.create(
            graph_query=mine,
            name="Here",
            id_column="id",
            x_column="x",
            y_column="y",
            creator=user,
        )
        also = core_models.ScatterPlot.objects.create(
            graph_query=second,
            name="Also here",
            id_column="id",
            x_column="x",
            y_column="y",
            creator=user,
        )
        core_models.ScatterPlot.objects.create(
            graph_query=theirs,
            name="Elsewhere",
            id_column="id",
            x_column="x",
            y_column="y",
            creator=user,
        )
        return str(here.pk), str(also.pk), str(mine.pk), str(test_graph.pk)

    here, also, query, graph = await sync_to_async(plots)()

    by_graph = await execute(
        api_schema, authenticated_context, SCATTER_PLOTS_OF, {"graph": graph}
    )
    assert sorted(row["id"] for row in by_graph["scatterPlots"]) == sorted([here, also])
    by_query = await execute(
        api_schema, authenticated_context, SCATTER_PLOTS_OF, {"query": query}
    )
    assert [row["id"] for row in by_query["scatterPlots"]] == [here]
