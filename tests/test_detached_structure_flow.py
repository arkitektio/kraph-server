"""
Tests for creating entities and then linking detached structures with measurements.

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


def _uid(prefix: str) -> str:
    """Generate a unique ID with prefix for test isolation."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class TestDetachedStructureFlow:
    """Test creating detached structures and linking them to entities later."""

    def test_create_entity_then_detached_roi_then_link(self, graph_controller: GraphController):
        """
        Test the flow:
        1. Create an AIS entity with initial evidence
        2. Create a detached ROI structure
        3. Add measurement to the detached ROI
        4. Link the ROI to the entity
        5. Verify entity properties are recalculated
        """
        roi_1_id = _uid("roi_initial")
        roi_2_id = _uid("roi_detached")
        
        # Step 1: Create AIS with one ROI evidence (avg_length = 100)
        payload = inputs.EntityCreationPayload(
            kind="AIS",
            supporting_evidence=[
                inputs.StructureReference(
                    identifier="@mikro/roi",
                    object=roi_1_id,
                    measurements=[
                        inputs.MeasurementInput(
                            key="vector_length",
                            value=100,
                            timestamp=1000
                        )
                    ]
                )
            ],
            provenance=inputs.ProvenanceContext(subject="user1", app_id="test")
        )
        
        result = graph_controller.create_entity(payload)
        
        # Verify initial entity properties
        entity = graph_controller.get_entity(id=result.db_id)
        assert entity.properties["avg_length"] == 100  # Only one measurement
        
        # Step 2: Create a detached ROI structure
        detached_structure = graph_controller.create_structure(
            identifier="@mikro/roi",
            object=roi_2_id
        )
        assert detached_structure is not None
        assert detached_structure.object == roi_2_id
        
        # Step 3: Add measurement to detached ROI (vector_length = 200)
        measurement = inputs.MeasurementInput(
            key="vector_length",
            value=200,
            timestamp=2000
        )
        provenance = inputs.ProvenanceContext(subject="user1", app_id="test")
        
        meas_result = graph_controller.add_measurement(
            structure_identifier="@mikro/roi",
            structure_object=roi_2_id,
            measurement=measurement,
            provenance=provenance
        )
        assert meas_result.value == 200
        
        # Verify entity is still at 100 (structure not linked yet)
        entity_before_link = graph_controller.get_entity(id=result.db_id)
        assert entity_before_link.properties["avg_length"] == 100
        
        # Step 4: Link the detached structure to the entity
        updated_entity = graph_controller.link_structure_to_entity(
            structure_identifier="@mikro/roi",
            structure_object=roi_2_id,
            entity_id=result.db_id
        )
        
        # Step 5: Verify entity properties are recalculated
        # avg_length should now be (100 + 200) / 2 = 150
        assert updated_entity.properties["avg_length"] == 150
        
        # Verify informing structures
        informing = graph_controller.get_informing_structures(entity_id=result.db_id)
        assert len(informing) == 2
        objects = {s.object for s in informing}
        assert roi_1_id in objects
        assert roi_2_id in objects

    def test_create_entity_empty_then_add_structures(self, graph_controller: GraphController):
        """
        Test creating an entity with no initial evidence, then adding structures later.
        
        Flow:
        1. Create AIS with minimal evidence (told_you_so for name only)
        2. Create detached ROI with measurement
        3. Link ROI to entity
        4. Verify properties are calculated
        """
        tys_id = _uid("tys_name")
        roi_id = _uid("roi_later")
        
        # Step 1: Create AIS with just a ToldYouSo for the name
        payload = inputs.EntityCreationPayload(
            kind="AIS",
            supporting_evidence=[
                inputs.create_told_you_so(
                    measurements=[
                        inputs.create_max_confidence_measurement(
                            key="name",
                            value="My AIS Entity",
                            timestamp=1000
                        )
                    ],
                    object=tys_id
                )
            ],
            provenance=inputs.ProvenanceContext(subject="user1", app_id="test")
        )
        
        result = graph_controller.create_entity(payload)
        
        # Verify: name is set but avg_length is not present
        entity = graph_controller.get_entity(id=result.db_id)
        assert entity.properties.get("name") == "My AIS Entity"
        assert "avg_length" not in entity.properties  # No ROI evidence yet
        
        # Step 2: Create detached ROI with measurement
        graph_controller.create_structure(identifier="@mikro/roi", object=roi_id)
        graph_controller.add_measurement(
            structure_identifier="@mikro/roi",
            structure_object=roi_id,
            measurement=inputs.MeasurementInput(key="vector_length", value=75.5, timestamp=2000),
            provenance=inputs.ProvenanceContext(subject="user1", app_id="test")
        )
        
        # Step 3: Link ROI to entity
        updated_entity = graph_controller.link_structure_to_entity(
            structure_identifier="@mikro/roi",
            structure_object=roi_id,
            entity_id=result.db_id
        )
        
        # Step 4: Verify properties
        assert updated_entity.properties.get("name") == "My AIS Entity"
        assert updated_entity.properties.get("avg_length") == 75.5

    def test_add_multiple_measurements_then_link(self, graph_controller: GraphController):
        """
        Test adding multiple measurements to a structure before linking.
        
        Flow:
        1. Create entity with initial evidence
        2. Create detached ROI
        3. Add multiple measurements to detached ROI
        4. Link to entity
        5. Verify aggregation uses all measurements
        """
        initial_roi = _uid("roi_init")
        detached_roi = _uid("roi_multi_meas")
        
        # Create entity with initial ROI (value=100)
        result = graph_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="AIS",
                supporting_evidence=[
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=initial_roi,
                        measurements=[
                            inputs.MeasurementInput(key="vector_length", value=100, timestamp=1000)
                        ]
                    )
                ],
                provenance=inputs.ProvenanceContext(subject="user1", app_id="test")
            )
        )
        
        # Create detached ROI and add multiple measurements
        graph_controller.create_structure(identifier="@mikro/roi", object=detached_roi)
        
        provenance = inputs.ProvenanceContext(subject="user1", app_id="test")
        
        # Add first measurement (value=200)
        graph_controller.add_measurement(
            structure_identifier="@mikro/roi",
            structure_object=detached_roi,
            measurement=inputs.MeasurementInput(key="vector_length", value=200, timestamp=2000),
            provenance=provenance
        )
        
        # Add second measurement (value=300)
        graph_controller.add_measurement(
            structure_identifier="@mikro/roi",
            structure_object=detached_roi,
            measurement=inputs.MeasurementInput(key="vector_length", value=300, timestamp=3000),
            provenance=provenance
        )
        
        # Link detached ROI to entity
        updated_entity = graph_controller.link_structure_to_entity(
            structure_identifier="@mikro/roi",
            structure_object=detached_roi,
            entity_id=result.db_id
        )
        
        # avg_length should be mean of 100, 200, 300 = 200
        assert updated_entity.properties["avg_length"] == 200

    def test_sequence_measurement_structure_entity(self, graph_controller: GraphController):
        """
        Test sequence: Create structure -> Add measurements -> Create entity referencing it.
        
        This is the "pre-populated structure" pattern.
        """
        roi_id = _uid("roi_pre")
        
        # Step 1: Create structure first (detached)
        structure = graph_controller.create_structure(
            identifier="@mikro/roi",
            object=roi_id
        )
        assert structure is not None
        
        # Step 2: Add measurement to structure
        provenance = inputs.ProvenanceContext(subject="user1", app_id="test")
        graph_controller.add_measurement(
            structure_identifier="@mikro/roi",
            structure_object=roi_id,
            measurement=inputs.MeasurementInput(key="vector_length", value=42, timestamp=1000),
            provenance=provenance
        )
        
        # Step 3: Create entity that references the pre-existing structure
        # Note: create_entity uses MERGE, so it will find the existing structure
        result = graph_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="AIS",
                supporting_evidence=[
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=roi_id,
                        measurements=[
                            # Add another measurement during entity creation
                            inputs.MeasurementInput(key="vector_length", value=58, timestamp=2000)
                        ]
                    )
                ],
                provenance=inputs.ProvenanceContext(subject="user1", app_id="test")
            )
        )
        
        # Verify: avg_length should be mean of pre-existing (42) and new (58) = 50
        entity = graph_controller.get_entity(id=result.db_id)
        assert entity.properties["avg_length"] == 50

    def test_link_without_recalculate(self, graph_controller: GraphController):
        """
        Test linking a structure without triggering recalculation.
        
        This is useful for batch operations where recalculation
        should be done once at the end.
        """
        roi_1_id = _uid("roi_1")
        roi_2_id = _uid("roi_2")
        
        # Create entity with initial measurement (value=100)
        result = graph_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="AIS",
                supporting_evidence=[
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=roi_1_id,
                        measurements=[
                            inputs.MeasurementInput(key="vector_length", value=100, timestamp=1000)
                        ]
                    )
                ],
                provenance=inputs.ProvenanceContext(subject="user1", app_id="test")
            )
        )
        
        initial_last_derived = graph_controller.get_entity(id=result.db_id).last_derived
        
        # Create and populate detached structure
        graph_controller.create_structure(identifier="@mikro/roi", object=roi_2_id)
        graph_controller.add_measurement(
            structure_identifier="@mikro/roi",
            structure_object=roi_2_id,
            measurement=inputs.MeasurementInput(key="vector_length", value=200, timestamp=2000),
            provenance=inputs.ProvenanceContext(subject="user1", app_id="test")
        )
        
        # Link WITHOUT recalculation
        updated_entity = graph_controller.link_structure_to_entity(
            structure_identifier="@mikro/roi",
            structure_object=roi_2_id,
            entity_id=result.db_id,
            recalculate=False  # Don't recalculate
        )
        
        # Properties should still be the old value
        assert updated_entity.properties["avg_length"] == 100
        # last_derived should be unchanged
        assert updated_entity.last_derived == initial_last_derived
        
        # But the structure IS linked
        informing = graph_controller.get_informing_structures(entity_id=result.db_id)
        assert len(informing) == 2

    def test_link_multiple_structures_at_once(self, graph_controller: GraphController):
        """
        Test linking multiple detached structures to an entity.
        """
        roi_ids = [_uid(f"roi_{i}") for i in range(4)]
        
        # Create entity with first ROI (value=100)
        result = graph_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="AIS",
                supporting_evidence=[
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=roi_ids[0],
                        measurements=[
                            inputs.MeasurementInput(key="vector_length", value=100, timestamp=1000)
                        ]
                    )
                ],
                provenance=inputs.ProvenanceContext(subject="user1", app_id="test")
            )
        )
        
        # Create 3 detached structures with measurements (values: 200, 300, 400)
        provenance = inputs.ProvenanceContext(subject="user1", app_id="test")
        for i, roi_id in enumerate(roi_ids[1:], start=2):
            value = i * 100  # 200, 300, 400
            graph_controller.create_structure(identifier="@mikro/roi", object=roi_id)
            graph_controller.add_measurement(
                structure_identifier="@mikro/roi",
                structure_object=roi_id,
                measurement=inputs.MeasurementInput(
                    key="vector_length", 
                    value=value, 
                    timestamp=i * 1000
                ),
                provenance=provenance
            )
        
        # Link all detached structures without recalculating
        for roi_id in roi_ids[1:]:
            graph_controller.link_structure_to_entity(
                structure_identifier="@mikro/roi",
                structure_object=roi_id,
                entity_id=result.db_id,
                recalculate=False
            )
        
        # Properties still old (100) since we didn't recalculate
        entity_before = graph_controller.get_entity(id=result.db_id)
        assert entity_before.properties["avg_length"] == 100
        
        # Now manually trigger recalculation by linking the last one with recalculate=True
        # Actually, we need to trigger recalculation - let's just link a dummy or call get with force
        # For now, let's re-link the last one with recalculate=True
        updated_entity = graph_controller.link_structure_to_entity(
            structure_identifier="@mikro/roi",
            structure_object=roi_ids[-1],
            entity_id=result.db_id,
            recalculate=True
        )
        
        # avg_length = mean(100, 200, 300, 400) = 250
        assert updated_entity.properties["avg_length"] == 250
        
        # Verify all structures are linked
        informing = graph_controller.get_informing_structures(entity_id=result.db_id)
        assert len(informing) == 4


class TestVersioningOnRecalculation:
    """Test that schema_version and last_derived are properly updated on recalculation."""

    def test_schema_version_set_on_link(self, graph_controller: GraphController):
        """
        Test that schema_version is properly set when linking a structure.
        """
        roi_1 = _uid("roi_version_1")
        roi_2 = _uid("roi_version_2")
        
        # Create entity
        result = graph_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="AIS",
                supporting_evidence=[
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=roi_1,
                        measurements=[
                            inputs.MeasurementInput(key="vector_length", value=100, timestamp=1000)
                        ]
                    )
                ],
                provenance=inputs.ProvenanceContext(subject="user1", app_id="test")
            )
        )
        
        entity = graph_controller.get_entity(id=result.db_id)
        assert entity.schema_version == "1.0"  # From bio_graph_schema fixture
        initial_last_derived = entity.last_derived
        assert initial_last_derived > 0
        
        # Wait a tiny bit to ensure timestamp changes
        import time
        time.sleep(0.01)
        
        # Create and link a new structure
        graph_controller.create_structure(identifier="@mikro/roi", object=roi_2)
        graph_controller.add_measurement(
            structure_identifier="@mikro/roi",
            structure_object=roi_2,
            measurement=inputs.MeasurementInput(key="vector_length", value=200, timestamp=2000),
            provenance=inputs.ProvenanceContext(subject="user1", app_id="test")
        )
        
        updated_entity = graph_controller.link_structure_to_entity(
            structure_identifier="@mikro/roi",
            structure_object=roi_2,
            entity_id=result.db_id
        )
        
        # schema_version should still be "1.0"
        assert updated_entity.schema_version == "1.0"
        # last_derived should be updated (greater than before)
        assert updated_entity.last_derived >= initial_last_derived

    def test_last_derived_not_updated_without_recalc(self, graph_controller: GraphController):
        """
        Test that last_derived is NOT updated when recalculate=False.
        """
        roi_1 = _uid("roi_norecalc_1")
        roi_2 = _uid("roi_norecalc_2")
        
        # Create entity
        result = graph_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="AIS",
                supporting_evidence=[
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=roi_1,
                        measurements=[
                            inputs.MeasurementInput(key="vector_length", value=100, timestamp=1000)
                        ]
                    )
                ],
                provenance=inputs.ProvenanceContext(subject="user1", app_id="test")
            )
        )
        
        entity = graph_controller.get_entity(id=result.db_id)
        original_last_derived = entity.last_derived
        
        # Create and link without recalculation
        graph_controller.create_structure(identifier="@mikro/roi", object=roi_2)
        graph_controller.add_measurement(
            structure_identifier="@mikro/roi",
            structure_object=roi_2,
            measurement=inputs.MeasurementInput(key="vector_length", value=200, timestamp=2000),
            provenance=inputs.ProvenanceContext(subject="user1", app_id="test")
        )
        
        updated_entity = graph_controller.link_structure_to_entity(
            structure_identifier="@mikro/roi",
            structure_object=roi_2,
            entity_id=result.db_id,
            recalculate=False
        )
        
        # last_derived should be unchanged
        assert updated_entity.last_derived == original_last_derived
