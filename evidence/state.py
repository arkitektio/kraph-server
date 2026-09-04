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

from evidence import claims as claims_module
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
    instance_refs: Iterable[str],
) -> list[evidence_models.State]:
    """Fold one metric into the state of every entity it informs.

    ``instance_refs`` is passed in rather than derived here: which entities a
    structure informs is a projection question, and the projector owns it. This
    module only knows how to fold.
    """
    updated: list[evidence_models.State] = []
    numeric = _numeric(metric.value)

    for claim_ref in instance_refs:
        state, _ = evidence_models.State.all_objects.select_for_update().get_or_create(
            organization=metric.organization,
            claim_ref=claim_ref,
            source_kind=metric.structure.kind,
            key=metric.key,
            value_kind=metric.value_kind,
        )

        state.n += 1
        if numeric is not None:
            state.sum = numeric if state.sum is None else state.sum + numeric
            state.min = numeric if state.min is None else min(state.min, numeric)
            state.max = numeric if state.max is None else max(state.max, numeric)

        # First and last are ordered by observation time, not by arrival: a
        # backfilled measurement from last year must not become "latest" just
        # because it was ingested today.
        if state.first_ts is None or metric.observed_at < state.first_ts:
            state.first_ts, state.first_value = metric.observed_at, metric.value
        if state.last_ts is None or metric.observed_at >= state.last_ts:
            state.last_ts, state.last_value = metric.observed_at, metric.value

        state.high_water_assertion = metric.assertion
        state.save()
        updated.append(state)

    return updated


@transaction.atomic
def retract(
    metric: evidence_models.Metric,
    instance_refs: Iterable[str],
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

    for claim_ref in instance_refs:
        state = (
            evidence_models.State.all_objects.select_for_update()
            .filter(
                organization=metric.organization,
                claim_ref=claim_ref,
                source_kind=metric.structure.kind,
                key=metric.key,
                value_kind=metric.value_kind,
            )
            .first()
        )
        if state is None:
            continue

        state.n = max(0, state.n - 1)
        if numeric is not None and state.sum is not None:
            state.sum -= numeric

        extremum_touched = numeric is not None and numeric in (state.min, state.max)
        order_touched = metric.observed_at in (state.first_ts, state.last_ts)
        if extremum_touched or order_touched:
            state.needs_recompute = True

        state.save()
        touched.append(state)

    return touched


def fold(metrics: Any, into: evidence_models.State) -> evidence_models.State:
    """Fold a set of metrics into a state vector, in place. Does not save.

    The batch counterpart of :func:`merge`, and the one place the statistics are
    computed from scratch. :func:`recompute` saves what this produces;
    :func:`graph_engine.projector.derive_properties` uses it **unsaved** to answer
    a selector-scoped read without keeping a second row per view.
    """
    aggregates = metrics.aggregate(total=Sum("value_num"), lowest=Min("value_num"), highest=Max("value_num"))
    ordered = list(metrics.order_by("observed_at"))

    into.n = len(ordered)
    into.sum = aggregates["total"]
    into.min = aggregates["lowest"]
    into.max = aggregates["highest"]
    into.first_ts = ordered[0].observed_at if ordered else None
    into.first_value = ordered[0].value if ordered else None
    into.last_ts = ordered[-1].observed_at if ordered else None
    into.last_value = ordered[-1].value if ordered else None
    return into


@transaction.atomic
def recompute(state: evidence_models.State) -> evidence_models.State:
    """Rebuild one row from the metrics that still support it.

    The correctness backstop for the whole scheme: whatever incremental
    maintenance did, this is what the answer should have been. `test_state_vector`
    asserts the two agree for random metric sequences, which is the only way to
    be confident a monoid was implemented rather than merely described.

    **No selector.** State is organization grain, so this counts every live
    metric reaching the entity — exactly as :func:`merge` does. It used to be
    that `refold_state` applied a graph's selector here and `merge` did not, so
    the incremental fold and the rebuild produced different rows, and this
    "backstop" agreed with the wrong one. Which metrics a *view* counts is a
    read-time question; see `projector.derive_properties`.
    """
    metrics = claims_module.standing(
        evidence_models.Metric.objects.for_organization(state.organization).filter(
            structure__kind=state.source_kind,
            key=state.key,
            value_kind=state.value_kind,
            structure__in=_structures_informing(state),
        ),
        "metric",
    )

    fold(metrics, state)
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
            target_ref=state.claim_ref,
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
    claim_ref: str,
    source_kind: Any,
    key: str,
    value_kinds: Iterable[str],
) -> evidence_models.State | None:
    """Read the state vector for a key, recomputing anything a retraction left stale.

    ``value_kinds`` is a set rather than a single kind because INT and FLOAT are
    distinct terms that both live in ``value_num`` — see
    :data:`graph_engine.projector.NUMERIC_FAMILY`. A rule naming FLOAT that read
    only the FLOAT row would silently miss every INT measurement of the same
    quantity, which is the under-derivation this grain exists to prevent. Rows
    are folded together with :func:`combine`, so the caller gets one vector
    whichever way the terms happened to split.

    Note the return may be an **unsaved** row — see :func:`combine`. Callers read
    it; they must not save it.

    Ordered so that two measurements sharing an `observed_at` across two terms
    resolve LATEST the same way every time. Unordered, the winner would depend on
    whatever order Postgres returned the rows in, which is not a decision worth
    leaving to chance for a value the API reports.
    """
    return state_for_many(organization, [claim_ref], source_kind, key, value_kinds)


def state_for_many(
    organization: Any,
    claim_refs: Iterable[str],
    source_kind: Any,
    key: str,
    value_kinds: Iterable[str],
) -> evidence_models.State | None:
    """The state vector for a key over several claims at once — an individual's members (RFC 0018).

    The stored grain is per instance, because the log is; a view that holds
    several instances to be one thing reads their rows and folds them with
    :func:`combine`, exactly as the value-kind family is folded. Ordered by
    `(claim_ref, value_kind)` so LATEST resolves the same way every time.
    Unsaved result; callers read it and must not save it.
    """
    refs = [str(ref) for ref in claim_refs]
    states = list(evidence_models.State.objects.for_organization(organization).filter(claim_ref__in=refs, source_kind=source_kind, key=key, value_kind__in=list(value_kinds)).order_by("claim_ref", "value_kind"))

    for state in states:
        if state.needs_recompute:
            recompute(state)

    return combine(states)


def combine(states: Iterable[evidence_models.State]) -> evidence_models.State | None:
    """Fold several state vectors into one, without saving it.

    The monoid the whole design rests on, finally used as one: statistics from
    disjoint metric sets compose. Returns an **unsaved** `State` — it is a read,
    not a row, and persisting it would create a second grain claiming to hold
    what two others already hold.
    """
    states = [state for state in states if state is not None]
    if not states:
        return None
    if len(states) == 1:
        return states[0]

    merged = evidence_models.State(
        organization=states[0].organization,
        claim_ref=states[0].claim_ref,
        source_kind=states[0].source_kind,
        key=states[0].key,
        value_kind=states[0].value_kind,
    )
    merged.n = sum(state.n for state in states)

    sums = [state.sum for state in states if state.sum is not None]
    merged.sum = sum(sums) if sums else None

    mins = [state.min for state in states if state.min is not None]
    merged.min = min(mins) if mins else None

    maxes = [state.max for state in states if state.max is not None]
    merged.max = max(maxes) if maxes else None

    # Ordered by observation time, exactly as `merge` does it — so a value that
    # is "latest" in a combined read is the same one that would be latest had the
    # metrics never split across terms.
    for state in states:
        if state.first_ts is not None and (merged.first_ts is None or state.first_ts < merged.first_ts):
            merged.first_ts, merged.first_value = state.first_ts, state.first_value
        if state.last_ts is not None and (merged.last_ts is None or state.last_ts >= merged.last_ts):
            merged.last_ts, merged.last_value = state.last_ts, state.last_value

    return merged
