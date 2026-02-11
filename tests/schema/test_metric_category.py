import pytest
from core import enums
from core import models as core_models
from core.models import Graph
from api.schema import schema
from kante.context import HttpContext


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_metric_category_filter_by_metric_kind(test_graph: Graph, authenticated_context: HttpContext):

    structure_category = await core_models.StructureCategory.objects.acreate(
        graph=test_graph,
        age_name="TEST_ROI",
        label="TEST_ROI",
        identifier="@mikro/roi_test",
    )

    await core_models.MetricCategory.objects.acreate(
        graph=test_graph,
        age_name="Intensity",
        label="Intensity",
        metric_kind=enums.MeasurementKindChoices.INT,
        structure_category=structure_category,
    )
    await core_models.MetricCategory.objects.acreate(
        graph=test_graph,
        age_name="Area",
        label="Area",
        metric_kind=enums.MeasurementKindChoices.FLOAT,
        structure_category=structure_category,
    )

    query = """
        query SearchMetricCategories($metricKind: MetricKind!) {
            metricCategories(filters: {metricKind: $metricKind}) {
                id
                label
            }
        }
    """

    result = await schema.execute(
        query,
        variable_values={"metricKind": "INT"},
        context_value=authenticated_context,
    )

    assert result.errors is None, result.errors
    assert result.data, result.errors

    labels = {item["label"] for item in result.data["metricCategories"]}

    assert "Intensity" in labels
    assert "Area" not in labels
