import pytest
from core.models import Graph
from core import models as core_models
from api.schema import schema
from kante.context import HttpContext


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_entity_category_search(test_graph: Graph, authenticated_context: HttpContext) -> None:
    await core_models.EntityCategory.objects.acreate(
        graph=test_graph,
        age_name="Neuron",
        key="Neuron",
        label="Neuron",
        instance_kind="neuron",
    )
    await core_models.EntityCategory.objects.acreate(
        graph=test_graph,
        age_name="Astrocyte",
        key="Astrocyte",
        label="Astrocyte",
        instance_kind="astrocyte",
    )

    query = """
        query SearchEntityCategories($instanceKind: String!) {
            entityCategories(filters: {instanceKind: $instanceKind}) {
                id
                label
            }
        }
    """

    result = await schema.execute(
        query,
        variable_values={"instanceKind": "neuron"},
        context_value=authenticated_context,
    )

    assert result.errors is None, result.errors
    assert result.data, result.errors

    labels = {item["label"] for item in result.data["entityCategories"]}

    assert "Neuron" in labels
    assert "Astrocyte" not in labels
