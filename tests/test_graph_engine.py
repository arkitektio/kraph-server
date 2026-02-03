"""
Tests for the Graph Engine

Tests the Pydantic validation layer, GraphController, and mutations.
"""
import pytest
from pydantic import ValidationError

from graph_engine.types import (
    GraphOperation,
    NodeChangeModel,
    EdgeChangeModel,
    ProvenanceModel,
    GraphMutationPayload,
    GraphMutationResult,
)
from graph_engine.controller import GraphController


class TestNodeChangeModel:
    """Tests for NodeChangeModel validation."""
    
    def test_valid_create_node(self):
        """CREATE operation with ref_id should be valid."""
        node = NodeChangeModel(
            ref_id="person1",
            label="Person",
            operation=GraphOperation.CREATE,
            properties={"name": "John", "age": 30},
        )
        assert node.label == "Person"
        assert node.ref_id == "person1"
        assert node.operation == GraphOperation.CREATE
    
    def test_create_with_id_fails(self):
        """CREATE operation should not have id set."""
        with pytest.raises(ValidationError) as exc_info:
            NodeChangeModel(
                id="graph:123",
                label="Person",
                operation=GraphOperation.CREATE,
                properties={"name": "John"},
            )
        assert "CREATE" in str(exc_info.value)
    
    def test_update_without_id_fails(self):
        """UPDATE operation requires id."""
        with pytest.raises(ValidationError) as exc_info:
            NodeChangeModel(
                label="Person",
                operation=GraphOperation.UPDATE,
                properties={"name": "Jane"},
            )
        assert "UPDATE" in str(exc_info.value)
    
    def test_update_with_id_succeeds(self):
        """UPDATE operation with id should succeed."""
        node = NodeChangeModel(
            id="test_graph:123",
            label="Person",
            operation=GraphOperation.UPDATE,
            properties={"name": "Jane"},
        )
        assert node.id == "test_graph:123"
        assert node.operation == GraphOperation.UPDATE
    
    def test_delete_requires_id(self):
        """DELETE operation requires id."""
        with pytest.raises(ValidationError):
            NodeChangeModel(
                label="Person",
                operation=GraphOperation.DELETE,
            )
    
    def test_merge_requires_external_id_or_id(self):
        """MERGE operation requires either external_id or id."""
        with pytest.raises(ValidationError):
            NodeChangeModel(
                label="Person",
                operation=GraphOperation.MERGE,
                properties={"name": "John"},
            )
    
    def test_merge_with_external_id_succeeds(self):
        """MERGE operation with external_id should succeed."""
        node = NodeChangeModel(
            label="Person",
            operation=GraphOperation.MERGE,
            external_id="ext-123",
            properties={"name": "John"},
        )
        assert node.external_id == "ext-123"
    
    def test_invalid_label_fails(self):
        """Label must be alphanumeric (with underscores)."""
        with pytest.raises(ValidationError):
            NodeChangeModel(
                ref_id="test",
                label="Person@Node",  # Invalid character
                operation=GraphOperation.CREATE,
            )


class TestEdgeChangeModel:
    """Tests for EdgeChangeModel validation."""
    
    def test_valid_edge(self):
        """Valid edge with refs."""
        edge = EdgeChangeModel(
            from_id="ref:person1",
            to_id="ref:org1",
            label="WORKS_FOR",
            properties={"since": "2020-01-01"},
        )
        assert edge.is_from_ref()
        assert edge.is_to_ref()
        assert edge.get_from_ref() == "person1"
        assert edge.get_to_ref() == "org1"
    
    def test_edge_with_db_ids(self):
        """Edge with database IDs."""
        edge = EdgeChangeModel(
            from_id="graph:123",
            to_id="graph:456",
            label="RELATES_TO",
        )
        assert not edge.is_from_ref()
        assert not edge.is_to_ref()
    
    def test_mixed_refs_and_ids(self):
        """Edge with mix of ref and DB ID."""
        edge = EdgeChangeModel(
            from_id="ref:new_node",
            to_id="graph:existing_123",
            label="CONNECTS",
        )
        assert edge.is_from_ref()
        assert not edge.is_to_ref()


class TestGraphMutationPayload:
    """Tests for GraphMutationPayload validation."""
    
    def test_valid_payload(self):
        """Valid payload with nodes and edges."""
        payload = GraphMutationPayload(
            graph_id="test_graph",
            provenance=ProvenanceModel(tool_name="test_tool", confidence=0.95),
            nodes=[
                NodeChangeModel(
                    ref_id="n1",
                    label="Person",
                    operation=GraphOperation.CREATE,
                    properties={"name": "John"},
                ),
                NodeChangeModel(
                    ref_id="n2",
                    label="Org",
                    operation=GraphOperation.CREATE,
                    properties={"name": "Acme"},
                ),
            ],
            edges=[
                EdgeChangeModel(
                    from_id="ref:n1",
                    to_id="ref:n2",
                    label="WORKS_FOR",
                )
            ],
        )
        assert len(payload.nodes) == 2
        assert len(payload.edges) == 1
    
    def test_invalid_edge_ref_fails(self):
        """Edge referencing non-existent ref should fail."""
        with pytest.raises(ValidationError) as exc_info:
            GraphMutationPayload(
                graph_id="test_graph",
                provenance=ProvenanceModel(tool_name="test_tool"),
                nodes=[
                    NodeChangeModel(
                        ref_id="n1",
                        label="Person",
                        operation=GraphOperation.CREATE,
                    ),
                ],
                edges=[
                    EdgeChangeModel(
                        from_id="ref:n1",
                        to_id="ref:n_missing",  # Does not exist
                        label="KNOWS",
                    )
                ],
            )
        assert "n_missing" in str(exc_info.value)
    
    def test_complexity_calculation(self):
        """Complexity score should be calculated correctly."""
        payload = GraphMutationPayload(
            graph_id="test_graph",
            provenance=ProvenanceModel(tool_name="test_tool"),
            nodes=[
                NodeChangeModel(
                    ref_id="n1",
                    label="Person",
                    operation=GraphOperation.CREATE,
                    properties={"a": 1, "b": 2, "c": 3},
                ),
                NodeChangeModel(
                    id="graph:123",
                    label="Org",
                    operation=GraphOperation.UPDATE,
                    properties={"x": 1},
                ),
            ],
            edges=[
                EdgeChangeModel(
                    from_id="ref:n1",
                    to_id="graph:123",
                    label="WORKS_FOR",
                    properties={"since": "2020"},
                )
            ],
        )
        # CREATE: 1 base + 3 props = 4
        # UPDATE: 2 base + 1 prop = 3
        # EDGE: 2 base + 1 prop = 3
        # Total = 10
        assert payload.calculate_complexity() == 10


class TestProvenanceModel:
    """Tests for ProvenanceModel validation."""
    
    def test_valid_provenance(self):
        """Valid provenance with all fields."""
        prov = ProvenanceModel(
            tool_name="my_analysis_tool",
            confidence=0.85,
            user_id="user123",
            client_id="client456",
            assignation_id="task789",
            metadata={"version": "1.0.0"},
        )
        assert prov.tool_name == "my_analysis_tool"
        assert prov.confidence == 0.85
    
    def test_confidence_bounds(self):
        """Confidence must be between 0 and 1."""
        with pytest.raises(ValidationError):
            ProvenanceModel(tool_name="test", confidence=1.5)
        
        with pytest.raises(ValidationError):
            ProvenanceModel(tool_name="test", confidence=-0.1)
    
    def test_tool_name_required(self):
        """Tool name is required."""
        with pytest.raises(ValidationError):
            ProvenanceModel(confidence=0.5)


class TestMigrationController:
    """Tests for MigrationController safety checks."""
    
    def test_limit_injection(self):
        """LIMIT clause should be injected if missing."""
        controller = MigrationController(default_limit=1000)
        
        query = "MATCH (n:Person) WHERE n.status = 'old' SET n.status = 'archived' RETURN n"
        safe_query = controller._ensure_limit_clause(query)
        
        assert "LIMIT 1000" in safe_query
        assert "SET n.status = 'archived'" in safe_query
    
    def test_existing_limit_preserved(self):
        """Existing LIMIT clause should be preserved."""
        controller = MigrationController(default_limit=1000)
        
        query = "MATCH (n:Person) WHERE n.status = 'old' WITH n LIMIT 500 SET n.status = 'archived' RETURN n"
        safe_query = controller._ensure_limit_clause(query)
        
        # Should not add another LIMIT
        assert safe_query.count("LIMIT") == 1
        assert "LIMIT 500" in safe_query
    
    def test_no_modification_query(self):
        """Query without SET/DELETE/REMOVE should be unchanged."""
        controller = MigrationController(default_limit=1000)
        
        query = "MATCH (n:Person) RETURN n"
        safe_query = controller._ensure_limit_clause(query)
        
        # Should not modify a read-only query
        assert "LIMIT" not in safe_query


class TestGraphMutationResult:
    """Tests for GraphMutationResult."""
    
    def test_success_result(self):
        """Successful result with id_map."""
        result = GraphMutationResult(
            success=True,
            transaction_id="tx-123",
            id_map={"n1": "graph:100", "n2": "graph:101"},
            assertion_id="graph:99",
        )
        assert result.success
        assert result.id_map["n1"] == "graph:100"
    
    def test_failure_result(self):
        """Failure result with errors."""
        result = GraphMutationResult.failure(
            errors=["Node not found", "Permission denied"],
            transaction_id="tx-456",
        )
        assert not result.success
        assert len(result.errors) == 2
        assert "Node not found" in result.errors
