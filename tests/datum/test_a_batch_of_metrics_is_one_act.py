"""A batch of metrics is one act, recorded once (C6, `evidence/metric_batch.py`).

`assertMetricValues` is how an app states what it computed: many values about many data, one
assertion, the structures created as needed. A metric may name its own uuid, and then a retried
batch records nothing twice and a race between two copies folds once. One that names none gets a
minted uuid, and a rerun is a second measurement. A batch that cannot be recorded is refused whole.
"""

import threading
import uuid
from collections.abc import Callable
from typing import Any

import kante
import pytest
from asgiref.sync import sync_to_async
from authentikate.models import Organization
from django.db import connection, connections, transaction
from kante.context import HttpContext

from evidence import claims as claims_module
from evidence import metric_batch
from evidence import models as evidence_models
from evidence import writer
from tests.support import writes

TABLE = "@mikro/tabledataset"
ROI = "@mikro/annotation"


def stated(identifier: str = ROI, object: str = "1", key: str = "area", value: Any = 4555.0, value_kind: str = "FLOAT", **extra: Any) -> dict[str, Any]:
    return {"uuid": str(uuid.uuid4()), "identifier": identifier, "object": object, "key": key, "value": value, "valueKind": value_kind, **extra}


async def assert_values(api_schema: kante.Schema, ctx: HttpContext, metrics: list[dict[str, Any]]) -> dict[str, Any]:
    return (await writes.execute(api_schema, ctx, writes.ASSERT_METRIC_VALUES, {"input": {"metrics": metrics}}))["assertMetricValues"]


async def refused(api_schema: kante.Schema, ctx: HttpContext, metrics: list[dict[str, Any]]) -> str:
    result = await api_schema.execute(writes.ASSERT_METRIC_VALUES, variable_values={"input": {"metrics": metrics}}, context_value=ctx)
    assert result.errors, "the batch should have been refused"
    return str(result.errors[0])


def _rows(**filters: Any) -> list[evidence_models.Metric]:
    return list(evidence_models.Metric.all_objects.select_related("structure", "assertion").filter(**filters))


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_many_values_about_many_data_are_one_assertion(api_schema: kante.Schema, api_context: HttpContext) -> None:
    batch = [stated(object="1", unit="µm**2"), stated(object="2", value=12.5), stated(identifier=TABLE, object="7", key="sum_over_mean_field")]
    payload = await assert_values(api_schema, api_context, batch)

    assert payload["recorded"] == 3 and payload["pending"] is False
    assert payload["assertion"]["subject"] == str(api_context.request.user.id)
    assert payload["assertion"]["appId"] == str(api_context.request.client.id)
    assert [metric["value"] for metric in payload["metrics"]] == [4555.0, 12.5, 4555.0]
    rows = await sync_to_async(_rows)(source_uuid__in=[metric["uuid"] for metric in batch])
    assert {str(row.assertion_id) for row in rows} == {payload["assertion"]["id"]}
    assert {(row.structure.identifier, row.structure.object) for row in rows} == {(ROI, "1"), (ROI, "2"), (TABLE, "7")}
    assert {row.unit for row in rows} == {"µm**2", None}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_batch_states_every_kind_of_value(api_schema: kante.Schema, api_context: HttpContext) -> None:
    """A category and a count are their own kinds: `assertMetricValue`'s vocabulary has no category."""
    batch = [stated(key="class", value="segmenter_v2/class_3", value_kind="CATEGORY"), stated(key="count", value=3, value_kind="INT"), stated(key="at", value=[1.0, 2.0, 3.0], value_kind="THREE_D_VECTOR")]
    await assert_values(api_schema, api_context, batch)

    rows = {row.key: row for row in await sync_to_async(_rows)(source_uuid__in=[metric["uuid"] for metric in batch])}
    assert (rows["class"].value, rows["class"].value_kind) == ("segmenter_v2/class_3", "CATEGORY")
    assert (rows["count"].value, rows["count"].value_kind) == (3, "INT")
    assert rows["at"].value == [1.0, 2.0, 3.0]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_when_it_was_observed_and_how_sure_are_the_callers(api_schema: kante.Schema, api_context: HttpContext) -> None:
    batch = [stated(observedAt="2026-06-01T12:00:00+00:00", confidence=0.5, confidenceType="p-value"), stated(object="2")]
    await assert_values(api_schema, api_context, batch)

    told, silent = await sync_to_async(_rows)(source_uuid=batch[0]["uuid"]), await sync_to_async(_rows)(source_uuid=batch[1]["uuid"])
    assert told[0].observed_at.isoformat() == "2026-06-01T12:00:00+00:00"
    assert (told[0].confidence, told[0].confidence_type) == (0.5, "p-value")
    assert silent[0].observed_at == silent[0].asserted_at and silent[0].confidence is None


def unnamed(**fields: Any) -> dict[str, Any]:
    return {key: value for key, value in stated(**fields).items() if key != "uuid"}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_metric_that_names_no_uuid_gets_one(api_schema: kante.Schema, api_context: HttpContext) -> None:
    payload = await assert_values(api_schema, api_context, [unnamed(object="1"), unnamed(object="2")])

    assert payload["recorded"] == 2 and [metric["value"] for metric in payload["metrics"]] == [4555.0, 4555.0]
    rows = await sync_to_async(_rows)(assertion_id=payload["assertion"]["id"])
    assert len({row.source_uuid for row in rows}) == 2 and all(row.source_uuid is not None for row in rows)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_rerunning_a_batch_that_names_no_uuids_is_a_second_measurement(api_schema: kante.Schema, api_context: HttpContext) -> None:
    """Both stand, each under its own act, and both reach what the datum informs."""
    entity = await writes.assert_entity(api_schema, api_context, "AIS", evidence=[{"identifier": ROI, "object": "1", "metrics": []}])
    first = await assert_values(api_schema, api_context, [unnamed(value=2.0)])
    second = await assert_values(api_schema, api_context, [unnamed(value=2.0)])

    assert second["recorded"] == 1 and second["assertion"]["id"] != first["assertion"]["id"]
    state = await evidence_models.State.all_objects.aget(claim_ref=entity["instance"]["id"], key="area")
    assert (state.n, state.sum) == (2, 4.0)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_batch_may_mix_named_and_unnamed_metrics(api_schema: kante.Schema, api_context: HttpContext) -> None:
    named = stated(object="1")
    first = await assert_values(api_schema, api_context, [named, unnamed(object="2")])
    again = await assert_values(api_schema, api_context, [named, unnamed(object="2")])

    assert (first["recorded"], again["recorded"]) == (2, 1)
    assert again["metrics"][0]["id"] == first["metrics"][0]["id"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_retried_batch_records_nothing_twice(api_schema: kante.Schema, api_context: HttpContext) -> None:
    """The retry mints no assertion and still answers with every metric, in the order given."""
    batch = [stated(object="1"), stated(object="2")]
    first = await assert_values(api_schema, api_context, batch)
    again = await assert_values(api_schema, api_context, list(reversed(batch)))

    assert again["recorded"] == 0 and again["assertion"] is None
    assert [metric["id"] for metric in again["metrics"]] == [metric["id"] for metric in reversed(first["metrics"])]
    assert await sync_to_async(evidence_models.Metric.all_objects.count)() == 2


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_batch_half_recorded_records_the_other_half(api_schema: kante.Schema, api_context: HttpContext) -> None:
    done, new = stated(object="1"), stated(object="2")
    first = await assert_values(api_schema, api_context, [done])
    payload = await assert_values(api_schema, api_context, [done, new])

    assert payload["recorded"] == 1 and payload["assertion"]["id"] != first["assertion"]["id"]
    assert len(payload["metrics"]) == 2


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_metric_reaches_what_its_datum_informs_once(api_schema: kante.Schema, api_context: HttpContext) -> None:
    """Rolled up through INFORMS, and a retry does not count it again."""
    entity = await writes.assert_entity(api_schema, api_context, "AIS", evidence=[{"identifier": ROI, "object": "1", "metrics": []}])
    batch = [stated(object="1", value=2.0), stated(object="1", value=3.0)]
    await assert_values(api_schema, api_context, batch)
    await assert_values(api_schema, api_context, batch)

    state = await evidence_models.State.all_objects.aget(claim_ref=entity["instance"]["id"], key="area")
    assert (state.n, state.sum) == (2, 5.0)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_value_cites_the_table_it_was_read_from(api_schema: kante.Schema, api_context: HttpContext) -> None:
    table = await writes.create_structure(api_schema, api_context, identifier=TABLE, object="7")
    batch = [stated(object="1", derivedFrom=[table]), stated(object="2", derivedFrom=[table])]
    payload = await assert_values(api_schema, api_context, batch)

    citing = {metric["id"] for metric in payload["metrics"]}
    links = [link async for link in evidence_models.Link.all_objects.filter(kind=evidence_models.Link.Kind.DERIVED_FROM, target_ref=table)]
    assert {link.source_ref for link in links} == citing
    assert {str(link.assertion_id) for link in links} == {payload["assertion"]["id"]}
    assert all(link.observed_at == link.assertion.asserted_at for link in await sync_to_async(lambda: list(evidence_models.Link.all_objects.select_related("assertion").filter(target_ref=table)))())


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_correction_retracts_and_cites_what_it_corrects(api_schema: kante.Schema, api_context: HttpContext) -> None:
    wrong = stated(value=1.0)
    await assert_values(api_schema, api_context, [wrong])
    right = stated(value=2.0, supersedes=wrong["uuid"])
    await assert_values(api_schema, api_context, [right])

    old = (await sync_to_async(_rows)(source_uuid=wrong["uuid"]))[0]
    new = (await sync_to_async(_rows)(source_uuid=right["uuid"]))[0]
    standing = await sync_to_async(lambda: set(claims_module.standing(evidence_models.Metric.all_objects.filter(pk__in=[old.pk, new.pk]), "metric").values_list("pk", flat=True)))()
    assert standing == {new.pk}
    assert await evidence_models.Link.all_objects.filter(kind=evidence_models.Link.Kind.DERIVED_FROM, source_ref=str(new.pk), target_ref=str(old.pk), assertion_id=new.assertion_id).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_batch_that_cannot_be_recorded_is_refused_whole(api_schema: kante.Schema, api_context: HttpContext) -> None:
    good = stated(object="1")
    message = await refused(api_schema, api_context, [good, stated(object="2", value="high")])
    assert "'area' is declared FLOAT" in message
    assert not await evidence_models.Metric.all_objects.aexists()
    assert not await evidence_models.Structure.all_objects.aexists()
    assert not await evidence_models.Assertion.all_objects.aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_what_a_batch_names_has_to_exist(api_schema: kante.Schema, api_context: HttpContext) -> None:
    missing = str(uuid.uuid4())
    assert "derived" in (await refused(api_schema, api_context, [stated(derivedFrom=[missing])])).lower()
    assert missing in await refused(api_schema, api_context, [stated(supersedes=missing)])
    assert not await evidence_models.Metric.all_objects.aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_uuid_names_one_metric(api_schema: kante.Schema, api_context: HttpContext) -> None:
    twice = stated()
    assert "more than once" in await refused(api_schema, api_context, [twice, {**twice, "object": "2"}])
    assert not await evidence_models.Metric.all_objects.aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("changed", [{"object": "2"}, {"identifier": TABLE}, {"key": "length"}, {"valueKind": "INT"}])
async def test_a_uuid_reused_for_something_else_is_a_collision(api_schema: kante.Schema, api_context: HttpContext, changed: dict[str, str]) -> None:
    """A retry repeats the datum, key and kind. Anything else would lose its value while the caller was told it went through."""
    first = stated()
    await assert_values(api_schema, api_context, [first])

    assert "already name a different metric" in await refused(api_schema, api_context, [{**first, **changed}])
    assert await evidence_models.Metric.all_objects.acount() == 1


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_retry_with_another_value_keeps_the_first(api_schema: kante.Schema, api_context: HttpContext) -> None:
    first = stated(value=1.0)
    await assert_values(api_schema, api_context, [first])
    again = await assert_values(api_schema, api_context, [{**first, "value": 2.0}])

    assert again["recorded"] == 0 and again["metrics"][0]["value"] == 1.0


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_time_without_an_offset_is_utc(api_schema: kante.Schema, api_context: HttpContext) -> None:
    """As it is on `assertMetricValue`: when a value was observed decides which one is latest."""
    batch = [stated(observedAt="2026-06-01T12:00:00")]
    await assert_values(api_schema, api_context, batch)

    row = (await sync_to_async(_rows)(source_uuid=batch[0]["uuid"]))[0]
    assert row.observed_at.isoformat() == "2026-06-01T12:00:00+00:00"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_batch_has_a_size(api_schema: kante.Schema, api_context: HttpContext) -> None:
    assert await refused(api_schema, api_context, [])
    assert await refused(api_schema, api_context, [stated(object=str(index)) for index in range(5001)])


def _foreign_metric(organization: Organization, source: uuid.UUID) -> None:
    assertion = writer.create_assertion(organization, subject="someone", app_id="elsewhere")
    with transaction.atomic():
        metric_batch.record_into(organization, [metric_batch.StatedMetric(source_uuid=source, identifier=ROI, object="1", key="area", value=1.0, value_kind="FLOAT")], assertion, metric_batch.Recorded())


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_uuid_another_organization_holds_is_refused(api_schema: kante.Schema, api_context: HttpContext, other_organization: Organization) -> None:
    """Skipped, the value would be lost while the caller was told its batch went through."""
    source = uuid.uuid4()
    await sync_to_async(_foreign_metric)(other_organization, source)

    assert "already name a different metric" in await refused(api_schema, api_context, [{**stated(), "uuid": str(source)}])
    row = (await sync_to_async(_rows)(source_uuid=source))[0]
    assert row.organization_id == other_organization.pk


def _in_thread(work: Callable[[], None]) -> threading.Thread:
    def run() -> None:
        try:
            work()
        finally:
            connections.close_all()

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def _a_backend_is_waiting_on_a_lock() -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_locks WHERE NOT granted")
        return cursor.fetchone()[0] > 0


@pytest.mark.django_db(transaction=True)
def test_two_copies_racing_past_the_check_fold_once(organization: Organization) -> None:
    """Both have passed `outstanding`: the second blocks on the unique index until the first commits, then records nothing."""
    entity = writer.ensure_term(organization, evidence_models.Instance.Kind.ENTITY, "AIS")
    opening = writer.create_assertion(organization, subject="someone", app_id="tool")
    instance = evidence_models.Instance.objects.create_for_organization(organization=organization, kind=evidence_models.Instance.Kind.ENTITY, term=entity, assertion=opening)
    structure_kind = writer.ensure_structure_kind(organization, ROI)
    structure = writer.ensure_structure(organization, kind=structure_kind, object="1", assertion=opening)
    # The term exists, as it does for all but a key's first metric: the second copy then waits on
    # the metric's uuid, not on the first copy's uncommitted term.
    writer.ensure_metric_kind(organization, structure_kind, "area", "FLOAT")
    writer.create_link(organization, kind=evidence_models.Link.Kind.INFORMS, source_ref=str(structure.pk), target_ref=str(instance.pk), assertion=opening)
    batch = [metric_batch.StatedMetric(source_uuid=uuid.uuid4(), identifier=ROI, object="1", key="area", value=2.0, value_kind="FLOAT")]

    first_wrote, may_commit = threading.Event(), threading.Event()
    results: dict[str, metric_batch.Recorded] = {}
    failures: list[BaseException] = []

    def first() -> None:
        try:
            with transaction.atomic():
                assertion = writer.create_assertion(organization, subject="someone", app_id="tool")
                results["first"] = metric_batch.Recorded()
                metric_batch.record_into(organization, batch, assertion, results["first"])
                first_wrote.set()
                assert may_commit.wait(30)
        except BaseException as error:  # noqa: BLE001  re-raised on the test's thread
            failures.append(error)
            first_wrote.set()

    def second() -> None:
        try:
            with transaction.atomic():
                assertion = writer.create_assertion(organization, subject="someone", app_id="tool")
                results["second"] = metric_batch.Recorded()
                metric_batch.record_into(organization, batch, assertion, results["second"])
        except BaseException as error:  # noqa: BLE001  re-raised on the test's thread
            failures.append(error)

    one = _in_thread(first)
    assert first_wrote.wait(30)
    two = _in_thread(second)
    second_waited = False
    for _ in range(600):
        second_waited = _a_backend_is_waiting_on_a_lock()
        if second_waited or not two.is_alive():
            break
        threading.Event().wait(0.05)
    may_commit.set()
    one.join(30)
    two.join(30)

    assert not failures, failures
    assert second_waited, "the second copy should have blocked on the first's uncommitted uuid"
    assert (results["first"].metrics, results["second"].metrics) == (1, 0)
    assert evidence_models.Metric.all_objects.count() == 1
    state = evidence_models.State.all_objects.get(claim_ref=str(instance.pk), key="area")
    assert (state.n, state.sum) == (1, 2.0)
