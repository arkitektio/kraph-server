from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Optional, Any, Union
from datetime import datetime, timezone
import uuid

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

class EntityResponse(BaseModel):
    """
    The complete Entity view.
    Acts as BOTH a dictionary (via .properties) and a metadata container.
    """
    id: int
    kind: str
    
    # 1. Simple Access: entity.properties['vector_length']
    properties: Dict[str, Any] = {}
    
    # 2. Rich Access: [p for p in entity.rich_properties if p.unit == 'um']
    rich_properties: List[RichProperty] = []
    
    # System Metadata
    schema_version: Optional[str] = Field(None, alias="__schema_version")
    last_derived: Optional[int] = Field(None, alias="__last_derived")