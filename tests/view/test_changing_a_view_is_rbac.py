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
import kante
from asgiref.sync import sync_to_async
from kante.context import HttpContext


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


@pytest.fixture
def outsider_graph(db, backend_stack, test_graph: core_models.Graph) -> core_models.Graph:
    """A graph in a tenant the requesting user is not a member of."""
    from authentikate.models import Membership, Organization, User

    other, _ = Organization.objects.get_or_create(slug="a-rival-lab")
    stranger, _ = User.objects.get_or_create(username="stranger", sub="stranger-sub")
    membership, _ = Membership.objects.get_or_create(user=stranger, organization=other)

    return core_models.Graph.objects.create(
        name="rival_graph",
        user=stranger,
        membership=membership,
        organization=other,
    )


@pytest.fixture
def outsider_category(outsider_graph: core_models.Graph) -> core_models.EntityCategory:
    """A category owned by that other tenant."""
    return core_models.EntityCategory.objects.create(graph=outsider_graph, key="Secret", age_name="secret")


async def _run(api_schema: kante.Schema, ctx: HttpContext, document: str, variables: dict):
    return await api_schema.execute(document, variable_values=variables, context_value=ctx)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_another_tenants_category_cannot_be_deleted(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    outsider_category: core_models.EntityCategory,
) -> None:
    """The worst of the eleven bare `.delete()` paths.

    Nothing was recoverable afterwards: a category is the rule that says what a
    word means in a view, and it has no history table.
    """
    result = await _run(
        api_schema,
        simple_api_context,
        "mutation D($input: DeleteEntityCategoryInput!) { deleteEntityCategory(input: $input) }",
        {"input": {"id": str(outsider_category.pk)}},
    )

    assert result.errors, "Another tenant's category must not be deletable"
    assert await core_models.EntityCategory.objects.filter(pk=outsider_category.pk).aexists(), "And the refusal must actually refuse"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_another_tenants_category_cannot_be_edited(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    outsider_category: core_models.EntityCategory,
) -> None:
    """Editing is quieter than deleting and no less serious.

    A category's `property_definitions` decide what its vertices carry, so an
    edit here rewrites another tenant's data through the rematerialization the
    resolver now triggers.
    """
    result = await _run(
        api_schema,
        simple_api_context,
        "mutation U($input: UpdateEntityCategoryInput!) { updateEntityCategory(input: $input) { id } }",
        {"input": {"id": str(outsider_category.pk), "label": "Renamed by a stranger"}},
    )

    assert result.errors, "Another tenant's category must not be editable"

    reloaded = await core_models.EntityCategory.objects.aget(pk=outsider_category.pk)
    assert reloaded.label != "Renamed by a stranger"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_category_cannot_be_created_in_another_tenants_graph(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    outsider_graph: core_models.Graph,
) -> None:
    """The create path took the graph id straight from the input and wrote into it."""
    result = await _run(
        api_schema,
        simple_api_context,
        "mutation C($input: CreateEntityCategoryInput!) { createEntityCategory(input: $input) { id } }",
        {"input": {"graph": str(outsider_graph.pk), "key": "Trespass"}},
    )

    assert result.errors, "Writing vocabulary into another tenant's graph must be refused"
    assert not await core_models.EntityCategory.objects.filter(graph=outsider_graph, key="Trespass").aexists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_another_tenants_graph_cannot_be_renamed(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    outsider_graph: core_models.Graph,
) -> None:
    """`update_graph`'s check guarded only the branch that did nothing.

    The owner test sat inside `if model.archived is not None`, and `archived` was
    backed by no column — so the one field that was checked was the one field
    that could not be written, while `name`, `description` and `pinned_by` went
    through unguarded.
    """
    result = await _run(
        api_schema,
        simple_api_context,
        "mutation U($input: UpdateGraphInput!) { updateGraph(input: $input) { id name } }",
        {"input": {"id": str(outsider_graph.pk), "name": "Renamed by a stranger"}},
    )

    assert result.errors, "Another tenant's graph must not be renamable"

    reloaded = await core_models.Graph.objects.aget(pk=outsider_graph.pk)
    assert reloaded.name == "rival_graph"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_colleague_may_rename_a_graph_but_not_archive_it(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Two different rules, and the difference is now deliberate.

    Renaming is tenancy-scoped, like every other schema mutation: a shared view
    is the organization's to curate. Archiving is not, because archiving is the
    *precondition of deletion* now — a colleague who could archive could set up a
    destruction the owner never agreed to. `archiveGraph` and `deleteGraph`
    require owner-or-superuser for the same reason.

    Until this change the owner check sat inside the `archived` branch and
    nowhere else, so the asymmetry ran the other way round by accident: the one
    field that was guarded was the one field with no column behind it.

    The *graph* is owned by somebody else rather than the caller being swapped:
    the auth extension re-resolves `request._user` from the token at the start of
    every operation, so mutating the context is undone before the resolver runs.
    """
    from authentikate.models import Membership, User

    @sync_to_async
    def a_colleagues_graph() -> core_models.Graph:
        colleague, _ = User.objects.get_or_create(username="colleague-in-org", sub="colleague-in-org-sub")
        membership, _ = Membership.objects.get_or_create(user=colleague, organization=test_graph.organization)
        # Same tenant, different owner — which is the whole scenario.
        return core_models.Graph.objects.create(
            name="a_colleagues_graph",
            user=colleague,
            membership=membership,
            organization=test_graph.organization,
        )

    graph = await a_colleagues_graph()

    renamed = await _run(
        api_schema,
        simple_api_context,
        "mutation U($input: UpdateGraphInput!) { updateGraph(input: $input) { id name } }",
        {"input": {"id": str(graph.pk), "name": "Renamed by a colleague"}},
    )
    assert renamed.errors is None, f"A colleague may curate a shared view: {renamed.errors}"
    assert renamed.data["updateGraph"]["name"] == "Renamed by a colleague"

    archived = await _run(
        api_schema,
        simple_api_context,
        "mutation U($input: UpdateGraphInput!) { updateGraph(input: $input) { id isArchived } }",
        {"input": {"id": str(graph.pk), "archived": True}},
    )
    assert archived.errors, "But archiving is the step before deletion, and stays with the owner"
    assert "archiving is the step before deletion" in str(archived.errors[0])

    reloaded = await core_models.Graph.objects.aget(pk=graph.pk)
    assert reloaded.is_archived is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_another_tenants_saved_query_cannot_be_deleted(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    outsider_graph: core_models.Graph,
) -> None:
    """One of nine identical delete paths, plus its nine archive twins.

    The error text is asserted, not just its presence, and that is not
    fussiness. These query models are **proxies over one table** and
    `KindedManager` narrows reads by `kind`, so `scoped(info, GraphTableQuery,
    pk)` refuses a `GraphPathQuery` id with "no such row" before authorization is
    ever reached. A test that only checked `result.errors` could therefore be
    green because the kind filter fired, leaving the tenancy guard — the thing
    under test — unexercised across all eighteen paths.
    """

    @sync_to_async
    def make() -> int:
        return core_models.GraphTableQuery.objects.create(graph=outsider_graph, key="secret", label="Secret", query="MATCH (n) RETURN n").pk

    pk = await make()

    result = await _run(
        api_schema,
        simple_api_context,
        "mutation D($input: DeleteGraphTableQueryInput!) { deleteGraphTableQuery(input: $input) }",
        {"input": {"id": str(pk)}},
    )

    assert result.errors, "Another tenant's saved query must not be deletable"
    message = str(result.errors[0])
    assert "allowed to access" in message, f"The refusal must come from the tenancy check, not from the kind filter or a missing row: {message}"
    assert await core_models.GraphTableQuery.objects.filter(pk=pk).aexists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_guard_still_lets_the_owner_through(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Every refusal above is only meaningful if the legitimate path still works.

    Without this the whole file would pass just as well on a guard that refused
    everybody — which is the easy way to make a security test green and a system
    useless.

    Paired with `test_a_category_cannot_be_created_in_another_tenants_graph`,
    which sends this same mutation at somebody else's graph: same caller, same
    input shape, opposite outcome, so the guard is shown to key on the graph
    rather than on the mutation.
    """
    result = await _run(
        api_schema,
        simple_api_context,
        "mutation C($input: CreateEntityCategoryInput!) { createEntityCategory(input: $input) { id key } }",
        {"input": {"graph": str(test_graph.pk), "key": "Mine"}},
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["createEntityCategory"]["key"] == "Mine"
    assert await core_models.EntityCategory.objects.filter(graph=test_graph, key="Mine").aexists(), "And it lands in the caller's own graph"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_plot_belongs_to_the_person_who_made_it(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`ScatterPlot.creator` was on the model and read by nothing.

    Tenancy alone does not cover this one: the other user is in the *same*
    organization, so the graph boundary passes. Somebody else's saved plot is
    still not yours to destroy.
    """
    from authentikate.models import User

    @sync_to_async
    def make() -> int:
        colleague, _ = User.objects.get_or_create(username="colleague", sub="colleague-sub")
        query = core_models.GraphTableQuery.objects.create(graph=test_graph, key="q", label="Q", query="MATCH (n) RETURN n")
        return core_models.ScatterPlot.objects.create(graph_query=query, name="Theirs", creator=colleague).pk

    pk = await make()

    result = await _run(
        api_schema,
        simple_api_context,
        "mutation D($input: DeleteScatterPlotInput!) { deleteScatterPlot(input: $input) }",
        {"input": {"id": str(pk)}},
    )

    assert result.errors, "A colleague's plot is not yours to delete"
    assert await core_models.ScatterPlot.objects.filter(pk=pk).aexists()
