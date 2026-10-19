"""kraph reads mikro's metrics through its hook agent: over HTTP, signed, once (C7).

The action a trigger on mikro's metrics and a schedule run, end to end: a signed read of the
feed (``arkitekt_service.feed``), each page applied with the organization's cursor. mikro's side
is stood up in this process (`tests.support.feed_urls`): entries in the feed tables, bodies
rendered from `feeds.BODIES`, served at ``/_feed`` by the live server.
"""

import pytest
from arkitekt_service import trust
from arkitekt_service.feed.models import FeedCursor
from arkitekt_service.hook import StructureRef
from authentikate.models import Organization
from joserfc.jwk import OKPKey

from evidence import models as evidence_models
from kraph_server.hook_agent import FeedHalted, ingest_metrics
from tests.support import feeds

pytestmark = pytest.mark.django_db(transaction=True)

KRAPH_KEY = OKPKey.generate_key("Ed25519")
DATASET = "@mikro/arraydataset"


@pytest.fixture
def mikro(settings, live_server) -> None:
    """mikro's feed at the live server, and kraph's instance key, as the hub would vouch for it."""
    prefix = f"/{settings.MY_SCRIPT_NAME.strip('/')}" if settings.MY_SCRIPT_NAME else ""
    settings.ROOT_URLCONF = "tests.support.feed_urls"
    settings.INSTANCE = {"PRIVATE_KEY": KRAPH_KEY.as_pem(private=True).decode(), "TRUST_JWKS": {"keys": [{**trust.public_jwk(KRAPH_KEY), "service": "kraph"}]}}
    settings.MIKRO_FEED = {"URL": f"{live_server.url}{prefix}/_feed", "IDENTIFIER": "mikro"}
    feeds.BODIES.clear()


def test_a_run_ingests_everything_new_and_the_next_finds_nothing(mikro, organization: Organization) -> None:
    feeds.serve(organization.slug, [feeds.body(DATASET, str(i), "a/b", magnitude=float(i), unit="s") for i in range(3)])

    first = ingest_metrics(organization=organization.slug, metric=StructureRef(identifier="@mikro/metric", object="1"))
    assert (first["ended"], first["applied"]) == ("CAUGHT_UP", 3)
    assert evidence_models.Metric.objects.for_organization(organization).count() == 3

    # A schedule's run: no metric, and nothing new.
    again = ingest_metrics(organization=organization.slug)
    assert (again["ended"], again["applied"]) == ("CAUGHT_UP", 0)
    cursor = FeedCursor.objects.get(feed="@mikro/metric", organization=organization.slug)
    assert cursor.producer == "mikro" and cursor.halted is None and cursor.entry > 0


def test_a_run_reads_its_own_organization_only(mikro, organization: Organization, other_organization: Organization) -> None:
    feeds.serve(organization.slug, [feeds.body(DATASET, "1", "a/b", magnitude=1.0, unit="s")])
    feeds.serve(other_organization.slug, [feeds.body(DATASET, "2", "a/b", magnitude=2.0, unit="s")])

    assert ingest_metrics(organization=other_organization.slug)["applied"] == 1
    assert evidence_models.Metric.objects.for_organization(organization).count() == 0
    assert evidence_models.Metric.objects.for_organization(other_organization).count() == 1


def test_a_poison_entry_halts_the_organizations_feed(mikro, organization: Organization) -> None:
    feeds.serve(organization.slug, [{**feeds.body(DATASET, "1", "a/b", magnitude=1.0, unit="s"), "magnitude": None}])
    # A failed run, as rekuest shows it -- every run, until someone resumes the feed.
    for _ in range(2):
        with pytest.raises(FeedHalted, match="neither a quantity nor a code"):
            ingest_metrics(organization=organization.slug)
    assert evidence_models.Metric.all_objects.count() == 0
    assert FeedCursor.objects.get(organization=organization.slug).entry == 0


def test_a_hub_that_tells_kraph_of_no_mikro_ingests_nothing(mikro, settings, organization: Organization) -> None:
    settings.MIKRO_FEED = None
    assert ingest_metrics(organization=organization.slug) == {"ended": "NO_FEED", "applied": 0}


def test_an_organization_kraph_has_not_seen_is_read_all_the_same(mikro) -> None:
    """rekuest gives every organization the agent; nobody need have opened kraph there first."""
    feeds.serve("newcomer", [feeds.body(DATASET, "1", "a/b", magnitude=1.0, unit="s")])
    assert ingest_metrics(organization="newcomer")["applied"] == 1
    assert evidence_models.Metric.objects.for_organization(Organization.objects.get(slug="newcomer")).count() == 1


def test_one_transaction_of_mikros_is_one_act_however_many_pages_it_fills(mikro, organization: Organization) -> None:
    """A batch larger than a page is read whole (the feed never ends a page inside a transaction): one assertion."""
    feeds.serve(organization.slug, [feeds.body(DATASET, str(i), "a/b", magnitude=float(i), unit="s") for i in range(2500)])
    assert ingest_metrics(organization=organization.slug)["applied"] == 2500
    assert evidence_models.Assertion.objects.for_organization(organization).filter(metrics__isnull=False).distinct().count() == 1
