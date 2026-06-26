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


@pytest.fixture(scope="function")
def authenticated_context(db, backend_stack):
    user, _ = User.objects.get_or_create(username="fart", password="123456789", sub="1")
    client, _ = Client.objects.get_or_create(client_id="oinsoins")
    org, _ = Organization.objects.get_or_create(slug="test-organization")
    membership, _ = Membership.objects.get_or_create(
        user=user,
        organization=org,
    )

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
    They are dynamically resolved via get_label_for_identifier() from
    the IDENTIFIER_MAP in graph_engine.base_models.
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
                        models.PropertyDefinitionInput(key="mitosis_count", type=models.PropertyType.INTEGER, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(key=None, source_node="Mitosis", aggregation=models.AggregationFunction.COUNT)),
                        models.PropertyDefinitionInput(key="ais_length_summary", type=models.PropertyType.FLOAT, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(key=None, source_node="AIS", aggregation=models.AggregationFunction.LATEST)),
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
                    properties=[models.PropertyDefinitionInput(key="cell_count", type=models.PropertyType.INTEGER, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(source_node="Cell", key=None, aggregation=models.AggregationFunction.COUNT))],
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
def minimal_schema():
    """A minimal schema for testing."""
    return models.GraphDefinitionModel(
        system_version="1.0.0",
        extensions=models.GraphExtensions(
            entities=[
                models.EntityDefinition(
                    key="Person",
                    description="A person",
                    properties=[
                        models.PropertyDefinition(key="name", type=models.PropertyType.STRING),
                        models.PropertyDefinition(key="age", type=models.PropertyType.INTEGER),
                    ],
                )
            ]
        ),
    )


@pytest.fixture(scope="function")
def age_engine(transactional_db, backend_stack) -> Generator[AgeEngine, None, None]:
    """
    Create an AGE engine.

    Uses transactional_db to maintain database state across the fixture.
    """

    engine = AgeEngine()

    yield engine

    # Don't drop the graph between tests - just leave it
    # This avoids the type cache invalidation issue


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
    user, _ = User.objects.get_or_create(username="fart", password="123456789", sub="1")
    client, _ = Client.objects.get_or_create(client_id="oinsoins")
    org, _ = Organization.objects.get_or_create(slug="test-organization")
    membership, _ = Membership.objects.get_or_create(
        user=user,
        organization=org,
    )

    request = UniversalRequest(
        _extensions={"token": "test"},
        _client=client,  # type: ignore
        _user=user,  # type: ignore
        _organization=org,  # type: ignore
    )
    request.set_membership(membership)  # type: ignore

    return HttpContext(request=request, response=TemporalResponse(), headers={"Authorization": "Bearer test"}, type="http")
