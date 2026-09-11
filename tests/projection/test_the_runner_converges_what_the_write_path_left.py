"""The runner converges what the write path left (A7).

A write whose drawing failed reports `pending` and leaves its outbox row. The
runner — `graph_engine/runner.py`, what `reproject --incremental --loop` runs —
applies it through the same `replay` the manual command uses, under the
organization's projection lock, and settles exactly what it read. `rebuild`
takes the same lock, so a runner pass and a rebuild never interleave on one
organization.

History: nothing ran `reproject --incremental` unattended; a failed drawing
stayed owed until an operator noticed the lag.
"""

import datetime
import threading
import time

import pytest
from asgiref.sync import sync_to_async
from django.db import connection
from core import models as core_models
from graph_engine import locks, projector, runner, watermark
from graph_engine.controller import GraphController
from tests.support import drawing, graphs, sessions, writes


def _down(*args, **kwargs):
    raise RuntimeError("projector down")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_pass_draws_the_pending_act_and_empties_the_outbox(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector, monkeypatch) -> None:
    monkeypatch.setattr(projector, "reproject_refs", _down)
    failed = await api_schema.execute(writes.ASSERT_ENTITY_EXISTS, variable_values={"input": {"term": "AIS", "supportingEvidence": []}}, context_value=simple_api_context)
    assert failed.errors is None and failed.data["assertEntityExists"]["pending"] is True
    ref = failed.data["assertEntityExists"]["instance"]["id"]
    monkeypatch.undo()

    @sync_to_async
    def converge():
        assert drawing.vertices_with_ref(test_graph, ref) == 0, "the failed draw left nothing"
        passes = runner.run_once(GraphController(projector=table_projector), [test_graph.organization])
        return passes, drawing.vertices_with_ref(test_graph, ref), watermark.pending_count(test_graph.organization), watermark.position(test_graph)

    passes, vertices, pending, position = await converge()
    assert len(passes) == 1 and passes[0].settled == 1 and not passes[0].idle
    assert vertices == 1, "the runner drew what the request could not"
    assert pending == 0
    assert position.lag == 0


@pytest.mark.django_db(transaction=True)
def test_an_idle_organization_costs_no_lock(test_graph: core_models.Graph, table_projector) -> None:
    [done] = runner.run_once(GraphController(projector=table_projector), [test_graph.organization])
    assert done.idle and done.report is None and done.settled == 0
    assert not locks.is_locked(test_graph.organization)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_pass_leaves_an_organization_another_session_is_redrawing(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector, monkeypatch) -> None:
    monkeypatch.setattr(projector, "reproject_refs", _down)
    await api_schema.execute(writes.ASSERT_ENTITY_EXISTS, variable_values={"input": {"term": "AIS", "supportingEvidence": []}}, context_value=simple_api_context)
    monkeypatch.undo()

    @sync_to_async
    def with_the_lock_held_elsewhere():
        other = sessions.raw_connection()
        try:
            with other.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(%s, %s)", [locks.LOCK_NAMESPACE, int(test_graph.organization.pk)])
            assert locks.is_locked(test_graph.organization)
            [skipped] = runner.run_once(GraphController(projector=table_projector), [test_graph.organization], wait_for_lock=False)
            still_owed = watermark.pending_count(test_graph.organization)
        finally:
            other.close()  # the session ends, and so does its lock
        [done] = runner.run_once(GraphController(projector=table_projector), [test_graph.organization], wait_for_lock=False)
        return skipped, still_owed, done

    skipped, still_owed, done = await with_the_lock_held_elsewhere()
    assert skipped.locked_elsewhere and skipped.settled == 0
    assert still_owed == 1, "nothing was applied under somebody else's lock"
    assert done.settled == 1, "and the next pass, with the lock free, applied it"


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_waits_for_the_organizations_lock(test_graph: core_models.Graph, table_projector) -> None:
    other = sessions.raw_connection()
    finished = threading.Event()

    def rebuild_in_another_thread() -> None:
        try:
            graphs.rebuild(test_graph.pk, table_projector)
        finally:
            connection.close()
            finished.set()

    try:
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s, %s)", [locks.LOCK_NAMESPACE, int(test_graph.organization.pk)])
        worker = threading.Thread(target=rebuild_in_another_thread, daemon=True)
        worker.start()
        assert not finished.wait(1.5), "the rebuild is queued behind the lock, not running beside its holder"
    finally:
        other.close()
    assert finished.wait(30), "and it runs once the lock is released"
    worker.join(5)
    assert watermark.position(test_graph).status == "consistent"


@pytest.mark.django_db(transaction=True)
def test_the_lock_is_not_granted_twice_across_sessions(test_graph: core_models.Graph) -> None:
    other = sessions.raw_connection()
    try:
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s, %s)", [locks.LOCK_NAMESPACE, int(test_graph.organization.pk)])
        with locks.organization_projection_lock(test_graph.organization, wait=False) as held:
            assert held is False
    finally:
        other.close()
    with locks.organization_projection_lock(test_graph.organization, wait=False) as held:
        assert held is True
        assert locks.is_locked(test_graph.organization)
    assert not locks.is_locked(test_graph.organization), "released on exit"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_young_row_is_left_for_the_next_pass(api_schema, simple_api_context, test_graph: core_models.Graph, table_projector, monkeypatch) -> None:
    """The grace window: a row the request may still be drawing is not raced."""
    monkeypatch.setattr(projector, "reproject_refs", _down)
    await api_schema.execute(writes.ASSERT_ENTITY_EXISTS, variable_values={"input": {"term": "AIS", "supportingEvidence": []}}, context_value=simple_api_context)
    monkeypatch.undo()

    @sync_to_async
    def passes():
        controller = GraphController(projector=table_projector)
        [young] = runner.run_once(controller, [test_graph.organization], older_than=datetime.timedelta(hours=1))
        owed_after_young = watermark.pending_count(test_graph.organization)
        cursor_while_owed = watermark.position(test_graph).cursor
        head = watermark.max_seq(test_graph.organization)
        [old] = runner.run_once(controller, [test_graph.organization], older_than=datetime.timedelta(seconds=0))
        return young, owed_after_young, cursor_while_owed, head, old, watermark.pending_count(test_graph.organization)

    young, owed, cursor_while_owed, head, old, owed_after = await passes()
    assert young.settled == 0 and owed == 1, "too young: left alone"
    assert cursor_while_owed < head, "and still holding the cursor down"
    assert old.settled == 1 and owed_after == 0


@pytest.mark.django_db(transaction=True)
def test_the_loop_runs_one_pass_and_stops(test_graph: core_models.Graph, table_projector) -> None:
    stop = threading.Event()
    started = time.monotonic()
    state = runner.run_forever(GraphController(projector=table_projector), interval=0.05, stop=stop, max_iterations=1)
    assert state.passes == 1 and state.failures == 0
    assert time.monotonic() - started < 5

    stop.set()
    state = runner.run_forever(GraphController(projector=table_projector), interval=60, stop=stop)
    assert state.passes == 0, "a stop set before the first pass runs nothing and does not wait"


@pytest.mark.django_db(transaction=True)
def test_a_failing_organization_is_backed_off_not_fatal(test_graph: core_models.Graph, table_projector, monkeypatch) -> None:
    calls = []

    def explode(controller, organizations, **kwargs):
        calls.append(organizations[0].pk)
        raise RuntimeError("poison pill")

    monkeypatch.setattr(runner, "run_once", explode)
    stop = threading.Event()
    state = runner.run_forever(GraphController(projector=table_projector), interval=0.01, stop=stop, max_iterations=4)
    assert state.failures >= 1
    assert len(calls) < 4, "after a failure the organization is skipped for a pass or more"
    assert state.passes == 4, "the loop itself kept going"
