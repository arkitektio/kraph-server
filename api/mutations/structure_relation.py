"""
Structure relation mutation resolvers.

Structure relations are evidence rows and nothing else. Both endpoints are
structures, which stopped being AGE vertices in M1, so there is no edge to
project and no graph in the identifier — the `Link` primary key names the claim
directly, the same way a structure's id does.

Their results therefore always carry an empty `drawings`, structurally: neither
endpoint has a vertex, so there is nothing for an edge to run between.
"""

from kante.types import Info

from api import context, inputs, types
from core import enums


def assert_structure_relation_exists(info: Info, input: inputs.AssertStructureRelationExistsInput) -> types.AssertedStructureRelation:
    """Assert a relation between two structures, under one of the organization's words.

    Names a term. Both endpoints were already organization-scoped and there is no
    projection to target, so the category this used to take was pure ceremony: it
    was reduced to its term and its graph's organization and then dropped.
    """
    payload = input.to_pydantic()
    controller = context.get_controller()
    organization = context.get_active_organization(info)
    context.assert_can_access_organization(info, organization)

    term = controller.ensure_term(organization, enums.CategoryKindChoices.STRUCTURE_RELATION, payload.term)

    return types.AssertedStructureRelation(
        _value=controller.create_structure_relation(
            organization=organization,
            term=term,
            payload=payload,
            info=info,
        )
    )


def update_structure_relation(info: Info, input: inputs.UpdateStructureRelationInput) -> types.AssertedStructureRelation:
    """Replace a structure relation, keeping the old assertion on the record.

    Two assertions are recorded and the result reports the second — see
    `update_relation`.
    """
    model = input.to_pydantic()
    controller = context.get_controller()

    link = controller.resolve_edge_link(str(model.id), info)
    organization = link.organization
    context.assert_can_access_organization(info, organization)

    # Retract then re-assert, never edit in place: the correction and what it
    # corrected both stay on the record. Same shape as `supersede_metric_value`.
    controller.retract_relation(relation_id=str(model.id), info=info)

    return types.AssertedStructureRelation(
        _value=controller.create_structure_relation(
            organization=organization,
            term=controller.edge_term(link),
            payload=model,
            info=info,
        )
    )


def retract_structure_relation(info: Info, input: inputs.RetractStructureRelationInput) -> types.AssertedStructureRelation:
    """Retract a structure relation assertion without destroying it."""
    model = input.to_pydantic()
    controller = context.get_controller()

    link = controller.resolve_edge_link(str(model.id), info)
    context.assert_can_access_organization(info, link.organization)

    return types.AssertedStructureRelation(_value=controller.retract_relation(relation_id=str(model.id), info=info, at=model.at))
