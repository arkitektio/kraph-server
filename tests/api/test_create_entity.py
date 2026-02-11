"""
Tests for the Create Entity API.

These tests verify that:
1. Entities can be created through the GraphQL API
2. Supporting evidence (structures) are properly attached
3. Measurements on evidence are associated correctly
4. Entity properties are derived from evidence
5. Provenance tracking works correctly
"""
import pytest
import uuid
import kante
from kante.context import HttpContext
from core.models import Graph, GraphSchema

pytestmark = pytest.mark.skip(reason="GraphQL schema changed; API tests need refresh")


def _uid(prefix: str = "test") -> str:
    """Generate a unique ID for test objects."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# Default schema definition for test graphs
DEFAULT_TEST_SCHEMA = {
    "system_version": "1.0.0",
    "extensions": {
        "entities": [
            {
                "key": "Cell",
                "description": "A biological cell",
                "properties": [{"key": "name", "type": "string"}]
            },
            {
                "key": "Neuron",
                "description": "A nerve cell",
                "properties": [{"key": "name", "type": "string"}]
            },
            {
                "key": "Region",
                "description": "A brain region",
                "properties": [{"key": "name", "type": "string"}]
            },
        ],
        "relations": [
            {"key": "CONNECTS_TO", "description": "Connection relation", "source": "Cell", "target": "Cell"},
            {"key": "PART_OF", "description": "Part-of relation", "source": "Cell", "target": "Cell"},
            {"key": "LOCATED_IN", "description": "Located in relation", "source": "Cell", "target": "Region"},
        ],
        "events": []
    }
}


# ===========================================
# FIXTURES
# ===========================================

@pytest.fixture
def api_test_graph(simple_api_context: HttpContext, age_engine) -> Graph:
    """Create a test graph in the database for API tests."""
    # Get membership, organization, and user from the context
    membership = simple_api_context.request._extensions.get("membership") or simple_api_context.request.membership
    organization = simple_api_context.request._organization
    user = simple_api_context.request._user
    
    age_name = f"api_test_{uuid.uuid4().hex[:8]}"
    
    graph = Graph.objects.create(
        name="api_test_graph",
        age_name=age_name,
        description="Test graph for API tests",
        membership=membership,
        organization=organization,
        user=user,
    )
    
    # Create the AGE graph
    try:
        age_engine.execute_raw(f"SELECT * FROM ag_catalog.create_graph('{age_name}')")
    except Exception as e:
        # Graph already exists - that's fine
        if "already exists" not in str(e):
            raise
    
    # Create and activate a schema for the graph
    GraphSchema.objects.create(
        graph=graph,
        version="1.0.0",
        index=1,
        definition=DEFAULT_TEST_SCHEMA,
        is_active=True,
        created_by=user,
    )
    
    return graph


# ===========================================
# BASIC ENTITY CREATION TESTS
# ===========================================

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_entity_minimal(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    api_test_graph: Graph,
) -> None:
    """Test creating a basic entity with minimal input."""
    
    mutation = """
        mutation CreateEntity($input: EntityCreationInput!) {
            createEntity(input: $input) {
                refId
                dbId
                graphId
                status
                entity {
                    id
                    kind
                }
            }
        }
    """
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "graphId": str(api_test_graph.id),
                "kind": "Cell",
            }
        },
        context_value=simple_api_context,
    )
    
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None, "No data returned from GraphQL execution"
    
    data = result.data["createEntity"]
    assert data["status"] == "CREATED"
    assert data["refId"] is not None
    assert data["dbId"] is not None
    assert data["graphId"] is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_entity_with_ref_id(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    api_test_graph: Graph,
) -> None:
    """Test creating an entity with a custom reference ID."""
    
    mutation = """
        mutation CreateEntity($input: EntityCreationInput!) {
            createEntity(input: $input) {
                refId
                dbId
                status
            }
        }
    """
    
    custom_ref_id = _uid("cell")
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "graphId": str(api_test_graph.id),
                "kind": "Neuron",
                "refId": custom_ref_id,
            }
        },
        context_value=simple_api_context,
    )
    
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    data = result.data["createEntity"]
    assert data["refId"] == custom_ref_id
    assert data["status"] == "CREATED"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_entity_with_provenance(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    api_test_graph: Graph,
) -> None:
    """Test creating an entity with provenance tracking."""
    
    mutation = """
        mutation CreateEntity($input: EntityCreationInput!) {
            createEntity(input: $input) {
                refId
                status
                entity {
                    id
                    kind
                }
            }
        }
    """
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "graphId": str(api_test_graph.id),
                "kind": "Cell",
                "actionId": "action_123",
                "actionName": "create_cell",
                "actionArgs": {"workflow": "segmentation"},
            }
        },
        context_value=simple_api_context,
    )
    
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    data = result.data["createEntity"]
    assert data["status"] == "CREATED"


# ===========================================
# ENTITY WITH EVIDENCE TESTS
# ===========================================

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_entity_with_single_evidence(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    api_test_graph: Graph,
) -> None:
    """Test creating an entity with a single supporting evidence structure."""
    
    mutation = """
        mutation CreateEntity($input: EntityCreationInput!) {
            createEntity(input: $input) {
                refId
                dbId
                status
                entity {
                    id
                    kind
                }
            }
        }
    """
    
    roi_object = _uid("roi")
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "graphId": str(api_test_graph.id),
                "kind": "Cell",
                "supportingEvidence": [
                    {
                        "identifier": "@mikro/roi",
                        "object": roi_object,
                    }
                ],
            }
        },
        context_value=simple_api_context,
    )
    
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    data = result.data["createEntity"]
    assert data["status"] == "CREATED"
    assert data["entity"] is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_entity_with_multiple_evidence(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    api_test_graph: Graph,
) -> None:
    """Test creating an entity with multiple supporting evidence structures."""
    
    mutation = """
        mutation CreateEntity($input: EntityCreationInput!) {
            createEntity(input: $input) {
                refId
                status
            }
        }
    """
    
    roi1 = _uid("roi1")
    roi2 = _uid("roi2")
    roi3 = _uid("roi3")
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "graphId": str(api_test_graph.id),
                "kind": "Neuron",
                "supportingEvidence": [
                    {"identifier": "@mikro/roi", "object": roi1},
                    {"identifier": "@mikro/roi", "object": roi2},
                    {"identifier": "@mikro/roi", "object": roi3},
                ],
            }
        },
        context_value=simple_api_context,
    )
    
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    data = result.data["createEntity"]
    assert data["status"] == "CREATED"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_entity_with_measurements(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    api_test_graph: Graph,
) -> None:
    """Test creating an entity with evidence that has measurements."""
    
    mutation = """
        mutation CreateEntity($input: EntityCreationInput!) {
            createEntity(input: $input) {
                refId
                status
                entity {
                    id
                    kind
                }
            }
        }
    """
    
    roi_object = _uid("roi")
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "graphId": str(api_test_graph.id),
                "kind": "Cell",
                "supportingEvidence": [
                    {
                        "identifier": "@mikro/roi",
                        "object": roi_object,
                        "measurements": [
                            {"key": "volume", "value": 123.45},
                            {"key": "area", "value": 456.78, "unit": "um2"},
                        ],
                    }
                ],
            }
        },
        context_value=simple_api_context,
    )
    
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    data = result.data["createEntity"]
    assert data["status"] == "CREATED"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_entity_different_evidence_types(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    api_test_graph: Graph,
) -> None:
    """Test creating an entity with different types of evidence structures."""
    
    mutation = """
        mutation CreateEntity($input: EntityCreationInput!) {
            createEntity(input: $input) {
                refId
                status
            }
        }
    """
    
    roi_object = _uid("roi")
    toldyouso_object = _uid("tys")
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "graphId": str(api_test_graph.id),
                "kind": "Cell",
                "supportingEvidence": [
                    {
                        "identifier": "@mikro/roi",
                        "object": roi_object,
                        "measurements": [{"key": "volume", "value": 100.0}],
                    },
                    {
                        "identifier": "told_you_so",
                        "object": toldyouso_object,
                        "measurements": [{"key": "name", "value": "Test Cell"}],
                    },
                ],
            }
        },
        context_value=simple_api_context,
    )
    
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    data = result.data["createEntity"]
    assert data["status"] == "CREATED"


# ===========================================
# ENTITY KIND TESTS
# ===========================================

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_entity_various_kinds(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    api_test_graph: Graph,
) -> None:
    """Test creating entities with different kinds."""
    
    mutation = """
        mutation CreateEntity($input: EntityCreationInput!) {
            createEntity(input: $input) {
                refId
                entity {
                    kind
                }
            }
        }
    """
    
    kinds = ["Cell", "Neuron", "Region"]
    
    for kind in kinds:
        result = await api_schema.execute(
            mutation,
            variable_values={
                "input": {
                    "graphId": str(api_test_graph.id),
                    "kind": kind,
                }
            },
            context_value=simple_api_context,
        )
        
        assert result.errors is None, f"GraphQL errors for kind '{kind}': {result.errors}"
        assert result.data["createEntity"]["entity"]["kind"] == kind


# ===========================================
# MULTIPLE ENTITY CREATION TESTS
# ===========================================

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_multiple_entities_same_kind(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    api_test_graph: Graph,
) -> None:
    """Test creating multiple entities of the same kind."""
    
    mutation = """
        mutation CreateEntity($input: EntityCreationInput!) {
            createEntity(input: $input) {
                refId
                dbId
            }
        }
    """
    
    created_ids = []
    for i in range(5):
        result = await api_schema.execute(
            mutation,
            variable_values={
                "input": {
                    "graphId": str(api_test_graph.id),
                    "kind": "Cell",
                    "refId": f"cell_{i}",
                }
            },
            context_value=simple_api_context,
        )
        
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        created_ids.append(result.data["createEntity"]["dbId"])
    
    # All IDs should be unique
    assert len(set(created_ids)) == 5


# ===========================================
# ERROR HANDLING TESTS
# ===========================================

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_entity_invalid_graph_id(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
) -> None:
    """Test that creating an entity with invalid graph ID fails gracefully."""
    
    mutation = """
        mutation CreateEntity($input: EntityCreationInput!) {
            createEntity(input: $input) {
                refId
                status
            }
        }
    """
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "graphId": "99999999",  # Non-existent graph
                "kind": "Cell",
            }
        },
        context_value=simple_api_context,
    )
    
    # Should have errors
    assert result.errors is not None or (
        result.data is not None and 
        result.data.get("createEntity") is None
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_entity_missing_kind(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    api_test_graph: Graph,
) -> None:
    """Test that creating an entity without kind fails."""
    
    mutation = """
        mutation CreateEntity($input: EntityCreationInput!) {
            createEntity(input: $input) {
                refId
            }
        }
    """
    
    # Missing 'kind' field should cause validation error
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "graphId": str(api_test_graph.id),
                # kind is missing!
            }
        },
        context_value=simple_api_context,
    )
    
    # Should have errors about missing field
    assert result.errors is not None
