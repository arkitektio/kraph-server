"""A write returns the claim it recorded, and the claim can answer.

The payload used to hand back an `Entity` — a drawing shape — for something that may
be drawn nowhere. Two of its fields could not answer in that case at all:
`schemaVersion` is non-null in the SDL and a row-backed reading has no value for it,
and `richProperties` asserted on a category that a claim under an undeclared word
does not have. Both were reachable through the mutation the moment a client selected
them, and through `entity(id:, graph:)` for a node the view admits but has not
drawn yet.

So the payload is `assertion` + `instance` (or `link`) + `drawings` now, and these
tests pin the three things that shape has to get right: the claim answers about
itself, its standing is readable, and the drawing stays where it belongs.
"""

import pytest
import kante
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from tests import writes

ASSERT_ENTITY = """
    mutation AssertEntityExists($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) {
            assertion { id seq subject }
            instance {
                id
                kind
                term { key kind }
                createdAt
                standings { stands at assertion { id } }
                drawnIn { graph { id } category { id } }
            }
            drawings { graph { id } category { id } node { id } }
        }
    }
"""

ATTEST_ENTITY = """
    mutation AttestEntity($input: AttestEntityInput!) {
        attestEntity(input: $input) {
            instance { id standings { stands at } }
            drawings { graph { id } }
        }
    }
"""

RETRACT_ENTITY = """
    mutation RetractEntity($input: RetractEntityInput!) {
        retractEntity(input: $input) {
            assertion { id }
            instance { id standings { stands } }
            drawings { graph { id } }
        }
    }
"""

READ_INSTANCE = """
    query ReadInstance($id: GraphID!) {
        instance(id: $id) { id kind term { key } standings { stands } }
    }
"""

READ_ENTITY = """
    query ReadEntity($id: GraphID!, $graph: ID!) {
        entity(id: $id, graph: $graph) { id schemaVersion richProperties { key } drawnIn { graph { id } } }
    }
"""

ASSERT_RELATION = """
    mutation AssertRelation($input: AssertRelationExistsInput!) {
        assertRelationExists(input: $input) {
            link {
                id
                kind
                term { key }
                sourceRef
                targetRef
                source { ... on Instance { id kind } }
                target { ... on Instance { id kind } }
            }
            drawings { graph { id } }
        }
    }
"""

CLASSIFY = """
    mutation ClassifyNodes($input: ClassifyNodesInput!) {
        classifyNodes(input: $input) {
            instances { id kind }
            assertion { id }
        }
    }
"""

READ_LINK = """
    query ReadLink($id: GraphID!) {
        link(id: $id) { id kind target { ... on Term { key } ... on Instance { id } } }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_payload_answers_about_the_claim(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Every field of the new shape resolves, including the ones that used to fail.

    Selecting the whole payload in one document is the point: the two defects this
    replaces were both *selection*-triggered, so a test that asks for `id` alone would
    have stayed green through either of them.
    """
    category = await test_graph.aget_entity_def("AIS")

    result = await api_schema.execute(
        ASSERT_ENTITY,
        variable_values={"input": {"term": category.key}},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    payload = result.data["assertEntityExists"]
    claim = payload["instance"]

    assert claim["id"], "The identity a client holds afterwards"
    assert claim["kind"] == "ENTITY", "What sort of individual it is — a fact about the claim"
    assert claim["term"]["key"] == "AIS", "and the word it was claimed under, which is not a label"
    assert claim["term"]["kind"] == "ENTITY"
    assert claim["createdAt"]

    assert claim["standings"] == [], "Nobody has disputed it, and asserting existence records no *position* on it — the claim is the assertion. Silence is not dissent"

    assert payload["assertion"]["id"] and payload["assertion"]["seq"], "The act, addressable and ordered"
    assert payload["drawings"], "The view declaring AIS drew it"
    assert payload["drawings"][0]["node"]["id"] == claim["id"], "and the drawing is of this claim"
    assert [entry["graph"]["id"] for entry in claim["drawnIn"]] == [entry["graph"]["id"] for entry in payload["drawings"]], "`drawnIn` on the claim and `drawings` on the act are the same question, asked of the claim and of the act"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_retraction_shows_up_as_a_standing(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """ "Does it still hold" is answerable from the claim, and disagreement is visible.

    The positions are reported and the folding is left to the reader, because for an
    instance there is no organization-wide answer to fold to: a graph's selector
    decides whose claims it count, so whether a *view* holds it is `drawings`. That is
    why there is no `stands` field beside this list.
    """
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS")

    retracted = await api_schema.execute(
        RETRACT_ENTITY,
        variable_values={"input": {"id": entity_id}},
        context_value=simple_api_context,
    )

    assert retracted.errors is None, f"GraphQL errors: {retracted.errors}"
    payload = retracted.data["retractEntity"]

    assert [row["stands"] for row in payload["instance"]["standings"]] == [False], "The retraction is on the record, newest first, with its own assertion"
    assert payload["drawings"] == [], "No view draws it any more"

    read = await api_schema.execute(READ_INSTANCE, variable_values={"id": entity_id}, context_value=simple_api_context)
    assert read.errors is None, f"GraphQL errors: {read.errors}"
    assert [row["stands"] for row in read.data["instance"]["standings"]] == [False], "and the same answer is readable afterwards, without the write"
    assert read.data["instance"]["term"]["key"] == "AIS", "The claim outlives the drawing it lost"

    # **Then attest it again.** Both positions stay on the record and the newest is
    # first, by `(at, assertion.seq)` — there is no "reinstate" operation, only more
    # evidence, so the order is the whole answer.
    attested = await api_schema.execute(
        ATTEST_ENTITY,
        variable_values={"input": {"id": entity_id}},
        context_value=simple_api_context,
    )
    assert attested.errors is None, f"GraphQL errors: {attested.errors}"
    claim = attested.data["attestEntity"]["instance"]

    assert [row["stands"] for row in claim["standings"]] == [True, False], "Newest first: it holds again, and the retraction is still on the record"
    assert attested.data["attestEntity"]["drawings"], "and the view that admits the word draws it again"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_reading_an_undrawn_claim_as_an_entity_does_not_fail(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """`schemaVersion` is null and `richProperties` is empty, rather than an error.

    Both are properties of a *derivation*, and nothing derived anything here: the
    view admits the node but its projection has not drawn it — the vertex is
    deleted directly, which is what a projection lagging the log looks like.
    `schemaVersion` was `String!` over a value only a projection supplies, and
    `richProperties` opened with `assert category_id is not None`.

    This used to reach the row-backed shape through a *retracted* claim, back when
    `entity(id:)` took no graph and answered from whichever view came first. A
    view read is refused for a node the view does not hold now — that case is
    pinned in `tests/instance/test_entity.py` — so the undrawn shape is produced
    the way `nodes(graph:)` meets it: admitted, not yet drawn.
    """
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS")
    category = await test_graph.aget_entity_def("AIS")

    @sync_to_async
    def undraw() -> int:
        age_engine.execute(test_graph, f"MATCH (e:{category.age_name}) WHERE e.id = $eid DETACH DELETE e", {"eid": entity_id})
        rows = age_engine.execute(test_graph, f"MATCH (e:{category.age_name}) WHERE e.id = $eid RETURN count(e) as c", {"eid": entity_id})
        return int(rows[0]["c"]) if rows else 0

    assert await undraw() == 0, "The vertex is gone, and no claim was withdrawn"

    read = await api_schema.execute(READ_ENTITY, variable_values={"id": entity_id, "graph": str(test_graph.id)}, context_value=simple_api_context)

    assert read.errors is None, f"GraphQL errors: {read.errors}"
    entity = read.data["entity"]
    assert entity["id"] == entity_id
    assert entity["schemaVersion"] is None, "No view derived anything, so there is no schema version to name"
    assert entity["richProperties"] == [], "and no category, so nothing to explain"
    assert entity["drawnIn"] == [], "which is the same thing said as a count"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_links_endpoints_resolve_by_kind(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Both ends of a relation claim resolve, and the refs stay opaque beside them.

    Dispatched on `kind` and never on the ref: every ref is a bare uuid, so nothing
    about one says which of the four tables it names.
    """
    source = await writes.create_entity(api_schema, simple_api_context, "Cell")
    target = await writes.create_entity(api_schema, simple_api_context, "Cell")

    created = await api_schema.execute(
        ASSERT_RELATION,
        variable_values={"input": {"term": "IS_CONNECTED_TO", "sourceId": source, "targetId": target, "supportingEvidence": []}},
        context_value=simple_api_context,
    )

    assert created.errors is None, f"GraphQL errors: {created.errors}"
    link = created.data["assertRelationExists"]["link"]

    assert link["kind"] == "RELATION"
    assert link["term"]["key"] == "IS_CONNECTED_TO"
    assert (link["sourceRef"], link["targetRef"]) == (source, target), "The refs as the log holds them"
    assert link["source"]["id"] == source and link["source"]["kind"] == "ENTITY", "resolved as instances, because that is what a relation relates"
    assert link["target"]["id"] == target


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_classification_targets_a_word(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The one kind whose target is not a claim at all.

    A classification runs instance → word, which is what lets every view declaring
    that word read it. The union is how the payload says so without a per-kind type.
    """
    entity_id = await writes.create_entity(api_schema, simple_api_context, "Cell")

    classified = await api_schema.execute(
        CLASSIFY,
        variable_values={"input": {"classifications": [{"node": entity_id, "term": "AIS"}]}},
        context_value=simple_api_context,
    )
    assert classified.errors is None, f"GraphQL errors: {classified.errors}"
    assert classified.data["classifyNodes"]["instances"][0]["kind"] == "ENTITY", "A batch reports each claim's own kind"

    @sync_to_async
    def classification_id() -> str:
        from evidence import models as evidence_models

        link = evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=entity_id, term__key="AIS").first()
        assert link is not None
        return str(link.pk)

    read = await api_schema.execute(READ_LINK, variable_values={"id": await classification_id()}, context_value=simple_api_context)

    assert read.errors is None, f"GraphQL errors: {read.errors}"
    assert read.data["link"]["kind"] == "CLASSIFIES"
    assert read.data["link"]["target"]["key"] == "AIS", "The target is the word, not a node"


RETRACT_LINKS = """
    mutation RetractLinks($input: RetractLinksInput!) {
        retractLinks(input: $input) {
            links { id kind standings { stands } }
        }
    }
"""

ASSERT_RELATION_WITH_EVIDENCE = """
    mutation AssertRelation($input: AssertRelationExistsInput!) {
        assertRelationExists(input: $input) {
            link { id kind standings { stands } drawnIn { graph { id } edge { __typename } } }
        }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_link_claim_reports_its_drawing_and_its_standing(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """A relation is one of the three kinds a view actually draws, so `drawnIn` is not empty.

    A link's standing is organization-grain, unlike an instance's — a retracted link is
    retracted everywhere, which is why `CurrentStanding` caches an answer for one — but
    it is still reported as the positions rather than as a folded boolean, so there is
    one way to ask across both kinds of claim.
    """
    source = await writes.create_entity(api_schema, simple_api_context, "Cell")
    target = await writes.create_entity(api_schema, simple_api_context, "Cell")

    created = await api_schema.execute(
        ASSERT_RELATION_WITH_EVIDENCE,
        variable_values={"input": {"term": "IS_CONNECTED_TO", "sourceId": source, "targetId": target, "supportingEvidence": []}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    link = created.data["assertRelationExists"]["link"]

    assert link["standings"] == [], "Nobody has disputed the claim"
    assert link["drawnIn"], "The view declaring IS_CONNECTED_TO drew the edge"
    assert link["drawnIn"][0]["edge"]["__typename"] == "Relation", "and the drawing is an edge, which is what a graph has"

    retracted = await api_schema.execute(
        RETRACT_LINKS,
        variable_values={"input": {"ids": [link["id"]]}},
        context_value=simple_api_context,
    )
    assert retracted.errors is None, f"GraphQL errors: {retracted.errors}"
    withdrawn = retracted.data["retractLinks"]["links"][0]

    assert withdrawn["kind"] == "RELATION"
    assert [row["stands"] for row in withdrawn["standings"]] == [False], "The retraction is the newest position on the claim"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_evidence_can_inform_a_claim_rather_than_a_node(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The `INFORMS` fallback: a ref that names another claim, not an instance.

    Structures justifying "these two cells are connected" inform the **relation**, so
    `_attach_supporting_evidence` writes the INFORMS link against the edge's own ref.
    That is the one endpoint whose table `kind` alone cannot decide, so
    `_resolve_claim_endpoint` tries an instance and then a link — and this is the only
    test that reaches the second try.
    """
    source = await writes.create_entity(api_schema, simple_api_context, "Cell")
    target = await writes.create_entity(api_schema, simple_api_context, "Cell")

    created = await api_schema.execute(
        ASSERT_RELATION,
        variable_values={
            "input": {
                "term": "IS_CONNECTED_TO",
                "sourceId": source,
                "targetId": target,
                "supportingEvidence": [{"identifier": "@mikro/roi", "object": "roi-informs-an-edge", "metrics": [{"key": "vector_length", "value": 7.0, "valueKind": "FLOAT"}]}],
            }
        },
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    relation_id = created.data["assertRelationExists"]["link"]["id"]

    @sync_to_async
    def informs_id() -> str:
        from evidence import models as evidence_models

        link = evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.INFORMS, target_ref=relation_id).first()
        assert link is not None, "The supporting structure informs the relation, not either endpoint"
        return str(link.pk)

    read = await api_schema.execute(
        """
        query ReadInforms($id: GraphID!) {
            link(id: $id) {
                kind
                source { ... on Structure { id identifier } }
                target { ... on Link { id kind } ... on Instance { id } }
            }
        }
        """,
        variable_values={"id": await informs_id()},
        context_value=simple_api_context,
    )

    assert read.errors is None, f"GraphQL errors: {read.errors}"
    informs = read.data["link"]
    assert informs["kind"] == "INFORMS"
    assert informs["source"]["identifier"] == "@mikro/roi", "The structure that justifies the claim"
    assert informs["target"]["id"] == relation_id, "and the claim it justifies, which is a link rather than a node"
    assert informs["target"]["kind"] == "RELATION"
