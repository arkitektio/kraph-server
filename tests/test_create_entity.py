import pytest
from datetime import datetime, timezone
from graph_engine.controller import GraphController
from graph_engine.engine.protocol import CypherEngine
from graph_engine import base_models as models
from graph_engine import input_models as inputs 
from graph_engine import vocab


def test_create_ais_with_timestamp_conversion(graph_controller: GraphController, bio_graph_schema: models.GraphDefinitionModel):
    """
    Test that ISO timestamps are converted to Unix Milliseconds (int).
    """

    # ISO String input
    ts_string = "2023-10-27T10:00:00.123Z"
    a_little_later = "2023-10-27T10:05:00.456Z"
    

    payload = inputs.EntityCreationPayload(
        kind="AIS",
        supporting_evidence=[
            inputs.StructureReference(
                identifier="@mikro/roi",
                object="1",
                measurements=[
                inputs.create_max_confidence_measurement(
                    key="vector_length", 
                    value=100, 
                    timestamp=ts_string  
                )]
            ),
            inputs.StructureReference(
                identifier="@mikro/roi",
                object="2",
                measurements=[
                inputs.create_max_confidence_measurement(
                    key="vector_length", 
                    value=120, 
                    timestamp=a_little_later  
                )]
            ),  
            inputs.create_told_you_so(
                measurements=[
                    inputs.create_max_confidence_measurement(
                        key="name", 
                        value="A little ducky", 
                        timestamp="2023-10-27T10:10:00.789Z"  
                    )                ],
                object="told_you_so_1"
            )
        ],
        provenance=inputs.ProvenanceContext(subject="test", app_id="test")
    )

    result = graph_controller.create_entity(payload)
    
    entity = graph_controller.get_entity(
        id=result.db_id,
    )
    
    # Verify properties
    assert "avg_length" in entity.properties
    assert entity.properties["avg_length"] == 110  # Average of 100 and 120
    assert entity.properties["name"] == "A little ducky"  # From told_you_so


def test_create_entity_with_single_evidence(graph_controller: GraphController):
    """
    Test creating an entity with a single supporting evidence creates correct graph structure.
    """
    payload = inputs.EntityCreationPayload(
        kind="AIS",
        supporting_evidence=[
            inputs.StructureReference(
                identifier="@mikro/roi",
                object="roi_single_001",
                measurements=[
                    inputs.MeasurementInput(
                        key="vector_length",
                        value=50.5,
                        confidence=0.95,
                        unit="um",
                        timestamp=1698400800000
                    )
                ]
            )
        ],
        provenance=inputs.ProvenanceContext(subject="user123", app_id="mikro")
    )
    
    result = graph_controller.create_entity(payload)
    
    # Check the result
    assert result.db_id is not None
    assert result.ref_id is not None
    
    # Verify entity was created with correct properties
    entity = graph_controller.get_entity(id=result.db_id)
    assert entity is not None
    assert "avg_length" in entity.properties
    assert entity.properties["avg_length"] == 50.5  # Single measurement = same value
    
    # Verify the structure exists and is linked
    structure = graph_controller.get_structure(identifier="@mikro/roi", object="roi_single_001")
    assert structure is not None
    
    # Verify INFORMS relationship exists
    informing_structures = graph_controller.get_informing_structures(entity_id=result.db_id)
    assert len(informing_structures) == 1
    assert informing_structures[0].object == "roi_single_001"


def test_create_entity_with_multiple_evidence_sources(graph_controller: GraphController):
    """
    Test creating an entity with multiple evidence sources from different structures.
    """
    payload = inputs.EntityCreationPayload(
        kind="AIS",
        supporting_evidence=[
            inputs.StructureReference(
                identifier="@mikro/roi",
                object="roi_multi_001",
                measurements=[
                    inputs.MeasurementInput(key="vector_length", value=100, timestamp=1000)
                ]
            ),
            inputs.StructureReference(
                identifier="@mikro/roi", 
                object="roi_multi_002",
                measurements=[
                    inputs.MeasurementInput(key="vector_length", value=200, timestamp=2000)
                ]
            ),
            inputs.StructureReference(
                identifier="@mikro/roi",
                object="roi_multi_003", 
                measurements=[
                    inputs.MeasurementInput(key="vector_length", value=150, timestamp=3000)
                ]
            )
        ],
        provenance=inputs.ProvenanceContext(subject="user1", app_id="app1")
    )
    
    result = graph_controller.create_entity(payload)
    
    # Verify entity was created
    entity = graph_controller.get_entity(id=result.db_id)
    assert entity is not None
    
    # Verify avg_length is the mean of all three measurements
    assert "avg_length" in entity.properties
    assert entity.properties["avg_length"] == 150  # (100 + 200 + 150) / 3
    
    # Verify all three structures are linked
    informing_structures = graph_controller.get_informing_structures(entity_id=result.db_id)
    assert len(informing_structures) == 3
    structure_objects = {s.object for s in informing_structures}
    assert structure_objects == {"roi_multi_001", "roi_multi_002", "roi_multi_003"}


def test_create_entity_with_told_you_so_evidence(graph_controller: GraphController):
    """
    Test creating an entity with ToldYouSo evidence for manual property assertions.
    """
    payload = inputs.EntityCreationPayload(
        kind="AIS",
        supporting_evidence=[
            inputs.create_told_you_so(
                object="tys_test_001",
                measurements=[
                    inputs.create_max_confidence_measurement(
                        key="name",
                        value="My Custom AIS",
                        timestamp=1698400800000
                    )
                ]
            )
        ],
        provenance=inputs.ProvenanceContext(subject="expert", app_id="manual_entry")
    )
    
    result = graph_controller.create_entity(payload)
    
    # Verify entity was created with the name from ToldYouSo
    entity = graph_controller.get_entity(id=result.db_id)
    assert entity is not None
    assert "name" in entity.properties
    assert entity.properties["name"] == "My Custom AIS"
    
    # Verify ToldYouSo structure exists and is linked
    informing_structures = graph_controller.get_informing_structures(entity_id=result.db_id)
    assert len(informing_structures) == 1
    assert informing_structures[0].object == "tys_test_001"


def test_create_entity_with_multiple_measurements_per_structure(graph_controller: GraphController):
    """
    Test creating an entity where a single structure has multiple measurements.
    """
    payload = inputs.EntityCreationPayload(
        kind="AIS",
        supporting_evidence=[
            inputs.StructureReference(
                identifier="@mikro/roi",
                object="roi_multi_measure",
                measurements=[
                    inputs.MeasurementInput(key="vector_length", value=100, unit="um", timestamp=1000),
                    inputs.MeasurementInput(key="vector_length", value=150, unit="um", timestamp=2000),
                    inputs.MeasurementInput(key="vector_length", value=125, unit="um", timestamp=3000),
                ]
            )
        ],
        provenance=inputs.ProvenanceContext(subject="tool", app_id="analyzer")
    )
    
    result = graph_controller.create_entity(payload)
    
    # Verify entity was created
    entity = graph_controller.get_entity(id=result.db_id)
    assert entity is not None
    
    # Verify avg_length is the mean of all three measurements
    assert "avg_length" in entity.properties
    assert entity.properties["avg_length"] == 125  # (100 + 150 + 125) / 3
    
    # Verify only one structure is linked (not three)
    informing_structures = graph_controller.get_informing_structures(entity_id=result.db_id)
    assert len(informing_structures) == 1
    assert informing_structures[0].object == "roi_multi_measure"
    
    # Verify structure has all three measurements
    measurements = graph_controller.get_measurements_for_structure(
        identifier="@mikro/roi", 
        structure_object="roi_multi_measure"
    )
    assert len(measurements) == 3


def test_create_entity_evidence_links_to_entity(graph_controller: GraphController):
    """
    Test that evidence structures are properly linked to the created entity via INFORMS.
    """
    payload = inputs.EntityCreationPayload(
        kind="AIS",
        supporting_evidence=[
            inputs.StructureReference(
                identifier="@mikro/roi",
                object="roi_link_test_001",
                measurements=[
                    inputs.MeasurementInput(key="vector_length", value=100, timestamp=1000)
                ]
            )
        ],
        provenance=inputs.ProvenanceContext(subject="user", app_id="app")
    )
    
    result = graph_controller.create_entity(payload)
    
    # Verify entity exists
    entity = graph_controller.get_entity(id=result.db_id)
    assert entity is not None
    
    # Verify INFORMS relationship exists by querying from entity side
    informing_structures = graph_controller.get_informing_structures(entity_id=result.db_id)
    assert len(informing_structures) == 1
    assert informing_structures[0].object == "roi_link_test_001"
    
    # Verify INFORMS relationship exists by querying from structure side
    informed_entities = graph_controller.get_entities_informed_by(
        identifier="@mikro/roi",
        structure_object="roi_link_test_001"
    )
    assert len(informed_entities) == 1
    assert informed_entities[0].entity_id == result.db_id


def test_create_entity_assertion_links_to_measurements(graph_controller: GraphController):
    """
    Test that all measurements are linked to the provenance assertion via ASSERTED.
    """
    payload = inputs.EntityCreationPayload(
        kind="AIS",
        supporting_evidence=[
            inputs.StructureReference(
                identifier="@mikro/roi",
                object="roi_assert_1",
                measurements=[
                    inputs.MeasurementInput(key="vector_length", value=1, timestamp=1000),
                    inputs.MeasurementInput(key="vector_length", value=2, timestamp=2000),
                ]
            ),
            inputs.StructureReference(
                identifier="@mikro/roi",
                object="roi_assert_2",
                measurements=[
                    inputs.MeasurementInput(key="vector_length", value=3, timestamp=3000),
                ]
            )
        ],
        provenance=inputs.ProvenanceContext(subject="user", app_id="app")
    )
    
    result = graph_controller.create_entity(payload)
    
    # Verify entity was created
    entity = graph_controller.get_entity(id=result.db_id)
    assert entity is not None
    
    # Get the assertion that generated this entity
    assertion = graph_controller.get_assertion_for_entity(entity_id=result.db_id)
    assert assertion is not None
    assert assertion.subject == "user"
    assert assertion.app_id == "app"
    
    # Verify all measurements are linked to this assertion
    asserted_measurements = graph_controller.get_measurements_for_assertion(assertion_id=assertion.graph_id)
    assert len(asserted_measurements) == 3


def test_create_entity_provenance_includes_action_info(graph_controller: GraphController):
    """
    Test that provenance with action info is correctly stored.
    """
    payload = inputs.EntityCreationPayload(
        kind="AIS",
        supporting_evidence=[
            inputs.StructureReference(
                identifier="@mikro/roi",
                object="roi_prov_001",
                measurements=[
                    inputs.MeasurementInput(key="vector_length", value=1, timestamp=1000)
                ]
            )
        ],
        provenance=inputs.ProvenanceContext(
            subject="user123",
            app_id="mikro-napari",
            action_id="segment_cells",
            action_name="Segment Cells",
            action_args={"threshold": 0.5, "min_size": 10}
        )
    )
    
    result = graph_controller.create_entity(payload)
    
    # Verify entity was created
    entity = graph_controller.get_entity(id=result.db_id)
    assert entity is not None
    
    # Get the assertion and verify provenance info
    assertion = graph_controller.get_assertion_for_entity(entity_id=result.db_id)
    assert assertion is not None
    assert assertion.subject == "user123"
    assert assertion.app_id == "mikro-napari"
    assert assertion.action_id == "segment_cells"
    assert assertion.action_name == "Segment Cells"


def test_create_entity_no_evidence(graph_controller: GraphController):
    """
    Test creating an entity with no supporting evidence (edge case).
    """
    payload = inputs.EntityCreationPayload(
        kind="AIS",
        supporting_evidence=[],
        provenance=inputs.ProvenanceContext(subject="user", app_id="app")
    )
    
    result = graph_controller.create_entity(payload)
    
    # Should still create the entity and assertion
    assert result.ref_id is not None
    assert result.db_id is not None
    
    # Verify entity exists
    entity = graph_controller.get_entity(id=result.db_id)
    assert entity is not None
    
    # Verify no structures are linked
    informing_structures = graph_controller.get_informing_structures(entity_id=result.db_id)
    assert len(informing_structures) == 0
    
    # Verify assertion still exists
    assertion = graph_controller.get_assertion_for_entity(entity_id=result.db_id)
    assert assertion is not None


def test_measurement_timestamp_conversion_datetime(graph_controller: GraphController):
    """
    Test that datetime objects are correctly converted to milliseconds.
    """
    dt = datetime(2023, 10, 27, 10, 0, 0, 123000, tzinfo=timezone.utc)
    expected_ms = 1698400800123  # Unix ms for this datetime
    
    payload = inputs.EntityCreationPayload(
        kind="AIS",
        supporting_evidence=[
            inputs.StructureReference(
                identifier="@mikro/roi",
                object="roi_dt_test",
                measurements=[
                    inputs.MeasurementInput(
                        key="vector_length",
                        value=100,
                        timestamp=dt  # Pass datetime directly
                    )
                ]
            )
        ],
        provenance=inputs.ProvenanceContext(subject="user", app_id="app")
    )
    
    result = graph_controller.create_entity(payload)
    
    # Verify entity was created
    entity = graph_controller.get_entity(id=result.db_id)
    assert entity is not None
    
    # Verify measurement has correct timestamp
    measurements = graph_controller.get_measurements_for_structure(
        identifier="@mikro/roi",
        structure_object="roi_dt_test"
    )
    assert len(measurements) == 1
    assert measurements[0].timestamp == expected_ms


def test_measurement_with_optional_fields(graph_controller: GraphController):
    """
    Test that optional measurement fields (unit, confidence) are stored when provided.
    """
    payload = inputs.EntityCreationPayload(
        kind="AIS",
        supporting_evidence=[
            inputs.StructureReference(
                identifier="@mikro/roi",
                object="roi_optional_test",
                measurements=[
                    # Full measurement with all fields
                    inputs.MeasurementInput(
                        key="vector_length",
                        value=100,
                        confidence=0.95,
                        confidence_type="max",
                        unit="um",
                        timestamp=1000
                    )
                ]
            )
        ],
        provenance=inputs.ProvenanceContext(subject="user", app_id="app")
    )
    
    result = graph_controller.create_entity(payload)
    
    # Verify entity was created
    entity = graph_controller.get_entity(id=result.db_id)
    assert entity is not None
    
    # Verify measurement has all optional fields
    measurements = graph_controller.get_measurements_for_structure(
        identifier="@mikro/roi",
        structure_object="roi_optional_test"
    )
    assert len(measurements) == 1
    
    m = measurements[0]
    assert m.key == "vector_length"
    assert m.value == 100
    assert m.unit == "um"
    assert m.confidence == 0.95
    assert m.confidence_type == "max"
    assert m.timestamp == 1000
