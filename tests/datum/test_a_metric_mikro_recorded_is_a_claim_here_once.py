"""A metric mikro recorded is a claim here, recorded once (C6, `evidence/ingest.py`).

mikro keeps every metric in its change feed; kraph reads it a page at a time and records each
metric as a `Metric` claim about the `Structure` mikro's object is. One transaction of mikro's
is one act, attributed to the producer mikro recorded. A page applied twice records nothing
twice; a withdrawal is a retraction, never a delete; a correction retracts and cites what it
corrects; an entry that can never be applied is poison, not skipped.
"""

import uuid

import pytest
from arkitekt_service.feed.consumer import Poison
from asgiref.sync import sync_to_async
from authentikate.models import Client, Organization, User

from evidence import claims as claims_module
from evidence import models as evidence_models
from tests.support import feeds, writes

pytestmark = pytest.mark.django_db(transaction=True)

DATASET = "@mikro/arraydataset"


def _metric(source: uuid.UUID) -> evidence_models.Metric:
    return evidence_models.Metric.all_objects.select_related("structure", "assertion").get(source_uuid=source)


def _stands(metric: evidence_models.Metric) -> bool:
    return claims_module.standing(evidence_models.Metric.all_objects.filter(pk=metric.pk), "metric").exists()


def test_a_metric_is_a_claim_about_the_datum_it_measures(organization: Organization) -> None:
    """The metric is recorded under the producer mikro verified: its user (as this service's user), its app, its task."""
    page = [feeds.entry(5, feeds.body(DATASET, "17", "ais_suite.measure_profile/threshold_distance", magnitude=31.2, unit="µm", task="task-1"))]
    recorded = feeds.apply(organization, page)

    metric = _metric(page[0].uuid)
    assert recorded.metrics == 1
    assert (metric.structure.identifier, metric.structure.object) == (DATASET, "17")
    assert (metric.key, metric.value, metric.unit, metric.value_kind) == ("ais_suite.measure_profile/threshold_distance", 31.2, "µm", "FLOAT")
    user = User.objects.get(sub="mikro-user-1", iss=feeds.ISSUER)
    client = Client.objects.get(client_id="ais-client")
    assert (metric.assertion.subject, metric.assertion.app_id, metric.assertion.action_id) == (str(user.id), str(client.id), "task-1")
    assert metric.assertion.action_args["app"] == "ais_suite" and metric.assertion.action_args["app_version"] == "0.4.1"
    assert metric.observed_at.isoformat() == "2026-10-19T09:12:03+00:00"


def test_a_code_is_a_category(organization: Organization) -> None:
    page = [feeds.entry(5, feeds.body(DATASET, "17", "segmenter_v2/class", code="segmenter_v2/class_3"))]
    feeds.apply(organization, page)
    metric = _metric(page[0].uuid)
    assert (metric.value, metric.value_kind) == ("segmenter_v2/class_3", "CATEGORY")


def test_a_page_applied_twice_records_nothing_twice(organization: Organization) -> None:
    page = [feeds.entry(5, feeds.body(DATASET, "17", "a/b", magnitude=1.0, unit="s"))]
    feeds.apply(organization, page)
    again = feeds.apply(organization, page)
    assert again.metrics == 0
    assert evidence_models.Metric.all_objects.count() == 1
    # An act that would record nothing mints no assertion.
    assert evidence_models.Assertion.objects.for_organization(organization).count() == 1


def test_one_transaction_of_mikros_is_one_act(organization: Organization) -> None:
    page = [
        feeds.entry(5, feeds.body(DATASET, "17", "a/b", magnitude=1.0, unit="s")),
        feeds.entry(5, feeds.body(DATASET, "18", "a/b", magnitude=2.0, unit="s")),
        feeds.entry(6, feeds.body(DATASET, "17", "a/b", magnitude=3.0, unit="s")),
    ]
    feeds.apply(organization, page)
    assert evidence_models.Assertion.objects.for_organization(organization).count() == 2
    assert {m.assertion_id for m in evidence_models.Metric.all_objects.filter(source_uuid__in=[page[0].uuid, page[1].uuid])} == {_metric(page[0].uuid).assertion_id}
    # One individual per datum, however often it is measured.
    assert evidence_models.Structure.all_objects.filter(organization=organization, identifier=DATASET).count() == 2


def test_a_withdrawn_metric_is_retracted_never_deleted(organization: Organization) -> None:
    uid = uuid.uuid4()
    feeds.apply(organization, [feeds.entry(5, feeds.body(DATASET, "17", "a/b", magnitude=1.0, unit="s"), uid=uid), feeds.withdrawal(6, uid)])
    metric = _metric(uid)
    assert not _stands(metric)
    # A withdrawal is mikro's: no user of it is named.
    standing = evidence_models.Standing.objects.for_organization(organization).get(target_id=str(metric.pk))
    assert standing.assertion.subject == "live.arkitekt.mikro"


def test_a_metric_gone_before_it_was_read_records_nothing(organization: Organization) -> None:
    uid = uuid.uuid4()
    recorded = feeds.apply(organization, [feeds.entry(5, None, uid=uid), feeds.withdrawal(6, uid)])
    assert recorded.metrics == 0 and evidence_models.Assertion.objects.for_organization(organization).count() == 0


def test_a_correction_retracts_and_cites_what_it_corrects(organization: Organization) -> None:
    first = uuid.uuid4()
    feeds.apply(organization, [feeds.entry(5, feeds.body(DATASET, "17", "a/b", magnitude=1.0, unit="s"), uid=first)])
    second = uuid.uuid4()
    feeds.apply(organization, [feeds.entry(6, feeds.body(DATASET, "17", "a/b", magnitude=1.5, unit="s", supersedes=first), uid=second)])

    old, new = _metric(first), _metric(second)
    assert not _stands(old) and _stands(new)
    assert evidence_models.Link.objects.for_organization(organization).filter(kind=evidence_models.Link.Kind.DERIVED_FROM, source_ref=str(new.pk), target_ref=str(old.pk)).exists()


@pytest.mark.parametrize(
    "broken",
    [
        {"magnitude": None, "code": None},
        {"magnitude": "thirty"},
        {"target": None},
        {"created_at": "yesterday"},
    ],
)
def test_an_entry_that_can_never_be_applied_is_poison(organization: Organization, broken: dict) -> None:
    good = feeds.body(DATASET, "17", "a/b", magnitude=1.0, unit="s")
    with pytest.raises(Poison):
        feeds.apply(organization, [feeds.entry(5, {**good, **broken})])
    assert evidence_models.Metric.all_objects.count() == 0


def test_an_update_is_poison(organization: Organization) -> None:
    updated = feeds.entry(5, feeds.body(DATASET, "17", "a/b", magnitude=1.0, unit="s"))
    with pytest.raises(Poison):
        feeds.apply(organization, [type(updated)(**{**updated.__dict__, "kind": "UPDATED"})])


def test_a_page_is_one_organizations(organization: Organization, other_organization: Organization) -> None:
    feeds.apply(organization, [feeds.entry(5, feeds.body(DATASET, "17", "a/b", magnitude=1.0, unit="s"))])
    assert evidence_models.Metric.objects.for_organization(other_organization).count() == 0
    assert evidence_models.Structure.objects.for_organization(other_organization).count() == 0


NODE_PROPERTIES = """
    query N($id: ID!, $graph: ID!) { node(id: $id, graph: $graph) { ... on Entity { properties } } }
"""


@pytest.mark.asyncio
async def test_a_metric_from_mikro_moves_the_value_it_informs(api_schema, simple_api_context, test_graph) -> None:
    """A datum an entity is evidence-backed by gets a metric in mikro: the entity's derived value folds it in, and is redrawn."""
    created = await api_schema.execute(
        writes.ASSERT_ENTITY_EXISTS,
        variable_values={"input": {"term": "AIS", "supportingEvidence": [{"identifier": "ROI", "object": "roi-17", "metrics": [{"key": "vector_length", "value": 30.0, "valueKind": "FLOAT"}]}]}},
        context_value=simple_api_context,
    )
    assert created.errors is None, created.errors
    entity = created.data["assertEntityExists"]["instance"]["id"]

    await sync_to_async(feeds.apply)(test_graph.organization, [feeds.entry(5, feeds.body("ROI", "roi-17", "vector_length", magnitude=10.0, unit="µm"), organization=test_graph.organization.slug)])

    read = await api_schema.execute(NODE_PROPERTIES, variable_values={"id": entity, "graph": str(test_graph.pk)}, context_value=simple_api_context)
    assert read.errors is None, read.errors
    assert read.data["node"]["properties"]["avg_length"] == pytest.approx(20.0)
