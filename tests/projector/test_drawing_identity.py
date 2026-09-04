"""Three small truths about drawings, each of which was a bug.

- A write reports the **rule's** category for every view that draws the claim,
  not whatever `category_id` happens to be stamped on the vertex (the cache was
  authoritative for the payload, so a stale vertex made the write stale).
- Two undrawn `RetrievedNode`s are two objects: hash and equality are on the
  claim's id, not on a vertex id that `from_row` leaves at 0.
- Deleting a `Graph` row by any path drops its projection namespace, not only
  through the `deleteGraph` mutation.
"""

import pytest
from asgiref.sync import sync_to_async

from core import models as core_models
from evidence import models as evidence_models
from graph_engine import models as graph_engine_models
from graph_engine.controller import GraphController
from graph_engine.retrieved import RetrievedNode
from tests import writes


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
        graph_engine_models.ProjectionVertex.objects.filter(graph=test_graph, ref=entity_id).update(category_pk=wrong.pk)
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
def test_deleting_a_graph_row_drops_its_namespace(test_graph: core_models.Graph, table_projector) -> None:
    table_projector.draw_node(test_graph, "00000000-0000-0000-0000-000000000001", "Cell", None, "ENTITY", ["00000000-0000-0000-0000-000000000001"])
    assert graph_engine_models.ProjectionVertex.objects.filter(graph=test_graph).exists()
    core_models.Graph.objects.filter(pk=test_graph.pk).delete()
    assert not graph_engine_models.ProjectionVertex.objects.filter(graph_id=test_graph.pk).exists(), "a deleted view takes its drawing with it, on every deletion path"
