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
from tests.support import claims, drawing, rules, writes

CREATE_CATEGORY = """
    mutation C($input: CreateEntityCategoryInput!) {
        createEntityCategory(input: $input) { id key definition { rules { when { field operator value } } } }
    }
"""

UPDATE_CATEGORY = """
    mutation U($input: UpdateEntityCategoryInput!) {
        updateEntityCategory(input: $input) { id definition { rules { when { field operator value } } } }
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
                "definition": rules.definition(rules.rule(rules.word("Cell"), rules.by("peter"))),
                "backfill": True,
            }
        },
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    assert {"field": "WORD", "operator": "IS", "value": "Cell"} in created.data["createEntityCategory"]["definition"]["rules"][0]["when"], "the meaning reads back from the same mutation"

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
        variable_values={"input": {"graph": graph_id, "key": "TheCells", "definition": rules.definition(rules.rule(rules.word("Cell"), rules.by("peter"))), "backfill": True}},
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
        variable_values={"input": {"id": category_id, "definition": rules.definition(rules.rule(rules.word("Cell"), rules.by("karl")))}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"
    assert {"field": "SUBJECT", "operator": "IS", "value": "karl"} in updated.data["updateEntityCategory"]["definition"]["rules"][0]["when"]

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

    empty_union = await attempt({"rules": []})
    assert empty_union.errors is not None, "an empty rule list matches nothing and is refused at the write"

    wordless = await attempt(rules.definition(rules.rule(rules.by("peter"))))
    assert wordless.errors is not None, "a rule must name the word(s) it derives from"

    empty_rule = await attempt({"rules": [{"when": []}]})
    assert empty_rule.errors is not None, "a rule needs at least one condition"

    unknown = await attempt({"rules": [{"when": [rules.word("Cell")], "tags": ["old"]}]})
    assert unknown.errors is not None, "an unknown key is an error, not a silent no-op"

    bad_operator = await attempt(rules.definition(rules.rule(rules.condition("SUBJECT", "BEFORE", "peter"))))
    assert bad_operator.errors is not None, "a time operator on an identity field is refused by name"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_graph_definition_document_carries_meaning(api_schema: kante.Schema, simple_api_context: HttpContext, literal_graph: core_models.Graph, table_projector) -> None:
    """The whole view — words *and* what they mean — arrives as one schema.

    `createGraph`'s definition document declares a defined category inline, and
    `backfill` draws the history its rules admit. No follow-up mutation, no
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
                            {"key": "PetersCell", "definition": rules.definition(rules.rule(rules.word("Cell"), rules.by("peter")))}
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
