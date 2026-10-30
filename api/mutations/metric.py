"""
Metric mutation resolvers.

Metrics live in the relational evidence base and are scoped to the organization,
not to a graph. Their IDs are therefore bare primary keys: there is no composite
`{graph}:{id}` to pull a graph out of, so the controller resolves the row first
and then authorizes the caller against *its* organization.

**Named for values, not existence.** A metric asserts that something *measures*
45.2µm; `assertMetricExists` would name the wrong thing. Nothing projects a
metric into the drawing either, so :class:`api.types.AssertedMetric` carries no
`drawings` field.
"""

from kante.types import Info

from api import types, inputs, context


def assert_metric_value(
    info: Info,
    input: inputs.AssertMetricValueInput,
) -> types.AssertedMetric:
    """Record a measurement, creating the structure it describes if this is its first sight.

    Takes the structure's `identifier` and `object` rather than a key, so an
    ingest can state a measurement about an ROI nobody has registered yet.

    **One controller call, so one assertion.** This used to call
    `create_structure` and then `create_metric`, minting two assertions for what
    the caller made as one claim — and `Assertion.action_id`, the field that would
    tie them back together, is never populated.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    organization = context.get_active_organization(info)

    # The structure is created if it is new. Refusing a measurement because no
    # graph had declared the identifier would be refusing a fact about the world
    # on a bookkeeping technicality — and the identifier belongs to the service
    # that produced the datum anyway.
    return types.AssertedMetric(
        _value=controller.record_metric(
            organization=organization,
            identifier=model.identifier,
            object=model.object,
            metric=model,
            info=info,
        )
    )


def assert_metric_values(
    info: Info,
    input: inputs.AssertMetricValuesInput,
) -> types.AssertedMetricValues:
    """Record many measurements as one act, the way an app states what it computed.

    Set-based, where `assertMetricValue` is one row per call (`evidence.metric_batch`). Who
    recorded them comes from the request, and the rekuest task from its provenance token,
    never from the input: a caller cannot name a task it was not called in.
    """
    model = input.to_pydantic()
    return types.AssertedMetricValues(_value=context.get_controller().assert_metric_values(context.get_active_organization(info), model.metrics, info))


def supersede_metric_value(
    info: Info,
    input: inputs.SupersedeMetricValueInput,
) -> types.AssertedMetric:
    """Correct a measurement by retracting it and asserting a new one.

    Not called `update`, because there is no update: both the original claim and
    the correction stay on the record and `as_of` can still recover what was
    believed before the revision. The returned metric therefore has a **different
    id** from the one passed in — it is a new row, not an edited one.

    One assertion covers both halves, which is why they share a transaction: the
    retraction and the replacement are one corrective act.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    return types.AssertedMetric(_value=controller.update_metric(payload=model, info=info))


def attest_metric(
    info: Info,
    input: inputs.AttestMetricInput,
) -> types.AssertedMetric:
    """Claim that a measurement still stands — see `attestStructure`.

    Refolds the derived values the metric feeds, because a measurement coming
    back changes every statistic that dropped it.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    return types.AssertedMetric(_value=controller.attest_metric(str(model.id), info=info, at=model.at, confidence=model.confidence))


def retract_metric(
    info: Info,
    input: inputs.RetractMetricInput,
) -> types.AssertedMetric:
    """Retract a measurement without destroying it.

    The metric stays readable afterwards, which is the point: a derived value that
    stopped counting this measurement still has to be explainable.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    return types.AssertedMetric(_value=controller.retract_metric(metric_id=str(model.id), info=info, at=model.at, confidence=model.confidence))
