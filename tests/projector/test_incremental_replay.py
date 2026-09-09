"""`reproject --incremental` draws what the outbox says is owed, and only that.

The write path projects synchronously; when it cannot (the projector raises, the
process dies between the evidence commit and the drawing), the outbox row stays
and the cursor holds below it. An incremental replay reads those assertions'
claims, converges every touched node in every consistent graph of the
organization, and settles exactly the rows it read. The result has to equal what
a full drop-and-replay would draw — that is the comparison at the end.
"""

import pytest
from asgiref.sync import sync_to_async
from django.core.management import call_command
from io import StringIO

from core import models as core_models
from evidence import models as evidence_models
from graph_engine import models as projection_models
from graph_engine import projector, watermark
from graph_engine.controller import GraphController
from tests import drawing, writes

ENTITY_PROPERTIES = """
    query Entity($id: ID!, $graph: ID!) {
        node(id: $id, graph: $graph) { ... on Entity { id properties } }
    }
"""


def _down(*args, **kwargs):
    raise RuntimeError("projector down")


def _replay(organization_slug: str) -> str:
    out = StringIO()
    call_command("reproject", incremental=True, organization=organization_slug, stdout=out)
    return out.getvalue()


def _vertices_with_id(table_projector, graph, ref: str) -> int:
    return drawing.vertices_with_ref(graph, ref)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_replay_draws_a_node_the_write_path_could_not(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector, monkeypatch) -> None:
    monkeypatch.setattr(projector, "reproject_refs", _down)
    failed = await api_schema.execute(
        writes.ASSERT_ENTITY_EXISTS,
        variable_values={"input": {"term": "AIS", "supportingEvidence": [{"identifier": "ROI", "object": "roi-replay", "metrics": [{"key": "vector_length", "value": 30.0, "valueKind": "FLOAT"}]}]}},
        context_value=simple_api_context,
    )
    assert failed.errors
    monkeypatch.undo()

    @sync_to_async
    def before():
        organization = test_graph.organization
        node = evidence_models.Instance.objects.for_organization(organization).latest("created_at")
        return str(node.pk), watermark.pending_count(organization), _vertices_with_id(table_projector, test_graph, str(node.pk)), watermark.position(test_graph)

    ref, pending, drawn, position = await before()
    assert pending == 1 and drawn == 0 and position.lag >= 1

    @sync_to_async
    def replay():
        output = _replay(test_graph.organization.slug)
        return output, watermark.pending_count(test_graph.organization), _vertices_with_id(table_projector, test_graph, ref), watermark.position(test_graph)

    output, pending, drawn, position = await replay()
    assert pending == 0, f"the replay settles what it applied: {output}"
    assert drawn == 1
    assert position.lag == 0
    assert "1 ref" in output or "refs" in output

    properties = await api_schema.execute(ENTITY_PROPERTIES, variable_values={"id": ref, "graph": str(test_graph.pk)}, context_value=simple_api_context)
    assert properties.errors is None, f"GraphQL errors: {properties.errors}"
    assert properties.data["node"]["properties"].get("avg_length") == pytest.approx(30.0), "derived properties come with the node"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_replay_removes_a_node_whose_retraction_was_not_drawn(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector, monkeypatch) -> None:
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS")

    monkeypatch.setattr(projector, "unproject", _down)
    retracted = await api_schema.execute("mutation($id: ID!) { retractEntity(input: {id: $id}) { assertion { id } } }", variable_values={"id": entity_id}, context_value=simple_api_context)
    assert retracted.errors
    monkeypatch.undo()

    @sync_to_async
    def replay():
        assert _vertices_with_id(table_projector, test_graph, entity_id) == 1, "the failed unproject left the vertex"
        _replay(test_graph.organization.slug)
        return _vertices_with_id(table_projector, test_graph, entity_id), watermark.pending_count(test_graph.organization)

    drawn, pending = await replay()
    assert drawn == 0
    assert pending == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_replay_draws_an_edge_whose_write_did_not_reach_age(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector, monkeypatch) -> None:
    a = await writes.create_entity(api_schema, simple_api_context, "AIS")
    b = await writes.create_entity(api_schema, simple_api_context, "AIS")

    monkeypatch.setattr(projector, "project_edges", _down)
    failed = await api_schema.execute(
        writes.ASSERT_RELATION_EXISTS,
        variable_values={"input": {"term": "IS_CONNECTED_TO", "sourceId": a, "targetId": b, "supportingEvidence": []}},
        context_value=simple_api_context,
    )
    assert failed.errors
    monkeypatch.undo()

    @sync_to_async
    def replay():
        _replay(test_graph.organization.slug)
        return drawing.edges_between(test_graph, a, b, "IS_CONNECTED_TO"), watermark.pending_count(test_graph.organization)

    edges, pending = await replay()
    assert edges == 1
    assert pending == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_replay_equals_a_full_rebuild(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector, monkeypatch) -> None:
    """The acceptance test: after an incremental replay, a full rebuild changes nothing."""
    a = await writes.create_entity(api_schema, simple_api_context, "AIS", evidence=[{"identifier": "ROI", "object": "roi-a", "metrics": [{"key": "vector_length", "value": 10.0, "valueKind": "FLOAT"}]}])

    monkeypatch.setattr(projector, "reproject_refs", _down)
    monkeypatch.setattr(projector, "project_edges", _down)
    monkeypatch.setattr(projector, "project", _down)
    # A second entity, a relation, and a new metric on the first — none drawn.
    b_result = await api_schema.execute(writes.ASSERT_ENTITY_EXISTS, variable_values={"input": {"term": "AIS", "supportingEvidence": []}}, context_value=simple_api_context)
    assert b_result.errors
    more = await api_schema.execute(
        "mutation($input: AssertMetricValueInput!) { assertMetricValue(input: $input) { metric { id } } }",
        variable_values={"input": {"identifier": "ROI", "object": "roi-a", "key": "vector_length", "value": 30.0, "valueKind": "FLOAT"}},
        context_value=simple_api_context,
    )
    assert more.errors
    monkeypatch.undo()

    @sync_to_async
    def replay_then_rebuild():
        organization = test_graph.organization
        assert watermark.pending_count(organization) == 2
        _replay(organization.slug)
        assert watermark.pending_count(organization) == 0
        controller = GraphController(projector=table_projector)
        snapshot = drawing.all_vertex_properties(test_graph)
        controller.rebuild_projection(test_graph)
        rebuilt = drawing.all_vertex_properties(test_graph)
        return snapshot, rebuilt

    after_replay, after_rebuild = await replay_then_rebuild()
    assert set(after_replay) == set(after_rebuild) and len(after_replay) == 2
    for ref in after_replay:
        assert after_replay[ref] == after_rebuild[ref], f"{ref}: replay and rebuild disagree"
    assert after_replay[a]["avg_length"] == pytest.approx(20.0)


@pytest.mark.django_db(transaction=True)
def test_replay_tolerates_an_assertion_with_no_claims(test_graph: core_models.Graph, table_projector) -> None:
    """An act with no claims — one `redact` emptied, or one an older writer split
    across two transactions — leaves an outbox row with nothing to draw. A live
    write cannot produce one any more: the act is a single transaction."""
    from evidence import writer

    organization = test_graph.organization
    assertion = writer.create_assertion(organization, subject="tester", app_id="tests", action_id=None, action_name=None, action_args={})
    watermark.expect(assertion)

    _replay(organization.slug)
    assert not projection_models.PendingProjection.objects.filter(pk=assertion.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_incremental_refuses_a_single_graph(test_graph: core_models.Graph, table_projector) -> None:
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="organization"):
        call_command("reproject", incremental=True, graph=str(test_graph.pk), stdout=StringIO())
