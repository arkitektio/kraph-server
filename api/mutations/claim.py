"""
Claim-level mutations: classification, and retraction of any claim.

Both are batch-shaped because a set of claims made together by one actor in one
act *is* one assertion. The singular forms are a batch of one.

Both return a **single** result carrying that one assertion and a list of
subjects — not a list of results. A list would have repeated the assertion once
per subject and claimed N acts had happened where the caller performed one.
"""

from kante.types import Info

from api import context, inputs, types


def classify_nodes(info: Info, input: inputs.ClassifyNodesInput) -> types.NodesAssertion:
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

    return types.NodesAssertion(_value=controller.classify_nodes(organization=organization, classifications=model.classifications, info=info))


def retract_claims(info: Info, input: inputs.RetractClaimsInput) -> types.EdgesAssertion:
    """Retract several claims as one act. Retraction is a claim too.

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

    return types.EdgesAssertion(_value=controller.archive_claims(claim_ids=[str(claim_id) for claim_id in model.ids], info=info))
