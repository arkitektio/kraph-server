"""A view draws one vertex per individual (RFC 0018).

Every observation mints its own instance, and "this is AIS 6" is a `SAME_AS`
claim between two of them. Until now the panel folded those claims but the
drawing did not: `create_vertex` drew one vertex per instance, so a view
showed two nodes for one cell and each edge and each derived property attached
to whichever observation happened to be named.

Now a view draws one vertex per **component** — the closure of the standing
sameness claims its category trusts (`identity.view_components`). The vertex's
ref is the lowest member uuid, `ProjectionMember` lists the rest, and every
address — `node(id:)`, an edge endpoint, a metric's INFORMS target — reaches
the vertex through any member.
"""

import pytest
from asgiref.sync import sync_to_async
from django.core.management import call_command
from io import StringIO

from core import models as core_models
from evidence import models as evidence_models
from graph_engine import projector, watermark
from graph_engine.controller import GraphController
from tests import claims, drawing, writes
from tests.api.test_category_trust import BEFORE, _example_graph
from tests.api.test_entity_identity import ASSERT_SAME, RETRACT_SAME, _assert_entity

NODE = """
    query Node($id: ID!, $graph: ID!) {
        node(id: $id, graph: $graph) { id label members ... on Entity { properties } }
    }
"""

NODES = """
    query Nodes($graph: ID!) {
        nodes(graph: $graph) { id members }
    }
"""


async def _execute(api_schema, ctx, document: str, variables: dict) -> dict:
    result = await api_schema.execute(document, variable_values=variables, context_value=ctx)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data


async def _merge(api_schema, ctx, refs: list[str]) -> str:
    data = await _execute(api_schema, ctx, ASSERT_SAME, {"input": {"instances": refs}})
    return data["assertSameInstance"]["links"][0]["id"]


def _roi(obj: str, length: float) -> list[dict]:
    return [{"identifier": "ROI", "object": obj, "metrics": [{"key": "vector_length", "value": length, "valueKind": "FLOAT"}]}]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_two_observations_claimed_the_same_draw_one_vertex(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """One vertex, addressed by either member, identified by the lowest uuid."""
    a = (await _assert_entity(api_schema, simple_api_context, "AIS"))["instance"]["id"]
    b = (await _assert_entity(api_schema, simple_api_context, "AIS", same_as=[a]))["instance"]["id"]
    representative = min(a, b)

    @sync_to_async
    def drawn():
        return drawing.vertex_count(test_graph, "AIS"), drawing.representative_of(test_graph, a), drawing.representative_of(test_graph, b), drawing.members_of(test_graph, a)

    count, rep_a, rep_b, members = await drawn()
    assert count == 1, "one individual, one vertex"
    assert rep_a == rep_b == representative, "the vertex is named by the lowest member uuid, whichever was asked for"
    assert members == sorted([a, b])

    via_a = (await _execute(api_schema, simple_api_context, NODE, {"id": a, "graph": str(test_graph.pk)}))["node"]
    via_b = (await _execute(api_schema, simple_api_context, NODE, {"id": b, "graph": str(test_graph.pk)}))["node"]
    assert via_a["id"] == via_b["id"] == representative, "`node(id:)` through any member answers the individual"
    assert sorted(via_a["members"]) == sorted([a, b])

    listed = (await _execute(api_schema, simple_api_context, NODES, {"graph": str(test_graph.pk)}))["nodes"]
    assert [row["id"] for row in listed] == [representative], "`nodes(graph:)` lists one row per individual"
    assert sorted(listed[0]["members"]) == sorted([a, b])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_edges_to_any_member_land_on_the_one_vertex(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """Two relation claims naming different members of one individual are one edge, counted twice."""
    a = await writes.create_entity(api_schema, simple_api_context, "Cell")
    b = await writes.create_entity(api_schema, simple_api_context, "Cell")
    c = await writes.create_entity(api_schema, simple_api_context, "Cell")
    await writes.create_relation(api_schema, simple_api_context, "IS_CONNECTED_TO", c, a)
    await writes.create_relation(api_schema, simple_api_context, "IS_CONNECTED_TO", c, b)
    await _merge(api_schema, simple_api_context, [a, b])

    @sync_to_async
    def drawn():
        return (
            drawing.edge_count(test_graph, "IS_CONNECTED_TO"),
            drawing.edges_between(test_graph, c, a, "IS_CONNECTED_TO"),
            drawing.edges_between(test_graph, c, b, "IS_CONNECTED_TO"),
            drawing.edge_properties_between(test_graph, c, a, "IS_CONNECTED_TO"),
        )

    total, to_a, to_b, properties = await drawn()
    assert total == 1
    assert to_a == to_b == 1, "the edge is reachable through either member"
    assert [p["__assertion_count"] for p in properties] == [2], "both claims support the one edge"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_relation_between_two_members_is_a_self_edge(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """The claims say a connects to b; the view says a and b are one thing. The edge is drawn, from the vertex to itself."""
    a = await writes.create_entity(api_schema, simple_api_context, "Cell")
    b = await writes.create_entity(api_schema, simple_api_context, "Cell")
    await writes.create_relation(api_schema, simple_api_context, "IS_CONNECTED_TO", a, b)
    await _merge(api_schema, simple_api_context, [a, b])

    @sync_to_async
    def drawn():
        return drawing.edge_count(test_graph, "IS_CONNECTED_TO"), drawing.edges_between(test_graph, a, a, "IS_CONNECTED_TO")

    total, loop = await drawn()
    assert total == 1 and loop == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_measurements_of_either_member_fold_into_the_individuals_properties(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """`avg_length` folds every ROI that informs any member (the cached `State` path)."""
    a = await writes.create_entity(api_schema, simple_api_context, "AIS", evidence=_roi("roi-a", 10.0))
    b = await writes.create_entity(api_schema, simple_api_context, "AIS", evidence=_roi("roi-b", 30.0))

    @sync_to_async
    def before():
        return drawing.vertex_properties(test_graph, a).get("avg_length"), drawing.vertex_properties(test_graph, b).get("avg_length")

    assert await before() == (pytest.approx(10.0), pytest.approx(30.0))

    await _merge(api_schema, simple_api_context, [a, b])

    @sync_to_async
    def after():
        return drawing.vertex_count(test_graph, "AIS"), drawing.vertex_properties(test_graph, a).get("avg_length"), drawing.vertex_properties(test_graph, b).get("avg_length")

    count, via_a, via_b = await after()
    assert count == 1
    assert via_a == via_b == pytest.approx(20.0), "the mean over both observations' ROIs"

    node = (await _execute(api_schema, simple_api_context, NODE, {"id": b, "graph": str(test_graph.pk)}))["node"]
    assert node["properties"]["avg_length"] == pytest.approx(20.0)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_rule_bound_property_folds_over_every_member(api_schema, simple_api_context, table_projector) -> None:
    """The `_scoped_state` path: a property with its own `rule.evidence` widens its metric filter to the component."""
    graph_id = await _example_graph(api_schema, simple_api_context, "individual-scoped")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        a = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        b = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        claims.measure(org, a, obj="roi-a", key="vector_length", value=10.0, subject="peter", app_id="segmenter-v3")
        claims.measure(org, b, obj="roi-b", key="vector_length", value=30.0, subject="peter", app_id="segmenter-v3")
        claims.measure(org, b, obj="roi-c", key="vector_length", value=99.0, subject="peter", app_id="segmenter-v2")
        claims.same(org, a, b, "peter", asserted_at=BEFORE)
        GraphController(projector=table_projector).rebuild_projection(graph)
        return drawing.vertex_count(graph, "AIS"), drawing.vertex_properties(graph, a).get("avg_length")

    count, avg_length = await build_and_read()
    assert count == 1
    assert avg_length == pytest.approx(20.0), "both members' segmenter-v3 measurements, and not the v2 one"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_the_sameness_splits_the_vertex(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """Each observation is its own individual again: own vertex, own fold, own edges."""
    a = await writes.create_entity(api_schema, simple_api_context, "AIS", evidence=_roi("roi-a", 10.0))
    b = await writes.create_entity(api_schema, simple_api_context, "AIS", evidence=_roi("roi-b", 30.0))
    c = await writes.create_entity(api_schema, simple_api_context, "Cell")
    await writes.create_relation(api_schema, simple_api_context, "PART_OF", a, c)
    await writes.create_relation(api_schema, simple_api_context, "PART_OF", b, c)
    sameness = await _merge(api_schema, simple_api_context, [a, b])

    @sync_to_async
    def merged():
        return drawing.vertex_count(test_graph, "AIS"), drawing.edge_count(test_graph, "PART_OF")

    assert await merged() == (1, 1)

    await _execute(api_schema, simple_api_context, RETRACT_SAME, {"input": {"id": sameness}})

    @sync_to_async
    def split():
        return (
            drawing.vertex_count(test_graph, "AIS"),
            drawing.members_of(test_graph, a),
            drawing.members_of(test_graph, b),
            drawing.vertex_properties(test_graph, a).get("avg_length"),
            drawing.vertex_properties(test_graph, b).get("avg_length"),
            drawing.edges_between(test_graph, a, c, "PART_OF"),
            drawing.edges_between(test_graph, b, c, "PART_OF"),
            drawing.edge_properties_between(test_graph, a, c, "PART_OF"),
        )

    count, members_a, members_b, avg_a, avg_b, a_to_c, b_to_c, properties = await split()
    assert count == 2
    assert members_a == [a] and members_b == [b]
    assert avg_a == pytest.approx(10.0) and avg_b == pytest.approx(30.0)
    assert a_to_c == 1 and b_to_c == 1
    assert [p["__assertion_count"] for p in properties] == [1]

    listed = (await _execute(api_schema, simple_api_context, NODES, {"graph": str(test_graph.pk)}))["nodes"]
    assert {row["id"] for row in listed} == {a, b, c}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_sameness_the_category_does_not_trust_draws_two_vertices(api_schema, simple_api_context, table_projector) -> None:
    """Sameness is the view's rule (RFC 0024): this view trusts Peter, so a stranger's merge changes nothing here."""
    graph_id = await _example_graph(api_schema, simple_api_context, "individual-trust")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        # Sameness is the view's rule (RFC 0024): this view counts Peter's merges.
        graph.sameness_rule = {"rules": [{"when": [{"field": "SUBJECT", "operator": "IS", "value": "peter"}]}]}
        graph.save(update_fields=["sameness_rule"])
        org = graph.organization
        a = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        b = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        claims.same(org, a, b, "stranger", asserted_at=BEFORE)
        controller = GraphController(projector=table_projector)
        controller.rebuild_projection(graph)
        ignored = drawing.vertex_count(graph, "AIS"), drawing.members_of(graph, a)
        claims.same(org, a, b, "peter", asserted_at=BEFORE)
        controller.rebuild_projection(graph)
        return ignored, (drawing.vertex_count(graph, "AIS"), drawing.members_of(graph, a)), a, b

    ignored, trusted, a, b = await build_and_read()
    assert ignored == (2, [a]), "the stranger's claim is not one this view counts"
    assert trusted == (1, sorted([a, b])), "Peter's is"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_retracted_member_leaves_the_individual(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """A member the view no longer admits is not a member; the vertex is renamed if it was the representative."""
    a = await writes.create_entity(api_schema, simple_api_context, "AIS")
    b = await writes.create_entity(api_schema, simple_api_context, "AIS")
    await _merge(api_schema, simple_api_context, [a, b])
    lowest, highest = sorted([a, b])

    retracted = await api_schema.execute("mutation($id: ID!) { retractEntity(input: {id: $id}) { assertion { id } } }", variable_values={"id": lowest}, context_value=simple_api_context)
    assert retracted.errors is None, f"GraphQL errors: {retracted.errors}"

    @sync_to_async
    def drawn():
        return drawing.vertex_count(test_graph, "AIS"), drawing.vertices_with_ref(test_graph, lowest), drawing.representative_of(test_graph, highest), drawing.members_of(test_graph, highest)

    count, lowest_drawn, representative, members = await drawn()
    assert count == 1
    assert lowest_drawn == 0
    assert representative == highest and members == [highest]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_redrawing_a_merged_individual_converges(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector) -> None:
    """`reproject_refs` through any member, twice, leaves one vertex with all its members."""
    a = await writes.create_entity(api_schema, simple_api_context, "AIS")
    b = await writes.create_entity(api_schema, simple_api_context, "AIS")
    await _merge(api_schema, simple_api_context, [a, b])

    @sync_to_async
    def redraw():
        controller = GraphController(projector=table_projector)
        projector.reproject_refs(controller, test_graph, [a])
        projector.reproject_refs(controller, test_graph, [b])
        projector.project_all(controller, test_graph)
        return drawing.vertex_count(test_graph, "AIS"), drawing.members_of(test_graph, a)

    assert await redraw() == (1, sorted([a, b]))


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_replay_folds_a_merge_the_write_path_could_not_draw(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector, monkeypatch) -> None:
    """The incremental path widens the touched set to the whole component."""
    a = await writes.create_entity(api_schema, simple_api_context, "AIS", evidence=_roi("roi-a", 10.0))
    b = await writes.create_entity(api_schema, simple_api_context, "AIS", evidence=_roi("roi-b", 30.0))

    def _down(*args, **kwargs):
        raise RuntimeError("projector down")

    monkeypatch.setattr(projector, "reproject_refs", _down)
    failed = await api_schema.execute(ASSERT_SAME, variable_values={"input": {"instances": [a, b]}}, context_value=simple_api_context)
    assert failed.errors
    monkeypatch.undo()

    @sync_to_async
    def replay():
        assert drawing.vertex_count(test_graph, "AIS") == 2, "the failed draw left the two observations apart"
        out = StringIO()
        call_command("reproject", incremental=True, organization=test_graph.organization.slug, stdout=out)
        return drawing.vertex_count(test_graph, "AIS"), drawing.members_of(test_graph, a), drawing.vertex_properties(test_graph, a).get("avg_length"), watermark.pending_count(test_graph.organization)

    count, members, avg_length, pending = await replay()
    assert count == 1
    assert members == sorted([a, b])
    assert avg_length == pytest.approx(20.0)
    assert pending == 0


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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_sameness_claim_survives_in_the_log_when_a_view_ignores_it(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """The organization-grain cache still folds every standing claim; only the drawing is per view."""
    from evidence import identity

    a = await writes.create_entity(api_schema, simple_api_context, "AIS")
    b = await writes.create_entity(api_schema, simple_api_context, "AIS")
    await _merge(api_schema, simple_api_context, [a, b])

    @sync_to_async
    def cached():
        links = evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.SAME_AS).count()
        return links, identity.component_refs(test_graph.organization, [a])[a]

    links, component = await cached()
    assert links == 1 and sorted(component) == sorted([a, b])
