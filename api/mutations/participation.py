"""
Participation mutation resolvers.

Who took part in an event is a claim, and claims are contestable. A second
observer reading the same timelapse may say a different cell went into that
division — before these existed, saying so meant `updateNaturalEvent`, which
archived the event and created a new one, so a disagreement about a participant
produced a different *event* and every metric keyed on the old one stopped
describing it.
"""

from kante.types import Info

from api import context, inputs, types


def assert_participation(info: Info, input: inputs.AssertParticipationInput) -> types.AssertedParticipation:
    """Claim that an entity took part in an event, without displacing anyone else's claim."""
    model = input.to_pydantic()
    controller = context.get_controller()

    return types.AssertedParticipation(
        _value=controller.assert_participation(
            event_id=model.event,
            entity_id=model.entity,
            role=model.role,
            is_input=model.is_input,
            info=info,
        )
    )


def retract_participation(info: Info, input: inputs.RetractParticipationInput) -> types.AssertedParticipation:
    """Retract one participation claim. The edge survives while another still stands.

    Which is what `drawings` reports: non-empty means somebody else's claim still
    holds the edge up.
    """
    model = input.to_pydantic()
    controller = context.get_controller()

    return types.AssertedParticipation(_value=controller.retract_participation(participation_id=str(model.id), info=info))


def assert_participations(info: Info, input: inputs.AssertParticipationsInput) -> types.AssertedLinks:
    """Claim that several entities took part in one event, as one act.

    One assertion covers the batch, and the result says so: a single
    `AssertedLinks` rather than one result per participant. Calling
    `assertParticipation` N times records the same act as N assertions, and
    `Assertion.action_id` — the field that would tie them back together — is
    never populated.
    """
    model = input.to_pydantic()
    controller = context.get_controller()

    return types.AssertedLinks(
        _value=controller.assert_participations(
            event_id=model.event,
            participants=model.participants,
            info=info,
        )
    )
