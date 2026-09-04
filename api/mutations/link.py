"""Writes over `evidence.Link`: classifying nodes, and retracting links.

The file was `claim.py` and the mutation was `retractClaims`, which named the wrong
table twice over: the ids it takes are `Link` primary keys, and `Standing` is what a
claim's *retraction* is a row of. Every kind of claim can be retracted — an
instance, a metric, a structure — but this one retracts links, so it says so.

Both are batch-shaped because a set of claims made together by one actor in one
act *is* one assertion. The singular forms are a batch of one.

Both return a **single** result carrying that one assertion and a list of
subjects — not a list of results. A list would have repeated the assertion once
per subject and claimed N acts had happened where the caller performed one.
"""

from kante.types import Info

from api import context, inputs, types


def classify_nodes(info: Info, input: inputs.ClassifyNodesInput) -> types.AssertedInstances:
    """Claim that several nodes are of a word, without displacing anyone else's claim.

    This is the additive alternative to what `updateEntity` used to do: it
    archived the node and minted a new uuid, so a disagreement about what
    something *is* produced a different entity.

    Each claim names a term, not a category. The word's *kind* is not stated: the
    controller takes it from the node, because a classification claiming an
    `ENTITY` word about an event would be a write no category is ever keyed on —
    accepted, stored, and readable by nothing.

    The nodes come back as their real kinds. This used to wrap every one in
    `types.Entity`, though the controller reads each node's kind from its row and
    accepts events — so classifying a natural event reported it as an entity, and
    only the `Node` interface made that type-check.
    """
    model = input.to_pydantic()
    controller = context.get_controller()

    organization = context.get_active_organization(info)
    context.assert_can_access_organization(info, organization)

    return types.AssertedInstances(_value=controller.classify_nodes(organization=organization, classifications=model.classifications, info=info))


def attest_link(
    info: Info,
    input: inputs.AttestLinkInput,
) -> types.AssertedLinks:
    """Claim that a link claim still stands — see `attestStructure`.

    One mutation for every link kind, as `retractLinks` is: a relation, a
    classification, a participation and a measurement are re-attested by the same
    act, and the payload reports the row's own `kind`.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    return types.AssertedLinks(_value=controller.attest_link(str(model.id), info=info, at=model.at))


def retract_links(info: Info, input: inputs.RetractLinksInput) -> types.AssertedLinks:
    """Retract several link claims as one act. Retraction is a claim too.

    The claims come back as their real kinds — dispatched on the `Link` row's
    kind, not on the edge's label. This used to wrap every one in
    `types.Measurement` though the controller retracts `CLASSIFIES`, `RELATION`,
    `PARTICIPATES_*` and `INFORMS` links alike, and label-based dispatch could not
    have fixed it: a participation edge is labelled with the *event category's*
    `age_name`, which says nothing about participation.

    Every kind now has a type of its own, `CLASSIFIES` included — it comes back as
    a `Classification`, whose target is a **term** rather than a node, which is
    what a classification actually claims. It used to be reported as a `Relation`
    for want of anything better.
    """
    model = input.to_pydantic()
    controller = context.get_controller()

    return types.AssertedLinks(_value=controller.retract_links(link_ids=[str(link_id) for link_id in model.ids], info=info, at=model.at))
