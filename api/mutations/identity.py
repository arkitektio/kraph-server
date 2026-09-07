"""Instance identity mutations: two recorded instances being one thing, or two.

Saying "this is AIS 6" is one act with four claims in it — mint the term, mint an
instance, say the structure measures it, say it is the same as one already known
— so the sameness half rides along on `assertEntityExists` under the same
assertion. The first two here are for the cases that are genuinely their own
act: noticing later that two recorded instances are one thing, and taking that
back. The other two are the mirror (RFC 0019): saying two recorded instances
are *not* one thing, which is a claim of one's own rather than a position on
somebody else's, and taking that back.
"""

from kante.types import Info

from api import context, inputs, types


def assert_same_instance(info: Info, input: inputs.AssertSameInstanceInput) -> types.AssertedSameness:
    """Claim that several already-recorded instances are one thing.

    Sameness is an equivalence with no primary, so the order of the ids carries
    no meaning — `evidence.identity` picks the lowest uuid as representative
    precisely so that identity does not depend on who was named first.
    """
    model = input.to_pydantic()
    controller = context.get_controller()

    organization = context.get_active_organization(info)
    context.assert_can_access_organization(info, organization)

    return types.AssertedSameness(_value=controller.assert_same_instance(organization=organization, instance_refs=model.instances, info=info, observed_at=model.observed_at, confidence=model.confidence, derived_from=model.derived_from))


def retract_same_instance(info: Info, input: inputs.RetractSameInstanceInput) -> types.AssertedSameness:
    """Withdraw one sameness claim.

    The component it held together is rebuilt from the claims that survive, which
    may split it — union-find has no un-union, so the fold is recomputed rather
    than adjusted.
    """
    model = input.to_pydantic()
    controller = context.get_controller()

    return types.AssertedSameness(_value=controller.retract_same_instance(str(model.id), info=info, at=model.at, confidence=model.confidence))


def assert_different_instance(info: Info, input: inputs.AssertDifferentInstanceInput) -> types.AssertedDifference:
    """Claim that several already-recorded instances are distinct things.

    A standing, trusted difference vetoes every direct sameness between its two
    ends in the fold; a difference contradicted through a third instance is
    reported on the node as `conflicts` rather than resolved by guessing.
    """
    model = input.to_pydantic()
    controller = context.get_controller()

    organization = context.get_active_organization(info)
    context.assert_can_access_organization(info, organization)

    return types.AssertedDifference(_value=controller.assert_different_instance(organization=organization, instance_refs=model.instances, info=info, observed_at=model.observed_at, confidence=model.confidence, derived_from=model.derived_from))


def retract_different_instance(info: Info, input: inputs.RetractDifferentInstanceInput) -> types.AssertedDifference:
    """Withdraw one difference claim. The sameness it vetoed counts again."""
    model = input.to_pydantic()
    controller = context.get_controller()

    return types.AssertedDifference(_value=controller.retract_different_instance(str(model.id), info=info, at=model.at, confidence=model.confidence))
