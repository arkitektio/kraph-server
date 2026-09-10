"""Editing the organization's measurement vocabulary.

No `create`, for the same reason as structure kinds: `ensure_metric_kind` mints
one the first time a measurement is recorded under a key, and it is that call —
not a declaration — that knows the value kind.
"""

import strawberry
from kante.types import Info

from api import context, inputs, types
from evidence import models as evidence_models
from ._guards import delete_or_explain, refuse_bad_color


def _resolve(info: Info, kind_id: str) -> evidence_models.MetricKind:
    """Fetch a kind and check the caller may act for its organization."""
    kind = evidence_models.MetricKind.all_objects.filter(id=kind_id).first()
    if kind is None:
        raise ValueError(f"Metric kind not found with id {kind_id}")
    context.assert_can_access_organization(info, kind.organization)
    return kind


def update_metric_kind(info: Info, input: inputs.UpdateMetricKindInput) -> types.MetricKind:
    """Update a metric kind's presentation.

    `value_kind` is deliberately not editable, now for two reasons. It is part of
    the term's identity, so changing it is not an edit but a move to a different
    term — and the term it moved to may already exist. And it would reinterpret
    every measurement already recorded here: values live in a column chosen by
    the kind, and the state vectors folded from them are keyed by it, so a term
    that changes type leaves both its history and its statistics in the wrong
    place. Record under the other term instead; both are allowed to exist.
    """
    model = input.to_pydantic()
    kind = _resolve(info, str(model.id))

    refuse_bad_color(model.color)

    kind.label = model.label or kind.label
    kind.description = model.description or kind.description
    kind.color = model.color or kind.color
    kind.save()

    return kind


def delete_metric_kind(info: Info, input: inputs.DeleteMetricKindInput) -> strawberry.ID:
    """Retire a metric kind nothing has been recorded under.

    The FK from `Metric` is `PROTECT`: a kind that has been used can be retired
    only after its metrics are retracted, never by deleting them.
    """
    model = input.to_pydantic()
    delete_or_explain(_resolve(info, str(model.id)), what="this metric kind", instead="Archive the metrics recorded under it first.")
    return model.id
