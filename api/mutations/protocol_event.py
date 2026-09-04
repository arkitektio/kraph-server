"""
Protocol event mutation resolvers.

Every one returns a :class:`api.types.AssertedProtocolEvent` — see `api/mutations/entity.py`.
"""

from kante.types import Info

from api import context, inputs, types
from core import enums
from evidence import models as evidence_models


def assert_protocol_event_exists(
    info: Info,
    input: inputs.AssertProtocolEventExistsInput,
) -> types.AssertedProtocolEvent:
    """Claim that a protocol step happened — see `assert_natural_event_exists`.

    States `PROTOCOL_EVENT` outright. The controller used to infer the node kind
    from `isinstance(category, models.ProtocolEventCategory)`, so the kind recorded
    in the log depended on which proxy class an FK happened to hydrate, in a
    resolver that already knew the answer.
    """
    controller = context.get_controller()

    protocol_event = input.to_pydantic()

    organization = context.get_active_organization(info)
    context.assert_can_access_organization(info, organization)

    term = controller.ensure_term(organization, enums.CategoryKindChoices.PROTOCOL_EVENT, protocol_event.term)

    return types.AssertedProtocolEvent(
        _value=controller.create_event(
            organization=organization,
            term=term,
            node_kind=evidence_models.Instance.Kind.PROTOCOL_EVENT,
            payload=protocol_event,
            info=info,
        )
    )


def retract_protocol_event(
    info: Info,
    input: inputs.RetractProtocolEventInput,
) -> types.AssertedProtocolEvent:
    """Claim that a protocol event did not happen. See `retract_entity`."""
    controller = context.get_controller()

    model = input.to_pydantic()

    # See `retract_natural_event`: one controller path for every node kind.
    return types.AssertedProtocolEvent(_value=controller.retract_node(model.id, info=info, at=model.at, confidence=model.confidence))


def attest_protocol_event(
    info: Info,
    input: inputs.AttestProtocolEventInput,
) -> types.AssertedProtocolEvent:
    """Claim that a protocol event exists. See `attest_entity`."""
    controller = context.get_controller()

    model = input.to_pydantic()
    return types.AssertedProtocolEvent(_value=controller.attest_node(model.id, info=info, at=model.at, confidence=model.confidence))
