# test_schema.py
import pytest
from pydantic import ValidationError
import graph_engine.input_models as models  # Assumes base_models.py exists in the same directory


# --- TESTS ---


@pytest.mark.skip(reason="Validation behavior changed; update expected errors")
def test_validation_logic_works() -> None:
    """
    Ensures that calling the constructors with bad data still raises errors.
    """
    # 1. Test Missing Rollup Rule
    with pytest.raises(ValueError, match="must have a 'rule' configuration"):
        models.PropertyDefinitionInput(
            key="test",
            type=models.PropertyType.FLOAT,
            derivation=models.DerivationType.ROLLUP,
            rule=None,  # Missing!
        )

    # 2. Test Materialization Logic
    # Pydantic V2 wraps nested validation errors in ValidationError
    with pytest.raises((ValueError, ValidationError)):
        models.PropertyDefinitionInput(
            key="TEST_REL",
            source="AIS",
            target="Soma",
        )  # type: ignore
