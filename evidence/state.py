"""Maintaining the sufficient-statistics state vector.

Three operations, and the difference between them is the whole design:

- :func:`merge` folds one new metric into a row. O(1), no read of prior metrics.
- :func:`retract` removes a metric's contribution. O(1) when the statistic is a
  group operation (SUM, COUNT, MEAN); otherwise it can only flag the row.
- :func:`recompute` rebuilds a row from the surviving metrics. The expensive
  path, reached only when a retraction invalidated something order-dependent.

Nothing here computes an *answer*. The row holds statistics; which aggregation
reads them is decided at read time by :mod:`graph_engine.aggregate`. That
separation is what makes changing a property from MEAN to MAX a zero-write
operation.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable

from django.db import transaction
from django.db.models import Max, Min, Sum

from evidence import models as evidence_models


def _numeric(value: Any) -> float | None:
    """The numeric view of a value, or None when it has none.

    Strings and booleans still participate in COUNT and LATEST, so a metric that
    is not numeric is not an error — it simply contributes nothing to sum, min or
    max.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


@transaction.atomic
def merge(
    metric: evidence_models.Metric,
    entity_refs: Iterable[str],
) -> list[evidence_models.State]:
    """Fold one metric into the state of every entity it informs.

    ``entity_refs`` is passed in rather than derived here: which entities a
    structure informs is a projection question, and the projector owns it. This
    module only knows how to fold.
    """
    updated: list[evidence_models.State] = []
    numeric = _numeric(metric.value)

    for entity_ref in entity_refs:
        state, _ = evidence_models.State.all_objects.select_for_update().get_or_create(
            organization=metric.organization,
            entity_ref=entity_ref,
            source_kind=metric.structure.kind,
            key=metric.key,
        )

        state.n += 1
        if numeric is not None:
            state.sum = numeric if state.sum is None else state.sum + numeric
            state.min = numeric if state.min is None else min(state.min, numeric)
            state.max = numeric if state.max is None else max(state.max, numeric)

        # First and last are ordered by observation time, not by arrival: a
        # backfilled measurement from last year must not become "latest" just
        # because it was ingested today.
        if state.first_ts is None or metric.measured_at < state.first_ts:
            state.first_ts, state.first_value = metric.measured_at, metric.value
        if state.last_ts is None or metric.measured_at >= state.last_ts:
            state.last_ts, state.last_value = metric.measured_at, metric.value

        state.high_water_assertion = metric.assertion
        state.save()
        updated.append(state)

    return updated


@transaction.atomic
def retract(
    metric: evidence_models.Metric,
    entity_refs: Iterable[str],
) -> list[evidence_models.State]:
    """Remove a metric's contribution.

    SUM, COUNT and MEAN are group operations, so the delta subtracts exactly and
    the row stays correct. MIN, MAX, RANGE, LATEST and EUCLIDEAN_RANGE cannot be
    un-merged — the value being removed may be the very one that set the
    extremum — so those columns are marked stale and left for
    :func:`recompute`. Guessing instead (say, leaving the old max in place) would
    quietly report a value no surviving evidence supports.
    """
    numeric = _numeric(metric.value)
    touched: list[evidence_models.State] = []

    for entity_ref in entity_refs:
        state = (
            evidence_models.State.all_objects.select_for_update()
            .filter(
                organization=metric.organization,
                entity_ref=entity_ref,
                source_kind=metric.structure.kind,
                key=metric.key,
            )
            .first()
        )
        if state is None:
            continue

        state.n = max(0, state.n - 1)
        if numeric is not None and state.sum is not None:
            state.sum -= numeric

        extremum_touched = numeric is not None and numeric in (state.min, state.max)
        order_touched = metric.measured_at in (state.first_ts, state.last_ts)
        if extremum_touched or order_touched:
            state.needs_recompute = True

        state.save()
        touched.append(state)

    return touched


@transaction.atomic
def recompute(state: evidence_models.State) -> evidence_models.State:
    """Rebuild one row from the metrics that still support it.

    The correctness backstop for the whole scheme: whatever incremental
    maintenance did, this is what the answer should have been. `test_state_vector`
    asserts the two agree for random metric sequences, which is the only way to
    be confident a monoid was implemented rather than merely described.
    """
    metrics = evidence_models.Metric.objects.for_organization(state.organization).filter(
        structure__kind=state.source_kind,
        key=state.key,
        status=evidence_models.LifecycleStatus.ACTIVE,
        structure__in=_structures_informing(state),
    )

    aggregates = metrics.aggregate(total=Sum("value_num"), lowest=Min("value_num"), highest=Max("value_num"))
    ordered = list(metrics.order_by("measured_at"))

    state.n = len(ordered)
    state.sum = aggregates["total"]
    state.min = aggregates["lowest"]
    state.max = aggregates["highest"]
    state.first_ts = ordered[0].measured_at if ordered else None
    state.first_value = ordered[0].value if ordered else None
    state.last_ts = ordered[-1].measured_at if ordered else None
    state.last_value = ordered[-1].value if ordered else None
    state.needs_recompute = False
    state.save()
    return state


def _structures_informing(state: evidence_models.State) -> list[uuid.UUID]:
    """The structures whose measurements reach this entity.

    Returns real UUIDs, materialized rather than left as a subquery. `source_ref`
    is deliberately an opaque CharField — it has to hold projection-scoped entity
    refs as well as evidence keys — so Postgres will not compare it against a
    `uuid` column, and a subquery here fails with "operator does not exist:
    uuid = character varying". Parsing at this boundary is the price of keeping
    the refs opaque everywhere else, which is what makes M7 a re-point.
    """
    refs = (
        evidence_models.Link.objects.for_organization(state.organization)
        .filter(
            kind=evidence_models.Link.Kind.INFORMS,
            target_ref=state.entity_ref,
            status=evidence_models.LifecycleStatus.ACTIVE,
        )
        .values_list("source_ref", flat=True)
    )

    structure_ids: list[uuid.UUID] = []
    for ref in refs:
        try:
            structure_ids.append(uuid.UUID(str(ref)))
        except ValueError:
            # A link whose source is not a structure (a relation link, say) is
            # simply not evidence for a rollup. Skipping is correct; raising
            # would make one unrelated link break every recompute.
            continue
    return structure_ids


def recompute_stale(organization: Any, limit: int | None = None) -> int:
    """Rebuild every row a retraction left stale. Returns how many were fixed."""
    stale = evidence_models.State.objects.for_organization(organization).filter(needs_recompute=True)
    if limit is not None:
        stale = stale[:limit]

    count = 0
    for state in list(stale):
        recompute(state)
        count += 1
    return count


def state_for(
    organization: Any,
    entity_ref: str,
    source_kind: Any,
    key: str,
) -> evidence_models.State | None:
    """Read one state vector, recomputing it first if a retraction left it stale."""
    state = evidence_models.State.objects.for_organization(organization).filter(entity_ref=entity_ref, source_kind=source_kind, key=key).first()
    if state is not None and state.needs_recompute:
        recompute(state)
    return state
