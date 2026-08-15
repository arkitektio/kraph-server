"""Deleting a graph destroys the only interpretation of the evidence it read.

`delete_or_explain` is a `try/except ProtectedError`, not a check, and **nothing
anywhere `PROTECT`s `core.Graph`** — every foreign key into it cascades. So the
guard on `delete_graph` could never fire, and the call was an unconditional
destruction wearing a refusal's clothes.

What went with it: every `Category`, `GraphSchema`, `GraphOntology`,
`GraphSequence`, `Protocol`, every saved query and plot,
`MaterializedEdge`, and the AGE namespace. The evidence itself survived, because
it is organization-scoped — the second axiom paying for itself — but the words
this view declared, what they meant here, and whose claims it counted did not,
and none of that is versioned anywhere else. `tests/api/test_no_hard_deletes.py`
says genuine erasure is *"unreachable from a GraphQL request"*. `deleteGraph` was
reachable and irreversible.

The guard is deliberately narrow: **archived first**, because the reversible step
should precede the irreversible one, and because it makes that refusal message
true for the first time. Not a refusal on *emptiness* — a graph is a view, there
is no foreign key from it to `Node`, and deleting a used view has to stay
possible. What a populated deletion owes is a record of what went, which
`_record_what_deletion_destroys` writes; a durable one needs the schema snapshot
to round-trip first.
"""

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models

DELETE_GRAPH = """
    mutation DeleteGraph($input: DeleteGraphInput!) {
        deleteGraph(input: $input)
    }
"""

ARCHIVE_GRAPH = """
    mutation ArchiveGraph($input: ArchiveGraphInput!) {
        archiveGraph(input: $input) { id isArchived }
    }
"""

CREATE_ENTITY = """
    mutation CreateEntity($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { entity { id } }
    }
"""


async def _delete(api_schema: kante.Schema, ctx: HttpContext, graph: core_models.Graph):
    return await api_schema.execute(DELETE_GRAPH, variable_values={"input": {"id": str(graph.id)}}, context_value=ctx)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_live_graph_cannot_be_deleted(
    api_schema: kante.Schema,
    authenticated_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Archiving is the reversible step, so it comes first.

    This also makes the refusal message honest. It has always said *"Archive the
    graph instead"* — and until `is_archived` became a real column, that pointed
    at a mutation which set an attribute and dropped it.
    """
    result = await _delete(api_schema, authenticated_context, test_graph)

    assert result.errors, "A live graph must not be deletable"
    assert "archive it first" in str(result.errors[0])

    assert await core_models.Graph.objects.filter(pk=test_graph.pk).aexists(), "And the refusal must actually refuse"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_archived_graph_holding_nodes_is_still_deletable(
    api_schema: kante.Schema,
    authenticated_context: HttpContext,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """A view is deletable, used or not — and the evidence outlives it.

    The gate is on deliberateness, not on emptiness. Refusing here would have
    been the easy over-correction, and it would contradict the design: a graph is
    a view, there is no foreign key from it to `Node`, and
    `test_deleting_a_graph_leaves_the_evidence_standing` holds exactly this
    property.

    What is genuinely lost is the *interpretation* — the categories, their
    definitions, the selector, the schema chain — and the answer to that is the
    record `_record_what_deletion_destroys` writes, not a refusal. A durable
    record needs the schema snapshot to round-trip first, which is Tier 2 work.

    This also exercises the AGE `drop_graph` on a populated namespace, which the
    empty case does not: the graph name is unique, so an orphaned namespace would
    collide with the next graph created under it.
    """
    from evidence import models as evidence_models

    created = await api_schema.execute(
        CREATE_ENTITY,
        variable_values={"input": {"term": "AIS"}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"

    @sync_to_async
    def node_count() -> int:
        return evidence_models.Node.objects.for_organization(test_graph.organization).count()

    before = await node_count()
    assert before >= 1

    await api_schema.execute(ARCHIVE_GRAPH, variable_values={"input": {"id": str(test_graph.id)}}, context_value=authenticated_context)

    result = await _delete(api_schema, authenticated_context, test_graph)
    assert result.errors is None, f"A used view is still deletable: {result.errors}"

    assert not await core_models.Graph.objects.filter(pk=test_graph.pk).aexists(), "The view goes"
    assert await node_count() == before, "And every node survives it — evidence is the organization's, not the view's"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_empty_archived_graph_is_deletable(
    api_schema: kante.Schema,
    authenticated_context: HttpContext,
    age_engine,
) -> None:
    """The guard has to let something through, or it is a removal, not a guard.

    A view somebody created, never wrote to, and put away is genuinely
    disposable: there is no evidence whose only reader it is.
    """
    from graph_engine import input_models
    from graph_engine.materialize import materialize

    request = authenticated_context.request

    @sync_to_async
    def make() -> core_models.Graph:
        graph = materialize(
            input_models.GraphDefinitionInput(system_version="1.0.0", extensions=input_models.GraphExtensionsInput()),
            age_engine,
            user=request._user,
            organization=request._organization,
            membership=request.membership,
            name="disposable_graph",
        )
        graph.is_archived = True
        graph.save()
        return graph

    graph = await make()

    result = await _delete(api_schema, authenticated_context, graph)
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    assert not await core_models.Graph.objects.filter(pk=graph.pk).aexists(), "An empty archived graph really goes"
