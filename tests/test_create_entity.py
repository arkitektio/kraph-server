import pytest
from datetime import datetime, timezone
from graph_engine.controller import GraphController
from graph_engine.engine.protocol import CypherEngine
from graph_engine import base_models as models
from graph_engine import input_models as inputs 


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
                id="1",
                measurements=[
                inputs.create_max_confidence_measurement(
                    key="vector_length", 
                    value=100, 
                    timestamp=ts_string  
                )]
            ),
            inputs.StructureReference(
                identifier="@mikro/roi",
                id="2",
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
                id="told_you_so_1"
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