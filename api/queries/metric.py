"""Metric query resolvers."""

from typing import List
import strawberry
from kante.types import Info

from api import types, context, filters, order, pagination
from graph_engine import scalars


def metric(
    info: Info,
    metric_id: scalars.GraphID,
) -> types.Metric:
    """
    Fetch a single metric by ID.

    Metrics live in the relational evidence base, so the id is a bare primary
    key rather than a `{graph}:{node}` composite.

    Args:
        info: Strawberry Info context
        metric_id: The metric's evidence primary key

    Returns:
        A Metric object

    Raises:
        ValueError: if no metric has that id
    """
    controller = context.get_controller()

    return types.Metric(_value=controller.get_metric(str(metric_id), info))


def metrics(
    info: Info,
    metric_category_id: strawberry.ID,
    filters: filters.MetricFilter | None = None,
    ordering: list[order.MetricOrder] | None = None,
    pagination: pagination.MetricPaginationInput | None = None,
) -> List[types.Metric]:
    """List metrics for a given metric category with typed filter/order/pagination arguments."""
    raise NotImplementedError("metrics resolver scaffold added; query execution not implemented yet")


def metrics_for_structure(
    info: Info,
    structure_id: scalars.GraphID,
) -> List[types.Metric]:
    """
    Fetch all measurements attached to a structure.

    Args:
        info: Strawberry Info context
        structure_id: The structure's evidence primary key

    Returns:
        List of Metric objects
    """
    controller = context.get_controller()

    responses = controller.get_metrics_for_structure_id(str(structure_id), info)
    return [types.Metric(_value=r) for r in responses]


def measurements_for_assertion(
    info: Info,
    assertion_id: scalars.GraphID,
) -> List[types.Metric]:
    """
    Fetch all measurements that were asserted by a given assertion.

    This used to be unimplementable: an assertion was an AGE vertex, so its id
    alone did not say which graph to look in. Assertions are organization-scoped
    rows now and their primary key is globally unique, which is what makes the
    query answerable at all.

    Args:
        info: Strawberry Info context
        assertion_id: The assertion's evidence primary key

    Returns:
        List of Metric objects
    """
    controller = context.get_controller()

    responses = controller.get_metrics_for_assertion_id(str(assertion_id), info)
    return [types.Metric(_value=r) for r in responses]
