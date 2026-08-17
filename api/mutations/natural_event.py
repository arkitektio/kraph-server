"""
Natural event mutation resolvers.

Every one returns a :class:`api.types.AssertedNaturalEvent` — see `api/mutations/entity.py`.
"""

from kante.types import Info

from api import types, inputs, context
from core import enums
from evidence import models as evidence_models


def assert_natural_event_exists(
    info: Info,
    input: inputs.AssertNaturalEventExistsInput,
) -> types.AssertedNaturalEvent:
    """Claim that a natural event happened, under one of the organization's words.

    Names a term rather than an event category — see `assert_entity_exists`. The
    roles the participants are given are the caller's own words for them and are
    recorded as such; nothing here checks them against a view's declared roles,
    and nothing did.

    Also gains an authorization check. This resolver fetched the category and never
    called `validate_graph_access` at all, unlike its entity and relation siblings,
    so an authenticated caller could write an event into any organization whose
    category id they could guess.
    """
    controller = context.get_controller()

    natural_event = input.to_pydantic()

    organization = context.get_active_organization(info)
    context.assert_can_access_organization(info, organization)

    term = controller.ensure_term(organization, enums.CategoryKindChoices.NATURAL_EVENT, natural_event.term)

    return types.AssertedNaturalEvent(
        _value=controller.create_event(
            organization=organization,
            term=term,
            node_kind=evidence_models.Instance.Kind.NATURAL_EVENT,
            payload=natural_event,
            info=info,
        )
    )


def retract_natural_event(
    info: Info,
    input: inputs.RetractNaturalEventInput,
) -> types.AssertedNaturalEvent:
    """Claim that a natural event did not happen. See `retract_entity`."""
    controller = context.get_controller()

    model = input.to_pydantic()

    # One controller path for every node kind. This used to be an inline copy of
    # the retraction flow with `target_type` hardcoded — which is how the entity
    # and event spellings drifted apart in the first place.
    return types.AssertedNaturalEvent(_value=controller.archive_node(model.id, info=info))


def attest_natural_event(
    info: Info,
    input: inputs.AttestNaturalEventInput,
) -> types.AssertedNaturalEvent:
    """Claim that a natural event exists. See `attest_entity`."""
    controller = context.get_controller()

    model = input.to_pydantic()
    return types.AssertedNaturalEvent(_value=controller.attest_node(model.id, info=info))
