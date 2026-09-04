"""The projection cursor: derived from the outbox, safe by construction.

`graph_engine/watermark.py` states the invariant; these tests pin the transitions
that keep it true. A write that finishes drawing deletes its outbox row; a write
whose projection raises leaves it, and the cursor of **every** graph in the
organization drops below it; a rebuild that dies after the drop leaves the graph
`REBUILDING` and honest about it.
"""

import pytest
from asgiref.sync import sync_to_async
from django.db import transaction

from core import models as core_models
from evidence import models as evidence_models
from graph_engine import models as projection_models
from graph_engine import projector, watermark
from graph_engine.controller import GraphController
from tests import writes


def test_cursor_is_a_pure_function_of_three_numbers() -> None:
    consistent = projection_models.Projection.Status.CONSISTENT
    assert watermark.cursor_from(consistent, 10, None) == 10, "nothing pending: caught up to the log head"
    assert watermark.cursor_from(consistent, 10, 7) == 6, "an outstanding seq 7 holds the cursor at 6"
    assert watermark.cursor_from(consistent, 10, 11) == 10, "a pending row above the head (uncommitted head) never lifts the cursor past it"
    assert watermark.cursor_from(projection_models.Projection.Status.NEEDS_BACKFILL, 10, None) == 0
    assert watermark.cursor_from(projection_models.Projection.Status.REBUILDING, 10, None) == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_write_settles_its_outbox_row_and_the_graph_is_caught_up(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def inspect():
        return watermark.pending_count(test_graph.organization), watermark.position(test_graph)

    pending, position = await inspect()
    assert pending == 0, "the synchronous projection finished, so nothing is owed"
    assert position.status == "consistent"
    assert position.lag == 0
    assert position.cursor == position.max_seq > 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_projection_failure_leaves_the_row_and_holds_every_cursor(api_schema, simple_api_context, test_graph: core_models.Graph, monkeypatch) -> None:
    """The evidence commits; the drawing does not; the cursor says so for the whole organization."""
    await writes.create_entity(api_schema, simple_api_context, "AIS")

    def down(*args, **kwargs):
        raise RuntimeError("projector down")

    monkeypatch.setattr(projector, "reproject_refs", down)

    failed = await api_schema.execute(
        writes.ASSERT_ENTITY_EXISTS,
        variable_values={"input": {"term": "AIS", "supportingEvidence": []}},
        context_value=simple_api_context,
    )
    assert failed.errors, "the projector raised, so the mutation reports it"

    @sync_to_async
    def inspect():
        organization = test_graph.organization
        pending = [int(seq) for seq in projection_models.PendingProjection.objects.filter(organization=organization).values_list("assertion__seq", flat=True)]
        return pending, watermark.position(test_graph), watermark.max_seq(organization), evidence_models.Instance.objects.for_organization(organization).count()

    pending, position, head, instances = await inspect()
    assert instances == 2, "the claim itself is durable — evidence first, always"
    assert len(pending) == 1, "one assertion is owed a drawing"
    assert position.cursor == pending[0] - 1, "the cursor sits just below the outstanding assertion"
    assert position.lag >= 1
    assert position.cursor < head


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_new_view_over_admitted_evidence_needs_a_backfill_until_it_gets_one(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector, bio_graph_schema, authenticated_context) -> None:
    from graph_engine.materialize import materialize

    await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def second_view(backfill: bool) -> core_models.Graph:
        request = authenticated_context.request
        return materialize(bio_graph_schema, table_projector, user=request._user, organization=request._organization, membership=request.membership, name=f"second_{backfill}", backfill=backfill)

    @sync_to_async
    def position(graph):
        return watermark.position(graph)

    cold = await second_view(False)
    cold_position = await position(cold)
    assert cold_position.status == "needs_backfill", "the organization already holds an AIS this view admits and has not drawn"
    assert cold_position.cursor == 0 and cold_position.lag == cold_position.max_seq

    warm = await second_view(True)
    warm_position = await position(warm)
    assert warm_position.status == "consistent"
    assert warm_position.lag == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_view_over_nothing_it_admits_starts_consistent(table_projector, minimal_schema, authenticated_context) -> None:
    """No backfill needed when there is nothing to backfill: the write path will draw everything that comes."""
    from graph_engine.materialize import materialize

    @sync_to_async
    def make():
        request = authenticated_context.request
        graph = materialize(minimal_schema, table_projector, user=request._user, organization=request._organization, membership=request.membership, name="empty_view")
        return watermark.position(graph)

    position = await make()
    assert position.status == "consistent"
    assert position.lag == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_rebuild_marks_consistent_and_a_dead_rebuild_is_honest(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector, monkeypatch) -> None:
    await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def rebuild():
        GraphController(projector=table_projector).rebuild_projection(test_graph)
        return watermark.position(test_graph), watermark.active_schema_hash(test_graph)

    position, active_hash = await rebuild()
    assert position.status == "consistent"
    assert position.lag == 0
    assert position.rebuilt_at is not None
    assert position.schema_hash == active_hash, "a full rebuild derives under the active schema"
    assert not position.schema_stale

    def explode(*args, **kwargs):
        raise RuntimeError("died after the drop")

    monkeypatch.setattr(projector, "project_all", explode)

    @sync_to_async
    def failing_rebuild():
        with pytest.raises(RuntimeError):
            GraphController(projector=table_projector).rebuild_projection(test_graph)
        return watermark.position(test_graph), watermark.active_schema_hash(test_graph)

    position, active_hash = await failing_rebuild()
    assert position.status == "rebuilding", "the namespace is gone and the replay did not finish; say so"
    assert position.cursor == 0
    assert position.lag == position.max_seq


@pytest.mark.django_db(transaction=True)
def test_an_outbox_row_is_written_with_the_assertion_and_cleared_by_id(test_graph: core_models.Graph) -> None:
    from evidence import writer

    organization = test_graph.organization
    with transaction.atomic():
        assertion = writer.create_assertion(organization, subject="tester", app_id="tests", action_id=None, action_name=None, action_args={})
        watermark.expect(assertion)
        assert projection_models.PendingProjection.objects.filter(pk=assertion.pk).exists()

    other = writer.create_assertion(organization, subject="tester", app_id="tests", action_id=None, action_name=None, action_args={})
    watermark.expect(other)

    watermark.settle(assertion)
    assert not projection_models.PendingProjection.objects.filter(pk=assertion.pk).exists()
    assert projection_models.PendingProjection.objects.filter(pk=other.pk).exists(), "settling one row never touches another, whatever their seqs"
