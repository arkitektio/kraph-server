"""An id a list query hands out is one the singular fetcher accepts (C4).

Edge list queries read `evidence.Link`, so the id *is* the claim id and the
answer is the claim; the `ids` filter accepts what the list issued.

History: the plural queries built ids from a drawn edge id that a reproject
reassigns, five of six matched labels the projector never wrote, and the `ids`
filter compared a uuid's first segment to the view's handle.
"""

import uuid
import kante
import pytest
from evidence import models as evidence_models
from asgiref.sync import sync_to_async
from kante.context import HttpContext
from core import models as core_models
from tests.support import reads, writes


LIST_RELATIONS = """
    query Relations($category: ID!, $ids: [ID!]) {
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
    query Relation($id: ID!) {
        relation(id: $id) { __typename id }
    }
"""


async def _entity(api_schema: kante.Schema, ctx: HttpContext, term: str) -> str:
    result = await api_schema.execute(
        writes.ASSERT_ENTITY_EXISTS,
        variable_values={"input": {"term": term, "supportingEvidence": []}},
        context_value=ctx,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["assertEntityExists"]["instance"]["id"]


async def _relation(api_schema: kante.Schema, ctx: HttpContext, term: str, source: str, target: str) -> str:
    result = await api_schema.execute(
        writes.ASSERT_RELATION_EXISTS,
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

    A drawn edge carries neither endpoint uuid nor an assertion — it is a
    projection, and `project_edges` merges every assertion of one proposition onto
    a single edge. So an edge built from the drawing could report `sourceId` only
    as another composite, and `assertion` not at all.
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
    `__assertion_count` onto the *drawing*, and both are bookkeeping. The fields
    are gone from the edge filter inputs now, so the refusal is GraphQL
    validation — the schema no longer advertises a question the resolvers
    always refused at runtime.
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_edge_can_be_read_back_by_the_id_it_was_given(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The id `createRelation` hands out is the id `relation(id:)` accepts.

    It was not. `RetrievedEdge.unique_id` returns the `Link` primary key for any
    row-backed edge — every relation, measurement and structure relation — and the
    resolver split that id on the first hyphen to recover a graph name and an
    integer drawn edge id. On a uuid that produced
    `invalid literal for int() with base 10: '2269-48bc-b049-53535f3be517'`, on the
    very identity the mutation had just returned.

    It was never fixable by parsing more carefully: a drawn edge carries no claim
    id, because `project_edges` merges every assertion of one proposition onto one
    edge. The claim's identity lives in Postgres, so the read has to go there.
    """
    source = await writes.create_entity(api_schema, simple_api_context, "Cell")
    target = await writes.create_entity(api_schema, simple_api_context, "Cell")
    relation_id = await writes.create_relation(api_schema, simple_api_context, "IS_CONNECTED_TO", source, target)

    result = await api_schema.execute(reads.RELATION, variable_values={"id": relation_id}, context_value=simple_api_context)

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["relation"]["id"] == relation_id, "The claim reads back as itself"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_edge_no_view_draws_is_labelled_by_its_kind(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """C4: a relation under a word no view declares is a claim with no drawing.
    Read back as an edge it carries the claim's kind as its label, because there
    is no category to have named it."""
    a = await writes.create_entity(api_schema, simple_api_context, "Cell")
    b = await writes.create_entity(api_schema, simple_api_context, "Cell")
    link = await writes.create_relation(api_schema, simple_api_context, f"touches_nobody_{uuid.uuid4().hex[:6]}", a, b)

    read = (await writes.execute(api_schema, simple_api_context, "query R($id: ID!) { relation(id: $id) { id label } }", {"id": link}))["relation"]
    assert read["id"] == link
    assert read["label"] == evidence_models.Link.Kind.RELATION.value, "no view named it, so the label is the kind"
