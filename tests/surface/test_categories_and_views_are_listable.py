"""Categories and views are listable, and a view's presentation is inert (C4, C7).
"""

from typing import Set
import pytest
from api.schema import schema
from core import models as core_models
from core.models import Graph
from graph_engine import input_models
from kante.context import HttpContext


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
