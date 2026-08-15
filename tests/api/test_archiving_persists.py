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

ARCHIVE_GRAPH = """
    mutation ArchiveGraph($input: ArchiveGraphInput!) {
        archiveGraph(input: $input) { id isArchived }
    }
"""

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
    result = await api_schema.execute(ARCHIVE_GRAPH, variable_values={"input": {"id": str(test_graph.id)}}, context_value=authenticated_context)
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
    await api_schema.execute(ARCHIVE_GRAPH, variable_values={"input": {"id": str(test_graph.id)}}, context_value=authenticated_context)

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
    await api_schema.execute(ARCHIVE_GRAPH, variable_values={"input": {"id": str(test_graph.id)}}, context_value=authenticated_context)

    result = await api_schema.execute(
        "query Graph($id: ID!) { graph(id: $id) { id isArchived } }",
        variable_values={"id": str(test_graph.id)},
        context_value=authenticated_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["graph"]["isArchived"] is True


#: The nine saved-query archive mutations, with the model each writes and the
#: mutation field name. All nine set `archived` on a field that did not exist;
#: the six proxy models share three tables, which is why three columns cover them.
QUERY_ARCHIVERS = [
    ("archiveGraphTableQuery", "GraphTableQuery"),
    ("archiveGraphPathQuery", "GraphPathQuery"),
    ("archiveGraphPairsQuery", "GraphPairsQuery"),
    ("archiveNodeTableQuery", "NodeTableQuery"),
    ("archiveNodePathQuery", "NodePathQuery"),
    ("archiveNodePairsQuery", "NodePairsQuery"),
    ("archiveEdgeTableQuery", "EdgeTableQuery"),
    ("archiveEdgePathQuery", "EdgePathQuery"),
    ("archiveEdgePairsQuery", "EdgePairsQuery"),
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

    Each returns a bare `ID`, so there is nothing in the response to check — the
    row itself is the only witness, which is exactly why a name check could never
    have found this.
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
        f"mutation Archive($input: Archive{model_name}Input!) {{ {mutation}(input: $input) }}",
        variable_values={"input": {"id": str(pk)}},
        context_value=authenticated_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    assert await archived(pk) is True, f"{mutation} must persist the flag, not set an attribute and drop it"
