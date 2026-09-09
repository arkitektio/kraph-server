"""A saved query is a plan (C7).

The contract is `graph_engine/query_ir.py`: a client sends matches, wheres and
returns, reads the same back under `plan`, and the projector renders it. Raw
query text is not accepted anywhere. Product state, inert to the log.
"""

import uuid
import kante
import pytest
from kante.context import HttpContext
from core import models as core_models
from graph_engine import input_models
from graph_engine.projection.table import TableProjector, compile_table_plan_sql
from graph_engine.query_ir import TableQueryPlan
from tests.support import writes


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
                id key label description legacy
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
    """A row saved as raw Cypher before plans existed: no plan, `legacy` true — and no `query` field to read it back, since no projection kind executes Cypher."""
    row = await core_models.GraphTableQuery.objects.acreate(graph=test_graph, key="legacy_row", label="Legacy", query="RETURN 1 AS value", columns=[])
    result = await api_schema.execute("query($id: ID!) { graphTableQuery(id: $id) { legacy plan { version } } }", variable_values={"id": str(row.pk)}, context_value=simple_api_context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    got = result.data["graphTableQuery"]
    assert got["legacy"] is True and got["plan"] is None


def _compile(plan, **kwargs):
    return compile_table_plan_sql(TableProjector(), plan, **kwargs)


def test_compile_table_plan_is_structural_and_parameterized() -> None:
    plan = TableQueryPlan(
        matches=[input_models.MatchPathInput(title="p0", nodes=["Entity", "Structure"], relations=["HAS_STRUCTURE"], relation_directions=[True], node_categories=["AIS", None])],
        wheres=[input_models.WhereClauseInput(path="p0", node="Entity", property="kind", operator=input_models.WhereOperator.EQUALS, value="AIS")],
        returns=[input_models.ReturnStatementInput(path="p0", node="Entity", property="name", alias="entity_name"), input_models.ReturnStatementInput(path="p0", node="Structure")],
    )
    sql, params = _compile(plan)
    # The path is one GRAPH_TABLE over the graph's property graph: the pattern
    # carries the labels as quoted identifiers (SQL/PGQ labels cannot be bound)
    # and the direction as the arrow.
    assert "GRAPH_TABLE" in sql
    assert '(p0_Entity IS "AIS")-[IS "HAS_STRUCTURE"]->(p0_Structure)' in sql
    assert 'AS "entity_name"' in sql
    assert 'AS "p0_Structure_1"' in sql
    # Every *value* is a parameter, never text — only labels are identifiers,
    # quoted whole so a label cannot smuggle syntax.
    assert '"AIS"' in sql and '"HAS_STRUCTURE"' in sql
    assert params["v_w0"] == '"AIS"', "the comparison value is jsonb-encoded and bound"


@pytest.mark.django_db(transaction=True)
def test_compile_table_plan_with_a_graph_refuses_an_undeclared_label(test_graph, table_projector) -> None:
    plan = TableQueryPlan(
        matches=[input_models.MatchPathInput(title="p0", nodes=["n"], relations=[], node_categories=["NotAWord"])],
        returns=[input_models.ReturnStatementInput(path="p0", node="n")],
    )
    with pytest.raises(ValueError, match="NotAWord"):
        _compile(plan, graph=test_graph)
    # And with the graph in scope, a declared label resolves and lands in the
    # pattern against that graph's namespace.
    good = TableQueryPlan(
        matches=[input_models.MatchPathInput(title="p0", nodes=["n"], relations=[], node_categories=["AIS"])],
        returns=[input_models.ReturnStatementInput(path="p0", node="n")],
    )
    sql, _ = _compile(good, graph=test_graph)
    assert f'"{test_graph.age_name}".graph' in sql
    assert '(p0_n IS "AIS")' in sql


def test_compile_table_plan_filters_on_a_returned_alias_and_pages() -> None:
    plan = TableQueryPlan(matches=[input_models.MatchPathInput(title="p", nodes=["n"], relations=[])], returns=[input_models.ReturnStatementInput(path="p", node="n", property="avg_length", alias="length")])
    sql, params = _compile(
        plan,
        filters=input_models.RenderGraphTableFilter(key="length", operator=input_models.WhereOperator.GREATER_THAN, value=10),
        order=input_models.RenderGraphTableOrder(key="length", direction="desc"),
        pagination=input_models.RenderGraphTablePagination(limit=5, offset=10),
    )
    # The render filter lands on the returned alias, outside the compiled body,
    # so it sees exactly what the client sees.
    assert 'WHERE _t."length"' in sql
    assert 'ORDER BY "length" DESC' in sql
    assert params["v_f"] == "10", "the filter value is jsonb-encoded and bound"
    assert params["page_limit"] == 5 and params["page_offset"] == 10
    with pytest.raises(ValueError, match="not a returned alias"):
        _compile(plan, filters=input_models.RenderGraphTableFilter(key="nope", value=1))


def test_compile_table_plan_refuses_an_unsafe_property_key() -> None:
    plan = TableQueryPlan(matches=[input_models.MatchPathInput(title="p", nodes=["n"], relations=[])], wheres=[input_models.WhereClauseInput(path="p", node="n", property="x; DROP", operator=input_models.WhereOperator.EQUALS, value=1)])
    with pytest.raises(ValueError, match="Invalid property key"):
        _compile(plan)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_graph_table_query_through_builder_stores_the_plan(api_schema: kante.Schema, simple_api_context: HttpContext, test_graph: core_models.Graph):
    mutation = """
        mutation CreateGraphTableQueryThroughBuilder($input: CreateGraphTableQueryThroughBuilderInput!) {
            createGraphTableQueryThroughBuilder(input: $input) { id legacy plan { matches { title } wheres { property } returns { property } columns { key } } }
        }
    """
    variables = {
        "input": {
            "graph": str(test_graph.id),
            "key": "ais_table",
            "name": "AIS Table",
            "description": "Built via mutation",
            "columnInput": [{"kind": "VALUE", "key": "entity_name", "type": "string", "valueKind": "STRING"}],
            "builderArgs": {
                "matchPaths": [{"title": "p0", "nodes": ["Entity", "Structure"], "relations": ["HAS_STRUCTURE"], "relationDirections": [True]}],
                "whereClauses": [{"path": "p0", "node": "Entity", "property": "kind", "operator": "EQUALS", "value": "AIS"}],
                "returnStatements": [{"path": "p0", "node": "Entity", "property": "name"}],
            },
        }
    }
    result = await api_schema.execute(mutation, variable_values=variables, context_value=simple_api_context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    payload = result.data["createGraphTableQueryThroughBuilder"]
    assert payload["legacy"] is False
    assert payload["plan"]["matches"][0]["title"] == "p0"
    assert payload["plan"]["wheres"][0]["property"] == "kind"
    assert payload["plan"]["returns"][0]["property"] == "name"
    assert payload["plan"]["columns"][0]["key"] == "entity_name"
    saved = await core_models.GraphTableQuery.objects.aget(graph=test_graph, key="ais_table")
    assert saved.query is None, "the builder stores a plan, not a compiled string"
    assert saved.plan["matches"][0]["title"] == "p0"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_and_render_graph_table_query_via_api(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    create_mutation = """
        mutation CreateGraphTableQueryThroughBuilder($input: CreateGraphTableQueryThroughBuilderInput!) {
            createGraphTableQueryThroughBuilder(input: $input) {
                id
            }
        }
    """

    create_result = await api_schema.execute(
        create_mutation,
        variable_values={
            "input": {
                "graph": str(test_graph.id),
                "key": "table_render_api_test",
                "name": "Table Render API Test",
                "columnInput": [
                    {
                        "kind": "VALUE",
                        "key": "node_value",
                        "type": "string",
                        "valueKind": "STRING",
                    }
                ],
                "builderArgs": {
                    "matchPaths": [
                        {
                            "title": "p0",
                            "nodes": ["n"],
                            "relations": [],
                        }
                    ],
                    "returnStatements": [
                        {
                            "path": "p0",
                            "node": "n",
                        }
                    ],
                },
            }
        },
        context_value=simple_api_context,
    )

    assert create_result.errors is None, f"GraphQL errors: {create_result.errors}"
    assert create_result.data is not None

    graph_query_id = create_result.data["createGraphTableQueryThroughBuilder"]["id"]

    render_query = """
        query RenderGraphTable($query: ID!) {
            renderGraphTable(query: $query) {
                graphName
                graph {
                    id
                }
                query {
                    id
                }
                rows
            }
        }
    """

    render_result = await api_schema.execute(
        render_query,
        variable_values={"query": graph_query_id},
        context_value=simple_api_context,
    )

    assert render_result.errors is None, f"GraphQL errors: {render_result.errors}"
    assert render_result.data is not None

    payload = render_result.data["renderGraphTable"]
    assert payload["graph"]["id"] == str(test_graph.id)
    assert payload["query"]["id"] == graph_query_id
    assert isinstance(payload["rows"], list)


def test_a_legacy_raw_cypher_row_is_refused(graph_controller, test_graph: core_models.Graph) -> None:
    graph_query = core_models.GraphTableQuery.objects.create(graph=test_graph, key="legacy_render", label="Legacy", query="RETURN 1 AS value", columns=[{"key": "value", "type": "integer", "value_kind": "INT"}])

    with pytest.raises(ValueError, match="legacy"):
        graph_controller.render_graph_table_query(graph_query)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_plan_renders_with_a_structural_filter_order_and_page(api_schema, simple_api_context, graph_controller, test_graph: core_models.Graph) -> None:
    from asgiref.sync import sync_to_async

    for value in (10.0, 30.0, 20.0):
        await writes.create_entity(api_schema, simple_api_context, "AIS", evidence=[{"identifier": "ROI", "object": f"roi-{value}", "metrics": [{"key": "vector_length", "value": value, "valueKind": "FLOAT"}]}])

    @sync_to_async
    def render():
        from graph_engine.query_ir import TableQueryPlan

        plan = TableQueryPlan(
            matches=[input_models.MatchPathInput(title="p", nodes=["ais"], relations=[], node_categories=["AIS"])],
            returns=[input_models.ReturnStatementInput(path="p", node="ais", property="avg_length", alias="length"), input_models.ReturnStatementInput(path="p", node="ais", property="id", alias="node_id")],
        )
        graph_query = core_models.GraphTableQuery.objects.create(graph=test_graph, key="lengths", label="Lengths", plan=plan.to_stored(), columns=[{"key": "length", "type": "float"}])
        everything = graph_controller.render_graph_table_query(graph_query, order=input_models.RenderGraphTableOrder(key="length", direction="desc"))
        filtered = graph_controller.render_graph_table_query(
            graph_query,
            filters=input_models.RenderGraphTableFilter(key="length", operator=input_models.WhereOperator.GREATER_THAN, value=15),
            order=input_models.RenderGraphTableOrder(key="length", direction="asc"),
            pagination=input_models.RenderGraphTablePagination(limit=1, offset=0),
        )
        return [row["length"] for row in everything.rows], [row["length"] for row in filtered.rows]

    everything, filtered = await render()
    assert everything == [30.0, 20.0, 10.0]
    assert filtered == [20.0], "the filter applies to the returned alias — the case the old regex splice could never do"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_relation_path_renders_through_the_namespace(api_schema, simple_api_context, graph_controller, test_graph: core_models.Graph) -> None:
    """A two-node path is one GRAPH_TABLE pattern with label dispatch."""
    from asgiref.sync import sync_to_async

    from tests.support import writes as writes_module

    cell_a = await writes_module.create_entity(api_schema, simple_api_context, "Cell")
    cell_b = await writes_module.create_entity(api_schema, simple_api_context, "Cell")
    await writes_module.create_relation(api_schema, simple_api_context, "IS_CONNECTED_TO", cell_a, cell_b)

    @sync_to_async
    def render():
        from graph_engine.query_ir import TableQueryPlan

        plan = TableQueryPlan(
            matches=[input_models.MatchPathInput(title="p", nodes=["a", "b"], relations=["IS_CONNECTED_TO"], relation_directions=[True], node_categories=["Cell", "Cell"])],
            returns=[input_models.ReturnStatementInput(path="p", node="a", property="id", alias="source_id"), input_models.ReturnStatementInput(path="p", node="b", property="id", alias="target_id")],
        )
        graph_query = core_models.GraphTableQuery.objects.create(graph=test_graph, key="connections", label="Connections", plan=plan.to_stored(), columns=[{"key": "source_id", "type": "string"}, {"key": "target_id", "type": "string"}])
        return graph_controller.render_graph_table_query(graph_query).rows

    rows = await render()
    assert [(row["source_id"], row["target_id"]) for row in rows] == [(cell_a, cell_b)], "the edge renders in its drawn direction, and only under its labels"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_optional_path_null_fills_like_optional_match(api_schema, simple_api_context, graph_controller, test_graph: core_models.Graph) -> None:
    """An optional path is a LEFT JOIN of its own GRAPH_TABLE: unmatched rows stay, with nulls."""
    from asgiref.sync import sync_to_async

    from tests.support import writes as writes_module

    await writes_module.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def render():
        from graph_engine.query_ir import TableQueryPlan

        plan = TableQueryPlan(
            matches=[
                input_models.MatchPathInput(title="p", nodes=["ais"], relations=[], node_categories=["AIS"]),
                input_models.MatchPathInput(title="q", nodes=["soma"], relations=[], node_categories=["Soma"], optional=True),
            ],
            returns=[input_models.ReturnStatementInput(path="p", node="ais", property="id", alias="ais_id"), input_models.ReturnStatementInput(path="q", node="soma", property="id", alias="soma_id")],
        )
        graph_query = core_models.GraphTableQuery.objects.create(graph=test_graph, key="optional", label="Optional", plan=plan.to_stored(), columns=[{"key": "ais_id", "type": "string"}, {"key": "soma_id", "type": "string"}])
        return graph_controller.render_graph_table_query(graph_query).rows

    rows = await render()
    assert len(rows) == 1
    assert rows[0]["ais_id"] is not None
    assert rows[0]["soma_id"] is None, "no Soma is drawn, so the optional path fills with null instead of dropping the row"
