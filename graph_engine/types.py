"""
Graph Engine Pydantic Types

Defines strict input models that enforce graph structure before touching the DB.
All business logic uses these Pydantic V2 models for validation.
"""
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator, field_validator
import uuid


class GraphOperation(str, Enum):
    """Operations that can be performed on graph nodes."""
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    MERGE = "MERGE"  # Create if not exists, update if exists


class ProvenanceModel(BaseModel):
    """
    Provenance information for tracking who/what made changes.
    
    This creates an Assertion node in the graph that links to all
    properties set during this mutation.
    """
    tool_name: str = Field(
        ...,
        description="The name of the tool/application making the change",
        min_length=1,
        max_length=255,
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence level of the assertion (0.0 to 1.0)",
    )
    user_id: Optional[str] = Field(
        default=None,
        description="The user ID making the change",
    )
    client_id: Optional[str] = Field(
        default=None,
        description="The client/application ID",
    )
    assignation_id: Optional[str] = Field(
        default=None,
        description="The task/assignation ID if from a workflow",
    )
    timestamp: Optional[str] = Field(
        default=None,
        description="ISO timestamp of when the change was made",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata about the provenance",
    )


class NodeChangeModel(BaseModel):
    """
    Model for a single node change operation.
    
    Uses ref_id for batch linking within the same mutation payload,
    and id for referencing existing nodes in the database.
    """
    ref_id: Optional[str] = Field(
        default=None,
        description="Reference ID for linking within this batch (not a DB ID)",
    )
    id: Optional[str] = Field(
        default=None,
        description="Real database ID (graph_name:node_id format)",
    )
    label: str = Field(
        ...,
        description="The node label/type (e.g., 'Person', 'Entity')",
        min_length=1,
        max_length=255,
    )
    operation: GraphOperation = Field(
        default=GraphOperation.CREATE,
        description="The operation to perform on this node",
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Properties to set on the node",
    )
    external_id: Optional[str] = Field(
        default=None,
        description="External ID for upsert operations (used with MERGE)",
    )
    
    @model_validator(mode="after")
    def validate_operation_requirements(self) -> "NodeChangeModel":
        """Ensure UPDATE and DELETE operations have an id."""
        if self.operation in (GraphOperation.UPDATE, GraphOperation.DELETE):
            if not self.id:
                raise ValueError(
                    f"Operation '{self.operation.value}' requires 'id' to be provided"
                )
        
        if self.operation == GraphOperation.CREATE and self.id:
            raise ValueError(
                "Operation 'CREATE' should not have 'id' set. Use 'ref_id' for batch linking."
            )
        
        if self.operation == GraphOperation.MERGE and not (self.external_id or self.id):
            raise ValueError(
                "Operation 'MERGE' requires either 'external_id' or 'id' to be provided"
            )
        
        return self
    
    @field_validator("label")
    @classmethod
    def validate_label_format(cls, v: str) -> str:
        """Ensure label is a valid identifier."""
        if not v.replace("_", "").isalnum():
            raise ValueError(
                f"Label '{v}' must be alphanumeric (underscores allowed)"
            )
        return v


class EdgeChangeModel(BaseModel):
    """
    Model for a single edge/relationship change.
    
    from_id and to_id can be either:
    - A ref_id from this batch (prefixed with 'ref:')
    - A real database ID (graph_name:node_id format)
    """
    from_id: str = Field(
        ...,
        description="Source node ID (ref:xxx for batch ref, or graph:id for DB ID)",
    )
    to_id: str = Field(
        ...,
        description="Target node ID (ref:xxx for batch ref, or graph:id for DB ID)",
    )
    label: str = Field(
        ...,
        description="The edge label/type (e.g., 'RELATES_TO', 'BELONGS_TO')",
        min_length=1,
        max_length=255,
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Properties to set on the edge",
    )
    
    @field_validator("label")
    @classmethod
    def validate_label_format(cls, v: str) -> str:
        """Ensure label is a valid identifier."""
        if not v.replace("_", "").isalnum():
            raise ValueError(
                f"Label '{v}' must be alphanumeric (underscores allowed)"
            )
        return v
    
    def is_from_ref(self) -> bool:
        """Check if from_id is a batch reference."""
        return self.from_id.startswith("ref:")
    
    def is_to_ref(self) -> bool:
        """Check if to_id is a batch reference."""
        return self.to_id.startswith("ref:")
    
    def get_from_ref(self) -> str:
        """Get the reference ID without prefix."""
        if self.is_from_ref():
            return self.from_id[4:]  # Remove "ref:" prefix
        raise ValueError("from_id is not a reference")
    
    def get_to_ref(self) -> str:
        """Get the reference ID without prefix."""
        if self.is_to_ref():
            return self.to_id[4:]  # Remove "ref:" prefix
        raise ValueError("to_id is not a reference")


class GraphMutationPayload(BaseModel):
    """
    Complete payload for a graph mutation operation.
    
    Contains provenance information and all node/edge changes to apply atomically.
    """
    graph_id: str = Field(
        ...,
        description="The graph ID (age_name) to apply changes to",
    )
    provenance: ProvenanceModel = Field(
        ...,
        description="Provenance information for this mutation",
    )
    nodes: list[NodeChangeModel] = Field(
        default_factory=list,
        description="List of node changes to apply",
    )
    edges: list[EdgeChangeModel] = Field(
        default_factory=list,
        description="List of edge changes to apply",
    )
    
    @model_validator(mode="after")
    def validate_refs_exist(self) -> "GraphMutationPayload":
        """Ensure all edge refs point to valid node refs."""
        # Collect all ref_ids from nodes with CREATE operation
        valid_refs = {
            node.ref_id
            for node in self.nodes
            if node.ref_id and node.operation == GraphOperation.CREATE
        }
        
        # Collect all node IDs for UPDATE/MERGE operations
        valid_ids = {
            node.id
            for node in self.nodes
            if node.id and node.operation in (GraphOperation.UPDATE, GraphOperation.MERGE)
        }
        
        # Check edge references
        for edge in self.edges:
            if edge.is_from_ref():
                ref = edge.get_from_ref()
                if ref not in valid_refs:
                    raise ValueError(
                        f"Edge references unknown ref_id '{ref}' in from_id. "
                        f"Valid refs: {valid_refs}"
                    )
            
            if edge.is_to_ref():
                ref = edge.get_to_ref()
                if ref not in valid_refs:
                    raise ValueError(
                        f"Edge references unknown ref_id '{ref}' in to_id. "
                        f"Valid refs: {valid_refs}"
                    )
        
        return self
    
    def calculate_complexity(self) -> int:
        """
        Calculate a complexity score for guardrail checks.
        
        Score is based on number of operations and properties.
        """
        score = 0
        
        for node in self.nodes:
            # Base cost per node operation
            if node.operation == GraphOperation.CREATE:
                score += 1
            elif node.operation == GraphOperation.UPDATE:
                score += 2
            elif node.operation == GraphOperation.DELETE:
                score += 3
            elif node.operation == GraphOperation.MERGE:
                score += 4
            
            # Additional cost per property
            score += len(node.properties)
        
        for edge in self.edges:
            score += 2  # Base cost per edge
            score += len(edge.properties)
        
        return score


class NodeResult(BaseModel):
    """Result of a single node operation."""
    ref_id: Optional[str] = None
    db_id: str = Field(..., description="The database ID (graph:node_id)")
    label: str
    operation: GraphOperation
    success: bool = True
    error: Optional[str] = None


class EdgeResult(BaseModel):
    """Result of a single edge operation."""
    db_id: str = Field(..., description="The database ID of the created edge")
    from_id: str
    to_id: str
    label: str
    success: bool = True
    error: Optional[str] = None


class GraphMutationResult(BaseModel):
    """
    Result of a graph mutation operation.
    """
    success: bool = Field(
        ...,
        description="Whether the entire mutation succeeded",
    )
    transaction_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique ID for this transaction",
    )
    id_map: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of ref_id -> real db_id for created nodes",
    )
    assertion_id: Optional[str] = Field(
        default=None,
        description="The ID of the provenance assertion node",
    )
    nodes: list[NodeResult] = Field(
        default_factory=list,
        description="Results for each node operation",
    )
    edges: list[EdgeResult] = Field(
        default_factory=list,
        description="Results for each edge operation",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="List of errors encountered",
    )
    
    @classmethod
    def failure(cls, errors: list[str], transaction_id: Optional[str] = None) -> "GraphMutationResult":
        """Create a failure result."""
        return cls(
            success=False,
            transaction_id=transaction_id or str(uuid.uuid4()),
            errors=errors,
        )
