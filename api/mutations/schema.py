"""
Schema mutation resolvers for managing graph schema versions.
"""
from typing import Dict, Any, List
from kante.types import Info
from pydantic import ValidationError

from api.types import (
    SchemaValidationResult, 
    SchemaValidationError, 
    SetSchemaResult,
    GraphSchemaType,
)
from api.inputs import ValidateSchemaInput, SetSchemaInput, ActivateSchemaInput
from core.models import GraphSchema, Graph
from graph_engine.base_models import GraphDefinitionModel
from graph_engine.input_models import validate_semver
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


def _schema_to_type(schema: GraphSchema) -> GraphSchemaType:
    """Convert a GraphSchema model to GraphSchemaType."""
    return GraphSchemaType(
        id=schema.id,
        version=schema.version,
        index=schema.index,
        is_active=schema.is_active,
        created_at=schema.created_at,
        description=schema.description,
        definition=schema.definition,
    )


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


def set_schema(
    info: Info,
    input: SetSchemaInput,
) -> SetSchemaResult:
    """
    Create a new schema version for a graph.
    
    The schema is validated before saving. If activate is True (default),
    the new schema becomes the active schema for the graph.
    
    Args:
        info: Strawberry Info context
        input: SetSchemaInput with version, definition, and options
        
    Returns:
        SetSchemaResult with the created schema
        
    Raises:
        ValueError: If the schema is invalid or version is not semantic
    """
    # Validate version is a proper semantic version
    try:
        version = validate_semver(input.version)
    except ValueError as e:
        raise ValueError(str(e))
    
    # Convert strawberry-pydantic input to pydantic model
    # The input.definition is already validated by strawberry-pydantic
    try:
        # Convert to dict and re-validate with full model
        input_model = input.definition.to_pydantic()
        definition_dict = input_model.model_dump(mode='json')
    except ValidationError as e:
        errors = _validation_errors_from_pydantic(e)
        error_msgs = [f"{'.'.join(err.location)}: {err.message}" for err in errors]
        raise ValueError(f"Invalid schema definition: {'; '.join(error_msgs)}")
    
    # Validate against the full GraphDefinitionModel (which has stricter cross-validation)
    try:
        GraphDefinitionModel.model_validate(definition_dict)
    except ValidationError as e:
        errors = _validation_errors_from_pydantic(e)
        error_msgs = [f"{'.'.join(err.location)}: {err.message}" for err in errors]
        raise ValueError(f"Invalid schema: {'; '.join(error_msgs)}")
    
    # Get the graph from the database
    from core.models import Graph
    try:
        graph = Graph.objects.get(id=input.graph_id)
    except Graph.DoesNotExist:
        raise ValueError(f"Graph with ID {input.graph_id} not found")
    
    # Check if this version already exists
    if GraphSchema.objects.filter(graph=graph, version=version).exists():
        raise ValueError(f"Schema version '{version}' already exists for this graph")
    
    # Determine if migration might be required
    current_schema = graph.active_schema
    migration_required = current_schema is not None
    
    # Create the new schema
    user = info.context.request.user if hasattr(info.context, 'request') else None
    
    schema = GraphSchema.objects.create(
        graph=graph,
        version=version,
        definition=definition_dict,
        description=input.description,
        created_by=user if user and user.is_authenticated else None,
        is_active=False,  # Will activate below if needed
    )
    
    # Activate if requested
    activated = False
    activate = input.activate if input.activate is not None else True
    if activate or current_schema is None:
        # Activate by default if no active schema exists
        schema.activate()
        activated = True
    
    return SetSchemaResult(
        schema=_schema_to_type(schema),
        activated=activated,
        migration_required=migration_required,
    )


def activate_schema(
    info: Info,
    input: ActivateSchemaInput,
) -> SetSchemaResult:
    """
    Activate an existing schema version.
    
    This makes the specified schema the active one for its graph,
    deactivating any previously active schema.
    
    Args:
        info: Strawberry Info context
        input: ActivateSchemaInput with the schema ID to activate
        
    Returns:
        SetSchemaResult with the activated schema
        
    Raises:
        ValueError: If the schema doesn't exist
    """
    try:
        schema = GraphSchema.objects.get(id=input.schema_id)
    except GraphSchema.DoesNotExist:
        raise ValueError(f"Schema with ID {input.schema_id} not found")
    
    # Check if there was a previous active schema (for migration tracking)
    previous_active = GraphSchema.objects.filter(
        graph=schema.graph, 
        is_active=True
    ).exclude(id=schema.id).first()
    
    migration_required = previous_active is not None
    
    schema.activate()
    
    return SetSchemaResult(
        schema=_schema_to_type(schema),
        activated=True,
        migration_required=migration_required,
    )
