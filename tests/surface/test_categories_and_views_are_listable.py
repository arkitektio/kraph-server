"""Categories and views are listable, and a view's presentation is inert (C4, C7).
"""

from typing import Set
import pytest
from asgiref.sync import sync_to_async
from api.schema import schema
from core import models as core_models
from core.models import Graph
from graph_engine import input_models
from kante.context import HttpContext
from tests.support.reads import ADMITTING_RELATIONS
from tests.support.writes import execute


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_entity_category_search(test_graph: Graph, authenticated_context: HttpContext) -> None:
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

    labels: Set[str] = {item["label"] for item in result.data["entityCategories"]}

    assert "Neuron" in labels
    assert "Astrocyte" not in labels


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_relation_category_filter_by_label(test_graph: Graph, authenticated_context: HttpContext) -> None:
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

    labels: Set[str] = {item["label"] for item in result.data["relationCategories"]}

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
async def test_a_pair_of_entity_categories_lists_the_relations_that_admit_it(api_schema, test_graph: Graph, authenticated_context: HttpContext) -> None:
    """`RelationCategoryFilter.admits`: the descriptors the namespace draws with, asked from the two ends in one query."""
    def ids() -> dict[str, str]:
        return {category.key: str(category.pk) for category in core_models.EntityCategory.objects.filter(graph=test_graph)}

    by_key = await sync_to_async(ids)()

    async def admitting(source: str, target: str) -> list[str]:
        data = await execute(api_schema, authenticated_context, ADMITTING_RELATIONS, {"source": by_key[source], "target": by_key[target]})
        return sorted(row["label"] for row in data["relationCategories"])

    assert await admitting("AIS", "Cell") == ["PART_OF"]
    assert await admitting("Cell", "Cell") == ["IS_CONNECTED_TO"]
    assert await admitting("Cell", "AIS") == [], "Direction matters: PART_OF runs from the part to the cell"
