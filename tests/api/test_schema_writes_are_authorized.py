"""The ontology and the saved queries belong to a tenant too.

Instance mutations have been authorized since the write API started naming terms:
they resolve the request's active organization and call
`context.assert_can_access_organization`. Everything around them did not. The
ontology, the saved queries and the plots were fetched by bare primary
key on managers that filter only by `kind`:

    item = models.EntityCategory.objects.get(id=model.id)
    item.delete()

Nothing there names an organization, a graph, or an owner. Primary keys are
sequential integers, so any authenticated member of any tenant could read, edit
and delete another tenant's schema by guessing a number — and eleven of those
paths ended in a bare `.delete()`. `update_graph` was the sharpest instance: its
permission check guarded only the `archived` branch, which was the one field that
did not exist, while `name`, `description` and `pinned_by` were written unchecked.

The scenario throughout is **a real second tenant**, not a user with no
membership at all. A caller who belongs to nothing is refused by the auth
extension long before any of this, so testing that would prove nothing about the
guard. What has to hold is that belonging *somewhere* does not mean belonging
*here*.

The check comes from the row rather than from the request, for the same reason
`GraphController._assert_same_organization` does: the client names a primary key
and never names a tenant, so a check against the request's own organization would
happily authorize a caller against their own tenant while acting on somebody
else's row.
"""

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models


@pytest.fixture
def outsider_graph(db, backend_stack, test_graph: core_models.Graph) -> core_models.Graph:
    """A graph in a tenant the requesting user is not a member of."""
    from authentikate.models import Membership, Organization, User

    other, _ = Organization.objects.get_or_create(slug="a-rival-lab")
    stranger, _ = User.objects.get_or_create(username="stranger", sub="stranger-sub")
    membership, _ = Membership.objects.get_or_create(user=stranger, organization=other)

    return core_models.Graph.objects.create(
        name="rival_graph",
        age_name="rival_graph_a_rival_lab",
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
        "mutation D($input: DeleteEntityDefinitionInput!) { deleteEntityCategory(input: $input) }",
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
        "mutation U($input: UpdateEntityDefinitionInput!) { updateEntityCategory(input: $input) { id } }",
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
        "mutation C($input: CreateEntityDefinitionInput!) { createEntityCategory(input: $input) { id } }",
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
            age_name="a_colleagues_graph_x",
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
        "mutation C($input: CreateEntityDefinitionInput!) { createEntityCategory(input: $input) { id key } }",
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
