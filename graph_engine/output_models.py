from pydantic import BaseModel
from typing import List, Dict, Optional, Any

# ... [Previous Input Models: MeasurementInput, StructureReference, etc. remain unchanged] ...

# ==========================================
# OUTPUT MODELS
# ==========================================

class RichProperty(BaseModel):
    """
    Detailed view of a property, combining the Database Value 
    with the Schema Definition.
    """
    key: str
    value: Any
    
    # Metadata from Schema
    unit: Optional[str] = None
    description: Optional[str] = None
    derivation_mode: str = "MANUAL" # e.g. "ROLLUP", "LATEST"
    
    # Metadata from Graph (if available/cached)
    confidence: Optional[float] = None
    last_updated: Optional[int] = None





class NodeResponse(BaseModel):
    """
    Base response model for a graph node.
    """
    graph_id: int  # Local AGE graph ID
    global_id: str  # Format: "graph_name:graph_id"
    label: str  # The AGE graph label
    
    
    
class VersionedNodeResponse(NodeResponse):
    """
    Extends NodeResponse to include versioning metadata.
    """
    schema_version: str
    last_derived: int

class EntityResponse(VersionedNodeResponse):
    """
    The complete Entity view.
    Acts as BOTH a dictionary (via .properties) and a metadata container.
    """
    id: str  # The user-facing UUID
    kind: str
    properties: Dict[str, Any] = {}
    
    # 2. Rich Access: [p for p in entity.rich_properties if p.unit == 'um']
    rich_properties: List[RichProperty] = []

class NaturalEventResponse(VersionedNodeResponse):
    """
    Response model for a NaturalEvent node.
    Acts as BOTH a dictionary (via .properties) and a metadata container.
    """
    id: str  # The user-facing UUID
    kind: str
    properties: Dict[str, Any] = {}
    
    # 2. Rich Access: [p for p in entity.rich_properties if p.unit == 'um']
    rich_properties: List[RichProperty] = []


# These are the property less models that actually carry data
class StructureResponse(NodeResponse):
    """
    Response model for a Structure node.
    Structures are identified by identifier + object.
    """
    identifier: str  # Schema identifier (e.g. '@mikro/roi')
    object: str  # The external object ID (what was previously 'id')

class MeasurementResponse(NodeResponse):
    """
    Response model for a Measurement node.
    """
    key: str
    value: Any
    unit: Optional[str] = None
    confidence: Optional[float] = None
    confidence_type: Optional[str] = None
    timestamp: Optional[int] = None

class AssertionResponse(NodeResponse):
    """
    Response model for an Assertion (provenance) node.
    """
    subject: Optional[str] = None
    app_id: Optional[str] = None
    action_id: Optional[str] = None
    action_name: Optional[str] = None
    action_args: Optional[str] = None
    action_name: Optional[str] = None
    action_args: Optional[str] = None