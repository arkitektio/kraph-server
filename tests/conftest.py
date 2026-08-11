import time
from typing import Generator
import pytest
import boto3
from moto import mock_aws
import os

from graph_engine.controller import GraphController
from graph_engine.engine.age_engine import AgeEngine
from api.schema import create_schema
from authentikate.models import Client, Organization, User, Membership
from kante.context import HttpContext, UniversalRequest
from strawberry.http.temporal_response import TemporalResponse
from dokker import local
from django.db import connections
from graph_engine.engine.testing.mock_cypher_engine import MockCypherEngine
from graph_engine import input_models as models
from graph_engine.materialize import materialize
from core import models as core_models


@pytest.fixture(scope="function")
def aws_credentials() -> None:
    """Mocked AWS Credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture(scope="function")
def s3(aws_credentials):
    with mock_aws():
        yield boto3.client("s3", region_name="us-east-1")


@pytest.fixture
def create_bucket1(s3) -> None:
    s3.create_bucket(Bucket="babanana")


@pytest.fixture
def create_bucket2(s3) -> None:
    s3.create_bucket(Bucket="cabanana")


@pytest.fixture(scope="session")
def backend_stack():
    docker_compose_path = os.path.join(os.path.dirname(__file__), "integration", "docker-compose.yaml")

    with local(docker_compose_path) as e:
        e.inspect()

        e.down()

        e.up()

        time.sleep(2)

        yield


# The identity `authentikate`'s static test token resolves to. Fixtures must build
# graphs under *this* organization, not one of their own invention: the auth
# extension overwrites the request's user and organization at execution time, so a
# graph owned by anything else belongs to a tenant the request cannot act for.
# That mismatch was invisible while `validate_graph_access` returned unconditionally;
# it stops being invisible the moment anything checks membership.
STATIC_USERNAME = "static_issuer_1"
STATIC_ORG_SLUG = "static_org"


def _static_identity():
    """The user, organization and membership the static test token authenticates as."""
    user, _ = User.objects.get_or_create(
        username=STATIC_USERNAME,
        defaults={"sub": "1", "iss": "static_issuer"},
    )
    org, _ = Organization.objects.get_or_create(slug=STATIC_ORG_SLUG)
    membership, _ = Membership.objects.get_or_create(user=user, organization=org)
    return user, org, membership


@pytest.fixture(scope="function")
def authenticated_context(db, backend_stack):
    user, org, membership = _static_identity()
    client, _ = Client.objects.get_or_create(client_id="oinsoins")

    request = UniversalRequest(
        _extensions={"token": "test"},
        _client=client,  # type: ignore
        _user=user,  # type: ignore
        _organization=org,  # type: ignore
    )
    request.set_membership(membership)  # type: ignore

    return HttpContext(request=request, response=TemporalResponse(), headers={"Authorization": "Bearer test"}, type="http")


@pytest.fixture(scope="session")
def bio_graph_schema() -> models.GraphDefinitionInput:
    """
    Fixture defined using EXPLICIT Pydantic Model constructors.
    Uses list-based definitions with key attributes.

    Note: Structures (ROI, ToldYouSo) are no longer defined in the schema.
    They are dynamically resolved from the structure identifier at write time.

    Every rollup rule here names an explicit metric key. A rule without one renders as
    `WHERE m.key = null`, which never matches, so the property silently stays unset and
    any test asserting on it passes vacuously. `build_rollup_query` now rejects that.
    """
    return models.GraphDefinitionInput(
        system_version="1.0.1",
        extensions=models.GraphExtensionsInput(
            # --- 1. ENTITIES ---
            entities=[
                models.EntityDefinitionInput(
                    key="AIS",
                    property_definitions=[
                        models.PropertyDefinitionInput(key="avg_length", type=models.PropertyType.FLOAT, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(source_node="ROI", key="vector_length", aggregation=models.AggregationFunction.MEAN)),
                        models.PropertyDefinitionInput(key="name", type=models.PropertyType.STRING, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(source_node="ToldYouSo", key="name", aggregation=models.AggregationFunction.LATEST)),
                    ],
                ),
                models.EntityDefinitionInput(key="Soma", property_definitions=[models.PropertyDefinitionInput(key="centroid", type=models.PropertyType.POINT_3D, derivation=models.DerivationType.LATEST, rule=models.DerivationRuleInput(source_node="ROI", key="centroid"))]),
                models.EntityDefinitionInput(
                    key="Cell",
                    property_definitions=[
                        models.PropertyDefinitionInput(key="id", type=models.PropertyType.STRING),
                        # These two express counting/summarising evidence attached via another
                        # node kind (a Mitosis event, an AIS entity). The current rollup shape is
                        # strictly (Metric)-[DESCRIBES]->(Structure)-[INFORMS]->(Entity), so they
                        # are modelled here as metric keys on the supporting structure.
                        models.PropertyDefinitionInput(key="mitosis_count", type=models.PropertyType.INTEGER, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(key="mitosis_event", source_node="ROI", aggregation=models.AggregationFunction.COUNT)),
                        models.PropertyDefinitionInput(key="ais_length_summary", type=models.PropertyType.FLOAT, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(key="vector_length", source_node="ROI", aggregation=models.AggregationFunction.LATEST)),
                    ],
                ),
            ],
            # --- 3. RELATIONS ---
            relations=[
                models.RelationDefinitionInput(
                    key="IS_CONNECTED_TO",
                    source=models.EntityDescriptorInput(keys=["Cell"]),
                    target=models.EntityDescriptorInput(keys=["Cell"]),
                    cardinality=models.Cardinality.ONE_TO_ONE,
                    properties=[models.PropertyDefinitionInput(key="distance", type=models.PropertyType.FLOAT, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(source_node="ROI", key="centroid", aggregation=models.AggregationFunction.EUCLIDEAN_RANGE))],
                ),
                models.RelationDefinitionInput(key="PART_OF", source=models.EntityDescriptorInput(keys=["AIS", "Soma"]), target=models.EntityDescriptorInput(keys=["Cell"])),
            ],
            # --- 4. EVENTS ---
            events=[
                models.EventDefinitionInput(
                    key="Mitosis",
                    kind=models.EventKind.INTRINSIC,
                    inputs=[models.EventRoleInput(key="Cell", role="a", descriptor=models.EntityDescriptorInput(keys=["Cell"]))],
                    outputs=[models.EventRoleInput(key="Cell", role="a", descriptor=models.EntityDescriptorInput(keys=["Cell"])), models.EventRoleInput(key="Cell", role="b", descriptor=models.EntityDescriptorInput(keys=["Cell"]))],
                    properties=[models.PropertyDefinitionInput(key="cell_count", type=models.PropertyType.INTEGER, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(source_node="ROI", key="cell_marker", aggregation=models.AggregationFunction.COUNT))],
                )
            ],
        ),
    )


@pytest.fixture(scope="function")
def test_graph(transactional_db, age_engine, bio_graph_schema, authenticated_context) -> core_models.Graph:
    """
    Create a test graph with the bio_graph schema.

    This is the standard test graph fixture that materializes a graph
    from the bio_graph_schema definition, creating all necessary
    Django models (EntityCategory, RelationCategory, etc.).
    """
    request = authenticated_context.request
    return materialize(
        bio_graph_schema,
        age_engine,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name="test_graph",
    )


@pytest.fixture(scope="function")
def mock_engine() -> MockCypherEngine:
    """A CypherEngine test double that records queries instead of executing them.

    Needs no database and no docker stack, so it is the right tool for asserting on the
    Cypher a code path *generates*, as opposed to what AGE does with it.
    """
    return MockCypherEngine()


@pytest.fixture
def mock_graph_controller(mock_engine, test_graph):
    """Create a graph controller with mock engine and test graph."""
    return GraphController(
        engine=mock_engine,
        subject="test_user",
        app_id="test_app",
    )


@pytest.fixture(scope="function")
def graph_controller(transactional_db, age_engine, test_graph) -> GraphController:
    """
    Create a graph controller with AGE engine and test graph.

    This fixture provides a ready-to-use GraphController instance
    that is connected to the test graph and AGE engine.
    """
    return GraphController(
        engine=age_engine,
        subject="test_user",
        app_id="test_app",
    )


@pytest.fixture(scope="function")
def bio_graph(transactional_db, age_engine, bio_graph_schema, authenticated_context) -> core_models.Graph:
    """
    Create a biological graph with the provided schema.
    Uses transactional_db to maintain database state across the fixture.
    The graph is created once and reused.
    """
    request = authenticated_context.request
    return materialize(
        bio_graph_schema,
        age_engine,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name="bio_graph",
    )


@pytest.fixture(scope="function")
def minimal_schema() -> models.GraphDefinitionInput:
    """A minimal schema for testing.

    Uses the canonical `*Input` names and `property_definitions`. The previous version
    passed `properties=`, which is not a field on EntityDefinitionInput, so the entity
    materialized with zero properties and any assertion about them passed vacuously.
    """
    return models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=[
                models.EntityDefinitionInput(
                    key="Person",
                    description="A person",
                    property_definitions=[
                        models.PropertyDefinitionInput(key="name", type=models.PropertyType.STRING),
                        models.PropertyDefinitionInput(key="age", type=models.PropertyType.INTEGER),
                    ],
                )
            ]
        ),
    )


# The dokker stack in tests/integration/docker-compose.yaml, as pinned by
# kraph_server/settings_test.py. _drop_all_age_graphs is destructive and unconditional,
# so it refuses to run anywhere else.
EXPECTED_TEST_DB_PORT = "5555"
EXPECTED_TEST_DB_HOST = "localhost"


def _assert_disposable_database() -> None:
    """Refuse to run destructive teardown against anything but the test stack.

    `_drop_all_age_graphs` drops *every* graph in `ag_catalog.ag_graph`, not just the
    ones a test created. That is correct against the throwaway compose database and
    catastrophic against a real one. Nothing structurally prevents someone from running
    the suite with DJANGO_SETTINGS_MODULE pointed at a development database, so check
    rather than trust.
    """
    params = connections["default"].get_connection_params()
    host = str(params.get("host", ""))
    port = str(params.get("port", ""))
    name = str(params.get("dbname") or params.get("database") or "")
    if host != EXPECTED_TEST_DB_HOST or port != EXPECTED_TEST_DB_PORT or not name.startswith("test_"):
        raise RuntimeError(
            f"Refusing to drop AGE graphs: connection is {host}:{port}/{name}, "
            f"not the disposable test stack at {EXPECTED_TEST_DB_HOST}:{EXPECTED_TEST_DB_PORT} "
            f"with a test_-prefixed database. Run the suite with "
            f"DJANGO_SETTINGS_MODULE=kraph_server.settings_test against tests/integration/docker-compose.yaml."
        )


def _drop_all_age_graphs(engine: AgeEngine) -> None:
    """Drop every AGE graph in the test database.

    Graph names are derived from the graph name plus the organization slug, so tests
    that materialize a graph with the same name collide unless the previous one is gone.
    """
    _assert_disposable_database()
    rows = engine.execute_raw("SELECT name::text FROM ag_catalog.ag_graph")
    for (name,) in rows:
        engine.drop_graph(name, cascade=True)


@pytest.fixture(scope="function")
def age_engine(transactional_db, backend_stack) -> Generator[AgeEngine, None, None]:
    """
    Create an AGE engine against a clean graph namespace.

    Previously this fixture deliberately leaked AGE graphs between tests to dodge an
    AGE type-cache problem: AGE caches label OIDs per *session*, so dropping and
    recreating a graph of the same name on a live connection raises on the stale OID.
    Leaking made tests order-dependent and would make the reproject test meaningless,
    since it cannot distinguish a rebuilt graph from a stale one.

    The actual fix is to drop the graphs and then close the connection, which discards
    the session-local cache along with it.
    """
    engine = AgeEngine()
    engine.init_db()

    # A previous run that died mid-test can leave graphs behind.
    _drop_all_age_graphs(engine)
    connections["default"].close()

    yield engine

    _drop_all_age_graphs(engine)
    connections["default"].close()


@pytest.fixture(scope="function")
def api_schema(age_engine):
    """
    Simple API context for validation tests that don't need database/AGE.
    Uses a mock engine for tests that just validate schema structure.
    Provides a proper HttpContext for the AuthentikateExtension.
    """

    return create_schema(
        max_depth=10,
        debug=True,
        include_subscriptions=True,
        cypher_engine=age_engine,
    )


@pytest.fixture(scope="function")
def simple_api_context(db, backend_stack) -> HttpContext:
    user, org, membership = _static_identity()
    client, _ = Client.objects.get_or_create(client_id="oinsoins")

    request = UniversalRequest(
        _extensions={"token": "test"},
        _client=client,  # type: ignore
        _user=user,  # type: ignore
        _organization=org,  # type: ignore
    )
    request.set_membership(membership)  # type: ignore

    return HttpContext(request=request, response=TemporalResponse(), headers={"Authorization": "Bearer test"}, type="http")
