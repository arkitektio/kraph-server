import pytest
import uuid
from graph_engine.controller import GraphController
from graph_engine import input_models as inputs


def _uid(prefix: str) -> str:
    """Generate a unique ID with prefix for test isolation."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_create_structure(graph_controller: GraphController):
    """
    Test creating a simple structure.
    """
    obj_id = _uid("roi_test")
    result = graph_controller.create_structure(
        identifier="@mikro/roi",
        object=obj_id
    )
    
    assert result is not None
    assert result.object == obj_id
    assert result.identifier == "@mikro/roi"
    assert result.label == "ROI"
    assert result.graph_id is not None
    assert result.global_id == f"{graph_controller.age_name}:{result.graph_id}"


def test_create_structure_told_you_so(graph_controller: GraphController):
    """
    Test creating a ToldYouSo structure.
    """
    obj_id = _uid("tys_test")
    result = graph_controller.create_structure(
        identifier="told_you_so",
        object=obj_id
    )
    
    assert result is not None
    assert result.object == obj_id
    assert result.identifier == "told_you_so"
    assert result.label == "ToldYouSo"
    assert result.graph_id is not None
    assert result.global_id == f"{graph_controller.age_name}:{result.graph_id}"


def test_create_structure_idempotent(graph_controller: GraphController):
    """
    Test that creating the same structure twice is idempotent.
    """
    obj_id = _uid("roi_idem")
    
    result1 = graph_controller.create_structure(
        identifier="@mikro/roi",
        object=obj_id
    )
    
    result2 = graph_controller.create_structure(
        identifier="@mikro/roi",
        object=obj_id
    )
    
    # Both should return the same structure (same graph_id)
    assert result1.graph_id == result2.graph_id
    assert result1.object == result2.object
    assert result1.identifier == result2.identifier
    
    # Verify only one structure exists
    structure = graph_controller.get_structure(
        identifier="@mikro/roi",
        object=obj_id
    )
    assert structure is not None
    assert structure.object == obj_id


def test_add_measurement_to_structure(graph_controller: GraphController):
    """
    Test adding a measurement to an existing structure.
    """
    obj_id = _uid("roi_meas")
    
    # Create structure first
    graph_controller.create_structure(
        identifier="@mikro/roi",
        object=obj_id
    )
    
    # Add measurement
    measurement = inputs.MeasurementInput(
        key="vector_length",
        value=100.5,
        unit="um",
        confidence=0.95,
        timestamp=1698400800000
    )
    
    provenance = inputs.ProvenanceContext(
        subject="user123",
        app_id="test_app"
    )
    
    result = graph_controller.add_measurement(
        structure_identifier="@mikro/roi",
        structure_object=obj_id,
        measurement=measurement,
        provenance=provenance
    )
    
    assert result is not None
    assert result.key == "vector_length"
    assert result.value == 100.5
    assert result.unit == "um"
    assert result.confidence == 0.95
    assert result.timestamp == 1698400800000
    assert result.graph_id is not None
    assert result.global_id == f"{graph_controller.age_name}:{result.graph_id}"


def test_add_measurement_creates_structure_if_not_exists(graph_controller: GraphController):
    """
    Test that add_measurement creates the structure if it doesn't exist.
    """
    obj_id = _uid("roi_auto_create")
    
    measurement = inputs.MeasurementInput(
        key="area",
        value=250.0,
        unit="um^2",
        timestamp=1698400800000
    )
    
    provenance = inputs.ProvenanceContext(
        subject="user123",
        app_id="test_app"
    )
    
    # Add measurement to non-existent structure
    result = graph_controller.add_measurement(
        structure_identifier="@mikro/roi",
        structure_object=obj_id,
        measurement=measurement,
        provenance=provenance
    )
    
    assert result is not None
    assert result.key == "area"
    
    # Verify structure was created
    structure = graph_controller.get_structure(
        identifier="@mikro/roi",
        object=obj_id
    )
    assert structure is not None
    assert structure.object == obj_id


def test_add_multiple_measurements_to_structure(graph_controller: GraphController):
    """
    Test adding multiple measurements to the same structure.
    """
    obj_id = _uid("roi_multi_meas")
    
    # Create structure
    graph_controller.create_structure(
        identifier="@mikro/roi",
        object=obj_id
    )
    
    provenance = inputs.ProvenanceContext(
        subject="user123",
        app_id="test_app"
    )
    
    # Add first measurement
    m1 = inputs.MeasurementInput(key="length", value=100, timestamp=1000)
    graph_controller.add_measurement(
        structure_identifier="@mikro/roi",
        structure_object=obj_id,
        measurement=m1,
        provenance=provenance
    )
    
    # Add second measurement
    m2 = inputs.MeasurementInput(key="width", value=50, timestamp=2000)
    graph_controller.add_measurement(
        structure_identifier="@mikro/roi",
        structure_object=obj_id,
        measurement=m2,
        provenance=provenance
    )
    
    # Add third measurement
    m3 = inputs.MeasurementInput(key="height", value=25, timestamp=3000)
    graph_controller.add_measurement(
        structure_identifier="@mikro/roi",
        structure_object=obj_id,
        measurement=m3,
        provenance=provenance
    )
    
    # Verify all measurements exist
    measurements = graph_controller.get_measurements_for_structure(
        identifier="@mikro/roi",
        structure_object=obj_id
    )
    
    assert len(measurements) == 3
    keys = {m.key for m in measurements}
    assert keys == {"length", "width", "height"}


def test_add_measurement_with_provenance_action(graph_controller: GraphController):
    """
    Test that measurement provenance includes action information.
    """
    obj_id = _uid("roi_provenance")
    
    graph_controller.create_structure(
        identifier="@mikro/roi",
        object=obj_id
    )
    
    measurement = inputs.MeasurementInput(
        key="intensity",
        value=0.75,
        timestamp=1698400800000
    )
    
    provenance = inputs.ProvenanceContext(
        subject="user123",
        app_id="analyzer",
        action_id="measure_intensity",
        action_name="Measure Intensity"
    )
    
    result = graph_controller.add_measurement(
        structure_identifier="@mikro/roi",
        structure_object=obj_id,
        measurement=measurement,
        provenance=provenance
    )
    
    assert result is not None
    assert result.key == "intensity"
    
    # Verify we can get the measurement
    measurements = graph_controller.get_measurements_for_structure(
        identifier="@mikro/roi",
        structure_object=obj_id
    )
    assert len(measurements) == 1
    assert measurements[0].value == 0.75


def test_get_structure_not_found(graph_controller: GraphController):
    """
    Test that get_structure returns None for non-existent structure.
    """
    with pytest.raises(ValueError, match="Structure not found"):
        result = graph_controller.get_structure(
            identifier="@mikro/roi",
            object=_uid("non_existent_structure")
        )
    


def test_add_measurement_minimal(graph_controller: GraphController):
    """
    Test adding a measurement with only required fields.
    """
    obj_id = _uid("roi_minimal")
    
    measurement = inputs.MeasurementInput(
        key="count",
        value=42
    )
    
    provenance = inputs.ProvenanceContext(
        subject="user",
        app_id="app"
    )
    
    result = graph_controller.add_measurement(
        structure_identifier="@mikro/roi",
        structure_object=obj_id,
        measurement=measurement,
        provenance=provenance
    )
    
    assert result is not None
    assert result.key == "count"
    assert result.value == 42
    assert result.unit is None
    assert result.confidence is None
    assert result.timestamp is None


def test_add_measurement_with_string_value(graph_controller: GraphController):
    """
    Test adding a measurement with a string value.
    """
    obj_id = _uid("tys_string")
    
    measurement = inputs.MeasurementInput(
        key="name",
        value="My Structure Name",
        timestamp=1698400800000
    )
    
    provenance = inputs.ProvenanceContext(
        subject="user",
        app_id="app"
    )
    
    result = graph_controller.add_measurement(
        structure_identifier="told_you_so",
        structure_object=obj_id,
        measurement=measurement,
        provenance=provenance
    )
    
    assert result is not None
    assert result.key == "name"
    assert result.value == "My Structure Name"
    
    # Verify retrieval
    measurements = graph_controller.get_measurements_for_structure(
        identifier="told_you_so",
        structure_object=obj_id
    )
    assert len(measurements) == 1
    assert measurements[0].value == "My Structure Name"
