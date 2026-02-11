import pytest
from core import models as core_models
from core.models import Graph
from api.schema import schema
from kante.context import HttpContext


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_relation_category_filter_by_label(test_graph: Graph, authenticated_context: HttpContext):

    await core_models.RelationCategory.objects.acreate(
        graph=test_graph,
        age_name="CONNECTED_TO_TEST",
        label="CONNECTED_TO_TEST",
        reverse_label="CONNECTED_FROM_TEST",
    )
    await core_models.RelationCategory.objects.acreate(
        graph=test_graph,
        age_name="PART_OF_TEST",
        label="PART_OF_TEST",
        reverse_label="HAS_PART_TEST",
    )

    query = """
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

    labels = {item["label"] for item in result.data["relationCategories"]}

    assert "CONNECTED_TO_TEST" in labels
    assert "PART_OF_TEST" not in labels
