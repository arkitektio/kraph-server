"""
Relation mutation resolvers.

A relation is a claim that two entities are connected, so it is evidence. The
`Link` row is the fact and the AGE edge is a projection of it — which is why
these resolvers address relations by their evidence id rather than by the AGE
edge id, the only identity that survives a `reproject`.

All of them return an :class:`api.types.AssertedRelation`, so a caller sees the
claim it made and every view that draws the edge afterwards.
"""

from kante.types import Info

from api import types, inputs, context
from core import enums


def assert_relation_exists(info: Info, input: inputs.AssertRelationExistsInput) -> types.AssertedRelation:
    """Assert a relation between two entities, under one of the organization's words.

    Names a term — so the edge is drawn in every view declaring the word, and the
    claim can be stated before any view declares it. Endpoint category pairs are
    not checked, and never were: the `MaterializedRelationEdge` cross-product that
    might have looked like a guard was a read surface, and is gone (RFC 0001 §6).
    """
    payload = input.to_pydantic()
    controller = context.get_controller()

    organization = context.get_active_organization(info)
    context.assert_can_access_organization(info, organization)

    term = controller.ensure_term(organization, enums.CategoryKindChoices.RELATION, payload.term)

    return types.AssertedRelation(
        _value=controller.create_relation(
            organization=organization,
            term=term,
            payload=payload,
            info=info,
        )
    )


def supersede_relation(info: Info, input: inputs.SupersedeRelationInput) -> types.AssertedRelation:
    """Replace a relation with a new assertion, keeping the old one on the record.

    Keeps the name `update`, unlike `supersedeMetricValue`: the retraction here is
    bookkeeping around a restatement, and what the caller means is one relation
    replacing another.

    **Two assertions are recorded and the result reports the second.** The
    retraction is its own act with its own row — that is what keeps the original
    claim explainable — but the assertion a caller wants a handle on is the one
    that made the relation now standing.

    The word comes off the existing `Link`, not from a category. It used to be
    `RelationCategory.objects.get(id=existing.category_id)` — where `category_id`
    is whichever view happened to declare the word, and is legitimately `None` when
    none does, so the lookup could raise `Category.DoesNotExist` on a perfectly
    good relation.
    """
    model = input.to_pydantic()
    controller = context.get_controller()

    link = controller.resolve_edge_link(str(model.id), info)
    organization = link.organization
    context.assert_can_access_organization(info, organization)

    controller.retract_relation(relation_id=str(model.id), info=info)

    return types.AssertedRelation(
        _value=controller.create_relation(
            organization=organization,
            term=controller.edge_term(link),
            payload=model,
            info=info,
        )
    )


def retract_relation(info: Info, input: inputs.RetractRelationInput) -> types.AssertedRelation:
    """Retract a relation assertion without destroying it.

    The edge survives wherever another live assertion still states the same
    proposition, which is exactly what the result's `drawings` reports — so this
    no longer re-reads the relation afterwards to build a payload. The controller
    returns the claim it made.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    link = controller.resolve_edge_link(str(model.id), info)
    context.assert_can_access_organization(info, link.organization)

    return types.AssertedRelation(_value=controller.retract_relation(relation_id=str(model.id), info=info, at=model.at, confidence=model.confidence))
