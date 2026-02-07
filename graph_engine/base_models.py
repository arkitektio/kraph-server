from enum import Enum
from typing import List, Dict, Optional, Union, Literal
from pydantic import BaseModel, Field, model_validator, ConfigDict
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


class EventRole(BaseModel):
    """Role of a node in an event (input or output)."""
    model_config = ConfigDict(frozen=True)
    key: str = Field(..., description="The label of the node participating in the event")
    role: str = Field(..., description="What type of role does this node play in the event")
    



class EventKind(str, Enum):
    INTRINSIC = "intrinsic"
    EXTRINSIC = "extrinsic"

class EventDefinition(BaseModel):
    """Definition of an event (spatio-temporal transition)."""
    model_config = ConfigDict(frozen=True)
    kind: EventKind = EventKind.INTRINSIC
    key: str = Field(..., description="The unique key/name for this event type")
    inputs: List[EventRole] = Field(default_factory=list)
    outputs: List[EventRole] = Field(default_factory=list)
    properties: List[PropertyDefinition] = Field(default_factory=list, description="Properties on this event")
    
    @cached_property
    def properties_map(self) -> Dict[str, PropertyDefinition]:
        """Cached dict lookup for properties by key."""
        return {p.key: p for p in self.properties}

# --- 5. The Root Schema ---

# --- Identifier to Label Mapping ---

# Maps external identifiers to internal graph labels for structures
IDENTIFIER_MAP: Dict[str, str] = {
    "@mikro/roi": "ROI",
    "told_you_so": "ToldYouSo",
    "default": "Structure"
}


def get_label_for_identifier(identifier: str) -> str:
    """
    Get the graph label for a given external identifier.
    
    Uses the IDENTIFIER_MAP to translate external identifiers (like '@mikro/roi')
    to internal graph labels (like 'ROI').
    
    Args:
        identifier: The external identifier (e.g., '@mikro/roi', 'told_you_so')
        
    Returns:
        The corresponding graph label, or 'Structure' as default fallback
    """
    return IDENTIFIER_MAP.get(identifier, IDENTIFIER_MAP.get("default", "Structure"))


def get_identifier_for_label(label: str) -> Optional[str]:
    """
    Get the external identifier for a given graph label.
    
    Reverse lookup in the IDENTIFIER_MAP.
    
    Args:
        label: The internal graph label (e.g., 'ROI', 'ToldYouSo')
        
    Returns:
        The corresponding external identifier, or None if not found
    """
    return next((k for k, v in IDENTIFIER_MAP.items() if v == label), None)


class GraphExtensions(BaseModel):
    """
    Container for all type definitions in the graph schema.
    
    Uses lists with keyed items for easy GraphQL input serialization.
    Provides cached dict properties for efficient runtime access.
    
    Note: Structures are no longer defined in the schema. Instead, use
    get_label_for_identifier() to map external identifiers to graph labels.
    """
    model_config = ConfigDict(frozen=True)
    
    entities: List[EntityDefinition] = Field(default_factory=list, description="Logical aggregations (Cells).")
    relations: List[RelationDefinition] = Field(default_factory=list, description="Edges between nodes.")
    events: List[EventDefinition] = Field(default_factory=list, description="Temporal transitions.")
    
    # --- Cached Dict Properties for Performance ---
    
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
        def check_duplicates(items: list, category: str) -> None:
            keys = [item.key for item in items]
            seen = set()
            for key in keys:
                if key in seen:
                    raise ValueError(f"Duplicate {category} key: '{key}'")
                seen.add(key)
        
        check_duplicates(self.entities, "entity")
        check_duplicates(self.relations, "relation")
        check_duplicates(self.events, "event")
        return self

    @model_validator(mode='after')
    def validate_references(self):
        """
        Cross-check that relations refer to existing Node Types.
        Structure labels from IDENTIFIER_MAP are also valid.
        """
        # Include both entity keys and structure labels from IDENTIFIER_MAP
        structure_labels = set(IDENTIFIER_MAP.values())
        all_nodes = structure_labels | set(e.key for e in self.entities)
        
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
        # Note: Structures are not in the schema, they come from IDENTIFIER_MAP
        all_node_defs: Dict[str, NodeDefinition] = {}
        all_node_defs.update(self.entities_map)
        
        # Also include events (they have properties too)
        event_defs: Dict[str, EventDefinition] = self.events_map
        
        # Structure labels from IDENTIFIER_MAP are valid source_node references
        valid_structure_labels = set(IDENTIFIER_MAP.values())
        
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
            
            # If source_node is specified, validate it exists
            if source_node:
                # Check in entities, events, OR structure labels from IDENTIFIER_MAP
                source_def = all_node_defs.get(source_node) or event_defs.get(source_node)
                is_valid_structure = source_node in valid_structure_labels
                
                if source_def is None and not is_valid_structure:
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