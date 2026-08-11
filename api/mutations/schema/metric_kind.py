"""Editing the organization's measurement vocabulary.

No `create`, for the same reason as structure kinds: `ensure_metric_kind` mints
one the first time a measurement is recorded under a key, and it is that call —
not a declaration — that knows the value kind.
"""

import strawberry
from kante.types import Info

from api import context, inputs, types
from evidence import models as evidence_models


def _resolve(info: Info, kind_id: str) -> evidence_models.MetricKind:
    """Fetch a kind and check the caller may act for its organization."""
    kind = evidence_models.MetricKind.all_objects.filter(id=kind_id).first()
    if kind is None:
        raise ValueError(f"Metric kind not found with id {kind_id}")
    context.assert_can_access_organization(info, kind.organization)
    return kind


def update_metric_kind(info: Info, input: inputs.UpdateMetricDefinitionInput) -> types.MetricKind:
    """Update a metric kind's presentation.

    `value_kind` is deliberately not editable. Changing it would reinterpret every
    measurement already recorded under this term — values live in a column chosen
    by the kind, so a term that changes type leaves its own history in the wrong
    place.
    """
    model = input.to_pydantic()
    kind = _resolve(info, str(model.id))

    if model.color:
        assert len(model.color) in (3, 4), "Color must be a list of 3 or 4 values RGBA"

    kind.label = model.label or kind.label
    kind.description = model.description or kind.description
    kind.color = model.color or kind.color
    kind.save()

    return kind


def delete_metric_kind(info: Info, input: inputs.DeleteMetricDefinitionInput) -> strawberry.ID:
    """Retire a metric kind, and the measurements recorded under it."""
    model = input.to_pydantic()
    _resolve(info, str(model.id)).delete()
    return model.id
