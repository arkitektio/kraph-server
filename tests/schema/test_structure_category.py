import pytest
from core import models as core_models
from core.models import Graph
from api.schema import schema
from kante.context import HttpContext


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_structure_category_filter_by_label(test_graph: Graph, authenticated_context: HttpContext):

    await core_models.StructureCategory.objects.acreate(
        graph=test_graph,
        age_name="TEST_ROI",
        label="TEST_ROI",
        identifier="@mikro/roi_test",
    )
    await core_models.StructureCategory.objects.acreate(
        graph=test_graph,
        age_name="TEST_NUCLEUS",
        label="TEST_NUCLEUS",
        identifier="@mikro/nucleus_test",
    )

    query = """
        query SearchStructureCategories($label: String!) {
            structureCategories(filters: {label: $label}) {
                id
                label
            }
        }
    """

    result = await schema.execute(
        query,
        variable_values={"label": "TEST_ROI"},
        context_value=authenticated_context,
    )

    assert result.errors is None, result.errors
    assert result.data, result.errors

    labels = {item["label"] for item in result.data["structureCategories"]}

    assert "TEST_ROI" in labels
    assert "TEST_NUCLEUS" not in labels
