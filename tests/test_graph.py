import pytest
from core.models import Graph
from core import models as core_models
from api.schema import schema
from kante.context import HttpContext

@pytest.mark.skip(reason="Requires full database migrations and backend stack - legacy test")
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_graph(db, authenticated_context: HttpContext):

    graph = await Graph.objects.acreate(
        name="Test Model",
        description="This is a test model",
        user=authenticated_context.request.user,
        organization=authenticated_context.request.organization,
        membership=authenticated_context.request.membership,
    )

    query = """
        query {
            graph(id: 1) {
                id
                name
            }
        }
    """

    sub = await schema.execute(
        query,
        context_value=authenticated_context,
    )

    assert sub.data, sub.errors

    assert sub.data["graph"]["name"] == "Test Model"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_entity_category_search(test_graph: Graph, authenticated_context: HttpContext):

    await core_models.EntityCategory.objects.acreate(
        graph=test_graph,
        age_name="Neuron",
        label="Neuron",
    )
    await core_models.EntityCategory.objects.acreate(
        graph=test_graph,
        age_name="Astrocyte",
        label="Astrocyte",
    )

    query = """
        query SearchEntityCategories($search: String!) {
            entityCategories(filters: {search: $search}) {
                id
                label
            }
        }
    """

    result = await schema.execute(
        query,
        variable_values={"search": "Neuron"},
        context_value=authenticated_context,
    )

    assert result.errors is None, result.errors
    assert result.data, result.errors

    labels = {item["label"] for item in result.data["entityCategories"]}

    assert "Neuron" in labels
    assert "Astrocyte" not in labels
