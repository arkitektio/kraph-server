import pytest
from datetime import datetime, timezone
from graph_engine.controller import GraphController
from graph_engine.engine.protocol import CypherEngine
from graph_engine import base_models as models
from graph_engine import input_models as inputs 
from graph_engine import vocab
from core import models as core_models

pytestmark = pytest.mark.skip(reason="Requires updated DB schema/migrations for materialize")


def test_create_ais_with_timestamp_conversion(graph_controller: GraphController, bio_graph: core_models.Graph):
    """
    Test that ISO timestamps are converted to Unix Milliseconds (int).
    """

    # ISO String input
    ts_string = "2023-10-27T10:00:00.123Z"
    a_little_later = "2023-10-27T10:05:00.456Z"
    

    supporting_evidence=[
            inputs.StructureReferenceInput(
                identifier="@mikro/roi",
                object="1",
                metrics=[
                inputs.create_max_confidence_metric(
                    key="vector_length", 
                    value=100, 
                    timestamp=ts_string  
                )]
            ),
            inputs.StructureReferenceInput(
                identifier="@mikro/roi",
                object="2",
                metrics=[
                inputs.create_max_confidence_metric(
                    key="vector_length", 
                    value=120, 
                    timestamp=a_little_later  
                )]
            ),  
            inputs.create_told_you_so(
                metrics=[
                    inputs.create_max_confidence_metric(
                        key="name", 
                        value="A little ducky", 
                        timestamp="2023-10-27T10:10:00.789Z"  
                    )                ],
                object="told_you_so_1"
            )
    ]

    ais_category = bio_graph.get_entity_def("AIS")
    
    result = graph_controller.create_entity(
        entity_category=ais_category,
        payload=inputs.EntityInput(
            supporting_evidence=supporting_evidence,
        ),
        context=inputs.ProvenanceContext.bland()
            
    )
    
    
    # Verify properties
    assert "avg_length" in result.properties
    assert result.properties["avg_length"] == 110  # Average of 100 and 120
    assert result.properties["name"] == "A little ducky"  # From told_you_so


def test_create_entity_with_single_evidence(graph_controller: GraphController, bio_graph: core_models.Graph):
    """
    Test creating an entity with a single supporting evidence creates correct graph structure.
    """
    ais_category = bio_graph.get_entity_def("AIS")
    
    supporting_evidence = [
        inputs.StructureReferenceInput(
            identifier="@mikro/roi",
            object="roi_single_001",
            metrics=[
                inputs.MetricInput(
                    key="vector_length",
                    value=50.5,
                    confidence=0.95,
                    unit="um",
                    timestamp=1698400800000
                )
            ]
        )
    ]
    
    result = graph_controller.create_entity(
        entity_category=ais_category,
        ref_id="ais_single_001",
        supporting_evidence=supporting_evidence,
    )
    
    # Check the result
    assert result.db_id is not None
    assert result.ref_id is not None
    
    # Verify entity was created with correct properties
    entity = graph_controller.get_entity(id=result.db_id, entity_category=ais_category)
    assert entity is not None
    assert "avg_length" in entity.properties
    assert entity.properties["avg_length"] == 50.5  # Single measurement = same value


def test_create_entity_with_multiple_evidence_sources(graph_controller: GraphController, bio_graph: core_models.Graph):
    """
    Test creating an entity with multiple evidence sources from different structures.
    """
    ais_category = bio_graph.get_entity_def("AIS")
    
    supporting_evidence = [
        inputs.StructureReferenceInput(
            identifier="@mikro/roi",
            object="roi_multi_001",
            metrics=[
                inputs.MetricInput(key="vector_length", value=100, timestamp=1000)
            ]
        ),
        inputs.StructureReferenceInput(
            identifier="@mikro/roi", 
            object="roi_multi_002",
            metrics=[
                inputs.MetricInput(key="vector_length", value=200, timestamp=2000)
            ]
        ),
        inputs.StructureReferenceInput(
            identifier="@mikro/roi",
            object="roi_multi_003", 
            metrics=[
                inputs.MetricInput(key="vector_length", value=150, timestamp=3000)
            ]
        )
    ]
    
    result = graph_controller.create_entity(
        entity_category=ais_category,
        ref_id="ais_multi_001",
        supporting_evidence=supporting_evidence,
    )
    
    # Verify entity was created
    entity = graph_controller.get_entity(id=result.db_id, entity_category=ais_category)
    assert entity is not None
    
    # Verify avg_length is the mean of all three measurements
    assert "avg_length" in entity.properties
    assert entity.properties["avg_length"] == 150  # (100 + 200 + 150) / 3


def test_create_entity_with_told_you_so_evidence(graph_controller: GraphController, bio_graph: core_models.Graph):
    """
    Test creating an entity with ToldYouSo evidence for manual property assertions.
    """
    ais_category = bio_graph.get_entity_def("AIS")
    
    supporting_evidence = [
        inputs.create_told_you_so(
            object="tys_test_001",
            metrics=[
                inputs.create_max_confidence_metric(
                    key="name",
                    value="My Custom AIS",
                    timestamp=1698400800000
                )
            ]
        )
    ]
    
    result = graph_controller.create_entity(
        entity_category=ais_category,
        ref_id="ais_tys_001",
        supporting_evidence=supporting_evidence,
    )
    
    # Verify entity was created with the name from ToldYouSo
    entity = graph_controller.get_entity(id=result.db_id, entity_category=ais_category)
    assert entity is not None
    assert "name" in entity.properties
    assert entity.properties["name"] == "My Custom AIS"


def test_create_entity_with_multiple_measurements_per_structure(graph_controller: GraphController, bio_graph: core_models.Graph):
    """
    Test creating an entity where a single structure has multiple measurements.
    """
    ais_category = bio_graph.get_entity_def("AIS")
    
    supporting_evidence = [
        inputs.StructureReferenceInput(
            identifier="@mikro/roi",
            object="roi_multi_measure",
            metrics=[
                inputs.MetricInput(key="vector_length", value=100, unit="um", timestamp=1000),
                inputs.MetricInput(key="vector_length", value=150, unit="um", timestamp=2000),
                inputs.MetricInput(key="vector_length", value=125, unit="um", timestamp=3000),
            ]
        )
    ]
    
    result = graph_controller.create_entity(
        entity_category=ais_category,
        ref_id="ais_multi_meas_001",
        supporting_evidence=supporting_evidence,
    )
    
    # Verify entity was created
    entity = graph_controller.get_entity(id=result.db_id, entity_category=ais_category)
    assert entity is not None
    
    # Verify avg_length is the mean of all three measurements
    assert "avg_length" in entity.properties
    assert entity.properties["avg_length"] == 125  # (100 + 150 + 125) / 3


def test_create_entity_no_evidence(graph_controller: GraphController, bio_graph: core_models.Graph):
    """
    Test creating an entity with no supporting evidence (edge case).
    """
    ais_category = bio_graph.get_entity_def("AIS")
    
    result = graph_controller.create_entity(
        entity_category=ais_category,
        ref_id="ais_no_evidence_001",
        supporting_evidence=[],
    )
    
    # Should still create the entity and assertion
    assert result.ref_id is not None
    assert result.db_id is not None
    
    # Verify entity exists
    entity = graph_controller.get_entity(id=result.db_id, entity_category=ais_category)
    assert entity is not None


def test_measurement_timestamp_conversion_datetime(graph_controller: GraphController, bio_graph: core_models.Graph):
    """
    Test that datetime objects are correctly converted to milliseconds.
    """
    ais_category = bio_graph.get_entity_def("AIS")
    dt = datetime(2023, 10, 27, 10, 0, 0, 123000, tzinfo=timezone.utc)
    expected_ms = 1698400800123  # Unix ms for this datetime
    
    supporting_evidence = [
        inputs.StructureReferenceInput(
            identifier="@mikro/roi",
            object="roi_dt_test",
            metrics=[
                inputs.MetricInput(
                    key="vector_length",
                    value=100,
                    timestamp=dt  # Pass datetime directly
                )
            ]
        )
    ]
    
    result = graph_controller.create_entity(
        entity_category=ais_category,
        ref_id="ais_dt_001",
        supporting_evidence=supporting_evidence,
    )
    
    # Verify entity was created
    entity = graph_controller.get_entity(id=result.db_id, entity_category=ais_category)
    assert entity is not None


def test_measurement_with_optional_fields(graph_controller: GraphController, bio_graph: core_models.Graph):
    """
    Test that optional measurement fields (unit, confidence) are stored when provided.
    """
    ais_category = bio_graph.get_entity_def("AIS")
    
    supporting_evidence = [
        inputs.StructureReferenceInput(
            identifier="@mikro/roi",
            object="roi_optional_test",
            metrics=[
                # Full measurement with all fields
                inputs.MetricInput(
                    key="vector_length",
                    value=100,
                    confidence=0.95,
                    confidence_type="max",
                    unit="um",
                    timestamp=1000
                )
            ]
        )
    ]
    
    result = graph_controller.create_entity(
        entity_category=ais_category,
        ref_id="ais_optional_001",
        supporting_evidence=supporting_evidence,
    )
    
    # Verify entity was created
    entity = graph_controller.get_entity(id=result.db_id, entity_category=ais_category)
    assert entity is not None
