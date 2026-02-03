from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Optional, Any, Union
from datetime import datetime, timezone
import uuid

# ==========================================
# INPUT MODELS
# ==========================================

class MeasurementInput(BaseModel):
    """ 
    A single measurement entry.
    Timestamps are converted to Unix Epoch Milliseconds (int) for Apache AGE.
    """
    key: str
    value: Any
    confidence: Optional[float] = None
    confidence_type: Optional[str] = None
    unit: Optional[str] = None
    
    # Internal storage is int (ms), but accepts str/datetime inputs
    timestamp: Optional[int] = Field(None, description="Unix epoch time in milliseconds")

    @field_validator('timestamp', mode='before')
    def parse_timestamp(cls, v: Any) -> Optional[int]:
        """
        Converts ISO strings, datetime objects, or float seconds to Millisecond Epoch Int.
        """
        if v is None:
            return None
        
        # Case 1: Already an int (assume ms)
        if isinstance(v, int):
            return v
            
        # Case 2: Datetime object
        if isinstance(v, datetime):
            # Ensure timezone awareness (default to UTC if missing)
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            return int(v.timestamp() * 1000)
            
        # Case 3: ISO String
        if isinstance(v, str):
            try:
                # Handle 'Z' manually if python version < 3.11 for isoformat compatibility
                v = v.replace('Z', '+00:00')
                dt = datetime.fromisoformat(v)
                return int(dt.timestamp() * 1000)
            except ValueError:
                raise ValueError(f"Invalid timestamp format: {v}")

        raise ValueError(f"Unsupported timestamp type: {type(v)}")


def create_max_confidence_measurement(key: str, value: Any, unit: Optional[str] = None, timestamp: Any = None) -> MeasurementInput:
    """ Helper to create a measurement with max confidence """
    return MeasurementInput(
        key=key,
        value=value,
        confidence=1.0,
        confidence_type="max",
        unit=unit,
        timestamp=timestamp
    )

class StructureReference(BaseModel):
    identifier: str = Field(..., description="Schema identifier, e.g. '@mikro/roi'")
    object: str = Field(..., description="The unique ID of the object this structure references")
    measurements: List[MeasurementInput] = []

def create_told_you_so(measurements: List[MeasurementInput], object: str) -> StructureReference:
    return StructureReference(identifier="told_you_so", object=object, measurements=measurements)

class ProvenanceContext(BaseModel):
    subject: str = Field(..., description="User ID")
    app_id: str = Field(..., description="Client ID")
    action_id: Optional[str] = None
    action_name: Optional[str] = None
    action_args: Optional[Dict[str, Any]] = None

class EntityCreationPayload(BaseModel):
    ref_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: str
    supporting_evidence: List[StructureReference] = []
    provenance: ProvenanceContext
    
    
    
# ... [Previous imports & models: MeasurementInput, StructureReference, ProvenanceContext] ...

class RelationCreationPayload(BaseModel):
    """
    Payload to create a relationship backed by evidence.
    """
    ref_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: str = Field(..., description="The relationship label (e.g. 'CONNECTED_TO')")
    
    source_id: str = Field(..., description="The ID of the source entity")
    target_id: str = Field(..., description="The ID of the target entity")
    
    # Evidence is used to calculate properties on the edge (e.g. confidence)
    supporting_evidence: List[StructureReference] = []
    provenance: ProvenanceContext
    
    

class EntityCreationResult(BaseModel):
    ref_id: str
    db_id: str
    graph_id: Any
    status: str = "CREATED"


class StructureCreationPayload(BaseModel):
    """Payload for creating a structure."""
    identifier: str = Field(..., description="Schema identifier, e.g. '@mikro/roi'")
    object: str = Field(..., description="The unique ID of the object this structure references")


class StructureCreationResult(BaseModel):
    """Result of structure creation."""
    id: str
    identifier: str
    label: str
    status: str = "CREATED"


class AddMeasurementPayload(BaseModel):
    """Payload for adding a measurement to a structure."""
    structure_identifier: str = Field(..., description="Schema identifier of the structure")
    structure_id: str = Field(..., description="The unique ID of the structure")
    measurement: MeasurementInput
    provenance: ProvenanceContext