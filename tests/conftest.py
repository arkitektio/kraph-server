import time
from typing import Generator
import pytest
import boto3
from moto import mock_aws
import os

import pytest
from django.contrib.auth import get_user_model
from graph_engine.controller import GraphController
from graph_engine.engine.age_engine import AgeEngine
from graph_engine.engine.protocol import GraphProtocol
from graph_engine.engine.testing.mock_cypher_engine import MockCypherEngine
from kraph_server.schema import schema
from guardian.shortcuts import get_perms
from asgiref.sync import sync_to_async
from authentikate.models import Client, Organization, User, Membership
from guardian.shortcuts import get_perms
from asgiref.sync import sync_to_async
from kante.context import HttpContext, UniversalRequest
from dokker import local, HealthCheck
from graph_engine import base_models as models



@pytest.fixture(scope="function")
def aws_credentials():
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
def create_bucket1(s3):
    s3.create_bucket(Bucket="babanana")


@pytest.fixture
def create_bucket2(s3):
    s3.create_bucket(Bucket="cabanana")


@pytest.fixture(scope="session")
def backend_stack():
    docker_compose_path = os.path.join(
        os.path.dirname(__file__), "integration", "docker-compose.yaml")
    
    
    
    
    
    with local(docker_compose_path) as e:
        e.inspect()
        
        e.down()
        e.pull()
        
        
        e.up()
        
        
        time.sleep(2)
        
        yield
    


@pytest.fixture(scope="function")
def authenticated_context(db, backend_stack):
    user, _ = User.objects.get_or_create(
        username="fart", password="123456789", sub="1")
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

    return HttpContext(
        request=request,
        headers={"Authorization": "Bearer test"},
        type="http"
    )


@pytest.fixture(scope="function")
def mock_engine():
    """Create a fresh mock engine for each test."""
    return MockCypherEngine()


@pytest.fixture(scope="session")
def bio_graph_schema():
    """
    Fixture defined using EXPLICIT Pydantic Model constructors.
    """
    return models.GraphDefinitionModel(
        system_version="1.0",
        extensions=models.GraphExtensions(
            
            # --- 1. STRUCTURES ---
            structures={
                "ROI": models.StructureDefinition(
                    description="Region of Interest",
                ),
                "ToldYouSo": models.StructureDefinition(
                    description="Evidence structure for assertions",
                )
            },

            # --- 2. ENTITIES ---
            entities={
                "AIS": models.EntityDefinition(
                    properties={
                        "avg_length": models.PropertyDefinition(
                            type=models.PropertyType.FLOAT,
                            derivation=models.DerivationType.ROLLUP,
                            rule=models.DerivationRule(
                                source_node="ROI",
                                key="vector_length",
                                aggregation=models.AggregationFunction.MEAN
                            )
                        ),
                        "name": models.PropertyDefinition(
                            type=models.PropertyType.STRING,
                            derivation=models.DerivationType.ROLLUP,
                            rule=models.DerivationRule(
                                source_node="ToldYouSo",
                                key="name",
                                aggregation=models.AggregationFunction.LATEST
                            )
                        )
                    }
                ),
                "Soma": models.EntityDefinition(
                    properties={
                        "centroid": models.PropertyDefinition(
                            type=models.PropertyType.POINT_3D,
                            derivation=models.DerivationType.LATEST,
                            rule=models.DerivationRule(
                                source_node="ROI", 
                                key="centroid"
                            )
                        )
                    }
                ),
                "Cell": models.EntityDefinition(
                    properties={
                        "id": models.PropertyDefinition(type=models.PropertyType.STRING),
                        "mitosis_count": models.PropertyDefinition(
                            type=models.PropertyType.INTEGER,
                            derivation=models.DerivationType.ROLLUP,
                            rule=models.DerivationRule(
                                key=None,
                                source_node="Mitosis",
                                relationship="INPUT_TO",
                                aggregation=models.AggregationFunction.COUNT
                            )
                        ),
                        "ais_length_summary": models.PropertyDefinition(
                            type=models.PropertyType.FLOAT,
                            derivation=models.DerivationType.ROLLUP,
                            rule=models.DerivationRule(
                                source_node="AIS",
                                relationship="PART_OF",
                                key="avg_length",
                                aggregation=models.AggregationFunction.LATEST
                            )
                        )
                    }
                )
            },

            # --- 3. RELATIONS ---
            relations={
                "IS_CONNECTED_TO": models.RelationDefinition(
                    source="AIS",
                    target="Soma",
                    cardinality="1:1",
                    materialization=models.MaterializationConfig(
                        backing_link_type="link_ais_soma",
                        desired_evidence=[
                            models.EvidenceRequirement(key="vector_alignment", unit="score_0_1"),
                            models.EvidenceRequirement(key="proximity", unit="um")
                        ],
                        properties={
                            "distance": models.PropertyDefinition(
                                type=models.PropertyType.FLOAT,
                                derivation=models.DerivationType.ROLLUP,
                                rule=models.DerivationRule(
                                    source_node="ROI",
                                    key="centroid",
                                    aggregation=models.AggregationFunction.EUCLIDEAN_RANGE
                                )
                            )
                        }
                    )
                ),
                "PART_OF": models.RelationDefinition(
                    source=["AIS", "Soma"],
                    target="Cell"
                )
            },

            # --- 4. EVENTS ---
            events={
                "Mitosis": models.EventDefinition(
                    inputs=["Cell"],
                    outputs=["Cell", "Cell"],
                    properties={
                        "cell_count": models.PropertyDefinition(
                            type=models.PropertyType.INTEGER,
                            derivation=models.DerivationType.ROLLUP,
                            rule=models.DerivationRule(
                                key=None,
                                source_node="Cell",
                                aggregation=models.AggregationFunction.COUNT
                            )
                        )
                    }
                )
            }
        )
    )

@pytest.fixture(scope="session")
def test_graph(bio_graph_schema):
    """Create a test graph with the bio schema."""
    from graph_engine.engine.protocol import SimpleGraph
    return SimpleGraph(age_name="test_graph", definition=bio_graph_schema)


@pytest.fixture
def mock_graph_controller(mock_engine, test_graph):
    """Create a graph controller with mock engine and test graph."""
    return GraphController(engine=mock_engine, graph=test_graph)

@pytest.fixture(scope="function")
def graph_controller(transactional_db, age_engine, test_graph):
    """Create a graph controller with AGE engine and test graph."""
    return GraphController(engine=age_engine, graph=test_graph)



@pytest.fixture(scope="function")
def minimal_schema():
    """A minimal schema for testing."""
    return models.GraphDefinitionModel(
        system_version="1.0",
        extensions=models.GraphExtensions(
            entities={
                "Person": models.EntityDefinition(
                    description="A person",
                    properties={
                        "name": models.PropertyDefinition(type=models.PropertyType.STRING),
                        "age": models.PropertyDefinition(type=models.PropertyType.INTEGER),
                    }
                )
            }
        )
    )



@pytest.fixture(scope="function")
def age_engine(transactional_db, backend_stack, test_graph: GraphProtocol) -> Generator[AgeEngine, None, None]:
    """
    Create an AGE engine with the test graph.
    
    Uses transactional_db to maintain database state across the fixture.
    The graph is created once and reused.
    """
    from django.db import connections, connection
    
    # Ensure the AGE extension is created first
    with connections["default"].cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS age;")
    
    engine = AgeEngine()
    
    # Create the graph if it doesn't exist
    try:
        engine.execute_raw(f"SELECT * FROM ag_catalog.create_graph('{test_graph.age_name}')")
    except Exception as e:
        # Graph already exists - that's fine
        if "already exists" not in str(e):
            raise
    
    yield engine
    
    # Don't drop the graph between tests - just leave it
    # This avoids the type cache invalidation issue