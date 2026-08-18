"""
Measurement mutation resolvers.

A measurement is the ontology-typed form of INFORMS: it names which term of the
schema the claim "this structure measures that entity" falls under. Its source is
a structure, which is a Postgres row, so like a structure relation it has no
projected edge and is addressed by its evidence id.

Its results therefore always carry an empty `drawings`, and structurally so:
there is no AGE edge for a measurement to be drawn as.
"""

from kante.types import Info

from api import types, inputs, context
from core import enums


def assert_measurement_exists(info: Info, input: inputs.AssertMeasurementExistsInput) -> types.AssertedMeasurement:
    """Assert that a structure measures an entity, under one of the organization's words.

    Names a term rather than a measurement category — see `assert_entity_exists`.
    The structure and the entity are both organization-scoped already, so this was
    the last part of the claim that named a view.
    """
    payload = input.to_pydantic()
    controller = context.get_controller()

    organization = context.get_active_organization(info)
    context.assert_can_access_organization(info, organization)

    term = controller.ensure_term(organization, enums.CategoryKindChoices.MEASUREMENT, payload.term)

    return types.AssertedMeasurement(
        _value=controller.create_measurement(
            organization=organization,
            term=term,
            payload=payload,
            info=info,
        )
    )


def retract_measurement(info: Info, input: inputs.RetractMeasurementInput) -> types.AssertedMeasurement:
    """Retract a measurement assertion without destroying it."""
    controller = context.get_controller()

    model = input.to_pydantic()
    link = controller.resolve_edge_link(str(model.id), info)
    context.assert_can_access_organization(info, link.organization)

    return types.AssertedMeasurement(_value=controller.retract_relation(relation_id=str(model.id), info=info))
