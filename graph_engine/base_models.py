from enum import Enum
from typing import List, Dict, Optional, Union, Literal
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict

# --- Enums for Strict Typing ---

class DerivationType(str, Enum):
    # Standard: User/Tool sets it directly
    LATEST = "LATEST"
    PRIORITY_LATEST = "PRIORITY_LATEST"
    
    # Computed: Calculated from children/neighbors
    ROLLUP = "ROLLUP"
    LATEST_ASSERTION_TOOL = "LATEST_ASSERTION_TOOL"

class AggregationFunction(str, Enum):
    MEAN = "MEAN"
    SUM = "SUM"
    MAX = "MAX"
    MIN = "MIN"
    COUNT = "COUNT"
    RANGE = "RANGE"             # Max - Min (Temporal)
    EUCLIDEAN_RANGE = "EUCLIDEAN_RANGE" # Distance between First & Last
    LATEST = "LATEST"           # Grab the most recent child value

class PropertyType(str, Enum):
    STRING = "string"
    FLOAT = "float"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    POINT_3D = "point_3d"


# --- Type compatibility mappings for aggregations ---

# Aggregations that require numeric source types
NUMERIC_AGGREGATIONS = {
    AggregationFunction.MEAN,
    AggregationFunction.SUM,
    AggregationFunction.MIN,
    AggregationFunction.MAX,
}

# Aggregations that work with any type
ANY_TYPE_AGGREGATIONS = {
    AggregationFunction.COUNT,
    AggregationFunction.LATEST,
}

# Property types considered numeric
NUMERIC_TYPES = {
    PropertyType.FLOAT,
    PropertyType.INTEGER,
}

# Map aggregation -> required source types (None means any type allowed)
AGGREGATION_SOURCE_TYPES: Dict[AggregationFunction, Optional[set]] = {
    AggregationFunction.MEAN: NUMERIC_TYPES,
    AggregationFunction.SUM: NUMERIC_TYPES,
    AggregationFunction.MIN: NUMERIC_TYPES | {PropertyType.DATETIME},
    AggregationFunction.MAX: NUMERIC_TYPES | {PropertyType.DATETIME},
    AggregationFunction.COUNT: None,  # Any type
    AggregationFunction.LATEST: None,  # Any type
    AggregationFunction.RANGE: NUMERIC_TYPES | {PropertyType.DATETIME},
    AggregationFunction.EUCLIDEAN_RANGE: {PropertyType.POINT_3D},
}

# Map aggregation -> result type (None means same as source)
AGGREGATION_RESULT_TYPES: Dict[AggregationFunction, Optional[PropertyType]] = {
    AggregationFunction.MEAN: PropertyType.FLOAT,  # Mean always produces float
    AggregationFunction.SUM: None,  # Same as source (int->int, float->float)
    AggregationFunction.MIN: None,  # Same as source
    AggregationFunction.MAX: None,  # Same as source
    AggregationFunction.COUNT: PropertyType.INTEGER,  # Count produces integer
    AggregationFunction.LATEST: None,  # Same as source
    AggregationFunction.RANGE: PropertyType.FLOAT,  # Range produces float (for datetime too)
    AggregationFunction.EUCLIDEAN_RANGE: PropertyType.FLOAT,  # Distance is float
}

# --- 1. Property & Derivation Rules ---

class DerivationRule(BaseModel):
    """
    Configuration for how to calculate a value if derivation != LATEST.
    """
    source_node: Optional[str] = Field(..., description="The label of the the describing structure to read from.")
    key: Optional[str] = Field(..., description="The property key on the source node.")
    aggregation: Optional[AggregationFunction] = None
    
    
    
    
def user_defined(cls, v):
    """Validator to ensure user-defined derivation types are valid."""
    if v not in DerivationType:
        raise ValueError(f"Invalid derivation type: {v}")
    return v

class PropertyDefinition(BaseModel):
    """
    Defines a single field on a Node, Event, or Relation.
    """
    type: PropertyType
    unit: Optional[str] = None
    description: Optional[str] = None
    # Logic
    derivation: DerivationType = DerivationType.LATEST
    rule: Optional[DerivationRule] = None

    @model_validator(mode='after')
    def validate_rule_presence(self):
        """If using ROLLUP, a rule definition is mandatory."""
        if self.derivation == DerivationType.ROLLUP and not self.rule:
            raise ValueError(f"Property with derivation 'ROLLUP' must have a 'rule' configuration.")
        return self
    
    @model_validator(mode='after')
    def validate_aggregation_result_type(self):
        """
        Validate that the property type is compatible with the aggregation result.
        
        For example:
        - MEAN always produces FLOAT, so property type must be FLOAT
        - COUNT always produces INTEGER, so property type must be INTEGER
        - EUCLIDEAN_RANGE produces FLOAT (distance)
        """
        if self.derivation != DerivationType.ROLLUP or not self.rule or not self.rule.aggregation:
            return self
        
        aggregation = self.rule.aggregation
        expected_result_type = AGGREGATION_RESULT_TYPES.get(aggregation)
        
        # If aggregation has a fixed result type, check compatibility
        if expected_result_type is not None and self.type != expected_result_type:
            raise ValueError(
                f"Aggregation '{aggregation.value}' produces type '{expected_result_type.value}', "
                f"but property is defined as '{self.type.value}'. "
                f"Change property type to '{expected_result_type.value}'."
            )
        
        return self

# --- 2. Node Definitions ---



class NodeDefinition(BaseModel):
    description: Optional[str] = None


class EntityDefinition(NodeDefinition):
    properties: Dict[str, PropertyDefinition] = {}


class StructureDefinition(NodeDefinition):
    """
    Definition of a Structure (physical observation).
    """
    pass
    
    
    
# --- 3. Edge Definitions (Relation Materialization) ---

class EvidenceRequirement(BaseModel):
    key: str
    unit: str
    description: Optional[str] = None

class MaterializationConfig(BaseModel):
    """
    Rules for turning a TemporalLink (Evidence) into an Edge (Relation).
    """
    backing_link_type: str = Field(..., description="The internal label for the Evidence Node (e.g. 'link_ais_soma').")
    desired_evidence: List[EvidenceRequirement] = Field(..., description="Measurements expected on the backing link.")
    properties: Dict[str, PropertyDefinition] = {}

class RelationDefinition(BaseModel):
    source: Union[str, List[str]]
    target: Union[str, List[str]]
    cardinality: Literal["1:1", "1:N", "N:N"] = "1:N"
    
    # Optional: If this relation is materialized from evidence
    materialization: Optional[MaterializationConfig] = None

    @model_validator(mode='after')
    def validate_materialization_props(self):
        """Ensure materialized edges define how to calculate their properties."""
        if self.materialization:
            for key, prop in self.materialization.properties.items():
                if prop.derivation == DerivationType.ROLLUP and not prop.rule:
                     raise ValueError(f"Materialized property '{key}' must have a derivation rule.")
        return self

# --- 4. Event Definitions ---

class EventDefinition(BaseModel):
    inputs: List[str]
    outputs: List[str]
    properties: Dict[str, PropertyDefinition] = {}

# --- 5. The Root Schema ---

class GraphExtensions(BaseModel):
    structures: Dict[str, StructureDefinition] = Field(default_factory=dict, description="Physical observations (ROIs).")
    entities: Dict[str, EntityDefinition] = Field(default_factory=dict, description="Logical aggregations (Cells).")
    relations: Dict[str, RelationDefinition] = Field(default_factory=dict, description="Edges between nodes.")
    events: Dict[str, EventDefinition] = Field(default_factory=dict, description="Spatio-temporal transitions.")

    @model_validator(mode='after')
    def validate_references(self):
        """
        Cross-check that relations refer to existing Node Types.
        """
        all_nodes = set(self.structures.keys()) | set(self.entities.keys())
        
        for name, rel in self.relations.items():
            sources = [rel.source] if isinstance(rel.source, str) else rel.source
            targets = [rel.target] if isinstance(rel.target, str) else rel.target
            
            for s in sources:
                if s not in all_nodes:
                    raise ValueError(f"Relation '{name}' defines source '{s}' which is not a defined Structure or Entity.")
            for t in targets:
                if t not in all_nodes:
                    raise ValueError(f"Relation '{name}' defines target '{t}' which is not a defined Structure or Entity.")
        return self
    
    @model_validator(mode='after')
    def validate_rollup_source_types(self):
        """
        Validate that ROLLUP derivations reference valid source nodes/properties
        and that the source property type is compatible with the aggregation function.
        """
        # Collect all node definitions (structures, entities, events)
        all_node_defs: Dict[str, NodeDefinition] = {}
        all_node_defs.update(self.structures)
        all_node_defs.update(self.entities)
        
        # Also include events (they have properties too)
        event_defs: Dict[str, EventDefinition] = dict(self.events)
        
        def validate_property_rollup(
            container_name: str,
            prop_name: str,
            prop_def: PropertyDefinition,
        ) -> None:
            """Validate a single property's rollup configuration."""
            if prop_def.derivation != DerivationType.ROLLUP or not prop_def.rule:
                return
            
            rule = prop_def.rule
            aggregation = rule.aggregation
            
            if not aggregation:
                raise ValueError(
                    f"Property '{prop_name}' on '{container_name}' has ROLLUP derivation "
                    f"but no aggregation function specified."
                )
            
            # COUNT doesn't require a source key
            if aggregation == AggregationFunction.COUNT:
                return
            
            source_node = rule.source_node
            source_key = rule.key
            
            # For non-COUNT aggregations, we need a key to aggregate
            if not source_key:
                raise ValueError(
                    f"Property '{prop_name}' on '{container_name}' uses '{aggregation.value}' "
                    f"aggregation but no source 'key' is specified."
                )
            
            # If source_node is specified, validate it exists and has the property
            if source_node:
                # Check in structures, entities, and events
                source_def = all_node_defs.get(source_node) or event_defs.get(source_node)
                
                if source_def is None:
                    raise ValueError(
                        f"Property '{prop_name}' on '{container_name}' references "
                        f"source_node '{source_node}' which does not exist."
                    )
                
                
        
        # Validate all entities
        for entity_name, entity_def in self.entities.items():
            for prop_name, prop_def in entity_def.properties.items():
                validate_property_rollup(f"entity:{entity_name}", prop_name, prop_def)
        
        # Validate all events
        for event_name, event_def in self.events.items():
            for prop_name, prop_def in event_def.properties.items():
                validate_property_rollup(f"event:{event_name}", prop_name, prop_def)
        
        # Validate materialized relation properties
        for rel_name, rel_def in self.relations.items():
            if rel_def.materialization:
                for prop_name, prop_def in rel_def.materialization.properties.items():
                    validate_property_rollup(f"relation:{rel_name}", prop_name, prop_def)
        
        return self

class GraphDefinitionModel(BaseModel):
    system_version: str
    extensions: GraphExtensions