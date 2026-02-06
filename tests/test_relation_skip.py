"""
Tests for relationship creation with supporting evidence.

TODO: These tests need to be refactored to use the new pattern where:
- Each method receives graph or entity_category/relation_category as first parameter  
- No graph parameter in GraphController.__init__()
- Use bio_graph fixture to get entity/relation categories

These tests verify that:
1. Relations between entities can be created with supporting evidence (ROIs)
2. Measurements on supporting structures are properly rolled up to the relation edge
3. ShadowLink nodes are created to track evidence
4. The relation edge properties are correctly materialized from evidence
"""
import pytest
import uuid
from graph_engine.controller import GraphController
from graph_engine import input_models as inputs
from graph_engine import base_models as models
from core import models as core_models


def _uid(prefix: str = "test") -> str:
    """Generate a unique ID for test objects."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class TestRelationCreation:
    """Tests for basic relation creation."""
    
    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category/relation_category parameters")
    def test_create_relation_with_single_roi_evidence(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test creating a relation between two entities with a single ROI as evidence."""
        pass

    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category/relation_category parameters")
    def test_create_relation_with_multiple_roi_evidence(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test creating a relation with multiple ROIs as evidence."""
        pass


class TestRelationMaterialization:
    """Tests for relation property materialization from evidence."""
    
    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category/relation_category parameters")
    def test_mean_aggregation_materializes_correctly(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test that MEAN aggregation correctly averages measurements across ROIs."""
        pass
        
    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category/relation_category parameters")
    def test_sum_aggregation_materializes_correctly(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test that SUM aggregation correctly sums measurements across ROIs."""
        pass
    
    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category/relation_category parameters")
    def test_min_aggregation_materializes_correctly(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test that MIN aggregation correctly finds minimum across ROIs."""
        pass
    
    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category/relation_category parameters")
    def test_count_aggregation_materializes_correctly(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test that COUNT aggregation correctly counts measurements."""
        pass


class TestRelationEvidenceGraph:
    """Tests for the evidence graph structure (ShadowLink, INFORMS, etc.)."""
    
    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category/relation_category parameters")
    def test_shadow_link_created_for_relation(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test that a ShadowLink node is created when creating a relation."""
        pass
        
    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category/relation_category parameters")
    def test_evidence_structures_informs_shadow_link(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test that evidence structures are connected to ShadowLink via INFORMS."""
        pass
        
    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category/relation_category parameters")
    def test_shadow_link_reifies_entities(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test that ShadowLink is connected to both source and target via REIFIES."""
        pass


class TestRelationProvenance:
    """Tests for relation provenance tracking."""
    
    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category/relation_category parameters")
    def test_relation_has_assertion_provenance(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test that relations are created with an Assertion tracking provenance."""
        pass
