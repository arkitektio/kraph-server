"""Deleting a graph destroys the only interpretation of the evidence it read.

`delete_or_explain` is a `try/except ProtectedError`, not a check, and **nothing
anywhere `PROTECT`s `core.Graph`** — every foreign key into it cascades. So the
guard on `delete_graph` could never fire, and the call was an unconditional
destruction wearing a refusal's clothes.

What went with it: every `Category`, `GraphSchema`, `GraphOntology`, every saved
query and plot, and the AGE namespace. The evidence itself survived, because
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
import uuid
from evidence import models as evidence_models
from tests.support import writes


DELETE_GRAPH = """
    mutation DeleteGraph($input: DeleteGraphInput!) {
        deleteGraph(input: $input)
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
        writes.ASSERT_ENTITY_EXISTS,
        variable_values={"input": {"term": "AIS"}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"

    @sync_to_async
    def node_count() -> int:
        return evidence_models.Instance.objects.for_organization(test_graph.organization).count()

    before = await node_count()
    assert before >= 1

    await api_schema.execute(writes.ARCHIVE_GRAPH, variable_values={"input": {"id": str(test_graph.id)}}, context_value=authenticated_context)

    result = await _delete(api_schema, authenticated_context, test_graph)
    assert result.errors is None, f"A used view is still deletable: {result.errors}"

    assert not await core_models.Graph.objects.filter(pk=test_graph.pk).aexists(), "The view goes"
    assert await node_count() == before, "And every node survives it — evidence is the organization's, not the view's"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_empty_archived_graph_is_deletable(
    api_schema: kante.Schema,
    authenticated_context: HttpContext,
    table_projector,
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
            table_projector,
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


DELETE_ENTITY_CATEGORY = """
    mutation DeleteEntityCategory($input: DeleteEntityCategoryInput!) {
        deleteEntityCategory(input: $input)
    }
"""


DELETE_STRUCTURE_KIND = """
    mutation DeleteStructureKind($input: DeleteStructureKindInput!) {
        deleteStructureKind(input: $input)
    }
"""


async def _an_entity(api_schema: kante.Schema, ctx: HttpContext, graph: core_models.Graph) -> tuple[str, core_models.EntityCategory]:
    category = await core_models.EntityCategory.objects.filter(graph=graph, key="AIS").afirst()
    assert category is not None
    created = await api_schema.execute(
        writes.ASSERT_ENTITY_EXISTS,
        variable_values={"input": {"term": category.key, "supportingEvidence": []}},
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertEntityExists"]["instance"]["id"], category


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_deleting_a_used_entity_category_is_allowed_and_the_evidence_survives(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """A category is one view's rule, so removing it takes nothing with it.

    This asserted the opposite, and had to: `Node.category` pointed straight at
    the graph-scoped row, so deleting a category could destroy organization-scoped
    evidence and a `PROTECT` was the only thing standing in the way.

    The log names a **term** now. Deleting this category drops the word from
    *this* graph and leaves the node, its claims and the word itself untouched —
    so the failure the guard existed for is not prevented, it is unreachable.
    What cannot be deleted is the term, and `test_deleting_a_used_term_is_refused`
    covers that.
    """
    _, category = await _an_entity(api_schema, simple_api_context, test_graph)
    term_id = category.term_id

    result = await api_schema.execute(
        DELETE_ENTITY_CATEGORY,
        variable_values={"input": {"id": str(category.pk)}},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"A view's own rule is its to remove: {result.errors}"

    @sync_to_async
    def survivors() -> tuple[int, int, int]:
        return (
            evidence_models.Instance.objects.for_organization(test_graph.organization).filter(term_id=term_id).count(),
            core_models.EntityCategory.objects.filter(pk=category.pk).count(),
            evidence_models.Term.objects.for_organization(test_graph.organization).filter(pk=term_id).count(),
        )

    nodes, categories, terms = await survivors()
    assert nodes == 1, "The evidence is organization-scoped and outlives any view built from it"
    assert categories == 0, "The view's rule is gone"
    assert terms == 1, "And the word it declared is still the organization's"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_deleting_a_used_term_is_refused(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The guard did not disappear — it moved to the thing the log names.

    Same shape as `test_deleting_a_used_structure_kind_is_refused`, which is the
    organization vocabulary this now matches.
    """
    _, category = await _an_entity(api_schema, simple_api_context, test_graph)

    @sync_to_async
    def delete_the_term() -> str:
        from django.db.models import ProtectedError

        try:
            evidence_models.Term.objects.for_organization(test_graph.organization).get(pk=category.term_id).delete()
        except ProtectedError as error:
            return str(error)
        return ""

    refusal = await delete_the_term()
    assert refusal, "A word that has been claimed against cannot be removed"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_deleting_a_graph_leaves_the_evidence_standing(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The case that mattered most, and the one now structurally impossible.

    `deleteGraph` cascaded through its categories into organization evidence, so
    it destroyed rows that were not the deleted graph's to destroy. The refusal
    that stopped it was doing real work, but it was guarding a foreign key that
    should never have existed.

    **There is no FK path from `Graph` to `Node` any more.** A graph is a view;
    deleting it removes the view. So this asserts the evidence count is unchanged
    rather than that the deletion was blocked — a stronger property, because it
    holds without anything having to remember to check.
    """
    await _an_entity(api_schema, simple_api_context, test_graph)

    @sync_to_async
    def node_count() -> int:
        return evidence_models.Instance.objects.for_organization(test_graph.organization).count()

    before = await node_count()
    assert before >= 1

    # Archived first. Deleting a graph is irreversible and takes every rule for
    # reading the evidence with it, so the reversible step is a precondition —
    # see `_refuse_unless_archived`. The property under test here is unchanged:
    # a used view is still deletable, and the evidence still survives it.
    archived = await api_schema.execute(
        "mutation ArchiveGraph($input: ArchiveGraphInput!) { archiveGraph(input: $input) { id isArchived } }",
        variable_values={"input": {"id": str(test_graph.pk)}},
        context_value=simple_api_context,
    )
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    result = await api_schema.execute(
        DELETE_GRAPH,
        variable_values={"input": {"id": str(test_graph.pk)}},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"A view is deletable: {result.errors}"

    @sync_to_async
    def survivors() -> tuple[int, int]:
        return (
            evidence_models.Instance.objects.for_organization(test_graph.organization).count(),
            core_models.Graph.objects.filter(pk=test_graph.pk).count(),
        )

    nodes, graphs = await survivors()
    assert nodes == before, "Every node survives the view that showed it"
    assert graphs == 0, "And the view is gone"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_deleting_a_used_structure_kind_is_refused(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Vocabulary outlives what was recorded under it.

    `delete_structure_kind`'s own docstring used to say it "cascades to the
    structures and metrics recorded under it… deleting vocabulary deletes the
    evidence expressed in it" — which is exactly what append-only forbids.
    """
    created = await api_schema.execute(
        writes.ASSERT_STRUCTURE,
        variable_values={"input": {"identifier": "ROI", "object": f"roi_{uuid.uuid4().hex[:8]}", "metrics": []}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"

    @sync_to_async
    def the_kind() -> evidence_models.StructureKind:
        return evidence_models.StructureKind.objects.for_organization(test_graph.organization).get(identifier="ROI")

    kind = await the_kind()

    result = await api_schema.execute(
        DELETE_STRUCTURE_KIND,
        variable_values={"input": {"id": str(kind.pk)}},
        context_value=simple_api_context,
    )

    assert result.errors is not None, "Deleting a structure kind in use must be refused"

    @sync_to_async
    def structures() -> int:
        return evidence_models.Structure.objects.for_organization(test_graph.organization).filter(kind=kind).count()

    assert await structures() == 1
