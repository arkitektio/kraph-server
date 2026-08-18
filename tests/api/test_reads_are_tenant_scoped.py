"""The read side fences every declaratively-served field to the caller's organization.

The write side has always closed this deliberately — `api/mutations/_scoped.py`
resolves a row and then checks the caller belongs to its tenant. The read side did
not. `api/queries/kinds.py` states the problem exactly, for the two vocabularies it
resolves by hand:

    The old `structureCategories` / `metricCategories` fields had no resolver at
    all — their only tenant fence was the client happening to pass
    `CategoryFilter.graph`. Kinds have no graph to filter on, so scoping has to
    happen here or not at all.

That fix was applied to kinds and nowhere else. `graphs`, the six `*Categories`
families, the twelve saved-query families and `scatterPlots` are bare
`kante.django_field`s with no resolver, over managers that do not scope
(`core/managers.py::GraphManager` is a plain `models.Manager`). Neither
`authentikate`'s schema extension nor `kante` filters querysets — the extension
resolves the organization onto the request and stops there — so nothing narrowed
the rows a query could reach, and both the list forms and the `(id:)` forms were
answerable across tenants by guessing a sequential integer primary key.

`api/types.py::org_scoped` and the fence folded into `_kind_dispatch` close it.
These tests are the confirmation: each builds a graph under a *second*
organization the request is not a member of, and asserts the caller cannot see it.
"""

import pytest
from authentikate.models import Membership, Organization, User

from core import models as core_models


@pytest.fixture
def other_organization(db) -> Organization:
    """An organization the static test token is **not** a member of."""
    org, _ = Organization.objects.get_or_create(slug="a_tenant_you_are_not_in")
    return org


@pytest.fixture
def foreign_graph(transactional_db, other_organization) -> core_models.Graph:
    """A graph belonging to that other organization.

    Owned by its own user and membership, so nothing about it is reachable from
    the static token's identity except by an unfenced query.
    """
    user, _ = User.objects.get_or_create(
        username="a_stranger",
        defaults={"sub": "999", "iss": "static_issuer"},
    )
    membership, _ = Membership.objects.get_or_create(user=user, organization=other_organization)

    return core_models.Graph.objects.create(
        age_name="foreigngraph_atenantyouarenotin",
        name="Foreign Graph",
        description="Belongs to a tenant the caller has no membership in",
        organization=other_organization,
        user=user,
        membership=membership,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_graphs_does_not_list_another_tenants_graph(api_schema, simple_api_context, foreign_graph):
    """The list form is scoped."""
    result = await api_schema.execute(
        "query { graphs { id name } }",
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    ids = [g["id"] for g in result.data["graphs"]]
    assert str(foreign_graph.pk) not in ids, "`graphs` handed back a graph belonging to another organization"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_graph_by_id_refuses_another_tenants_graph(api_schema, simple_api_context, foreign_graph):
    """The singular form is scoped too — the pk is a sequential integer, so guessing it is trivial.

    `get_queryset` is applied by strawberry-django to pk lookups as well as root
    lists, which is what makes one fence cover both.
    """
    result = await api_schema.execute(
        "query Graph($id: ID!) { graph(id: $id) { id name } }",
        variable_values={"id": str(foreign_graph.pk)},
        context_value=simple_api_context,
    )

    assert result.errors is not None or result.data.get("graph") is None, "`graph(id:)` returned another organization's graph"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_entity_categories_does_not_list_another_tenants_category(api_schema, simple_api_context, foreign_graph, test_graph):
    """Category types are `kind_type`s, so their fence rides on `_kind_dispatch`.

    That override filtered on `kind` alone — it narrowed a shared table to one
    category type and handed back every organization's rows of it.
    """
    foreign = await core_models.EntityCategory.objects.acreate(
        graph=foreign_graph,
        key="foreign_word",
        age_name="FOREIGNWORD",
        label="Foreign Word",
    )

    result = await api_schema.execute(
        "query { entityCategories { id } }",
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    ids = [c["id"] for c in result.data["entityCategories"]]
    assert str(foreign.pk) not in ids, "`entityCategories` handed back a category from another organization"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_callers_own_graph_is_still_visible(api_schema, simple_api_context, test_graph):
    """The fence must not be a blanket refusal — the caller's own rows still resolve."""
    result = await api_schema.execute(
        "query { graphs { id } }",
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    ids = [g["id"] for g in result.data["graphs"]]
    assert str(test_graph.pk) in ids, "The fence hid the caller's own graph"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_saved_queries_do_not_list_another_tenants_row(api_schema, simple_api_context, foreign_graph):
    """The twelve saved-query families are proxies over `GraphQuery`/`NodeQuery`/`EdgeQuery`.

    Worth its own test because the fence looks these up by model name, and a proxy
    queryset reports the *proxy's* name (`GraphTableQuery`), not the concrete one
    (`GraphQuery`). Every `kind_type` here happens to register against the concrete
    model, so the plain `__name__` lookup worked — but only by coincidence of the
    registration, and a fence that misses its table returns `None` and fails open.
    `_organization_filter` keys on `_meta.concrete_model` so it cannot.
    """
    foreign = await core_models.GraphTableQuery.objects.acreate(
        graph=foreign_graph,
        key="foreign_table_query",
        label="Foreign Table Query",
        query="MATCH (n) RETURN n",
    )

    result = await api_schema.execute(
        "query { graphTableQueries { id } }",
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    ids = [q["id"] for q in result.data["graphTableQueries"]]
    assert str(foreign.pk) not in ids, "`graphTableQueries` handed back a saved query from another organization"
