"""Deleting schema must not destroy the evidence recorded under it.

The widest silent destroyer in the codebase, and the one that came from the
direction nothing was watching. `Node.category` and `Link.category` pointed at
graph-scoped `core.Category` on `CASCADE`, and `Structure.kind` / `Metric.kind`
cascaded from the organization's vocabulary. So `deleteEntityCategory` removed
every entity ever recorded under the term, and `deleteGraph` removed every `Node`
and categorised `Link` in the graph — organization-scoped rows that *other*
projections were built from.

Nothing announced it. The append-only guarantee held perfectly against every
mutation that wrote evidence, and was undone by one that wrote schema.

These keys are `PROTECT` now. A term that has been used cannot be removed, and
the refusal names what is in the way.
"""

import uuid

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models

CREATE_ENTITY = """
    mutation CreateEntity($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { instance { id } }
    }
"""

DELETE_ENTITY_CATEGORY = """
    mutation DeleteEntityCategory($input: DeleteEntityCategoryInput!) {
        deleteEntityCategory(input: $input)
    }
"""

DELETE_GRAPH = """
    mutation DeleteGraph($input: DeleteGraphInput!) {
        deleteGraph(input: $input)
    }
"""

CREATE_STRUCTURE = """
    mutation CreateStructure($input: AssertStructureExistsInput!) {
        assertStructureExists(input: $input) { structure { id } }
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
        CREATE_ENTITY,
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
        CREATE_STRUCTURE,
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
