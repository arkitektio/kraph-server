"""Who may change a graph's definition: its owner, and admins.

The old `Graph.rules` (per-action allow/deny lists) are gone — see RFC 0013.
Editing the schema — creating, updating or deleting categories — requires that
the requester is the graph's owner, has the "admin" role in the graph's
organization, or is a superuser. Reads and instance writes are untouched:
they stay organization-scoped as before.
"""

import pytest
from authentikate.models import Membership, User

from core import models as core_models

UPDATE_ENTITY_CATEGORY = """
    mutation U($input: UpdateEntityCategoryInput!) {
        updateEntityCategory(input: $input) { id }
    }
"""



def _info_for(user: User, organization, membership: Membership):
    """A minimal info for the guard itself.

    The auth extension resolves the static test token to one fixed identity,
    so multi-identity checks exercise `validate_definition_editable` directly —
    the same level the old `can_perform_action` tests used.
    """
    from types import SimpleNamespace

    request = SimpleNamespace(user=user, membership=membership, organization=organization)
    return SimpleNamespace(context=SimpleNamespace(request=request))


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_owner_may_edit_the_definition(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector) -> None:
    """End to end: the request identity owns `test_graph`, so the mutation passes."""
    category_id = str((await core_models.EntityCategory.objects.aget(graph=test_graph, key="Cell")).pk)
    updated = await api_schema.execute(
        UPDATE_ENTITY_CATEGORY,
        variable_values={"input": {"id": category_id, "description": "the owner may say what this means"}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"


@pytest.mark.django_db(transaction=True)
def test_a_plain_colleague_may_not(test_graph: core_models.Graph, table_projector) -> None:
    """Same organization, so reads work — but the schema is not theirs to change."""
    user, _ = User.objects.get_or_create(username="plain-colleague", defaults={"sub": "colleague", "iss": "static_issuer"})
    membership, _ = Membership.objects.get_or_create(user=user, organization=test_graph.organization)

    with pytest.raises(PermissionError, match="owner or an organization admin"):
        test_graph.validate_definition_editable(_info_for(user, test_graph.organization, membership))


@pytest.mark.django_db(transaction=True)
def test_an_admin_may(test_graph: core_models.Graph, table_projector) -> None:
    user, _ = User.objects.get_or_create(username="org-admin", defaults={"sub": "org-admin", "iss": "static_issuer"})
    membership, _ = Membership.objects.get_or_create(user=user, organization=test_graph.organization)
    membership.roles = ["admin"]
    membership.save()

    test_graph.validate_definition_editable(_info_for(user, test_graph.organization, membership))


@pytest.mark.django_db(transaction=True)
def test_an_admin_of_another_organization_may_not(test_graph: core_models.Graph, table_projector) -> None:
    """The admin role is per organization, not global."""
    from authentikate.models import Organization

    other, _ = Organization.objects.get_or_create(slug="somewhere-else")
    user, _ = User.objects.get_or_create(username="foreign-admin", defaults={"sub": "foreign-admin", "iss": "static_issuer"})
    membership, _ = Membership.objects.get_or_create(user=user, organization=other)
    membership.roles = ["admin"]
    membership.save()

    with pytest.raises(PermissionError):
        test_graph.validate_definition_editable(_info_for(user, other, membership))


@pytest.mark.django_db(transaction=True)
def test_a_superuser_may(test_graph: core_models.Graph, table_projector) -> None:
    user, _ = User.objects.get_or_create(username="the-superuser", defaults={"sub": "root", "iss": "static_issuer", "is_superuser": True})
    user.is_superuser = True
    user.save()
    test_graph.validate_definition_editable(_info_for(user, test_graph.organization, None))


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_graph_rules_are_gone_from_the_schema(api_schema, simple_api_context) -> None:
    made = await api_schema.execute(
        "mutation G($input: CreateGraphInput!) { createGraph(input: $input) { id } }",
        variable_values={"input": {"name": "no-rules", "definition": {"rules": [{"action": "AUTO_ADD_STRUCTURES", "allow": False}], "extensions": {"entities": [{"key": "X"}]}}}},
        context_value=simple_api_context,
    )
    assert made.errors is not None, "the per-action rule list is not an input any more"
