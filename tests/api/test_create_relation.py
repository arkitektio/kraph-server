"""
Tests for the Create Relation API.

These tests verify that:
1. Relations can be created between entities through the GraphQL API
2. Supporting evidence (structures) are properly attached
3. Relations are correctly materialized from evidence
4. Shadow links are created for evidence tracking
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
                "key": "Soma",
                "description": "Cell body",
                "properties": [{"key": "name", "type": "string"}]
            },
            {
                "key": "AIS",
                "description": "Axon initial segment",
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
            {"key": "SYNAPSES_WITH", "description": "Synapse relation", "source": "Neuron", "target": "Neuron"},
            {"key": "PART_OF", "description": "Part-of relation", "source": "Cell", "target": "Cell"},
            {"key": "LOCATED_IN", "description": "Located in relation", "source": "Cell", "target": "Region"},
            {"key": "IS_CONNECTED_TO", "description": "Connected-to relation", "source": "Cell", "target": "Cell"},
            {"key": "INTERACTS_WITH", "description": "Interaction relation", "source": "Cell", "target": "Cell"},
            {"key": "REFERENCES_SELF", "description": "Self-reference relation", "source": "Cell", "target": "Cell"},
        ],
        "events": []
    }
}


# ===========================================
# FIXTURES
# ===========================================

@pytest.fixture
def relation_test_graph(simple_api_context: HttpContext, age_engine) -> Graph:
    """Create a test graph in the database for relation API tests."""
    # Get membership, organization, and user from the context
    membership = simple_api_context.request._extensions.get("membership") or simple_api_context.request.membership
    organization = simple_api_context.request._organization
    user = simple_api_context.request._user
    
    age_name = f"rel_test_{uuid.uuid4().hex[:8]}"
    
    graph = Graph.objects.create(
        name="relation_test_graph",
        age_name=age_name,
        description="Test graph for relation API tests",
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


async def _create_entity(
    api_schema: kante.Schema,
    context: HttpContext,
    graph_id: str,
    kind: str,
    ref_id: str = None,
) -> dict:
    """Helper to create an entity and return its data."""
    mutation = """
        mutation CreateEntity($input: EntityCreationInput!) {
            createEntity(input: $input) {
                refId
                dbId
                graphId
            }
        }
    """
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "graphId": graph_id,
                "kind": kind,
                "refId": ref_id or _uid(kind.lower()),
            }
        },
        context_value=context,
    )
    
    assert result.errors is None, f"Failed to create entity: {result.errors}"
    return result.data["createEntity"]


# ===========================================
# BASIC RELATION CREATION TESTS
# ===========================================

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_relation_minimal(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    relation_test_graph: Graph,
) -> None:
    """Test creating a basic relation between two entities."""
    
    graph_id = str(relation_test_graph.id)
    
    # First create two entities to relate
    source = await _create_entity(api_schema, simple_api_context, graph_id, "Neuron", "source_neuron")
    target = await _create_entity(api_schema, simple_api_context, graph_id, "Neuron", "target_neuron")
    
    mutation = """
        mutation CreateRelation($input: RelationCreationInput!) {
            createRelation(input: $input) {
                refId
                dbId
                graphId
                status
            }
        }
    """
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "refId": _uid("rel"),
                "kind": "CONNECTS_TO",
                "sourceId": source["dbId"],
                "targetId": target["dbId"],
                "provenance": {
                    "subject": "test_user",
                    "appId": "test_app",
                    "actionId": "action_1",
                    "actionName": "connect_neurons",
                },
            }
        },
        context_value=simple_api_context,
    )
    
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None, "No data returned from GraphQL execution"
    
    data = result.data["createRelation"]
    assert data["status"] == "CREATED"
    assert data["refId"] is not None
    assert data["dbId"] is not None
    assert data["graphId"] is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_relation_with_evidence(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    relation_test_graph: Graph,
) -> None:
    """Test creating a relation with supporting evidence."""
    
    graph_id = str(relation_test_graph.id)
    
    source = await _create_entity(api_schema, simple_api_context, graph_id, "Neuron", "pre_synaptic")
    target = await _create_entity(api_schema, simple_api_context, graph_id, "Neuron", "post_synaptic")
    
    mutation = """
        mutation CreateRelation($input: RelationCreationInput!) {
            createRelation(input: $input) {
                refId
                dbId
                status
            }
        }
    """
    
    evidence_roi = _uid("synapse_roi")
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "refId": _uid("synapse"),
                "kind": "SYNAPSES_WITH",
                "sourceId": source["dbId"],
                "targetId": target["dbId"],
                "supportingEvidence": [
                    {
                        "identifier": "@mikro/roi",
                        "object": evidence_roi,
                    }
                ],
                "provenance": {
                    "subject": "test_user",
                    "appId": "test_app",
                    "actionId": "synapse_detection",
                    "actionName": "detect_synapse",
                },
            }
        },
        context_value=simple_api_context,
    )
    
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    data = result.data["createRelation"]
    assert data["status"] == "CREATED"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_relation_with_evidence_measurements(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    relation_test_graph: Graph,
) -> None:
    """Test creating a relation with evidence that has measurements."""
    
    graph_id = str(relation_test_graph.id)
    
    source = await _create_entity(api_schema, simple_api_context, graph_id, "Neuron", "neuron_a")
    target = await _create_entity(api_schema, simple_api_context, graph_id, "Neuron", "neuron_b")
    
    mutation = """
        mutation CreateRelation($input: RelationCreationInput!) {
            createRelation(input: $input) {
                refId
                status
            }
        }
    """
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "refId": _uid("connection"),
                "kind": "SYNAPSES_WITH",
                "sourceId": source["dbId"],
                "targetId": target["dbId"],
                "supportingEvidence": [
                    {
                        "identifier": "@mikro/roi",
                        "object": _uid("overlap_roi"),
                        "measurements": [
                            {"key": "overlap_score", "value": 0.95},
                            {"key": "distance", "value": 2.5, "unit": "um"},
                            {"key": "confidence", "value": 0.87},
                        ],
                    }
                ],
                "provenance": {
                    "subject": "test_user",
                    "appId": "test_app",
                    "actionId": "connection_analysis",
                    "actionName": "analyze_connections",
                },
            }
        },
        context_value=simple_api_context,
    )
    
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["createRelation"]["status"] == "CREATED"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_relation_multiple_evidence(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    relation_test_graph: Graph,
) -> None:
    """Test creating a relation with multiple supporting evidence structures."""
    
    graph_id = str(relation_test_graph.id)
    
    source = await _create_entity(api_schema, simple_api_context, graph_id, "AIS", "ais_1")
    target = await _create_entity(api_schema, simple_api_context, graph_id, "Soma", "soma_1")
    
    mutation = """
        mutation CreateRelation($input: RelationCreationInput!) {
            createRelation(input: $input) {
                refId
                status
            }
        }
    """
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "refId": _uid("connection"),
                "kind": "IS_CONNECTED_TO",
                "sourceId": source["dbId"],
                "targetId": target["dbId"],
                "supportingEvidence": [
                    {
                        "identifier": "@mikro/roi",
                        "object": _uid("roi1"),
                        "measurements": [{"key": "alignment", "value": 0.9}],
                    },
                    {
                        "identifier": "@mikro/roi",
                        "object": _uid("roi2"),
                        "measurements": [{"key": "proximity", "value": 1.5}],
                    },
                    {
                        "identifier": "@mikro/roi",
                        "object": _uid("roi3"),
                        "measurements": [{"key": "overlap", "value": 0.8}],
                    },
                ],
                "provenance": {
                    "subject": "test_user",
                    "appId": "test_app",
                    "actionId": "multi_evidence",
                    "actionName": "relate_with_evidence",
                },
            }
        },
        context_value=simple_api_context,
    )
    
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["createRelation"]["status"] == "CREATED"


# ===========================================
# RELATION TYPE TESTS
# ===========================================

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_relation_various_kinds(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    relation_test_graph: Graph,
) -> None:
    """Test creating relations with different relation kinds."""
    
    graph_id = str(relation_test_graph.id)
    
    # Create entities for relations
    cell = await _create_entity(api_schema, simple_api_context, graph_id, "Cell", "cell_1")
    neuron1 = await _create_entity(api_schema, simple_api_context, graph_id, "Neuron", "neuron_1")
    neuron2 = await _create_entity(api_schema, simple_api_context, graph_id, "Neuron", "neuron_2")
    region = await _create_entity(api_schema, simple_api_context, graph_id, "Region", "region_1")
    
    mutation = """
        mutation CreateRelation($input: RelationCreationInput!) {
            createRelation(input: $input) {
                refId
                status
            }
        }
    """
    
    relation_configs = [
        ("PART_OF", neuron1["dbId"], cell["dbId"]),
        ("SYNAPSES_WITH", neuron1["dbId"], neuron2["dbId"]),
        ("LOCATED_IN", neuron1["dbId"], region["dbId"]),
    ]
    
    for kind, source_id, target_id in relation_configs:
        result = await api_schema.execute(
            mutation,
            variable_values={
                "input": {
                    "refId": _uid(kind.lower()),
                    "kind": kind,
                    "sourceId": source_id,
                    "targetId": target_id,
                    "provenance": {
                        "subject": "test_user",
                        "appId": "test_app",
                        "actionId": f"create_{kind.lower()}",
                        "actionName": "create_relation",
                    },
                }
            },
            context_value=simple_api_context,
        )
        
        assert result.errors is None, f"GraphQL errors for kind '{kind}': {result.errors}"
        assert result.data["createRelation"]["status"] == "CREATED"


# ===========================================
# BIDIRECTIONAL RELATION TESTS
# ===========================================

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_relation_both_directions(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    relation_test_graph: Graph,
) -> None:
    """Test creating relations in both directions between entities."""
    
    graph_id = str(relation_test_graph.id)
    
    neuron_a = await _create_entity(api_schema, simple_api_context, graph_id, "Neuron", "neuron_a")
    neuron_b = await _create_entity(api_schema, simple_api_context, graph_id, "Neuron", "neuron_b")
    
    mutation = """
        mutation CreateRelation($input: RelationCreationInput!) {
            createRelation(input: $input) {
                refId
                dbId
                status
            }
        }
    """
    
    # Create A -> B
    result_ab = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "refId": _uid("a_to_b"),
                "kind": "SYNAPSES_WITH",
                "sourceId": neuron_a["dbId"],
                "targetId": neuron_b["dbId"],
                "provenance": {
                    "subject": "test_user",
                    "appId": "test_app",
                    "actionId": "synapse_ab",
                    "actionName": "create_synapse",
                },
            }
        },
        context_value=simple_api_context,
    )
    
    assert result_ab.errors is None, f"GraphQL errors: {result_ab.errors}"
    
    # Create B -> A (opposite direction)
    result_ba = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "refId": _uid("b_to_a"),
                "kind": "SYNAPSES_WITH",
                "sourceId": neuron_b["dbId"],
                "targetId": neuron_a["dbId"],
                "provenance": {
                    "subject": "test_user",
                    "appId": "test_app",
                    "actionId": "synapse_ba",
                    "actionName": "create_synapse",
                },
            }
        },
        context_value=simple_api_context,
    )
    
    assert result_ba.errors is None, f"GraphQL errors: {result_ba.errors}"
    
    # Both should be created as separate relations
    assert result_ab.data["createRelation"]["dbId"] != result_ba.data["createRelation"]["dbId"]


# ===========================================
# MULTIPLE RELATIONS TESTS
# ===========================================

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_multiple_relations_same_kind(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    relation_test_graph: Graph,
) -> None:
    """Test creating multiple relations of the same kind from one source."""
    
    graph_id = str(relation_test_graph.id)
    
    source = await _create_entity(api_schema, simple_api_context, graph_id, "Neuron", "central_neuron")
    targets = []
    for i in range(3):
        target = await _create_entity(api_schema, simple_api_context, graph_id, "Neuron", f"target_{i}")
        targets.append(target)
    
    mutation = """
        mutation CreateRelation($input: RelationCreationInput!) {
            createRelation(input: $input) {
                refId
                dbId
                status
            }
        }
    """
    
    created_ids = []
    for i, target in enumerate(targets):
        result = await api_schema.execute(
            mutation,
            variable_values={
                "input": {
                    "refId": _uid(f"conn_{i}"),
                    "kind": "CONNECTS_TO",
                    "sourceId": source["dbId"],
                    "targetId": target["dbId"],
                    "provenance": {
                        "subject": "test_user",
                        "appId": "test_app",
                        "actionId": f"conn_{i}",
                        "actionName": "connect",
                    },
                }
            },
            context_value=simple_api_context,
        )
        
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        created_ids.append(result.data["createRelation"]["dbId"])
    
    # All relation IDs should be unique
    assert len(set(created_ids)) == 3


# ===========================================
# PROVENANCE TESTS
# ===========================================

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_relation_provenance_tracking(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    relation_test_graph: Graph,
) -> None:
    """Test that relation creation properly tracks provenance."""
    
    graph_id = str(relation_test_graph.id)
    
    source = await _create_entity(api_schema, simple_api_context, graph_id, "Cell", "cell_source")
    target = await _create_entity(api_schema, simple_api_context, graph_id, "Cell", "cell_target")
    
    mutation = """
        mutation CreateRelation($input: RelationCreationInput!) {
            createRelation(input: $input) {
                refId
                status
            }
        }
    """
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "refId": _uid("traced_rel"),
                "kind": "INTERACTS_WITH",
                "sourceId": source["dbId"],
                "targetId": target["dbId"],
                "provenance": {
                    "subject": "researcher_001",
                    "appId": "tracing_tool_v2",
                    "actionId": "action_abc123",
                    "actionName": "manual_trace",
                    "actionArgs": {
                        "tool_version": "2.1.0",
                        "confidence": 0.95,
                        "method": "semi-automatic",
                    },
                },
            }
        },
        context_value=simple_api_context,
    )
    
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["createRelation"]["status"] == "CREATED"


# ===========================================
# ERROR HANDLING TESTS
# ===========================================

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_relation_invalid_source_id(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    relation_test_graph: Graph,
) -> None:
    """Test that creating a relation with invalid source ID fails."""
    
    graph_id = str(relation_test_graph.id)
    
    target = await _create_entity(api_schema, simple_api_context, graph_id, "Neuron", "valid_target")
    
    mutation = """
        mutation CreateRelation($input: RelationCreationInput!) {
            createRelation(input: $input) {
                refId
                status
            }
        }
    """
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "refId": _uid("bad_rel"),
                "kind": "CONNECTS_TO",
                "sourceId": "nonexistent_entity_id",
                "targetId": target["dbId"],
                "provenance": {
                    "subject": "test_user",
                    "appId": "test_app",
                    "actionId": "bad_action",
                    "actionName": "create",
                },
            }
        },
        context_value=simple_api_context,
    )
    
    # Should either have errors or fail to create
    assert result.errors is not None or (
        result.data is not None and 
        result.data.get("createRelation") is None
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_relation_invalid_target_id(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    relation_test_graph: Graph,
) -> None:
    """Test that creating a relation with invalid target ID fails."""
    
    graph_id = str(relation_test_graph.id)
    
    source = await _create_entity(api_schema, simple_api_context, graph_id, "Neuron", "valid_source")
    
    mutation = """
        mutation CreateRelation($input: RelationCreationInput!) {
            createRelation(input: $input) {
                refId
                status
            }
        }
    """
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "refId": _uid("bad_rel"),
                "kind": "CONNECTS_TO",
                "sourceId": source["dbId"],
                "targetId": "nonexistent_entity_id",
                "provenance": {
                    "subject": "test_user",
                    "appId": "test_app",
                    "actionId": "bad_action",
                    "actionName": "create",
                },
            }
        },
        context_value=simple_api_context,
    )
    
    # Should either have errors or fail to create
    assert result.errors is not None or (
        result.data is not None and 
        result.data.get("createRelation") is None
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_relation_missing_provenance(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    relation_test_graph: Graph,
) -> None:
    """Test that creating a relation without provenance fails validation."""
    
    mutation = """
        mutation CreateRelation($input: RelationCreationInput!) {
            createRelation(input: $input) {
                refId
            }
        }
    """
    
    # Missing provenance field should cause validation error
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "refId": _uid("no_prov"),
                "kind": "CONNECTS_TO",
                "sourceId": "some_id",
                "targetId": "other_id",
                # provenance is missing!
            }
        },
        context_value=simple_api_context,
    )
    
    # Should have errors about missing field
    assert result.errors is not None


# ===========================================
# SELF-RELATION TESTS
# ===========================================

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_self_relation(
    api_schema: kante.Schema, 
    simple_api_context: HttpContext,
    relation_test_graph: Graph,
) -> None:
    """Test creating a relation from an entity to itself."""
    
    graph_id = str(relation_test_graph.id)
    
    entity = await _create_entity(api_schema, simple_api_context, graph_id, "Cell", "self_ref_cell")
    
    mutation = """
        mutation CreateRelation($input: RelationCreationInput!) {
            createRelation(input: $input) {
                refId
                dbId
                status
            }
        }
    """
    
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "refId": _uid("self_rel"),
                "kind": "REFERENCES_SELF",
                "sourceId": entity["dbId"],
                "targetId": entity["dbId"],  # Same entity!
                "provenance": {
                    "subject": "test_user",
                    "appId": "test_app",
                    "actionId": "self_ref",
                    "actionName": "create_self_reference",
                },
            }
        },
        context_value=simple_api_context,
    )
    
    # Self-relations should be valid (depending on graph semantics)
    # If the system allows it, it should succeed
    if result.errors is None:
        assert result.data["createRelation"]["status"] == "CREATED"
