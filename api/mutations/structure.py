"""
Structure mutation resolvers.

A structure is a pointer to an external datum — a Mikro ROI, an image — and lives
only in the relational evidence base. Nothing projects one into Apache AGE, so
:class:`api.types.AssertedStructure` carries no `drawings` field at all: the
absence is a permanent property of the model rather than a per-call answer.
"""

from typing import cast

from kante.types import Info

from api import types, inputs, context


def assert_structure_exists(
    info: Info,
    input: inputs.AssertStructureExistsInput,
) -> types.AssertedStructure:
    """Claim that an external datum exists and is worth pointing at.

    Idempotent by `(identifier, object)` within the organization: two projections
    referencing the same external object converge on one row instead of each
    getting a private copy. So a second call is a second *assertion* about the
    same structure, which is exactly what the log should record.
    """
    payload = input.to_pydantic()

    controller = context.get_controller()
    organization = context.get_active_organization(info)

    return types.AssertedStructure(
        _value=controller.create_structure(
            organization=organization,
            identifier=payload.identifier,
            payload=payload,
            info=info,
        )
    )


def retract_structure(
    info: Info,
    input: inputs.RetractStructureInput,
) -> types.AssertedStructure:
    """Claim that a structure should no longer be pointed at.

    The row survives, and so do its metrics: a derived value that dropped a
    contributing measurement still has to be explainable afterwards.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    return types.AssertedStructure(
        _value=controller.retract_structure(
            structure_id=str(model.id),
            info=info,
            at=model.at,
            confidence=model.confidence,
        )
    )


def record_metrics(
    info: Info,
    input: inputs.RecordMetricsInput,
) -> types.AssertedStructure:
    """Record measurements against a datum already on the record.

    Named for the act (it was `updateStructure`): nothing about the structure
    changes — its `(identifier, object)` is its identity and repointing it is
    rejected — only new metric claims are appended under one assertion.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    return types.AssertedStructure(
        _value=controller.record_metrics(
            structure_id=str(model.id),
            payload=model,
            info=info,
        )
    )


def attest_structure(
    info: Info,
    input: inputs.AttestStructureInput,
) -> types.AssertedStructure:
    """Claim that a structure still stands.

    The counterpart of `retractStructure`, and it had none. `attest*` covered
    entity, natural event, protocol event and comment — four claim kinds out of
    ten — so every other retraction was one-way through the API, against the rule
    the write side is built on: existence is evidence, and two people may
    disagree about it.

    Not "un-retract": this records a fresh position beside the retraction rather
    than removing it.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    return types.AssertedStructure(_value=controller.attest_structure(str(model.id), info=info, at=model.at, confidence=model.confidence))


def assert_informs(
    info: Info,
    input: inputs.AssertInformsInput,
) -> types.AssertedDescription:
    """
    Assert that a datum is evidence for an entity — an INFORMS claim.

    Named for the claim it records (it was `linkStructureToEntity`): what it
    claims is a relation between two individuals, not the existence of either.

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

    return types.AssertedDescription(
        _value=controller.assert_informs(
            structure_id=str(structure.pk),
            entity_id=input.entity_id,
            info=info,
        )
    )
