"""
Entity mutation resolvers.

Every one of these returns a :class:`api.types.EntityAssertion` — the claim it
recorded, the node it was about, and every view that draws that node afterwards.
See `graph_engine/results.py`.
"""

from api import inputs, types, context
from core import enums
from kante import Info


def assert_entity_exists(
    info: Info,
    input: inputs.AssertEntityExistsInput,
) -> types.EntityAssertion:
    """Claim that an entity exists, under one of the organization's words.

    Named for the act rather than for a row being made: nothing is *created*
    here. Somebody is claiming there is an AIS in this image, and a second
    annotator may claim there is not — both are recorded, and each view's
    selector decides whose word it counts. `create*` implied the writer owned the
    fact, and had no honest answer for a second caller claiming the same thing.

    Names a term, not a graph's category for one — so the claim can be made before
    any view exists to hold it, and every view that declares the word holds it once
    one does. Which views those are is decided by their own rules at projection
    time; if none declare it, the entity is recorded and simply undrawn, which the
    result reports as an empty `drawings`.

    Authorization is the organization, because the claim is the organization's.
    This used to resolve `entity_category.graph` and check access to that graph,
    which was really an organization check reached the long way round.
    """
    input_model = input.to_pydantic()

    organization = context.get_active_organization(info)
    context.assert_can_access_organization(info, organization)

    controller = context.get_controller()
    term = controller.ensure_term(organization, enums.CategoryKindChoices.ENTITY, input_model.term)

    return types.EntityAssertion(
        _value=controller.create_entity(
            organization=organization,
            term=term,
            payload=input_model,
            info=info,
        )
    )


def retract_entity(
    info: Info,
    input: inputs.RetractEntityInput,
) -> types.EntityAssertion:
    """Claim that an entity is not there, and stop drawing it where that counts.

    Called retraction rather than archiving because nothing is put away: a
    `Claim(stands=False)` is written and the vertex is removed. The entity's own
    row, its metrics and its relations are all untouched — a derived value that
    dropped a contributing measurement still has to be explainable afterwards.

    The result's `drawings` is read back rather than assumed empty. Existence is
    folded under each view's own selector, so a view that does not count this
    subject still draws the node.
    """
    controller = context.get_controller()

    model = input.to_pydantic()

    # The id is the entity's uuid, so there is no graph to extract from it and no
    # `get_accessible_graph` call to make here. Authorization comes from the row:
    # `archive_entity` resolves the node and checks the caller belongs to its
    # organization.
    return types.EntityAssertion(_value=controller.archive_entity(model.id, info=info))


def attest_entity(
    info: Info,
    input: inputs.AttestEntityInput,
) -> types.EntityAssertion:
    """Claim that an entity exists, and draw it back into every view that admits it.

    The counterpart of `retract_entity`, and deliberately not called "unarchive":
    nothing is being undone. This records new evidence that the thing is there,
    alongside whatever said it was not, and each graph decides which of them it
    counts.

    Distinct from `assertEntityExists` because the subject differs, not the act:
    that one names a word and mints a node, this one names a node that already
    exists. Whether any projection picks the attestation up is reported in
    `drawings`, and is not something this mutation fails on.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    return types.EntityAssertion(_value=controller.attest_node(model.id, info=info))
