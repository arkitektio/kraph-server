"""
Tests for the API types and type matching functionality.
"""
import pytest
from api.types import (
    Assertion,
    Entity,
    Metric,
    NaturalEvent,
    Property,
    ProtocolEvent,
    Reagent,
    Relation,
    Structure,
    cast_edge_to_graphql_type,
    cast_node_to_graphql_type,
)
from graph_engine.retrieved import RetrievedNode, RetrievedEdge, RetrievedVariable


class TestRetrievedNode:
    """Tests for the RetrievedNode dataclass."""
    
    def test_basic_properties(self) -> None:
        """Test basic property access."""
        node = RetrievedNode(
            graph_name="test_graph",
            id=123,
            label="Entity",
            properties={"name": "Test", "value": 42}
        )
        
        assert node.graph_name == "test_graph"
        assert node.id == 123
        assert node.label == "Entity"
        assert node.unique_id == "test_graph:123"
        assert node.global_id == "test_graph:123"
    
    def test_node_type_discrimination(self) -> None:
        """Test type property for discrimination."""
        entity_node = RetrievedNode(
            graph_name="g",
            id=1,
            label="Cell",
            properties={"type": "ENTITY", "kind": "Cell"}
        )
        assert entity_node.node_type == "ENTITY"
        assert entity_node.category_type == "ENTITY"
        
        structure_node = RetrievedNode(
            graph_name="g",
            id=2,
            label="ROI",
            properties={"type": "STRUCTURE", "identifier": "@mikro/roi"}
        )
        assert structure_node.node_type == "STRUCTURE"
    
    def test_cleaned_properties(self) -> None:
        """Test that reserved keys are filtered out."""
        node = RetrievedNode(
            graph_name="g",
            id=1,
            label="Entity",
            properties={
                "type": "ENTITY",  # reserved
                "category_id": "abc",  # reserved
                "name": "Test",  # user property
                "value": 42,  # user property
            }
        )
        
        cleaned = node.cleaned_properties
        assert "type" not in cleaned
        assert "category_id" not in cleaned
        assert cleaned["name"] == "Test"
        assert cleaned["value"] == 42
    
    def test_versioning_properties(self) -> None:
        """Test schema versioning properties."""
        node = RetrievedNode(
            graph_name="g",
            id=1,
            label="Entity",
            properties={
                "schema_version": "2.0.0",
                "last_derived": 1700000000000,
            }
        )
        
        assert node.schema_version == "2.0.0"
        assert node.last_derived == 1700000000000
    
    def test_structure_properties(self) -> None:
        """Test structure-specific properties."""
        node = RetrievedNode(
            graph_name="g",
            id=1,
            label="ROI",
            properties={
                "type": "STRUCTURE",
                "identifier": "@mikro/roi",
                "object": "roi-123-abc",
            }
        )
        
        assert node.identifier == "@mikro/roi"
        assert node.object == "roi-123-abc"


class TestRetrievedEdge:
    """Tests for the RetrievedEdge dataclass."""
    
    def test_basic_properties(self) -> None:
        """Test basic property access."""
        edge = RetrievedEdge(
            graph_name="test_graph",
            id=456,
            label="MEASURES",
            left_id=1,
            right_id=2,
            properties={"key": "area", "value": 42.5}
        )
        
        assert edge.graph_name == "test_graph"
        assert edge.id == 456
        assert edge.label == "MEASURES"
        assert edge.left_id == 1
        assert edge.right_id == 2
        assert edge.unique_id == "test_graph:456"
        assert edge.unique_left_id == "test_graph:1"
        assert edge.unique_right_id == "test_graph:2"
    
    def test_measurement_properties(self) -> None:
        """Test measurement-specific properties."""
        edge = RetrievedEdge(
            graph_name="g",
            id=1,
            label="MEASURES",
            left_id=1,
            right_id=2,
            properties={
                "type": "MEASUREMENT",
                "key": "area",
                "value": 42.5,
                "unit": "um^2",
                "confidence": 0.95,
                "confidence_type": "statistical",
            }
        )
        
        assert edge.edge_type == "MEASUREMENT"
        assert edge.key == "area"
        assert edge.value == 42.5
        assert edge.unit == "um^2"
        assert edge.confidence == 0.95
        assert edge.confidence_type == "statistical"
    
    def test_assertion_properties(self) -> None:
        """Test assertion-specific properties."""
        edge = RetrievedEdge(
            graph_name="g",
            id=1,
            label="ASSERTS",
            left_id=1,
            right_id=2,
            properties={
                "type": "ASSERTION",
                "subject": "user123",
                "app_id": "mikro",
                "action_name": "create_roi",
            }
        )
        
        assert edge.edge_type == "ASSERTION"
        assert edge.subject == "user123"
        assert edge.app_id == "mikro"
        assert edge.action_name == "create_roi"


class TestCastNodeToGraphqlType:
    """Tests for cast_node_to_graphql_type matching function."""
    
    def test_entity_matching(self) -> None:
        """Test matching ENTITY type."""
        node = RetrievedNode(
            graph_name="g",
            id=1,
            label="Cell",
            properties={"type": "ENTITY", "kind": "Cell", "external_id": "abc123"}
        )
        result = cast_node_to_graphql_type(node)
        
        assert isinstance(result, Entity)
        assert result.kind() == "Cell"
        assert result.id() == "g:1"
    
    def test_structure_matching(self) -> None:
        """Test matching STRUCTURE type."""
        node = RetrievedNode(
            graph_name="g",
            id=2,
            label="ROI",
            properties={"type": "STRUCTURE", "identifier": "@mikro/roi", "object": "obj123"}
        )
        result = cast_node_to_graphql_type(node)
        
        assert isinstance(result, Structure)
        assert result.identifier() == "@mikro/roi"
        assert result.object() == "obj123"
    
    def test_natural_event_matching(self) -> None:
        """Test matching NATURAL_EVENT type."""
        node = RetrievedNode(
            graph_name="g",
            id=3,
            label="Mitosis",
            properties={"type": "NATURAL_EVENT", "kind": "Mitosis"}
        )
        result = cast_node_to_graphql_type(node)
        
        assert isinstance(result, NaturalEvent)
        assert result.kind() == "Mitosis"
    
    def test_metric_matching(self) -> None:
        """Test matching METRIC type."""
        node = RetrievedNode(
            graph_name="g",
            id=4,
            label="AreaMetric",
            properties={"type": "METRIC"}
        )
        result = cast_node_to_graphql_type(node)
        
        assert isinstance(result, Metric)
    
    def test_reagent_matching(self) -> None:
        """Test matching REAGENT type."""
        node = RetrievedNode(
            graph_name="g",
            id=5,
            label="Antibody",
            properties={"type": "REAGENT"}
        )
        result = cast_node_to_graphql_type(node)
        
        assert isinstance(result, Reagent)
    
    def test_protocol_event_matching(self) -> None:
        """Test matching PROTOCOL_EVENT type."""
        node = RetrievedNode(
            graph_name="g",
            id=6,
            label="Staining",
            properties={"type": "PROTOCOL_EVENT", "kind": "Staining"}
        )
        result = cast_node_to_graphql_type(node)
        
        assert isinstance(result, ProtocolEvent)
        assert result.kind() == "Staining"
    
    def test_fallback_to_label_entity(self) -> None:
        """Test fallback to Entity when type is None and label is ENTITY."""
        node = RetrievedNode(
            graph_name="g",
            id=1,
            label="Entity",
            properties={"name": "Test"}  # No type property
        )
        result = cast_node_to_graphql_type(node)
        
        assert isinstance(result, Entity)
    
    def test_fallback_to_label_structure(self) -> None:
        """Test fallback to Structure when type is None and label is STRUCTURE."""
        node = RetrievedNode(
            graph_name="g",
            id=1,
            label="Structure",
            properties={"identifier": "@test"}  # No type property
        )
        result = cast_node_to_graphql_type(node)
        
        assert isinstance(result, Structure)
    
    def test_unknown_type_raises(self) -> None:
        """Test that unknown types raise ValueError."""
        node = RetrievedNode(
            graph_name="g",
            id=1,
            label="Unknown",
            properties={"type": "UNKNOWN_TYPE"}
        )
        
        with pytest.raises(ValueError, match="Unknown node type"):
            cast_node_to_graphql_type(node)


class TestCastEdgeToGraphqlType:
    """Tests for cast_edge_to_graphql_type matching function."""
    
    def test_measurement_matching(self) -> None:
        """Test matching MEASUREMENT type."""
        edge = RetrievedEdge(
            graph_name="g",
            id=1,
            label="MEASURES",
            left_id=1,
            right_id=2,
            properties={"type": "MEASUREMENT", "key": "area", "value": 42.5}
        )
        result = cast_edge_to_graphql_type(edge)
        
        assert isinstance(result, Metric)
        assert result.value() == 42.5
    
    def test_assertion_matching(self) -> None:
        """Test matching ASSERTION type."""
        edge = RetrievedEdge(
            graph_name="g",
            id=2,
            label="ASSERTS",
            left_id=1,
            right_id=2,
            properties={"type": "ASSERTION", "subject": "user123"}
        )
        result = cast_edge_to_graphql_type(edge)
        
        assert isinstance(result, Assertion)
        assert result.subject() == "user123"
    
    def test_relation_matching(self) -> None:
        """Test matching RELATION type."""
        edge = RetrievedEdge(
            graph_name="g",
            id=3,
            label="RELATED_TO",
            left_id=1,
            right_id=2,
            properties={"type": "RELATION"}
        )
        result = cast_edge_to_graphql_type(edge)
        
        assert isinstance(result, Relation)
    
    def test_fallback_to_label_measurement_raises(self) -> None:
        """Test fallback based on label containing MEASURE raises for missing type."""
        edge = RetrievedEdge(
            graph_name="g",
            id=1,
            label="HAS_MEASUREMENT",
            left_id=1,
            right_id=2,
            properties={"key": "area"}  # No type property
        )
        with pytest.raises(NameError, match="Measurement"):
            cast_edge_to_graphql_type(edge)
    
    def test_fallback_to_label_assertion(self) -> None:
        """Test fallback based on label containing ASSERT."""
        edge = RetrievedEdge(
            graph_name="g",
            id=1,
            label="ASSERTS_VALUE",
            left_id=1,
            right_id=2,
            properties={"subject": "user"}  # No type property
        )
        result = cast_edge_to_graphql_type(edge)
        
        assert isinstance(result, Assertion)
    
    def test_fallback_to_relation(self) -> None:
        """Test fallback to Relation for unknown labels."""
        edge = RetrievedEdge(
            graph_name="g",
            id=1,
            label="CONNECTED_TO",
            left_id=1,
            right_id=2,
            properties={}  # No type property
        )
        result = cast_edge_to_graphql_type(edge)
        
        assert isinstance(result, Relation)
    
    def test_unknown_type_raises(self) -> None:
        """Test that unknown types raise ValueError."""
        edge = RetrievedEdge(
            graph_name="g",
            id=1,
            label="UNKNOWN",
            left_id=1,
            right_id=2,
            properties={"type": "UNKNOWN_EDGE_TYPE"}
        )
        
        with pytest.raises(ValueError, match="Unknown edge type"):
            cast_edge_to_graphql_type(edge)


class TestStrawberryTypeFields:
    """Tests for Strawberry type field access."""
    
    def test_entity_fields(self) -> None:
        """Test Entity field access via _value."""
        node = RetrievedNode(
            graph_name="test",
            id=42,
            label="Cell",
            properties={
                "type": "ENTITY",
                "kind": "Cell",
                "external_id": "ext-123",
                "schema_version": "1.0.0",
                "last_derived": 1700000000000,
                "name": "My Cell",
                "area": 100.5,
            }
        )
        entity = Entity(_value=node)
        
        # Test inherited Node fields
        assert entity.graph_id() == 42
        assert entity.global_id() == "test:42"
        assert entity.label() == "Cell"
        assert entity.id() == "test:42"
        
        # Test VersionedNode fields
        assert entity.schema_version() == "1.0.0"
        assert entity.last_derived() == 1700000000000
        
        # Test Entity-specific fields
        assert entity.kind() == "Cell"
        assert entity.external_id() == "ext-123"
        
        # Test property access
        props = entity.properties()
        assert props["name"] == "My Cell"
        assert props["area"] == 100.5
        assert "type" not in props  # Reserved key filtered
    
    def test_structure_fields(self) -> None:
        """Test Structure field access via _value."""
        node = RetrievedNode(
            graph_name="test",
            id=10,
            label="ROI",
            properties={
                "type": "STRUCTURE",
                "identifier": "@mikro/roi",
                "object": "roi-abc-123",
            }
        )
        structure = Structure(_value=node)
        
        assert structure.graph_id() == 10
        assert structure.identifier() == "@mikro/roi"
        assert structure.object() == "roi-abc-123"
    
    def test_edge_fields(self) -> None:
        """Test Edge field access via a Relation instance."""
        edge = RetrievedEdge(
            graph_name="test",
            id=100,
            label="MEASURES",
            left_id=1,
            right_id=2,
            properties={"type": "RELATION"},
        )
        relation = Relation(_value=edge)

        assert relation.graph_id() == 100
        assert relation.label() == "MEASURES"
        assert relation.left_id() == "test:1"
        assert relation.right_id() == "test:2"

    def test_property_fields(self) -> None:
        """Test Property field access via _value."""
        variable = RetrievedVariable(key="name", value="Test")
        prop = Property(_value=variable)

        assert prop.key() == "name"
        assert prop.value() == "Test"
