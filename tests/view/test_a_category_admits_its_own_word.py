"""A category admits its own word, unless its rules name it (RFC 0026, A6).

Declaring a category declares a word: its key becomes the organization's `Term`.
In the view that declared it, that word means the category — so "a new
CuratedAIS" is drawn as a CuratedAIS even when CuratedAIS is *defined* over
other words. The rules extend the word; they replace it only where they name it,
which is how the worked example's `AIS` still refuses a student's `AIS` claim.

History: only a primitive category honoured its own word. A defined one admitted
exactly what its rules matched, so a claim under its word was a member of the
view that declared the word and drawn nowhere in it.
"""

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from api.queries import _edges
from core import models as core_models
from evidence import models as evidence_models
from tests.support import claims, drawing, graphs, reads, rules, writes

ENTITIES = """
    query Entities($category: ID!) {
        entities(entityCategoryId: $category) { id }
    }
"""

#: A view whose words are all combinations of other words: a CuratedAIS is
#: anything claimed AIS or AxonInitialSegment, a LINKED anybody's TOUCHES, a
#: Division what the event annotator called Mitosis. None of the rules names
#: the category's own word.
COMBINED: dict = {
    "systemVersion": "2.0.0",
    "extensions": {
        "entities": [
            {"key": "Cell"},
            {"key": "CuratedAIS", "definition": rules.definition(rules.rule(rules.word("AIS", "AxonInitialSegment")))},
        ],
        "relations": [
            {
                "key": "LINKED",
                "source": {"keys": ["Cell"]},
                "target": {"keys": ["Cell"]},
                "definition": rules.definition(rules.rule(rules.word("TOUCHES"))),
            }
        ],
        "events": [
            {
                "key": "Division",
                "kind": "INTRINSIC",
                "definition": rules.definition(rules.rule(rules.word("Mitosis"), rules.via("event-annotator"))),
                "inputs": [],
                "outputs": [],
            }
        ],
    },
}


async def _combined(api_schema: kante.Schema, ctx: HttpContext) -> core_models.Graph:
    graph_id = await graphs.graph_with(api_schema, ctx, "combined", COMBINED)
    return await sync_to_async(core_models.Graph.objects.get)(pk=graph_id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_claim_under_a_defined_categorys_word_is_drawn_under_it(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    table_projector,
) -> None:
    """ "A new CuratedAIS" lands in the view that declared the word, beside what the rules derive."""

    graph = await _combined(api_schema, simple_api_context)

    written = (await writes.execute(api_schema, simple_api_context, writes.ASSERT_ENTITY_DRAWN, {"input": {"term": "CuratedAIS"}}))["assertEntityExists"]
    own = written["instance"]["id"]
    derived = await writes.create_entity(api_schema, simple_api_context, "AIS")

    curated = await sync_to_async(core_models.EntityCategory.objects.get)(graph=graph, key="CuratedAIS")
    assert [d["category"]["id"] for d in written["drawings"]] == [str(curated.pk)], "the write reports where it landed: under its own word's category"

    listed = await writes.execute(api_schema, simple_api_context, ENTITIES, {"category": str(curated.pk)})
    assert sorted(row["id"] for row in listed["entities"]) == sorted([own, derived]), "the category lists both: its own word and what its rules derive from"

    in_view = await writes.execute(api_schema, simple_api_context, reads.NODES_PAGED, {"graph": str(graph.pk)})
    assert own in {row["id"] for row in in_view["nodes"]}, "the view lists it"
    single = await writes.execute(api_schema, simple_api_context, reads.NODE, {"id": own, "graph": str(graph.pk)})
    assert single["node"]["id"] == own, "and answers for it by id, as the plural read does"

    @sync_to_async
    def after_rebuild() -> tuple[int, int, set[str]]:
        result = graphs.rebuild(graph, table_projector)
        return result.unclassified, drawing.vertex_count(graph, curated.age_name), drawing.labels_of(graph, own)

    unclassified, count, labels = await after_rebuild()
    assert unclassified == 0, "nothing in the view is left undrawn"
    assert count == 2, "a rebuild draws what the write path drew"
    assert labels == {curated.age_name}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_rules_that_name_their_own_word_govern_it(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    table_projector,
) -> None:
    """The worked example's AIS counts Peter's AIS claims and not a student's."""

    graph_id = await graphs.graph_declaring(api_schema, simple_api_context, "AIS", definition=rules.definition(rules.rule(rules.word("AIS"), rules.by("peter"))))

    @sync_to_async
    def claim_and_rebuild() -> tuple[str, str, int]:
        graph = core_models.Graph.objects.get(pk=graph_id)
        peters = claims.mint(graph.organization, "AIS", "peter")
        students = claims.mint(graph.organization, "AIS", "student")
        result = graphs.rebuild(graph, table_projector)
        return peters, students, result.unclassified

    peters, students, unclassified = await claim_and_rebuild()

    @sync_to_async
    def drawn(ref: str) -> int:
        return drawing.vertices_with_ref(core_models.Graph.objects.get(pk=graph_id), ref)

    assert await drawn(peters) == 1
    assert await drawn(students) == 0, "the rules name AIS, so they — not the implicit own-word clause — decide who counts"
    assert unclassified == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_relation_under_a_defined_categorys_word_is_drawn_and_listed(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    table_projector,
) -> None:
    """Edges too: a LINKED claim is a LINKED edge, beside the TOUCHES the rule derives from."""

    graph = await _combined(api_schema, simple_api_context)

    @sync_to_async
    def relate_and_rebuild() -> int:
        organization = graph.organization
        a, b, c = (claims.mint(organization, "Cell", "student") for _ in range(3))
        own = claims.relate(organization, "LINKED", a, b, "student")
        derived = claims.relate(organization, "TOUCHES", b, c, "student")
        graphs.rebuild(graph, table_projector)
        linked = core_models.RelationCategory.objects.get(graph=graph, key="LINKED")
        listed = {str(link.pk) for link in _edges.links_for_category(organization, linked, evidence_models.Link.Kind.RELATION)}
        assert listed == {str(own.pk), str(derived.pk)}, "the edge list agrees with the drawing"
        return drawing.edge_count(graph, linked.age_name)

    edges = await relate_and_rebuild()
    assert edges == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_event_under_a_defined_categorys_word_is_drawn_under_it(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    table_projector,
) -> None:
    """Events too: a Division claimed by anyone is a Division, whatever app the rule scopes Mitosis to."""

    graph = await _combined(api_schema, simple_api_context)

    @sync_to_async
    def claim_and_rebuild() -> tuple[set[str], int, int]:
        organization = graph.organization
        own = claims.mint(organization, "Division", "student", app_id="some-other-app", kind="NATURAL_EVENT")
        claims.mint(organization, "Mitosis", "student", app_id="some-other-app", kind="NATURAL_EVENT")
        result = graphs.rebuild(graph, table_projector)
        division = core_models.NaturalEventCategory.objects.get(graph=graph, key="Division")
        return drawing.labels_of(graph, own), drawing.vertex_count(graph, division.age_name), result.unclassified

    labels, count, unclassified = await claim_and_rebuild()
    assert labels == {"Division"}
    assert count == 1, "the Mitosis from the wrong app stays out: the rules still govern the words they name"
    assert unclassified == 1
