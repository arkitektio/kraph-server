"""Category definitions through the API: structured, validated, reprojected.

`Category.definition` used to be settable only from Python, as hand-written JSON
whose unknown keys were silently ignored. It is a mutation input now
(`CategoryDefinitionInput`, RFC 0007): clauses are validated at the write,
membership moves when the predicate moves, and the stored meaning reads back.
"""

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models
from tests import claims, drawing, writes

CREATE_CATEGORY = """
    mutation C($input: CreateEntityCategoryInput!) {
        createEntityCategory(input: $input) { id key definition { anyOf { assertedAs since assertionFilter { subjects } } } }
    }
"""

UPDATE_CATEGORY = """
    mutation U($input: UpdateEntityCategoryInput!) {
        updateEntityCategory(input: $input) { id definition { anyOf { assertedAs assertionFilter { subjects } } } }
    }
"""

CREATE_GRAPH = """
    mutation G($input: CreateGraphInput!) {
        createGraph(input: $input) { id }
    }
"""


async def _claimed_cells(api_schema, ctx, literal_graph) -> tuple[str, str]:
    """Two Cells, one claimed by peter, one by karl."""
    c1 = await writes.create_entity(api_schema, ctx, "Cell")
    c2 = await writes.create_entity(api_schema, ctx, "Cell")

    @sync_to_async
    def annotate():
        cell = core_models.Category.objects.get(graph=literal_graph, key="Cell")
        claims.classify(literal_graph, c1, cell, "peter")
        claims.classify(literal_graph, c2, cell, "karl")

    await annotate()
    return c1, c2


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_with_a_definition_backfills_the_admitted_history(api_schema: kante.Schema, simple_api_context: HttpContext, literal_graph: core_models.Graph, table_projector) -> None:
    peters, _ = await _claimed_cells(api_schema, simple_api_context, literal_graph)

    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": {"name": "defined-views"}}, context_value=simple_api_context)
    assert made.errors is None, f"GraphQL errors: {made.errors}"
    graph_id = made.data["createGraph"]["id"]

    created = await api_schema.execute(
        CREATE_CATEGORY,
        variable_values={
            "input": {
                "graph": graph_id,
                "key": "PetersCells",
                "definition": {"anyOf": [{"assertedAs": ["Cell"], "assertionFilter": {"subjects": ["peter"]}}]},
                "backfill": True,
            }
        },
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    assert created.data["createEntityCategory"]["definition"]["anyOf"][0]["assertedAs"] == ["Cell"], "the meaning reads back from the same mutation"

    @sync_to_async
    def drawn():
        graph = core_models.Graph.objects.get(pk=graph_id)
        return drawing.refs_with_label(graph, "PetersCells")

    assert await drawn() == [peters], "backfill drew exactly the history the clauses admit — under this view's own word"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_updating_a_definition_moves_membership_and_writes_no_evidence(api_schema: kante.Schema, simple_api_context: HttpContext, literal_graph: core_models.Graph, table_projector) -> None:
    peters, karls = await _claimed_cells(api_schema, simple_api_context, literal_graph)

    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": {"name": "movable"}}, context_value=simple_api_context)
    assert made.errors is None
    graph_id = made.data["createGraph"]["id"]
    created = await api_schema.execute(
        CREATE_CATEGORY,
        variable_values={"input": {"graph": graph_id, "key": "TheCells", "definition": {"anyOf": [{"assertedAs": ["Cell"], "assertionFilter": {"subjects": ["peter"]}}]}, "backfill": True}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    category_id = created.data["createEntityCategory"]["id"]

    @sync_to_async
    def evidence_rows() -> int:
        return evidence_models.Assertion.objects.for_organization(literal_graph.organization).count()

    before = await evidence_rows()

    updated = await api_schema.execute(
        UPDATE_CATEGORY,
        variable_values={"input": {"id": category_id, "definition": {"anyOf": [{"assertedAs": ["Cell"], "assertionFilter": {"subjects": ["karl"]}}]}}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"
    assert updated.data["updateEntityCategory"]["definition"]["anyOf"][0]["assertionFilter"]["subjects"] == ["karl"]

    @sync_to_async
    def drawn():
        graph = core_models.Graph.objects.get(pk=graph_id)
        return drawing.refs_with_label(graph, "TheCells")

    assert await drawn() == [karls], "membership moved with the meaning — the mutation reprojected"
    assert await evidence_rows() == before, "a definition is a read-side reinterpretation: zero evidence writes"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_malformed_definitions_are_refused_by_name(api_schema: kante.Schema, simple_api_context: HttpContext, literal_graph: core_models.Graph, table_projector) -> None:
    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": {"name": "refusals"}}, context_value=simple_api_context)
    graph_id = made.data["createGraph"]["id"]

    async def attempt(definition):
        return await api_schema.execute(
            CREATE_CATEGORY,
            variable_values={"input": {"graph": graph_id, "key": "Broken", "definition": definition}},
            context_value=simple_api_context,
        )

    both = await attempt({"assertedAs": ["Cell"], "anyOf": [{"assertedAs": ["Cell"]}]})
    assert both.errors is not None and "not both" in str(both.errors[0]), "flat form and anyOf together is refused, not silently merged"

    empty_union = await attempt({"anyOf": []})
    assert empty_union.errors is not None, "an empty union matches nothing and is refused at the write"

    wordless = await attempt({"anyOf": [{"assertionFilter": {"subjects": ["peter"]}}]})
    assert wordless.errors is not None, "a clause must name the words it derives from"

    unknown = await attempt({"anyOf": [{"assertedAs": ["Cell"], "tags": ["old"]}]})
    assert unknown.errors is not None, "an unknown key is an error, not a silent no-op"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_graph_definition_document_carries_meaning(api_schema: kante.Schema, simple_api_context: HttpContext, literal_graph: core_models.Graph, table_projector) -> None:
    """The whole view — words *and* what they mean — arrives as one schema.

    `createGraph`'s definition document declares a defined category inline, and
    `backfill` draws the history its clauses admit. No follow-up mutation, no
    Python: the definition input is part of `GraphDefinitionInput`.
    """
    peters, _ = await _claimed_cells(api_schema, simple_api_context, literal_graph)

    made = await api_schema.execute(
        """
        mutation G($input: CreateGraphInput!) {
            createGraph(input: $input) { id }
        }
        """,
        variable_values={
            "input": {
                "name": "peters-view",
                "backfill": True,
                "definition": {
                    "extensions": {
                        "entities": [
                            {"key": "PetersCell", "definition": {"anyOf": [{"assertedAs": ["Cell"], "assertionFilter": {"subjects": ["peter"]}}]}}
                        ]
                    }
                },
            }
        },
        context_value=simple_api_context,
    )
    assert made.errors is None, f"GraphQL errors: {made.errors}"
    graph_id = made.data["createGraph"]["id"]

    @sync_to_async
    def drawn():
        return drawing.refs_with_label(core_models.Graph.objects.get(pk=graph_id), "PetersCell")

    assert await drawn() == [peters], "one mutation: the schema declared the meaning and the backfill drew what it admits"
