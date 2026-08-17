"""An id a list query hands out must be one the singular fetcher accepts.

That was not true. The plural edge queries built a `RetrievedEdge` with no
`row_id`, so `unique_id` fell back to ``{graph_name}:{age_edge_id}`` — while
`relation(id:)` and its siblings resolve a `Link` primary key. The two halves of
the same surface disagreed about what an id is, and nothing tested the pair
together, so each looked fine on its own.

The `ids` **filter** had the mirror defect. It compared
`extract_graph_id(id)` against the graph's `age_name`; a uuid contains hyphens,
so that call returned the uuid's *first segment*, the comparison was never true,
and the filter silently answered "no matches" to ids the API had just issued.

And most of these queries could not return anything at all. `create_vertex` labels
a vertex with its category's `age_name` and writes exactly ``{id, category_id}``,
so the patterns they matched — `(:Entity)-[r]->(:NaturalEvent)` for participations,
`(m:Metric)-[r]->(s:Structure)` for descriptions — named labels the projector has
never written. Measurements and structure relations have no AGE edge at all. Only
`relations` was ever able to produce a row.

They read `evidence.Link` now (`api/queries/_edges.py`), which fixes both halves at
once: the id *is* the claim id, and the answer is the claim rather than the drawing.
"""

import uuid

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models

ASSERT_STRUCTURE = """
    mutation AssertStructureExists($input: AssertStructureExistsInput!) {
        assertStructureExists(input: $input) { structure { id } }
    }
"""

ASSERT_ENTITY = """
    mutation AssertEntityExists($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { instance { id } }
    }
"""

ASSERT_RELATION = """
    mutation AssertRelationExists($input: AssertRelationExistsInput!) {
        assertRelationExists(input: $input) { link { id } }
    }
"""

LIST_RELATIONS = """
    query Relations($category: ID!, $ids: [GraphID!]) {
        relations(relationCategoryId: $category, filters: {ids: $ids}) {
            __typename
            id
            source { id }
            target { id }
            assertion { id }
        }
    }
"""

GET_RELATION = """
    query Relation($id: GraphID!) {
        relation(id: $id) { __typename id }
    }
"""


async def _entity(api_schema: kante.Schema, ctx: HttpContext, term: str) -> str:
    result = await api_schema.execute(
        ASSERT_ENTITY,
        variable_values={"input": {"term": term, "supportingEvidence": []}},
        context_value=ctx,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["assertEntityExists"]["instance"]["id"]


async def _relation(api_schema: kante.Schema, ctx: HttpContext, term: str, source: str, target: str) -> str:
    result = await api_schema.execute(
        ASSERT_RELATION,
        variable_values={"input": {"term": term, "sourceId": source, "targetId": target}},
        context_value=ctx,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["assertRelationExists"]["link"]["id"]


@sync_to_async
def _relation_category(graph: core_models.Graph) -> tuple[str, str]:
    category = core_models.RelationCategory.objects.filter(graph=graph).first()
    assert category is not None, "The bio schema declares at least one relation category"
    return str(category.pk), str(category.key)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_listed_id_can_be_fetched_back(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The defect, stated as the thing it broke.

    `relations(...)` returned `{graph_name}:{age_edge_id}` and `relation(id:)`
    wanted a `Link` uuid, so no id from the list was usable anywhere else in the
    API.
    """
    category_id, term = await _relation_category(test_graph)
    source = await _entity(api_schema, simple_api_context, "AIS")
    target = await _entity(api_schema, simple_api_context, "AIS")
    written = await _relation(api_schema, simple_api_context, term, source, target)

    listed = await api_schema.execute(LIST_RELATIONS, variable_values={"category": category_id, "ids": None}, context_value=simple_api_context)
    assert listed.errors is None, f"GraphQL errors: {listed.errors}"
    rows = listed.data["relations"]

    assert [row["id"] for row in rows] == [written], "The list reports the claim's own id"
    assert rows[0]["__typename"] == "Relation"
    assert ":" not in rows[0]["id"], "A composite id would name a vertex a reproject reassigns"

    fetched = await api_schema.execute(GET_RELATION, variable_values={"id": rows[0]["id"]}, context_value=simple_api_context)
    assert fetched.errors is None, f"GraphQL errors: {fetched.errors}"
    assert fetched.data["relation"]["id"] == written


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_ids_filter_matches_the_ids_the_api_issued(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """It used to answer "no matches" to every one of them.

    `extract_graph_id` split a uuid on its first hyphen and returned the leading
    segment, which never equals a graph's `age_name` — so the branch collected no
    ids and returned `[]`. Silently: no error, just an empty list.
    """
    category_id, term = await _relation_category(test_graph)
    source = await _entity(api_schema, simple_api_context, "AIS")
    target = await _entity(api_schema, simple_api_context, "AIS")
    first = await _relation(api_schema, simple_api_context, term, source, target)
    second = await _relation(api_schema, simple_api_context, term, target, source)

    narrowed = await api_schema.execute(LIST_RELATIONS, variable_values={"category": category_id, "ids": [second]}, context_value=simple_api_context)
    assert narrowed.errors is None, f"GraphQL errors: {narrowed.errors}"

    assert [row["id"] for row in narrowed.data["relations"]] == [second]

    absent = await api_schema.execute(LIST_RELATIONS, variable_values={"category": category_id, "ids": [str(uuid.uuid4())]}, context_value=simple_api_context)
    assert absent.errors is None, f"GraphQL errors: {absent.errors}"
    assert absent.data["relations"] == [], "An id naming nothing is an empty result, not an error"
    assert first != second


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_listed_edge_carries_its_endpoints_and_provenance(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Reading the claim rather than the drawing is what makes these resolvable.

    An Apache AGE edge carries neither endpoint uuid nor an assertion — it is a
    projection, and `project_edges` merges every assertion of one proposition onto
    a single edge. So a Cypher-built edge could report `sourceId` only as another
    composite, and `assertion` not at all.
    """
    category_id, term = await _relation_category(test_graph)
    source = await _entity(api_schema, simple_api_context, "AIS")
    target = await _entity(api_schema, simple_api_context, "AIS")
    await _relation(api_schema, simple_api_context, term, source, target)

    listed = await api_schema.execute(LIST_RELATIONS, variable_values={"category": category_id, "ids": None}, context_value=simple_api_context)
    assert listed.errors is None, f"GraphQL errors: {listed.errors}"
    row = listed.data["relations"][0]

    assert row["source"]["id"] == source
    assert row["target"]["id"] == target
    assert row["assertion"]["id"], "Who claimed it — a projected edge could not say"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_property_filter_is_refused_rather_than_ignored(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`search` / `hasProperty` / `matches` filtered a projected edge's properties.

    A claim carries none — `project_edges` writes `category_id` and
    `__assertion_count` onto the *drawing*, and both are bookkeeping. Refusing
    says so; narrowing nothing and returning everything would look like an answer.
    """
    category_id, _ = await _relation_category(test_graph)

    result = await api_schema.execute(
        """
        query Filtered($category: ID!) {
            relations(relationCategoryId: $category, filters: {search: "anything"}) { id }
        }
        """,
        variable_values={"category": category_id},
        context_value=simple_api_context,
    )

    assert result.errors, "A filter that cannot be honoured must not silently pass"
