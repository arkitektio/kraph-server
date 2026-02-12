from typing import Set

import pytest
from api.schema import schema
from core import models as core_models
from core.models import Graph
from graph_engine import input_models
from kante.context import HttpContext


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
