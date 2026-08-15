"""
Structure mutation resolvers.

A structure is a pointer to an external datum — a Mikro ROI, an image — and lives
only in the relational evidence base. Nothing projects one into Apache AGE, so
:class:`api.types.StructureAssertion` carries no `drawings` field at all: the
absence is a permanent property of the model rather than a per-call answer.
"""

from typing import cast

from kante.types import Info

from api import types, inputs, context


def assert_structure_exists(
    info: Info,
    input: inputs.AssertStructureExistsInput,
) -> types.StructureAssertion:
    """Claim that an external datum exists and is worth pointing at.

    Idempotent by `(identifier, object)` within the organization: two projections
    referencing the same external object converge on one row instead of each
    getting a private copy. So a second call is a second *assertion* about the
    same structure, which is exactly what the log should record.
    """
    payload = input.to_pydantic()

    controller = context.get_controller()
    organization = context.get_active_organization(info)

    return types.StructureAssertion(
        _value=controller.create_structure(
            organization=organization,
            identifier=payload.identifier,
            payload=payload,
            info=info,
        )
    )


def ensure_structure(
    info: Info,
    input: inputs.EnsureStructureInput,
) -> types.StructureAssertion:
    """Get the structure for an external datum, creating it if this is the first sight of it.

    **Identical to `assertStructureExists` in every observable way.** Same
    controller call, same arguments, and the assertion each records is built from
    `_provenance_from_info` alone — nothing marks which field was called, so the
    evidence they produce cannot be told apart. The two names are kept for caller
    ergonomics: a structure is idempotent by `(identifier, object)`, so an ingest
    reaching for a handle and an annotator claiming the datum is worth pointing at
    are the same write, and both spellings read naturally at their own call sites.

    If that distinction ever needs to be recoverable from the log, it has to be
    *recorded* — an `action_name` on the assertion would do it. Until then, do not
    document a difference the rows do not carry.

    Delegates rather than repeating the body, so the claim above stays true by
    construction instead of by a reader diffing two functions.
    """
    return assert_structure_exists(info, cast(inputs.AssertStructureExistsInput, input))


def retract_structure(
    info: Info,
    input: inputs.RetractStructureInput,
) -> types.StructureAssertion:
    """Claim that a structure should no longer be pointed at.

    The row survives, and so do its metrics: a derived value that dropped a
    contributing measurement still has to be explainable afterwards.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    return types.StructureAssertion(
        _value=controller.archive_structure(
            structure_id=str(model.id),
            info=info,
        )
    )


def update_structure(
    info: Info,
    input: inputs.UpdateStructureInput,
) -> types.StructureAssertion:
    """Append metrics to an existing structure.

    Keeps the name `update` because it genuinely appends: a structure's
    `(identifier, object)` is its identity, so `object` is immutable and
    repointing it is rejected rather than superseded.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    return types.StructureAssertion(
        _value=controller.update_structure(
            structure_id=str(model.id),
            payload=model,
            info=info,
        )
    )


def link_structure_to_entity(
    info: Info,
    input: inputs.LinkStructureInput,
) -> types.StructureAssertion:
    """
    Assert that a structure is evidence for an entity.

    Keeps its name: it is already a claim verb, and what it claims is a relation
    between two things rather than the existence of either.

    This is a pure evidence write: it records the claim that a given ROI (or
    image, or file) justifies a given entity, as an `INFORMS` link under a fresh
    assertion. Which structures support an entity is a statement about the world,
    so it outlives any particular graph projected from it.

    Recording the link also refreshes the entity it now supports, so a structure
    attached after the fact still flows into the derived values.
    """
    controller = context.get_controller()

    organization = context.get_active_organization(info)
    structure = controller.get_structure_for_identifier(
        organization=organization,
        identifier=input.structure_identifier,
        object=input.structure_object,
    )

    return types.StructureAssertion(
        _value=controller.link_structure_to_entity(
            structure_id=str(structure.pk),
            entity_id=input.entity_id,
            info=info,
        )
    )
