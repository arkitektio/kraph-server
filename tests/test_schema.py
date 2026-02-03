# test_schema.py
import pytest
from pydantic import ValidationError
import graph_engine.base_models as models  # Assumes base_models.py exists in the same directory


# --- TESTS ---

def test_fixture_integrity(bio_graph_schema):
    """
    Simply verifies that the manually constructed object is valid.
    """
    assert bio_graph_schema.system_version == "1.0"
    
    # Check Structure
    assert "ROI" in bio_graph_schema.extensions.structures
    
    # Check Rollup Logic
    ais = bio_graph_schema.extensions.entities["AIS"]
    assert ais.properties["avg_length"].rule.aggregation == models.AggregationFunction.MEAN
    
    # Check Relation Materialization
    rel = bio_graph_schema.extensions.relations["IS_CONNECTED_TO"]
    assert rel.materialization.backing_link_type == "link_ais_soma"
    
def test_validation_logic_works():
    """
    Ensures that calling the constructors with bad data still raises errors.
    """
    # 1. Test Missing Rollup Rule
    with pytest.raises(ValueError, match="must have a 'rule' configuration"):
        models.PropertyDefinition(
            type=models.PropertyType.FLOAT,
            derivation=models.DerivationType.ROLLUP,
            rule=None # Missing!
        )

    # 2. Test Materialization Logic
    # Pydantic V2 wraps nested validation errors in ValidationError
    from pydantic import ValidationError
    with pytest.raises((ValueError, ValidationError)):
        models.RelationDefinition(
            source="AIS",
            target="Soma",
            materialization=models.MaterializationConfig(
                backing_link_type="foo",
                desired_evidence=[],
                properties={
                    "bad_prop": models.PropertyDefinition(
                        type=models.PropertyType.FLOAT,
                        derivation=models.DerivationType.ROLLUP,
                        rule=None # Missing!
                    )
                }
            )
        )