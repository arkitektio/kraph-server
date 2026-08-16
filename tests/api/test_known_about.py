"""What is currently known about a structure, in one query.

The panel the whole exercise is for: which measurements are there, how users have
labelled the thing, who else says it is the same thing, and where it is connected
in which graphs.

Two findings shaped it. **Connections need no graph query** — relations,
participations and INFORMS are all `Link` rows with indexed refs, and Apache AGE
holds a droppable drawing of them. And **everything is asked about the
component**, never about one node: every observation mints its own instance, so
what is known about a thing is spread across the instances somebody has claimed
are one.
"""

import uuid

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models

ASSERT_STRUCTURE = """
    mutation AssertStructureExists($input: AssertStructureExistsInput!) {
        assertStructureExists(input: $input) { structure { id } }
    }
"""

ASSERT_ENTITY = """
    mutation AssertEntityExists($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { entity { id } }
    }
"""

CLASSIFY_NODES = """
    mutation ClassifyNodes($input: ClassifyNodesInput!) {
        classifyNodes(input: $input) { assertion { id } }
    }
"""

RETRACT_CLAIMS = """
    mutation RetractClaims($input: RetractClaimsInput!) {
        retractClaims(input: $input) { assertion { id } }
    }
"""

PANEL = """
    query KnownAbout($id: GraphID!) {
        structure(id: $id) {
            id
            metrics { __typename id key value assertion { id subject } }
            informs {
                __typename
                id
                component
                labels { __typename nodeId assertionCount term { key } latestAssertion { id subject } }
                sameAs { __typename id }
                connections { __typename id assertion { id } }
                drawnIn { graph { id } category { id } }
            }
        }
    }
"""


async def _structure(api_schema: kante.Schema, ctx: HttpContext, metrics: list[dict] | None = None) -> tuple[str, str]:
    """A structure, as `(id, object)`.

    Both, because a structure is addressed by its primary key on the read side and
    by `(identifier, object)` when it is named as supporting evidence — the write
    API takes the external identity, since that is what a caller producing a
    measurement actually holds.
    """
    object_id = f"roi-{uuid.uuid4().hex[:8]}"
    result = await api_schema.execute(
        ASSERT_STRUCTURE,
        variable_values={"input": {"identifier": "@mikro/roi", "object": object_id, "metrics": metrics or []}},
        context_value=ctx,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["assertStructureExists"]["structure"]["id"], object_id


async def _entity(api_schema: kante.Schema, ctx: HttpContext, term: str, evidence_object: str | None = None, same_as: list[str] | None = None) -> str:
    evidence = [{"identifier": "@mikro/roi", "object": evidence_object, "metrics": []}] if evidence_object else []
    result = await api_schema.execute(
        ASSERT_ENTITY,
        variable_values={"input": {"term": term, "supportingEvidence": evidence, "sameAs": same_as or []}},
        context_value=ctx,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["assertEntityExists"]["entity"]["id"]


async def _panel(api_schema: kante.Schema, ctx: HttpContext, structure_id: str) -> dict:
    result = await api_schema.execute(PANEL, variable_values={"id": structure_id}, context_value=ctx)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["structure"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_structures_measurements_are_no_longer_silently_empty(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`Structure.metrics` was a hardcoded `return []`.

    The field existed, was selectable, and said there were no measurements — while
    `metricsForStructure(structureId:)` answered the same question correctly at the
    top level. A field that lies is worse than one that is absent.
    """
    structure_id, _ = await _structure(api_schema, simple_api_context, metrics=[{"key": "length", "value": 42.0, "valueKind": "FLOAT"}])

    panel = await _panel(api_schema, simple_api_context, structure_id)

    assert [metric["key"] for metric in panel["metrics"]] == ["length"]
    assert panel["metrics"][0]["value"] == 42.0
    assert panel["metrics"][0]["__typename"] == "Metric"
    # `RetrievedMetric.from_row` used to drop the row, so a measurement could say
    # when it was claimed and never by whom.
    assert panel["metrics"][0]["assertion"]["subject"], "Who measured this has to be answerable"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_panel_reaches_labels_through_what_the_structure_informs(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """A structure is never itself an AIS.

    It is a pointer to an external datum, idempotent by `(identifier, object)`.
    Saying "this is an AIS" mints an *entity* and claims the structure is evidence
    for it — so labels, merges and connections all live on the entity, and the
    panel takes one hop to get there.
    """
    structure_id, object_id = await _structure(api_schema, simple_api_context)
    entity_id = await _entity(api_schema, simple_api_context, "AIS", evidence_object=object_id)

    panel = await _panel(api_schema, simple_api_context, structure_id)

    assert [node["id"] for node in panel["informs"]] == [entity_id]
    assert panel["informs"][0]["__typename"] == "Entity"
    assert [label["term"]["key"] for label in panel["informs"][0]["labels"]] == ["AIS"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_agreement_is_counted_and_disagreement_is_shown(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The distinction the panel exists to draw.

    Two annotators claiming the **same** word give one label with
    `assertionCount == 2` — agreement, counted. Two claiming **different** words
    give two labels — the conflict represented rather than resolved. A fold that
    picked a winner would be answering a question nobody asked.
    """
    structure_id, object_id = await _structure(api_schema, simple_api_context)
    entity_id = await _entity(api_schema, simple_api_context, "AIS", evidence_object=object_id)

    concurring = await api_schema.execute(
        CLASSIFY_NODES,
        variable_values={"input": {"classifications": [{"node": entity_id, "term": "AIS"}, {"node": entity_id, "term": "Soma"}]}},
        context_value=simple_api_context,
    )
    assert concurring.errors is None, f"GraphQL errors: {concurring.errors}"

    panel = await _panel(api_schema, simple_api_context, structure_id)
    labels = {label["term"]["key"]: label for label in panel["informs"][0]["labels"]}

    assert labels["AIS"]["assertionCount"] == 2, "Concurrence is countable — the log records a claim that restates a position already held"
    assert labels["Soma"]["assertionCount"] == 1
    assert labels["AIS"]["latestAssertion"] is not None, "Who says so, for the claim that currently stands"
    assert labels["AIS"]["__typename"] == "Label"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_retracted_label_does_not_appear(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Retraction is a `Claim(stands=False)`, not a delete.

    Nothing about the `CLASSIFIES` row says it is gone; only the anti-join against
    `ClaimCurrent` does. `selector.classification_claims_for` was missing that
    wrapper while its docstring promised "every *live* claim".
    """
    structure_id, object_id = await _structure(api_schema, simple_api_context)
    entity_id = await _entity(api_schema, simple_api_context, "AIS", evidence_object=object_id)

    added = await api_schema.execute(
        CLASSIFY_NODES,
        variable_values={"input": {"classifications": [{"node": entity_id, "term": "Soma"}]}},
        context_value=simple_api_context,
    )
    assert added.errors is None, f"GraphQL errors: {added.errors}"

    @sync_to_async
    def soma_claim_id() -> str:
        link = evidence_models.Link.all_objects.filter(kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=entity_id, term__key="Soma").first()
        assert link is not None
        return str(link.pk)

    retracted = await api_schema.execute(
        RETRACT_CLAIMS,
        variable_values={"input": {"ids": [await soma_claim_id()]}},
        context_value=simple_api_context,
    )
    assert retracted.errors is None, f"GraphQL errors: {retracted.errors}"

    panel = await _panel(api_schema, simple_api_context, structure_id)

    assert [label["term"]["key"] for label in panel["informs"][0]["labels"]] == ["AIS"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_everything_is_unioned_over_the_component(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The point of the merge, and the reason the panel is not per node.

    Two observations of one cell each mint their own instance and carry their own
    evidence. Once somebody says they are the same thing, either one has to answer
    for both — otherwise a merge would be a claim with no consequence.
    """
    first_structure, first_object = await _structure(api_schema, simple_api_context)
    first = await _entity(api_schema, simple_api_context, "AIS", evidence_object=first_object)

    second_structure, second_object = await _structure(api_schema, simple_api_context)
    second = await _entity(api_schema, simple_api_context, "AIS", evidence_object=second_object, same_as=[first])

    panel = await _panel(api_schema, simple_api_context, first_structure)
    node = panel["informs"][0]

    assert sorted(node["component"]) == sorted([first, second]), "Asking about either instance answers for both"
    assert len(node["sameAs"]) == 1
    assert node["sameAs"][0]["__typename"] == "Sameness", "A sameness claim used to have no type of its own and came back as a Relation"

    # Both observations' INFORMS claims, reachable from either end of the merge.
    informing = {connection["__typename"] for connection in node["connections"]}
    assert informing == {"Description"}, f"Only the INFORMS claims here, got {informing}"
    assert len(node["connections"]) == 2, "One per observation — the merge is what makes the second one visible from here"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_labels_and_merges_are_not_reported_as_connections(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`connections` answers "what is this attached to", not "what is claimed about it".

    A classification and a sameness claim are both `Link` rows, so a naive query
    over the ref indexes returns them — and the panel would then report a node's
    own labels as things it is connected to.
    """
    structure_id, object_id = await _structure(api_schema, simple_api_context)
    first = await _entity(api_schema, simple_api_context, "AIS", evidence_object=object_id)
    await _entity(api_schema, simple_api_context, "AIS", same_as=[first])

    panel = await _panel(api_schema, simple_api_context, structure_id)
    kinds = {connection["__typename"] for connection in panel["informs"][0]["connections"]}

    assert "Classification" not in kinds
    assert "Sameness" not in kinds


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_drawn_in_reports_the_views_that_actually_draw_it(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Read back from the projection, not approximated from the vocabulary.

    `graphs_for_refs` answers which graphs declare a word *admitting* this node —
    a superset. `drawnIn` asks each candidate view for the vertex, so it reports
    where the thing is genuinely drawn and under which category.
    """
    structure_id, object_id = await _structure(api_schema, simple_api_context)
    await _entity(api_schema, simple_api_context, "AIS", evidence_object=object_id)

    panel = await _panel(api_schema, simple_api_context, structure_id)
    drawings = panel["informs"][0]["drawnIn"]

    assert [drawing["graph"]["id"] for drawing in drawings] == [str(test_graph.pk)]
    assert drawings[0]["category"]["id"], "A drawing says which category the view draws it under"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_view_that_declares_the_word_but_refuses_the_node_is_not_listed(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The exact case an approximate answer would over-report.

    A category carrying a `definition` is a rule over classification claims, and
    a claim by somebody the definition does not count leaves the node out of that
    view — while the graph still declares the word, so the cheap answer would
    list it.

    The definition is narrowed **before** the claim is made. Changing it
    afterwards is a different question — the vertex already drawn stays drawn
    until something reprojects, which is what `docs/REMATERIALIZATION.md` is
    about, and `drawnIn` deliberately reports what each view holds rather than
    what it would hold after a rebuild.
    """

    @sync_to_async
    def define_ais_narrowly() -> None:
        category = core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").first()
        assert category is not None, "The bio schema declares AIS"
        category.definition = {"asserted_as": "AIS", "assertion_filter": {"subjects": ["somebody-else-entirely"]}}
        category.save()

    await define_ais_narrowly()
    structure_id, object_id = await _structure(api_schema, simple_api_context)
    await _entity(api_schema, simple_api_context, "AIS", evidence_object=object_id)

    panel = await _panel(api_schema, simple_api_context, structure_id)

    assert panel["informs"][0]["drawnIn"] == [], "The graph declares the word, but its definition refuses this node"
    assert [label["term"]["key"] for label in panel["informs"][0]["labels"]] == ["AIS"], "The claim itself is untouched — a definition narrows a view, not the log"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_panel_does_not_scale_with_the_number_of_subjects(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The whole point of the exercise.

    Every section of the panel is a range on an index `Link` already carries, and
    each takes every ref on the page at once — so selecting all of them for five
    structures must cost what it costs for one, plus the per-structure work that
    genuinely cannot be batched.

    Counted as load-function calls rather than as queries: the ORM runs on a
    `sync_to_async` thread, which Django's query capture does not see across.
    """
    from api import loaders

    structures = []
    for index in range(5):
        structure_id, object_id = await _structure(api_schema, simple_api_context, metrics=[{"key": "length", "value": float(index), "valueKind": "FLOAT"}])
        await _entity(api_schema, simple_api_context, "AIS", evidence_object=object_id)
        structures.append(structure_id)

    batches: list[list] = []
    original = loaders._batch_known_about_nodes

    def counting():
        inner = original()

        async def load(keys):
            batches.append(list(keys))
            return await inner(keys)

        return load

    loaders._batch_known_about_nodes = counting
    loaders._CUSTOM_LOADER_FACTORIES["known_about_node"] = counting
    try:
        result = await api_schema.execute(
            """
            query ManyPanels($ids: [GraphID!]!) {
                structures(filters: {ids: $ids}) {
                    id
                    metrics { id }
                    informs { id component labels { assertionCount } sameAs { id } connections { id } }
                }
            }
            """,
            variable_values={"ids": structures},
            context_value=simple_api_context,
        )
    finally:
        loaders._batch_known_about_nodes = original
        loaders._CUSTOM_LOADER_FACTORIES["known_about_node"] = original

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert len(result.data["structures"]) == 5

    assert len(batches) == 1, f"Five subjects, one batched read of the panel — got {len(batches)}"
    assert len(batches[0]) == 5, "and every subject in it"
