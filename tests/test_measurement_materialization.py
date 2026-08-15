from asgiref.sync import sync_to_async

import pytest

from core import models as core_models
from evidence import models as evidence_models
from core.models import Graph
from evidence import writer
from graph_engine import input_models


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_measurement_category_create_and_delete_materializes_edges(test_graph: Graph) -> None:
    # Structure kinds are organization vocabulary now, created by the write that
    # first names an identifier rather than declared per graph.
    structure = await sync_to_async(writer.ensure_structure_kind)(test_graph.organization, "@mikro/roi_test")
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
            source=input_models.StructureDescriptorInput(identifiers=[structure.identifier]),
            target=input_models.EntityDescriptorInput(keys=[entity.key]),
        ),
    )

    materialized_edges = core_models.MaterializedMeasurementEdge.objects.filter(
        graph=test_graph,
        edge_category=measurement,
    )

    assert await materialized_edges.acount() == 1

    edge = await materialized_edges.aget()
    # A measurement edge runs from a structure kind to an entity category, so the two
    # endpoints live in differently-typed columns rather than one polymorphic pair.
    assert edge.source_structure_kind_id == structure.id
    assert edge.target_category_id == entity.id

    await sync_to_async(measurement.delete)()

    assert await core_models.MaterializedMeasurementEdge.objects.filter(graph=test_graph).acount() == 0
