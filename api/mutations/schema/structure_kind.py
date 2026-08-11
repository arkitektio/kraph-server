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


def _resolve(info: Info, kind_id: str) -> evidence_models.StructureKind:
    """Fetch a kind and check the caller may act for its organization."""
    kind = evidence_models.StructureKind.all_objects.filter(id=kind_id).first()
    if kind is None:
        raise ValueError(f"Structure kind not found with id {kind_id}")
    context.assert_can_access_organization(info, kind.organization)
    return kind


def update_structure_kind(info: Info, input: inputs.UpdateStructureDefinitionInput) -> types.StructureKind:
    """Update a structure kind's presentation.

    Only descriptive fields. `identifier` is the kind's identity within the
    organization and is owned by the service that produces the datum, so it is
    not editable here — renaming it would silently orphan every structure that
    refers to it.
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


def delete_structure_kind(info: Info, input: inputs.DeleteStructureDefinitionInput) -> strawberry.ID:
    """Retire a structure kind.

    Cascades to the structures and metrics recorded under it, which is why it
    should be rare — the kind is vocabulary, and deleting vocabulary deletes the
    evidence expressed in it.
    """
    model = input.to_pydantic()
    _resolve(info, str(model.id)).delete()
    return model.id
