import time
import pytest
import boto3
import moto
from moto import mock_aws
import os

import pytest
from django.contrib.auth import get_user_model
from graph_engine.controller import GraphController
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


@pytest.fixture
def mock_engine():
    return MockCypherEngine()

@pytest.fixture
def graph_controller(mock_engine):
    return GraphController(engine=mock_engine)

@pytest.fixture
def bio_graph_schema():
    """
    Fixture defined using EXPLICIT Pydantic Model constructors.
    """
    return models.GraphDefinitionModel(
        system_version="1.0",
        extensions=models.GraphExtensions(
            
            # --- 1. STRUCTURES ---
            structures={
                "ROI": models.NodeDefinition(
                    description="Region of Interest",
                    properties={
                        "vector_length": models.PropertyDefinition(
                            type=models.PropertyType.FLOAT, 
                            unit="um"
                        ),
                        "centroid": models.PropertyDefinition(
                            type=models.PropertyType.POINT_3D
                        ),
                        "valid_time": models.PropertyDefinition(
                            type=models.PropertyType.DATETIME
                        )
                    }
                )
            },

            # --- 2. ENTITIES ---
            entities={
                "AIS": models.NodeDefinition(
                    allowed_parents=["Cell"],
                    properties={
                        "id": models.PropertyDefinition(type=models.PropertyType.STRING),
                        "avg_length": models.PropertyDefinition(
                            type=models.PropertyType.FLOAT,
                            derivation=models.DerivationType.ROLLUP,
                            rule=models.DerivationRule(
                                source_node="ROI",
                                relationship="DEFINES",
                                key="vector_length",
                                aggregation=models.AggregationFunction.MEAN
                            )
                        ),
                        "name": models.PropertyDefinition(type=models.PropertyType.STRING,
                                derivation=models.DerivationType.ROLLUP,
                                rule=models.DerivationRule(
                                    source_node="ToldYouSo",
                                    relationship="DEFINES",
                                    key="name",
                                    aggregation=models.AggregationFunction.MEAN
                                )
                        )
                    }
                ),
                "Soma": models.NodeDefinition(
                    allowed_parents=["Cell"],
                    properties={
                        "id": models.PropertyDefinition(type=models.PropertyType.STRING),
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
                "Cell": models.NodeDefinition(
                    properties={
                        "id": models.PropertyDefinition(type=models.PropertyType.STRING),
                        "mitosis_count": models.PropertyDefinition(
                            type=models.PropertyType.INTEGER,
                            derivation=models.DerivationType.ROLLUP,
                            rule=models.DerivationRule(
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
                            "confidence": models.PropertyDefinition(
                                type=models.PropertyType.FLOAT,
                                derivation=models.DerivationType.ROLLUP,
                                rule=models.DerivationRule(
                                    path="(:TemporalLink)<-[:INFORMS]-(:Measurement)",
                                    key="vector_alignment",
                                    aggregation=models.AggregationFunction.MAX
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
                        "duration": models.PropertyDefinition(
                            type=models.PropertyType.FLOAT,
                            derivation=models.DerivationType.ROLLUP,
                            rule=models.DerivationRule(
                                relationships=["INPUT_TO", "OUTPUT_TO"],
                                source_node="Cell",
                                key="valid_time",
                                aggregation=models.AggregationFunction.RANGE
                            )
                        )
                    }
                )
            }
        )
    )
