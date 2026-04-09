"""
Structure relation mutation resolvers.
"""

from typing import cast

from kante.types import Info

from api import context, inputs, types
from core import models
from graph_engine import scalars


def create_structure_relation(info: Info, input: inputs.CreateStructureRelationInput) -> types.StructureRelation:
    payload = input.to_pydantic()
    controller = context.get_controller()

    graph1 = context.extract_graph_id(cast(scalars.GraphID, payload.source_id))
    graph2 = context.extract_graph_id(cast(scalars.GraphID, payload.target_id))

    if graph1 != graph2:
        raise ValueError("Source and target structures must belong to the same graph")

    graph = context.get_accessible_graph(info, graph1)

    category = models.StructureRelationCategory.objects.get(id=payload.category)
    context.validate_graph_access(info, category.graph)
    if str(category.graph.age_name) != str(graph.age_name):
        raise ValueError("Structure relation category must belong to the same graph as the structures")

    created = controller.create_relation(
        category=cast(models.RelationCategory, category),
        payload=payload,
        info=info,
    )

    return types.StructureRelation(_value=created)


def update_structure_relation(info: Info, input: inputs.UpdateStructureRelationInput) -> types.StructureRelation:
    model = input.to_pydantic()
    controller = context.get_controller()

    graph_id = context.extract_graph_id(model.id)
    local_id = context.extract_node_id(model.id)
    graph = context.get_accessible_graph(info, graph_id)

    existing = controller.get_relation_by_id(local_id)
    if existing is None:
        raise ValueError(f"Structure relation not found with ID {model.id}")

    category = models.StructureRelationCategory.objects.get(graph=graph, age_name=existing.label)

    controller.archive_relation(graph, relation_id=local_id, info=info)

    updated = controller.create_relation(
        category=cast(models.RelationCategory, category),
        payload=model,
        info=info,
    )

    return types.StructureRelation(_value=updated)


def delete_structure_relation(info: Info, input: inputs.DeleteStructureRelationInput) -> scalars.GraphID:
    model = input.to_pydantic()
    controller = context.get_controller()

    graph_id = context.extract_graph_id(model.id)
    local_id = context.extract_node_id(model.id)
    graph = context.get_accessible_graph(info, graph_id)

    controller.delete_relation(graph, relation_id=local_id, info=info)
    return model.id


def archive_structure_relation(info: Info, input: inputs.ArchiveStructureRelationInput) -> types.StructureRelation:
    model = input.to_pydantic()
    controller = context.get_controller()

    graph_id = context.extract_graph_id(model.id)
    local_id = context.extract_node_id(model.id)
    graph = context.get_accessible_graph(info, graph_id)

    controller.archive_relation(graph, relation_id=local_id, info=info)
    archived = controller.get_relation_by_id(local_id)
    assert archived is not None, "Structure relation was archived but could not be loaded"

    return types.StructureRelation(_value=archived)
