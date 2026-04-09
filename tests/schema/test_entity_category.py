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
