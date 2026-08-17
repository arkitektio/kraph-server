"""Instance identity mutations: two recorded instances being one thing.

Saying "this is AIS 6" is one act with four claims in it — mint the term, mint an
instance, say the structure measures it, say it is the same as one already known
— so the sameness half rides along on `assertEntityExists` under the same
assertion. These two are for the cases that are genuinely their own act: noticing
later that two recorded instances are one thing, and taking that back.
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

    return types.AssertedSameness(_value=controller.assert_same_instance(organization=organization, instance_refs=model.instances, info=info))


def retract_same_instance(info: Info, input: inputs.RetractSameInstanceInput) -> types.AssertedSameness:
    """Withdraw one sameness claim.

    The component it held together is rebuilt from the claims that survive, which
    may split it — union-find has no un-union, so the fold is recomputed rather
    than adjusted.
    """
    model = input.to_pydantic()
    controller = context.get_controller()

    return types.AssertedSameness(_value=controller.retract_same_instance(str(model.id), info=info))
