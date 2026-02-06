"""
Tests for creating entities and then linking detached structures with measurements.

TODO: These tests need to be refactored to use the new pattern where:
- Each method receives graph or entity_category as first parameter
- No _payload_to_kwargs helper needed
- Use bio_graph fixture to get entity categories

These tests verify that:
1. Entities can be created first (with or without initial evidence)
2. Structures can be created independently (detached)
3. Measurements can be added to detached structures
4. Detached structures can later be linked to entities
5. Entity properties are correctly recalculated after linking
"""
import pytest
import uuid
from graph_engine.controller import GraphController
from graph_engine import input_models as inputs
from core import models as core_models


def _uid(prefix: str) -> str:
    """Generate a unique ID with prefix for test isolation."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class TestDetachedStructureFlow:
    """Test creating detached structures and linking them to entities later."""

    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category parameters")
    def test_create_entity_then_detached_roi_then_link(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """
        Test the flow:
        1. Create an AIS entity with initial evidence
        2. Create a detached ROI structure
        3. Add measurement to the detached ROI
        4. Link the ROI to the entity
        5. Verify entity properties are recalculated
        """
        pass

    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category parameters")
    def test_create_entity_empty_then_add_structures(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test creating an entity with no initial evidence, then adding structures later."""
        pass

    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category parameters")
    def test_add_multiple_measurements_then_link(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test adding multiple measurements to a structure before linking."""
        pass

    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category parameters")
    def test_sequence_measurement_structure_entity(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test sequence: Create structure -> Add measurements -> Create entity referencing it."""
        pass

    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category parameters")
    def test_link_without_recalculate(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test linking a structure without triggering recalculation."""
        pass

    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category parameters")
    def test_link_multiple_structures_at_once(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test linking multiple detached structures to an entity."""
        pass


class TestVersioningOnRecalculation:
    """Test that schema_version and last_derived are properly updated on recalculation."""

    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category parameters")
    def test_schema_version_set_on_link(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test that schema_version is properly set when linking a structure."""
        pass

    @pytest.mark.skip(reason="Needs refactoring to new pattern with graph/entity_category parameters")
    def test_last_derived_not_updated_without_recalc(self, graph_controller: GraphController, bio_graph: core_models.Graph):
        """Test that last_derived is NOT updated when recalculate=False."""
        pass
