"""Metric query resolvers."""

from typing import List
import strawberry
from kante.types import Info

from api import types, context


def metric(
    info: Info,
    id: strawberry.ID,
) -> types.Metric:
    """
    Fetch a single metric by ID.

    Metrics live in the relational evidence base, so the id is a bare primary
    key rather than a `{graph}:{node}` composite.

    The argument is `id`, and it was `metricId` — the only singular fetcher on
    the surface whose id argument was not called `id`, so a client reading the
    schema had to remember one exception.

    Args:
        info: Strawberry Info context
        id: The metric's evidence primary key

    Returns:
        A Metric object

    Raises:
        ValueError: if no metric has that id
    """
    controller = context.get_controller()

    return types.Metric(_value=controller.get_metric(str(id), info))


def metrics(
    info: Info,
    metric_kind_id: strawberry.ID,
) -> List[types.Metric]:
    """Every un-retracted metric recorded under one metric kind.

    The argument used to be `metric_category_id`. **There is no metric
    category** — measurement vocabulary became the organization-scoped
    `evidence.MetricKind` when structures left the `Category` hierarchy, and
    `structures(structureKindId:)` was updated at the time while this was not.
    The resolver was `raise NotImplementedError`, so nothing ever exercised the
    argument and nothing could notice.

    It also took `filters`, `ordering` and `pagination`, and those are gone. A
    resolver that raises can advertise any argument it likes; one that answers
    cannot, and applying them would mean inventing a filter language for a
    surface nothing has asked for yet. Better to offer what is implemented than
    to accept three arguments and ignore them — that is the silent no-op this
    whole pass exists to remove.

    Scoped by the kind's organization rather than by the request's: the kind is
    resolved first and the caller authorized against *its* tenant, the same order
    `metric(id:)` and every other evidence read use, because the client names a
    primary key and never names a tenant.
    """
    from evidence import models as evidence_models
    from evidence import writer
    from graph_engine.retrieved import RetrievedMetric

    kind = evidence_models.MetricKind.all_objects.filter(pk=str(metric_kind_id)).first()
    if kind is None:
        raise ValueError(f"Metric kind not found with id {metric_kind_id}")

    controller = context.get_controller()
    controller._assert_can_access(kind.organization, info)

    return [types.Metric(_value=RetrievedMetric.from_row(controller, row)) for row in writer.standing_metrics_for_kind(kind)]


def metrics_for_structure(
    info: Info,
    structure_id: strawberry.ID,
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


def metrics_for_assertion(
    info: Info,
    assertion_id: strawberry.ID,
) -> List[types.Metric]:
    """
    Fetch all metrics that were recorded under a given assertion.

    Named `metrics_for_assertion`, and it was `measurements_for_assertion` while
    returning `List[types.Metric]` and being wired to the `metricsForAssertion`
    field. `Metric` and `Measurement` are two different types here — a metric is a
    claim shape, a measurement is a `Link` a view can draw — so the resolver name
    and its docstring named the one concept the function has nothing to do with.

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
