from enum import Enum
from typing import List, Dict, Optional, Union, Literal
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict, computed_field
from functools import cached_property

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
    model_config = ConfigDict(frozen=True)
    
    key: str = Field(..., description="The unique key/name for this property")
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
    """Base class for node definitions."""
    model_config = ConfigDict(frozen=True)
    
    key: str = Field(..., description="The unique key/name for this node type")
    description: Optional[str] = None


class EntityDefinition(NodeDefinition):
    """Definition of an Entity (logical aggregation like a Cell)."""
    properties: List[PropertyDefinition] = Field(default_factory=list, description="Properties on this entity")
    
    @cached_property
    def properties_map(self) -> Dict[str, PropertyDefinition]:
        """Cached dict lookup for properties by key."""
        return {p.key: p for p in self.properties}


class StructureDefinition(NodeDefinition):
    """
    Definition of a Structure (physical observation).
    """
    pass
    
    
    
# --- 3. Edge Definitions (Relation Materialization) ---

class EvidenceRequirement(BaseModel):
    """A required measurement on evidence for relation materialization."""
    model_config = ConfigDict(frozen=True)
    
    key: str
    unit: str
    description: Optional[str] = None

class MaterializationConfig(BaseModel):
    """
    Rules for turning a TemporalLink (Evidence) into an Edge (Relation).
    """
    model_config = ConfigDict(frozen=True)
    
    backing_link_type: str = Field(..., description="The internal label for the Evidence Node (e.g. 'link_ais_soma').")
    desired_evidence: List[EvidenceRequirement] = Field(default_factory=list, description="Measurements expected on the backing link.")
    properties: List[PropertyDefinition] = Field(default_factory=list, description="Properties to derive on the relation")
    
    @cached_property
    def properties_map(self) -> Dict[str, PropertyDefinition]:
        """Cached dict lookup for properties by key."""
        return {p.key: p for p in self.properties}

class RelationDefinition(BaseModel):
    """Definition of a relation (edge) between entities."""
    model_config = ConfigDict(frozen=True)
    
    key: str = Field(..., description="The unique key/name for this relation type")
    source: Union[str, List[str]]
    target: Union[str, List[str]]
    cardinality: Literal["1:1", "1:N", "N:N"] = "1:N"
    
    # Optional: If this relation is materialized from evidence
    materialization: Optional[MaterializationConfig] = None

    @model_validator(mode='after')
    def validate_materialization_props(self):
        """Ensure materialized edges define how to calculate their properties."""
        if self.materialization:
            for prop in self.materialization.properties:
                if prop.derivation == DerivationType.ROLLUP and not prop.rule:
                     raise ValueError(f"Materialized property '{prop.key}' must have a derivation rule.")
        return self

# --- 4. Event Definitions ---

class EventDefinition(BaseModel):
    """Definition of an event (spatio-temporal transition)."""
    model_config = ConfigDict(frozen=True)
    
    key: str = Field(..., description="The unique key/name for this event type")
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    properties: List[PropertyDefinition] = Field(default_factory=list, description="Properties on this event")
    
    @cached_property
    def properties_map(self) -> Dict[str, PropertyDefinition]:
        """Cached dict lookup for properties by key."""
        return {p.key: p for p in self.properties}

# --- 5. The Root Schema ---

class GraphExtensions(BaseModel):
    """
    Container for all type definitions in the graph schema.
    
    Uses lists with keyed items for easy GraphQL input serialization.
    Provides cached dict properties for efficient runtime access.
    """
    model_config = ConfigDict(frozen=True)
    
    structures: List[StructureDefinition] = Field(default_factory=list, description="Physical observations (ROIs).")
    entities: List[EntityDefinition] = Field(default_factory=list, description="Logical aggregations (Cells).")
    relations: List[RelationDefinition] = Field(default_factory=list, description="Edges between nodes.")
    events: List[EventDefinition] = Field(default_factory=list, description="Spatio-temporal transitions.")
    
    # --- Cached Dict Properties for Performance ---
    
    @cached_property
    def structures_map(self) -> Dict[str, StructureDefinition]:
        """Cached dict lookup for structures by key."""
        return {s.key: s for s in self.structures}
    
    @cached_property
    def entities_map(self) -> Dict[str, EntityDefinition]:
        """Cached dict lookup for entities by key."""
        return {e.key: e for e in self.entities}
    
    @cached_property
    def relations_map(self) -> Dict[str, RelationDefinition]:
        """Cached dict lookup for relations by key."""
        return {r.key: r for r in self.relations}
    
    @cached_property
    def events_map(self) -> Dict[str, EventDefinition]:
        """Cached dict lookup for events by key."""
        return {e.key: e for e in self.events}
    
    @model_validator(mode='after')
    def validate_unique_keys(self):
        """Validate that all keys within each category are unique."""
        def check_duplicates(items: list, category: str):
            keys = [item.key for item in items]
            seen = set()
            for key in keys:
                if key in seen:
                    raise ValueError(f"Duplicate {category} key: '{key}'")
                seen.add(key)
        
        check_duplicates(self.structures, "structure")
        check_duplicates(self.entities, "entity")
        check_duplicates(self.relations, "relation")
        check_duplicates(self.events, "event")
        return self

    @model_validator(mode='after')
    def validate_references(self):
        """
        Cross-check that relations refer to existing Node Types.
        """
        all_nodes = set(s.key for s in self.structures) | set(e.key for e in self.entities)
        
        for rel in self.relations:
            sources = [rel.source] if isinstance(rel.source, str) else rel.source
            targets = [rel.target] if isinstance(rel.target, str) else rel.target
            
            for s in sources:
                if s not in all_nodes:
                    raise ValueError(f"Relation '{rel.key}' defines source '{s}' which is not a defined Structure or Entity.")
            for t in targets:
                if t not in all_nodes:
                    raise ValueError(f"Relation '{rel.key}' defines target '{t}' which is not a defined Structure or Entity.")
        return self
    
    @model_validator(mode='after')
    def validate_rollup_source_types(self):
        """
        Validate that ROLLUP derivations reference valid source nodes/properties
        and that the source property type is compatible with the aggregation function.
        """
        # Collect all node definitions using the cached maps
        all_node_defs: Dict[str, NodeDefinition] = {}
        all_node_defs.update(self.structures_map)
        all_node_defs.update(self.entities_map)
        
        # Also include events (they have properties too)
        event_defs: Dict[str, EventDefinition] = self.events_map
        
        def validate_property_rollup(
            container_name: str,
            prop_def: PropertyDefinition,
        ) -> None:
            """Validate a single property's rollup configuration."""
            if prop_def.derivation != DerivationType.ROLLUP or not prop_def.rule:
                return
            
            rule = prop_def.rule
            aggregation = rule.aggregation
            
            if not aggregation:
                raise ValueError(
                    f"Property '{prop_def.key}' on '{container_name}' has ROLLUP derivation "
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
                    f"Property '{prop_def.key}' on '{container_name}' uses '{aggregation.value}' "
                    f"aggregation but no source 'key' is specified."
                )
            
            # If source_node is specified, validate it exists and has the property
            if source_node:
                # Check in structures, entities, and events
                source_def = all_node_defs.get(source_node) or event_defs.get(source_node)
                
                if source_def is None:
                    raise ValueError(
                        f"Property '{prop_def.key}' on '{container_name}' references "
                        f"source_node '{source_node}' which does not exist."
                    )
        
        # Validate all entities
        for entity_def in self.entities:
            for prop_def in entity_def.properties:
                validate_property_rollup(f"entity:{entity_def.key}", prop_def)
        
        # Validate all events
        for event_def in self.events:
            for prop_def in event_def.properties:
                validate_property_rollup(f"event:{event_def.key}", prop_def)
        
        # Validate materialized relation properties
        for rel_def in self.relations:
            if rel_def.materialization:
                for prop_def in rel_def.materialization.properties:
                    validate_property_rollup(f"relation:{rel_def.key}", prop_def)
        
        return self

class GraphDefinitionModel(BaseModel):
    """
    The root graph schema definition.
    
    This model defines all types (entities, structures, relations, events)
    in a graph database schema.
    """
    model_config = ConfigDict(frozen=True)
    
    system_version: str = Field(..., description="Semantic version of the schema")
    extensions: GraphExtensions = Field(..., description="All type definitions")