"""
Metric mutation resolvers.

Metrics live in the relational evidence base and are scoped to the organization,
not to a graph. Their IDs are therefore bare primary keys: there is no composite
`{graph}:{id}` to pull a graph out of, so the controller resolves the row first
and then authorizes the caller against *its* organization.
"""

from kante.types import Info

from api import types, inputs, context
from graph_engine.scalars import GraphID
from graph_engine import input_models


def record_metric(
    info: Info,
    input: inputs.RecordMetricInput,
) -> types.Metric:
    """
    Record a new metric for a structure. If the structure doesn't exist, it will be created automatically.

    Args:
        info: Strawberry Info context
        input: RecordMetricInput
    Returns:
        Created Metric object
    """

    controller = context.get_controller()

    model = input.to_pydantic()
    organization = context.get_active_organization(info)

    # The structure is created if it is new. Refusing a measurement because no
    # graph had declared the identifier would be refusing a fact about the world
    # on a bookkeeping technicality — and the identifier belongs to the service
    # that produced the datum anyway.
    structure = controller.create_structure(
        organization=organization,
        identifier=model.identifier,
        payload=input_models.StructureInput(object=model.object),
        info=info,
    )

    response = controller.create_metric(
        structure_id=structure.unique_id,
        input=model,
        info=info,
    )

    return types.Metric.from_specific(response)  # Convert to GraphQL type, preserving specific subtype information. If the metric already exists, it will be updated with the new value and timestamp.


def create_metric(
    info: Info,
    input: inputs.CreateMetricInput,
) -> types.Metric:
    """
    Add a measurement to an existing structure.

    Args:
        info: Strawberry Info context
        input: CreateMetricInput, where `structure` is an evidence primary key

    Returns:
        Created Metric object
    """
    controller = context.get_controller()

    model = input.to_pydantic()

    response = controller.create_metric(
        structure_id=str(model.structure),
        input=model,
        info=info,
    )

    return types.Metric.from_specific(response)


def delete_metric(
    info: Info,
    input: inputs.DeleteMetricInput,
) -> GraphID:
    """
    Hard delete a measurement by its ID.

    Prefer `archiveMetric`: evidence is append-only, and deleting destroys the
    record of what a derived value was once computed from.

    Args:
        info: Strawberry Info context
        input: The evidence ID of the measurement to delete

    Returns:
        The ID of the deleted measurement
    """
    controller = context.get_controller()

    model = input.to_pydantic()

    controller.delete_metric(
        metric_id=str(model.id),
        info=info,
    )

    return model.id


def update_metric(
    info: Info,
    input: inputs.UpdateMetricInput,
) -> types.Metric:
    """
    Update a metric by archiving the previous one and asserting a new one.

    Args:
        info: Strawberry Info context
        input: The metric update payload

    Returns:
        The newly created metric
    """
    controller = context.get_controller()

    model = input.to_pydantic()

    updated = controller.update_metric(
        payload=model,
        info=info,
    )

    return types.Metric(_value=updated)


def archive_metric(
    info: Info,
    input: inputs.ArchiveMetricInput,
) -> types.Metric:
    """
    Archive (retract) a measurement by its ID.

    The metric stays readable afterwards — a derived value that stopped counting
    it still has to be explainable.

    Args:
        info: Strawberry Info context
        input: The evidence ID of the measurement to archive

    Returns:
        The archived measurement
    """
    controller = context.get_controller()

    model = input.to_pydantic()

    controller.archive_metric(
        metric_id=str(model.id),
        info=info,
    )

    archived_metric = controller.get_metric(str(model.id), info)

    return types.Metric(_value=archived_metric)
