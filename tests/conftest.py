import time
# (Generator import removed with the AGE engine fixture)
import pytest
import boto3
from moto import mock_aws
import os

from graph_engine.controller import GraphController
from api.schema import create_schema
from authentikate.models import Client, Organization, User, Membership
from kante.context import HttpContext, UniversalRequest
from strawberry.http.temporal_response import TemporalResponse
from dokker import local
from graph_engine import input_models as models
from graph_engine.materialize import materialize
from graph_engine.projection import TableProjector
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

    Every rollup rule here names an explicit metric key and a *structure* source.
    Both are now enforced: `materialize.validate_derivation_rules` rejects a rule with
    no key, and rejects one whose source is an entity or event kind. Before that, such
    rules rendered as `WHERE m.key = null`, which never matches — so the property
    silently stayed unset and any test asserting on it passed vacuously.
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
                        # These originally counted/summarised evidence reached through
                        # another node kind (a Mitosis event, an AIS entity). The state
                        # vector's grain is (entity, source_category, key) over metrics
                        # reached via (Metric)-[DESCRIBES]->(Structure)-[INFORMS]->(Entity),
                        # so cross-entity rollups are not expressible — and are now
                        # rejected at materialization rather than silently never computing.
                        # Modelled here as metric keys on the supporting structure.
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
                    # No `properties`. This used to declare `distance` as a
                    # EUCLIDEAN_RANGE rollup, and `project_edges` has never run a
                    # derivation rule — it writes `category_id` and
                    # `__assertion_count` and stops. So the fixture the whole
                    # suite runs against contained a rule nothing executed, and
                    # nothing failed. `validate_derivation_rules` now refuses it.
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
def test_graph(transactional_db, table_projector, bio_graph_schema, authenticated_context) -> core_models.Graph:
    """
    Create a test graph with the bio_graph schema.

    This is the standard test graph fixture that materializes a graph
    from the bio_graph_schema definition, creating all necessary
    Django models (EntityCategory, RelationCategory, etc.).
    """
    request = authenticated_context.request
    return materialize(
        bio_graph_schema,
        table_projector,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name="test_graph",
    )


@pytest.fixture(scope="function")
def graph_controller(transactional_db, table_projector, test_graph) -> GraphController:
    """A ready-to-use GraphController drawing through the table projector."""
    return GraphController(
        projector=table_projector,
        subject="test_user",
        app_id="test_app",
    )


@pytest.fixture(scope="function")
def bio_graph(transactional_db, table_projector, bio_graph_schema, authenticated_context) -> core_models.Graph:
    """
    Create a biological graph with the provided schema.
    Uses transactional_db to maintain database state across the fixture.
    The graph is created once and reused.
    """
    request = authenticated_context.request
    return materialize(
        bio_graph_schema,
        table_projector,
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

    Both properties carry a rule. They did not, which made them inert — nothing
    writes a property directly — so `materialize` now rejects that shape and this
    fixture would fail to build the graph it exists to provide.
    """
    return models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=[
                models.EntityDefinitionInput(
                    key="Person",
                    description="A person",
                    property_definitions=[
                        models.PropertyDefinitionInput(
                            key="name",
                            type=models.PropertyType.STRING,
                            derivation=models.DerivationType.LATEST,
                            rule=models.DerivationRuleInput(source_node="ROI", key="name"),
                        ),
                        models.PropertyDefinitionInput(
                            key="age",
                            type=models.PropertyType.INTEGER,
                            derivation=models.DerivationType.ROLLUP,
                            rule=models.DerivationRuleInput(source_node="ROI", key="age", aggregation=models.AggregationFunction.LATEST),
                        ),
                    ],
                )
            ]
        ),
    )


@pytest.fixture(scope="function")
def table_projector(transactional_db, backend_stack) -> TableProjector:
    """The projection kind the suite draws through.

    Stateless: the drawing lives in the projection tables of the same test
    database, so `transactional_db` flushes it between tests — real isolation,
    where the Apache AGE namespace this replaced had to be dropped by hand and
    (before that) was deliberately leaked around a type-cache bug.
    """
    return TableProjector()


@pytest.fixture(scope="function")
def api_schema(table_projector):
    """The served schema, drawing through the table projector."""

    return create_schema(
        max_depth=10,
        debug=True,
        projector=table_projector,
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
