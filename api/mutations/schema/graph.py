from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from api.extensions.cypher import get_current_cypher_engine
from core import models
from graph_engine import input_models, materialize


def create_graph(
    info: Info,
    input: inputs.CreateGraphInput,
) -> types.Graph:
    """GraphQL mutation wrapper for creating graph."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    cypher = get_current_cypher_engine()

    graph = materialize.materialize(
        definition=model.definition or input_models.GraphDefinitionInput(),
        engine=cypher,
        user=info.context.request.user,
        organization=info.context.request.organization,
        name=model.name,
        description=model.description,
        membership=info.context.request.membership,
    )

    return graph


def delete_graph(
    info: Info,
    input: inputs.DeleteGraphInput,
) -> strawberry.ID:
    """GraphQL mutation wrapper for deleting a graph."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    graph = models.Graph.objects.get(id=model.id)

    # Check permissions - only graph owner or admin can delete
    if not info.context.request.user.is_superuser and graph.owner != info.context.request.user:
        raise PermissionError("You do not have permission to delete this graph.")

    graph.delete()

    return model.id


def archive_graph(
    info: Info,
    input: inputs.ArchiveGraphInput,
) -> types.Graph:
    """GraphQL mutation wrapper for archiving a graph."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    graph = models.Graph.objects.get(id=model.id)

    # Check permissions - only graph owner or admin can archive
    if not info.context.request.user.is_superuser and graph.owner != info.context.request.user:
        raise PermissionError("You do not have permission to archive this graph.")

    graph.is_archived = True
    graph.save()

    return graph


def update_graph(
    info: Info,
    input: inputs.UpdateGraphInput,
) -> types.Graph:
    """GraphQL mutation wrapper for updating a graph."""

    model = input.to_pydantic()

    graph = models.Graph.objects.get(id=model.id)

    if not info.context.request.user.is_superuser and graph.owner != info.context.request.user:
        raise PermissionError("You do not have permission to update this graph.")

    if model.name is not None:
        graph.name = model.name
    if model.description is not None:
        graph.description = model.description
    if model.archived is not None:
        graph.is_archived = model.archived

    graph.save()

    return graph


def pin_graph(
    info: Info,
    input: inputs.PinGraphInput,
) -> types.Graph:
    """GraphQL mutation wrapper for pinning a graph."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    graph = models.Graph.objects.get(id=model.graph_id)

    if model.pin:
        graph.pinned_by.add(info.context.request.user)
    else:
        graph.pinned_by.remove(info.context.request.user)

    return types.Graph(id=model.graph_id)
