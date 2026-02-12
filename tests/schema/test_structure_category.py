from typing import Set

import pytest
from api.schema import schema
from core import models as core_models
from core.models import Graph
from graph_engine import input_models
from kante.context import HttpContext


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_structure_category_filter_by_label(test_graph: Graph, authenticated_context: HttpContext) -> None:
    await core_models.StructureCategory.objects.acreate_from_structure_definition(
        graph=test_graph,
        definition=input_models.StructureDefinitionInput(
            key="TEST_ROI",
            label="TEST_ROI",
            identifier="@mikro/roi_test",
        ),
    )
    await core_models.StructureCategory.objects.acreate_from_structure_definition(
        graph=test_graph,
        definition=input_models.StructureDefinitionInput(
            key="TEST_NUCLEUS",
            label="TEST_NUCLEUS",
            identifier="@mikro/roi_test",
        ),
    )

    query: str = """
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

    labels: Set[str] = {item["label"] for item in result.data["structureCategories"]}

    assert "TEST_ROI" in labels
    assert "TEST_NUCLEUS" not in labels
