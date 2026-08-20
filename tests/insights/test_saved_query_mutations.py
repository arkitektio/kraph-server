"""Saving a table query as a plan, reading it back, and changing it.

The contract is the plan (`graph_engine/query_ir.py`): a client sends matches,
wheres and returns; it reads the same back under `plan`; and `query` — the
compiled Cypher — is read-only and deprecated. Raw Cypher is not accepted
anywhere. The eight other saved-query kinds that used to have create/update
mutations are gone: nothing could ever render one.
"""

import uuid

import kante
import pytest
from kante.context import HttpContext

from core import models as core_models

COLUMN = {"kind": "VALUE", "key": "node", "type": "string", "valueKind": "STRING"}
PLAN = {
    "matches": [{"title": "p0", "nodes": ["n"], "relations": []}],
    "wheres": [],
    "returns": [{"path": "p0", "node": "n", "alias": "node"}],
}


@pytest.fixture
def outsider_graph(db, backend_stack, test_graph: core_models.Graph) -> core_models.Graph:
    """A graph in an organization the test identity is not a member of."""
    from authentikate.models import Membership, Organization, User

    other, _ = Organization.objects.get_or_create(slug="a-rival-lab")
    stranger, _ = User.objects.get_or_create(username="stranger", sub="stranger-sub")
    membership, _ = Membership.objects.get_or_create(user=stranger, organization=other)
    return core_models.Graph.objects.create(name="rival_graph", user=stranger, membership=membership, organization=other)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_saved_query_is_a_plan_that_round_trips(api_schema: kante.Schema, simple_api_context: HttpContext, test_graph: core_models.Graph) -> None:
    key = f"q_{uuid.uuid4().hex[:8]}"
    created = await api_schema.execute(
        """
        mutation Create($input: CreateGraphTableQueryInput!) {
            createGraphTableQuery(input: $input) {
                id key label description legacy query
                plan { version matches { title nodes } returns { path node alias } wheres { property } columns { key } }
            }
        }
        """,
        variable_values={"input": {"graph": str(test_graph.id), "key": key, "name": "First name", "description": "First description", "plan": PLAN, "columnInput": [COLUMN]}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"createGraphTableQuery must work: {created.errors}"
    made = created.data["createGraphTableQuery"]
    assert made["key"] == key and made["label"] == "First name"
    assert made["legacy"] is False
    assert made["plan"]["version"] == 1
    assert made["plan"]["matches"][0]["nodes"] == ["n"]
    assert made["plan"]["returns"][0]["alias"] == "node"
    assert made["plan"]["columns"][0]["key"] == "node", "the columns ride with the plan"
    assert "MATCH" in made["query"] and "RETURN node" in made["query"], "`query` is the compiled form, read-only"

    listed = await api_schema.execute("query { graphTableQueries { id key plan { matches { title } } } }", context_value=simple_api_context)
    assert listed.errors is None, f"GraphQL errors: {listed.errors}"
    assert made["id"] in {row["id"] for row in listed.data["graphTableQueries"]}

    updated = await api_schema.execute(
        """
        mutation Update($input: UpdateGraphTableQueryInput!) {
            updateGraphTableQuery(input: $input) { id key label description plan { wheres { property operator } } }
        }
        """,
        variable_values={"input": {"id": made["id"], "name": "Second name", "plan": {**PLAN, "wheres": [{"path": "p0", "node": "n", "property": "type", "operator": "EQUALS", "value": "ENTITY"}]}}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"updateGraphTableQuery must work: {updated.errors}"
    changed = updated.data["updateGraphTableQuery"]
    assert changed["id"] == made["id"] and changed["label"] == "Second name" and changed["key"] == key
    assert changed["description"] == "First description", "A field omitted from an update means 'unchanged', not 'blank it'"
    assert changed["plan"]["wheres"][0]["property"] == "type"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_raw_cypher_is_not_an_input(api_schema: kante.Schema, simple_api_context: HttpContext, test_graph: core_models.Graph) -> None:
    result = await api_schema.execute(
        "mutation Create($input: CreateGraphTableQueryInput!) { createGraphTableQuery(input: $input) { id } }",
        variable_values={"input": {"graph": str(test_graph.id), "key": "raw", "query": "MATCH (n) RETURN n", "plan": PLAN}},
        context_value=simple_api_context,
    )
    assert result.errors, "`query` is not a field of the input any more"
    assert "query" in str(result.errors[0])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_plan_that_cannot_compile_is_refused_at_save_time(api_schema: kante.Schema, simple_api_context: HttpContext, test_graph: core_models.Graph) -> None:
    result = await api_schema.execute(
        "mutation Create($input: CreateGraphTableQueryInput!) { createGraphTableQuery(input: $input) { id } }",
        variable_values={"input": {"graph": str(test_graph.id), "key": "bad", "plan": {"matches": [{"title": "p0", "nodes": ["n"], "relations": []}], "returns": [{"path": "nope", "node": "x"}]}}},
        context_value=simple_api_context,
    )
    assert result.errors
    assert "Unknown path/node reference" in str(result.errors[0])
    assert not await core_models.GraphTableQuery.objects.filter(graph=test_graph, key="bad").aexists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_saved_query_defaults_its_label_to_its_key(api_schema: kante.Schema, simple_api_context: HttpContext, test_graph: core_models.Graph) -> None:
    key = f"q_{uuid.uuid4().hex[:8]}"
    result = await api_schema.execute(
        "mutation Create($input: CreateGraphTableQueryInput!) { createGraphTableQuery(input: $input) { id key label } }",
        variable_values={"input": {"graph": str(test_graph.id), "key": key, "plan": PLAN}},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["createGraphTableQuery"]["label"] == key


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_saved_query_cannot_be_created_in_another_tenants_graph(api_schema: kante.Schema, simple_api_context: HttpContext, outsider_graph: core_models.Graph) -> None:
    result = await api_schema.execute(
        "mutation Create($input: CreateGraphTableQueryInput!) { createGraphTableQuery(input: $input) { id } }",
        variable_values={"input": {"graph": str(outsider_graph.id), "key": f"q_{uuid.uuid4().hex[:8]}", "plan": PLAN, "columnInput": [COLUMN]}},
        context_value=simple_api_context,
    )
    assert result.errors, "Saving a query into another tenant's graph must be refused"
    assert not await core_models.GraphTableQuery.objects.filter(graph=outsider_graph).aexists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_legacy_row_reads_back_as_legacy(api_schema: kante.Schema, simple_api_context: HttpContext, test_graph: core_models.Graph) -> None:
    """A row saved as raw Cypher before plans existed: no plan, `legacy` true, `query` is the stored string."""
    row = await core_models.GraphTableQuery.objects.acreate(graph=test_graph, key="legacy_row", label="Legacy", query="RETURN 1 AS value", columns=[])
    result = await api_schema.execute("query($id: ID!) { graphTableQuery(id: $id) { legacy plan { version } query } }", variable_values={"id": str(row.pk)}, context_value=simple_api_context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    got = result.data["graphTableQuery"]
    assert got["legacy"] is True and got["plan"] is None and got["query"] == "RETURN 1 AS value"
