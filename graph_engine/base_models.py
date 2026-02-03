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

# --- 1. Property & Derivation Rules ---

class DerivationRule(BaseModel):
    """
    Configuration for how to calculate a value if derivation != LATEST.
    """
    source_node: Optional[str] = Field(None, description="The label of the the describing structure to read from.")
    key: Optional[str] = Field(None, description="The property key on the source node.")
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

# --- 2. Node Definitions ---




class NodeDefinition(BaseModel):
    description: Optional[str] = None
    allowed_parents: List[str] = [] # e.g. AIS can only belong to Cell
    properties: Dict[str, PropertyDefinition] = {}

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
    structures: Dict[str, NodeDefinition] = Field(default_factory=dict, description="Physical observations (ROIs).")
    entities: Dict[str, NodeDefinition] = Field(default_factory=dict, description="Logical aggregations (Cells).")
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

class GraphDefinitionModel(BaseModel):
    system_version: str
    extensions: GraphExtensions