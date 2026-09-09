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
from tests.support import drawing, writes
from evidence import models as evidence_models
from graph_engine import models as graph_engine_models
from graph_engine.controller import GraphController
from graph_engine.retrieved import RetrievedNode
from tests.support.writes import assert_entity as _assert_entity
from tests.support import rules
import uuid


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
    query ReadInstance($id: ID!) {
        instance(id: $id) { id kind term { key } standings { stands } }
    }
"""
READ_ENTITY = """
    query ReadEntity($id: ID!, $graph: ID!) {
        entity(id: $id, graph: $graph) { id graph { id } asOfSeq categoryIds richProperties { key value } drawnIn { graph { id } } }
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
    query ReadLink($id: ID!) {
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
async def test_reading_an_undrawn_claim_as_an_entity_does_not_fail(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """An admitted-but-undrawn node still names its view and its categories (RFC 0025).

    The view admits the node but its projection has not drawn it — the vertex is
    deleted directly, which is what a projection lagging the log looks like. The
    `Node` still knows its `graph` and answers `categoryIds` from the **rule**,
    not from the missing vertex; `richProperties` is empty because nothing was
    derived. (`schemaVersion` — a projection stamp on the node interface — is
    gone; `asOfSeq` is the view's cursor instead.)

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
        table_projector.erase_nodes(test_graph, [entity_id])
        return drawing.vertices_with_ref(test_graph, entity_id)

    assert await undraw() == 0, "The vertex is gone, and no claim was withdrawn"

    read = await api_schema.execute(READ_ENTITY, variable_values={"id": entity_id, "graph": str(test_graph.id)}, context_value=simple_api_context)

    assert read.errors is None, f"GraphQL errors: {read.errors}"
    entity = read.data["entity"]
    assert entity["id"] == entity_id
    assert entity["graph"]["id"] == str(test_graph.id), "a Node always names its view"
    assert entity["asOfSeq"] >= 0
    assert entity["categoryIds"] == [str(category.pk)], "the rule admits it, whether or not the cache has caught up"
    assert entity["richProperties"] and all(prop["value"] is None for prop in entity["richProperties"] if prop["key"] != "id"), "the rule's properties are listed; nothing was derived, so none has a value"
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
async def test_drawings_report_the_rules_category_not_the_vertex_stamp(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector) -> None:
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def stamp_and_read():
        # Corrupt the cache on purpose: the payload must not read it back. The
        # composite FK (RFC 0006) refuses an invented id, so the worst corruption
        # still expressible is a *declared but wrong* category of the same graph —
        # which is exactly the stale-vertex shape the original bug had.
        wrong = core_models.EntityCategory.objects.get(graph=test_graph, key="Cell")
        graph_engine_models.ProjectionLabel.objects.filter(graph=test_graph, vertex__ref=entity_id).update(category_pk=wrong.pk, label=wrong.age_name)
        node = evidence_models.Instance.objects.for_organization(test_graph.organization).select_related("term").get(pk=entity_id)
        drawings = GraphController(projector=table_projector).drawings_for_instance(node)
        rule = core_models.EntityCategory.objects.get(graph=test_graph, key="AIS")
        return [(drawing.graph.pk, drawing.category.pk) for drawing in drawings], rule.pk

    reported, rule_pk = await stamp_and_read()
    assert (test_graph.pk, rule_pk) in reported, f"the payload must name the rule's category, got {reported}"


@pytest.mark.django_db(transaction=True)
def test_two_undrawn_nodes_are_two_objects(test_graph: core_models.Graph, table_projector) -> None:
    from evidence import writer

    organization = test_graph.organization
    term = writer.ensure_term(organization, "ENTITY", "AIS")
    assertion = writer.create_assertion(organization, subject="t", app_id="tests", action_id=None, action_name=None, action_args={})
    rows = [evidence_models.Instance.objects.create_for_organization(organization=organization, kind=evidence_models.Instance.Kind.ENTITY, term=term, assertion=assertion) for _ in range(2)]
    controller = GraphController(projector=table_projector)
    nodes = [RetrievedNode.from_row(controller, row) for row in rows]
    assert len(set(nodes)) == 2
    assert nodes[0] != nodes[1]
    assert nodes[0] == RetrievedNode.from_row(controller, rows[0])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_write_reports_the_individuals_drawing(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """Asserting an entity `sameAs` an existing one returns the drawing of the individual, not of the observation alone."""
    a = (await _assert_entity(api_schema, simple_api_context, "AIS"))["instance"]["id"]
    result = await api_schema.execute(
        """
        mutation AssertEntityExists($input: AssertEntityExistsInput!) {
            assertEntityExists(input: $input) { instance { id } drawings { node { id members } } }
        }
        """,
        variable_values={"input": {"term": "AIS", "supportingEvidence": [], "sameAs": [a]}},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    payload = result.data["assertEntityExists"]
    b = payload["instance"]["id"]
    (drawn,) = payload["drawings"]
    assert drawn["node"]["id"] == min(a, b)
    assert sorted(drawn["node"]["members"]) == sorted([a, b])


CREATE_ENTITY = """
    mutation CreateEntity($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) {
            instance { id }
            drawings { category { id } node { id drawnLabels } }
        }
    }
"""
ENTITY = """
    query Entity($id: ID!, $graph: ID!) {
        entity(id: $id, graph: $graph) {
            id
            label
            drawnLabels
            categoryIds
            categories { id key }
            richProperties { key value }
        }
    }
"""


def _define(graph: core_models.Graph, key: str, definition: dict, properties: list[dict] | None = None) -> core_models.EntityCategory:
    """A defined entity category over the word AIS, created or redefined."""
    category, _ = core_models.EntityCategory.objects.get_or_create(graph=graph, key=key, defaults={"age_name": key.lower(), "label": key})
    category.age_name = key.lower()  # the fixture's AIS is labelled "AIS"; one spelling for every assertion below
    category.definition = definition
    if properties is not None:
        category.property_definitions = properties
    category.save()
    return category


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_write_reports_one_drawing_per_category(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """`drawings` lists the node once per (view, category) — that is what the
    field promises, and now it can be more than one entry for one view."""

    @sync_to_async
    def declare() -> set[str]:
        ais = _define(test_graph, "AIS", rules.definition(rules.rule(rules.word("AIS"))))
        excitatory = _define(test_graph, "Excitatory", rules.definition(rules.rule(rules.word("AIS"))))
        return {str(ais.pk), str(excitatory.pk)}

    category_ids = await declare()

    created = await api_schema.execute(CREATE_ENTITY, variable_values={"input": {"term": "AIS", "supportingEvidence": []}}, context_value=simple_api_context)
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    drawings = created.data["assertEntityExists"]["drawings"]
    assert {entry["category"]["id"] for entry in drawings} == category_ids
    assert all(sorted(entry["node"]["drawnLabels"]) == ["ais", "excitatory"] for entry in drawings)

    ref = created.data["assertEntityExists"]["instance"]["id"]
    read = await api_schema.execute(ENTITY, variable_values={"id": ref, "graph": str(test_graph.pk)}, context_value=simple_api_context)
    assert read.errors is None, f"GraphQL errors: {read.errors}"
    entity = read.data["entity"]
    assert entity["drawnLabels"] == ["ais", "excitatory"]
    assert entity["label"] == "ais", "the first label, for a client that shows one"
    assert set(entity["categoryIds"]) == category_ids
    assert {c["key"] for c in entity["categories"]} == {"AIS", "Excitatory"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_entity(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    """Create an entity through the GraphQL createEntity mutation."""
    entity_category = await test_graph.aget_entity_def("AIS")

    mutation = """
        mutation CreateEntity($input: AssertEntityExistsInput!) {
            assertEntityExists(input: $input) { instance { id kind term { key } } }
        }
    """

    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "term": entity_category.key,
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None, "No data returned from GraphQL execution"
    data = result.data["assertEntityExists"]["instance"]
    assert data["id"]
    # The **word** is `term.key`; `kind` says what sort of individual it is. They used
    # to be one field: `Entity.kind` returned the vertex label, which is the word as
    # one view renames it, so a claim and a drawing answered the same question
    # differently.
    assert data["term"]["key"] == "AIS"
    assert data["kind"] == "ENTITY"


ASSERT_ENTITY_WITH_DRAWINGS = """
    mutation AssertEntityExists($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) {
            assertion { id subject seq }
            instance { id kind term { key } }
            drawings {
                graph { id name }
                category { id key }
                node { id label }
            }
        }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_claim_no_view_declares_is_recorded_and_undrawn(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The write succeeds, the assertion is real, and nothing draws it.

    This is the case that used to raise — `create_entity` ended with
    `ValueError("... no category in {age_name} admits it")` *after* the claim was
    durably committed — and then, once it stopped raising, the case that returned
    a stranger's category.
    """
    word = f"Unlikely{uuid.uuid4().hex[:8]}"

    result = await api_schema.execute(
        ASSERT_ENTITY_WITH_DRAWINGS,
        variable_values={"input": {"term": word, "supportingEvidence": []}},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"A claim under an undeclared word must succeed: {result.errors}"
    payload = result.data["assertEntityExists"]

    assert payload["instance"]["id"], "The claim has a durable identity whether or not any view draws it"
    assert payload["instance"]["term"]["key"] == word, "And it names the word claimed, not a category's name"
    assert payload["drawings"] == [], "No view declares the word, so no view draws it"

    assert payload["assertion"]["id"], "The act itself is addressable"
    assert payload["assertion"]["seq"] is not None, "including its position in the log"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_claim_two_views_declare_reports_both_drawings(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    second_graph: core_models.Graph,
) -> None:
    """Two views declaring one word both draw the claim, and the result says so.

    The old return could only name one of them. Note the assertion is on the *set*
    of graphs rather than on ordering: which view is reported first is not a fact
    about the claim, and a test that pinned it would be pinning `order_by("pk")`.
    """
    from asgiref.sync import sync_to_async

    @sync_to_async
    def declared_word() -> str:
        """A word both graphs declare a category for."""
        for graph in (test_graph, second_graph):
            assert core_models.EntityCategory.objects.filter(graph=graph, key="AIS").exists(), f"{graph.name} must declare AIS"
        return "AIS"

    word = await declared_word()

    result = await api_schema.execute(
        ASSERT_ENTITY_WITH_DRAWINGS,
        variable_values={"input": {"term": word, "supportingEvidence": []}},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    payload = result.data["assertEntityExists"]

    drawn_in = {drawing["graph"]["id"] for drawing in payload["drawings"]}
    assert drawn_in == {str(test_graph.id), str(second_graph.id)}, f"Both views declaring the word must draw it, got {payload['drawings']}"

    for drawing in payload["drawings"]:
        assert drawing["category"]["key"] == word, "Each drawing reports the category *that view* drew it under"
        assert drawing["node"]["id"] == payload["instance"]["id"], "and the same node, seen from that view"


CREATE_ENTITY_FOR_PARTICIPATION = """
    mutation CreateEntity($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { instance { id } }
    }
"""


CREATE_NATURAL_EVENT = """
    mutation CreateNaturalEvent($input: AssertNaturalEventExistsInput!) {
        assertNaturalEventExists(input: $input) { instance { id } }
    }
"""


async def _cell(api_schema: kante.Schema, ctx: HttpContext, graph: core_models.Graph) -> str:
    category = await core_models.EntityCategory.objects.filter(graph=graph, key="Cell").afirst()
    assert category is not None
    created = await api_schema.execute(
        CREATE_ENTITY_FOR_PARTICIPATION,
        variable_values={"input": {"term": category.key, "supportingEvidence": []}},
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertEntityExists"]["instance"]["id"]


async def _mitosis(api_schema: kante.Schema, ctx: HttpContext, graph: core_models.Graph, source: str, target: str) -> str:
    category = await core_models.NaturalEventCategory.objects.filter(graph=graph, key="Mitosis").afirst()
    assert category is not None, "The bio schema declares a Mitosis event with Cell in and out"
    created = await api_schema.execute(
        CREATE_NATURAL_EVENT,
        variable_values={
            "input": {
                "term": category.key,
                "inputs": [{"role": "a", "entityId": source}],
                "outputs": [{"role": "b", "entityId": target}],
                "supportingEvidence": [],
            }
        },
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertNaturalEventExists"]["instance"]["id"]


def _participations(table_projector, graph: core_models.Graph) -> list[tuple[str, str]]:
    """Every projected participation edge, as (label, role).

    Two queries rather than one `UNION ALL`: AGE rejects the union with "column
    name 'label' specified more than once", and the point here is the edges, not
    the query.
    """
    found: list[tuple[str, str]] = []
    for label in ("WENT_THROUGH", "CAME_OUT_OF"):
        found.extend((label, str(role)) for role in drawing.edge_property_values(graph, label, "role"))
    return sorted(found)


ASSERT_PARTICIPATION = """
    mutation AssertParticipation($input: AssertParticipationInput!) {
        assertParticipation(input: $input) { link { id } }
    }
"""


ARCHIVE_PARTICIPATION = """
    mutation ArchiveParticipation($input: RetractParticipationInput!) {
        retractParticipation(input: $input) { link { id } }
    }
"""


def _assertion_count(table_projector, graph: core_models.Graph, label: str) -> list[int]:
    return sorted(int(count) for count in drawing.edge_property_values(graph, label, "__assertion_count"))


ASSERT_PARTICIPATION = """
    mutation AssertParticipation($input: AssertParticipationInput!) {
        assertParticipation(input: $input) {
            link { kind id }
            drawings { graph { id } category { id } edge { __typename id } }
        }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("is_input", [True, False], ids=["input", "output"])
async def test_a_participation_reports_the_view_that_drew_it(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
    is_input: bool,
) -> None:
    """Both sides of a participation must be findable, and this is the test that says so.

    **The failure this exists to catch is silent.** Reading a drawing back asks
    AGE for the edge, and the reader used to build that pattern itself, wrongly
    in two ways at once:

    - it matched `[r:{category.age_name}]`, but a participation's label is not the
      category's `age_name` — it is `AGE_INPUT_EDGE` / `AGE_OUTPUT_EDGE` off the
      *event's* category;
    - it matched `(source)-[r]->(target)`, but `participation_key` stores the
      entity as source and the event as target on **both** sides, while an output
      participation is drawn event → entity.

    Neither mistake raises. `MATCH` simply finds nothing, `drawings` comes back
    empty, and empty is a legitimate answer everywhere else — so without
    parametrising over both directions this would pass while output
    participations were permanently invisible. `projector.edge_pattern_for` is
    now the single source of the label and the direction, shared with the writer.
    """
    entity = await _cell(api_schema, simple_api_context, test_graph)
    other = await _cell(api_schema, simple_api_context, test_graph)
    event = await _mitosis(api_schema, simple_api_context, test_graph, other, other)

    result = await api_schema.execute(
        ASSERT_PARTICIPATION,
        variable_values={"input": {"event": event, "entity": entity, "role": "extra", "isInput": is_input}},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    payload = result.data["assertParticipation"]

    assert payload["link"]["id"], "The claim has an identity"

    # `kind`, not just `id`. This used to be `__typename` over the drawing types,
    # which is how the test could pass while every participation came back as a
    # `Relation`: the label a participation edge carries is the *event category's*
    # `age_name` ("Mitosis"), so nothing readable from the label could ever have said
    # "participation". The claim states the side outright.
    expected = "PARTICIPATES_AS_INPUT" if is_input else "PARTICIPATES_AS_OUTPUT"
    assert payload["link"]["kind"] == expected, f"A participation names the side it claims, got {payload['link']['kind']}"

    assert payload["drawings"], f"The graph draws this participation, so the result must say so (isInput={is_input})"
    assert payload["drawings"][0]["graph"]["id"] == str(test_graph.id)
    assert payload["drawings"][0]["category"]["id"], "and name the category it was drawn under"
    # The *drawing* is still an `Edge` subtype — that is what a graph holds, and where
    # `InputParticipation` / `OutputParticipation` belong. The claim beside it names the
    # same side in the vocabulary of the log.
    drawn_as = "InputParticipation" if is_input else "OutputParticipation"
    assert payload["drawings"][0]["edge"]["__typename"] == drawn_as, "and the drawing agrees about what it drew"
