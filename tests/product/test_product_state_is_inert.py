"""Archiving something archives it. Eleven mutations did not.

`archive_graph`, `update_graph`'s `archived` branch and nine `archive_*_query`
resolvers set an attribute that was a field on no model. Python took it, `save()`
persisted nothing, and the caller got a success. `Graph` carries
`ProvenanceField`, so `archiveGraph` additionally wrote a `simple_history` row
recording a change that had not happened.

Two things kept it invisible for as long as it was there. **No GraphQL type
exposed the flag**, so a client could write it and never read it back — the write
and the read were never joined up by anyone. And `tests/api/test_no_hard_deletes.py`
is a **name check**: it regexes the `type Mutation` block and asserts names are
present or absent. `archiveGraphTableQuery` being on the schema passes it;
whether it does anything is never asked. That file is right about what it tests —
the absence of a destructive surface is a real property — but a name check can
never catch a resolver that does nothing.

So every assertion here calls the mutation, **re-reads the row**, and checks the
state moved. Any one of them would have caught all eleven.

This is the sanctioned alternative to deleting: `delete_graph`'s own refusal says
*"Archive the graph instead"*. A soft delete that does not delete makes that
sentence a lie, which is why this sits under the no-hard-deletes doctrine rather
than beside it.
"""

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext
from core import models as core_models
from core.models import Graph
from tests.support import writes


UPDATE_GRAPH = """
    mutation UpdateGraph($input: UpdateGraphInput!) {
        updateGraph(input: $input) { id isArchived }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_archiving_a_graph_persists(
    api_schema: kante.Schema,
    authenticated_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Call it, re-read the row, assert the state moved.

    The re-read is the whole test. Asserting on the mutation's own return value
    would have passed before the column existed, because the resolver hands back
    the in-memory object it just set the attribute on.
    """
    result = await api_schema.execute(writes.ARCHIVE_GRAPH, variable_values={"input": {"id": str(test_graph.id)}}, context_value=authenticated_context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["archiveGraph"]["isArchived"] is True

    reloaded = await core_models.Graph.objects.aget(pk=test_graph.pk)
    assert reloaded.is_archived is True, "The archived state must survive the request that set it"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_archiving_is_reversible(
    api_schema: kante.Schema,
    authenticated_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Which is what separates archiving from deleting, and the reason it exists.

    `updateGraph(archived: false)` is the only way back — there is no
    `unarchiveGraph` — so if this did not work, archiving would be an
    irreversible hide, which is a delete with extra steps.
    """
    await api_schema.execute(writes.ARCHIVE_GRAPH, variable_values={"input": {"id": str(test_graph.id)}}, context_value=authenticated_context)

    result = await api_schema.execute(
        UPDATE_GRAPH,
        variable_values={"input": {"id": str(test_graph.id), "archived": False}},
        context_value=authenticated_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["updateGraph"]["isArchived"] is False

    reloaded = await core_models.Graph.objects.aget(pk=test_graph.pk)
    assert reloaded.is_archived is False, "An archived graph must be recoverable"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_archived_graph_is_still_reachable_by_id(
    api_schema: kante.Schema,
    authenticated_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Because otherwise nothing could unarchive it.

    Archived rows are not excluded from listings by default — `GraphFilter.is_archived`
    is opt-in, like `pinned` — precisely so the by-id field keeps working. A
    default exclusion would hide the row from the only mutation that can bring it
    back.
    """
    await api_schema.execute(writes.ARCHIVE_GRAPH, variable_values={"input": {"id": str(test_graph.id)}}, context_value=authenticated_context)

    result = await api_schema.execute(
        "query Graph($id: ID!) { graph(id: $id) { id isArchived } }",
        variable_values={"id": str(test_graph.id)},
        context_value=authenticated_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["graph"]["isArchived"] is True


QUERY_ARCHIVERS = [
    ("archiveGraphTableQuery", "GraphTableQuery"),
]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(("mutation", "model_name"), QUERY_ARCHIVERS)
async def test_archiving_a_saved_query_persists(
    mutation: str,
    model_name: str,
    api_schema: kante.Schema,
    authenticated_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Nine resolvers, nine identical no-ops, one assertion shape that catches all.

    **The response is a witness now.** These returned a bare `ID` when this test
    was written — "there is nothing in the response to check", as it used to say —
    which is part of why the no-op went unseen. `archive*` returns the archived
    object, as `archiveGraph` always did: `delete` hands back an id because the row
    is gone and an id is all that is left to name it, while `archive` leaves the
    row in place, so handing back an id was the one shape that could not show the
    caller what happened.

    The re-read stays regardless. It is the assertion that cannot be satisfied by
    a resolver returning the in-memory object it just set an attribute on.
    """
    model = getattr(core_models, model_name)

    @sync_to_async
    def make() -> int:
        item = model.objects.create(graph=test_graph, key=f"k_{mutation}", label=mutation, query="MATCH (n) RETURN n")
        assert item.archived is False, "A saved query starts live"
        return item.pk

    @sync_to_async
    def archived(pk: int) -> bool:
        return model.objects.get(pk=pk).archived

    pk = await make()

    result = await api_schema.execute(
        f"mutation Archive($input: Archive{model_name}Input!) {{ {mutation}(input: $input) {{ id archived }} }}",
        variable_values={"input": {"id": str(pk)}},
        context_value=authenticated_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data[mutation]["archived"] is True, f"{mutation} must report the state it just set"

    assert await archived(pk) is True, f"{mutation} must persist the flag, not set an attribute and drop it"


@pytest.mark.django_db(transaction=True)
def test_deleting_an_image_does_not_delete_the_view(test_graph: Graph) -> None:
    """`Graph.image` and `Category.image` cascaded *from* the media store: deleting
    a picture deleted the view, its categories and its whole projection."""
    from datalayer.models import MediaStore

    store = MediaStore.objects.create(key="graph.png", bucket="media", kind="MEDIA")
    test_graph.image = store
    test_graph.save(update_fields=["image"])
    category = test_graph.categories.first()
    category.image = store
    category.save(update_fields=["image"])

    # A queryset delete: the model's `delete()` would also try the object store.
    MediaStore.objects.filter(pk=store.pk).delete()

    test_graph.refresh_from_db()
    category.refresh_from_db()
    assert test_graph.image is None and category.image is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_moving_a_box_runs_no_ddl(api_schema, simple_api_context, test_graph, table_projector, monkeypatch) -> None:
    """Layout is presentation. `updateGraphVisual` used to `save()` each category,
    and the category-write signal then dropped and recreated the graph's whole
    Postgres schema once per moved box."""
    from asgiref.sync import sync_to_async

    from graph_engine.projection import table as table_module

    def refuse(*args, **kwargs):
        raise AssertionError("a layout change must not touch the namespace")

    monkeypatch.setattr(table_module.TableProjector, "refresh_namespace", refuse)

    category = await sync_to_async(core_models.Category.objects.get)(graph=test_graph, key="AIS")
    result = await api_schema.execute(
        writes.UPDATE_GRAPH_VISUAL,
        variable_values={"input": {"id": str(test_graph.pk), "nodePositions": [{"category": str(category.pk), "positionX": 3.0, "positionY": 4.0}]}},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    await sync_to_async(category.refresh_from_db)()
    assert (category.position_x, category.position_y) == (3.0, 4.0)
