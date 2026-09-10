"""Editing the organization's structure vocabulary.

There is no `create` here on purpose. Structure kinds are created lazily by
`ensure_structure_kind` the first time a measurement names an identifier, so
declaring one up front would only create a term nothing yet refers to. What
remains is editing how a kind presents itself, and retiring one.
"""

import strawberry
from kante.types import Info

from api import context, inputs, types
from evidence import models as evidence_models
from ._guards import delete_or_explain, refuse_bad_color


def _resolve(info: Info, kind_id: str) -> evidence_models.StructureKind:
    """Fetch a kind and check the caller may act for its organization."""
    kind = evidence_models.StructureKind.all_objects.filter(id=kind_id).first()
    if kind is None:
        raise ValueError(f"Structure kind not found with id {kind_id}")
    context.assert_can_access_organization(info, kind.organization)
    return kind


def update_structure_kind(info: Info, input: inputs.UpdateStructureKindInput) -> types.StructureKind:
    """Update a structure kind's presentation.

    Only descriptive fields. `identifier` is the kind's identity within the
    organization and is owned by the service that produces the datum, so it is
    not editable here — renaming it would silently orphan every structure that
    refers to it.
    """
    model = input.to_pydantic()
    kind = _resolve(info, str(model.id))

    refuse_bad_color(model.color)

    kind.label = model.label or kind.label
    kind.description = model.description or kind.description
    kind.color = model.color or kind.color
    kind.save()

    return kind


def delete_structure_kind(info: Info, input: inputs.DeleteStructureKindInput) -> strawberry.ID:
    """Retire a structure kind that nothing has been recorded under.

    This used to cascade to the structures and metrics recorded under it, and
    said so: "deleting vocabulary deletes the evidence expressed in it". That is
    exactly what evidence being append-only forbids, so the foreign key is
    `PROTECT` now and a kind in use cannot be removed at all.
    """
    model = input.to_pydantic()
    delete_or_explain(_resolve(info, str(model.id)), what="this structure kind", instead="Archive the structures recorded under it first.")
    return model.id
