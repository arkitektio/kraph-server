"""
Schema mutation resolvers for managing graph schema versions.
"""
from typing import List
from kante.types import Info
from pydantic import ValidationError

from api.types import (
    SchemaValidationResult, 
    SchemaValidationError,
)
from api.inputs import ValidateSchemaInput
from graph_engine.base_models import GraphDefinitionModel
from graph_engine.input_models import GraphDefinitionInput as PydanticGraphDefinitionInput


def _validation_errors_from_pydantic(exc: ValidationError) -> List[SchemaValidationError]:
    """Convert pydantic ValidationError to our SchemaValidationError list."""
    errors = []
    for error in exc.errors():
        location = [str(loc) for loc in error.get("loc", [])]
        errors.append(SchemaValidationError(
            location=location,
            message=error.get("msg", "Unknown error"),
            type=error.get("type", "validation_error"),
        ))
    return errors



def validate_schema(
    info: Info,
    input: ValidateSchemaInput,
) -> SchemaValidationResult:
    """
    Validate a schema definition without saving it.
    
    This performs full pydantic validation on the schema and returns
    any errors in a structured format similar to pydantic errors.
    
    Args:
        info: Strawberry Info context
        input: ValidateSchemaInput containing the definition to validate
        
    Returns:
        SchemaValidationResult with validation status and any errors
    """
    errors: List[SchemaValidationError] = []
    warnings: List[SchemaValidationError] = []
    
    try:
        # First validate with our input model (validates semver)
        input_model = PydanticGraphDefinitionInput.model_validate(input.definition)
        
        # Then validate with full GraphDefinitionModel (has cross-validation)
        definition_dict = input_model.model_dump(mode='json')
        model = GraphDefinitionModel.model_validate(definition_dict)
        
        # Additional semantic validations
        # Check for potential issues that aren't strict errors
        
        # Check for empty extensions
        if model.extensions:
            if not model.extensions.entities:
                warnings.append(SchemaValidationError(
                    location=["extensions", "entities"],
                    message="Schema has no entity definitions",
                    type="empty_entities",
                ))
            if not model.extensions.relations:
                warnings.append(SchemaValidationError(
                    location=["extensions", "relations"],
                    message="Schema has no relation definitions",
                    type="empty_relations",
                ))
        else:
            warnings.append(SchemaValidationError(
                location=["extensions"],
                message="Schema has no extensions defined",
                type="no_extensions",
            ))
        
        return SchemaValidationResult(
            is_valid=True,
            errors=[],
            warnings=warnings,
        )
        
    except ValidationError as e:
        errors = _validation_errors_from_pydantic(e)
        return SchemaValidationResult(
            is_valid=False,
            errors=errors,
            warnings=warnings,
        )
    except Exception as e:
        # Catch any other errors
        errors.append(SchemaValidationError(
            location=[],
            message=str(e),
            type="parse_error",
        ))
        return SchemaValidationResult(
            is_valid=False,
            errors=errors,
            warnings=warnings,
        )

