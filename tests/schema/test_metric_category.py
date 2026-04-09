from typing import Set

import pytest
from api.schema import schema
from core import enums
from core import models as core_models
from core.models import Graph
from graph_engine import input_models
from kante.context import HttpContext


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_metric_category_filter_by_metric_kind(test_graph: Graph, authenticated_context: HttpContext) -> None:
    structure_category: core_models.StructureCategory = await core_models.StructureCategory.objects.acreate_from_structure_definition(
        graph=test_graph,
        definition=input_models.StructureDefinitionInput(key="TEST_ROI", label="TEST_ROI", identifier="@mikro/roi_test"),
    )

    await core_models.MetricCategory.objects.acreate_from_metric_definition(
        graph=test_graph,
        definition=input_models.MetricDefinitionInput(key="Intensity", label="Intensity", value_kind=input_models.PropertyType.INTEGER, structure=structure_category.identifier),
    )

    await core_models.MetricCategory.objects.acreate_from_metric_definition(
        graph=test_graph,
        definition=input_models.MetricDefinitionInput(
            key="Area",
            label="Area",
            value_kind=input_models.PropertyType.FLOAT,
            structure=structure_category.identifier,
        ),
    )

    query: str = """
        query SearchMetricCategories($valueKind: ValueKind!) {
            metricCategories(filters: {valueKind: $valueKind}) {
                id
                label
            }
        }
    """

    result = await schema.execute(
        query,
        variable_values={"valueKind": "INT"},
        context_value=authenticated_context,
    )

    assert result.errors is None, result.errors
    assert result.data, result.errors

    labels: Set[str] = {item["label"] for item in result.data["metricCategories"]}

    assert "Intensity" in labels
    assert "Area" not in labels
