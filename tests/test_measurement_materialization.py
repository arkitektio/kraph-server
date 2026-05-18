from asgiref.sync import sync_to_async

import pytest

from core import models as core_models
from core.models import Graph
from graph_engine import input_models


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_measurement_category_create_and_delete_materializes_edges(test_graph: Graph) -> None:
    structure = await core_models.StructureCategory.objects.acreate_from_structure_definition(
        graph=test_graph,
        definition=input_models.StructureDefinitionInput(
            key="ROI_TEST",
            label="ROI_TEST",
            identifier="@mikro/roi_test",
        ),
    )
    entity = await core_models.EntityCategory.objects.acreate_from_entity_definition(
        graph=test_graph,
        definition=input_models.EntityDefinitionInput(
            key="CELL_TEST",
            label="CELL_TEST",
        ),
    )

    measurement = await core_models.MeasurementCategory.objects.acreate_from_measurement_definition(
        graph=test_graph,
        definition=input_models.MeasurementDefinitionInput(
            key="MEASURES_TEST",
            label="MEASURES_TEST",
            source=input_models.StructureDescriptorInput(keys=[structure.key]),
            target=input_models.EntityDescriptorInput(keys=[entity.key]),
        ),
    )

    materialized_edges = core_models.MaterializedMeasurementEdge.objects.filter(
        graph=test_graph,
        edge=measurement,
    )

    assert await materialized_edges.acount() == 1

    edge = await materialized_edges.aget()
    assert edge.source_id == structure.id
    assert edge.target_id == entity.id

    await sync_to_async(measurement.delete)()

    assert await core_models.MaterializedMeasurementEdge.objects.filter(graph=test_graph).acount() == 0
