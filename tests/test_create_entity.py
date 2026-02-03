import pytest
from datetime import datetime, timezone
from graph_engine.controller import GraphController
from graph_engine.engine.testing.mock_cypher_engine import MockCypherEngine
from graph_engine import base_models as models
from graph_engine import input_models as inputs 


def test_create_ais_with_timestamp_conversion(graph_controller: GraphController, mock_engine: MockCypherEngine, bio_graph_schema: models.GraphDefinitionModel):
    """
    Test that ISO timestamps are converted to Unix Milliseconds (int).
    """
    mock_engine.return_values = [[{"aid": 1}], [], [], [{"db_id": "AIS_1", "graph_id": 1}], []]

    # ISO String input
    ts_string = "2023-10-27T10:00:00.123Z"
    
    # Expected: 2023-10-27 10:00:00.123 UTC -> 1698400800123 ms
    expected_ms = 1698400800123

    payload = inputs.EntityCreationPayload(
        kind="AIS",
        properties={"id": "AIS_001"},
        supporting_evidence=[
            inputs.create_told_you_so(measurements=[
                inputs.create_max_confidence_measurement(
                    key="vector_length", 
                    value=100, 
                    timestamp=ts_string  
                )
            ], id="TYS_1")
        ],
        provenance=inputs.ProvenanceContext(subject="test", app_id="test")
    )

    graph_controller.create_entity(bio_graph_schema, payload)
    
    # Assert
    # Find measurement creation call
    meas_call = [c for c in mock_engine.log if "CREATE (m:Measurement" in c[0]][0]
    params = meas_call[1]
    
    assert params["timestamp"] == expected_ms
    assert isinstance(params["timestamp"], int) # Critical for AGE compatibility