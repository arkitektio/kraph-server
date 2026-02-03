"""
Retrieved Entity and Relation Data Classes

These dataclasses wrap raw AGE graph data and provide convenient accessors
for type discrimination and property access. They follow the same pattern
as core/age.py's RetrievedEntity and RetrievedRelation.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Union
from datetime import datetime
from graph_engine import vocab

# Reserved property keys that should not be exposed as user properties
RESERVED_PROPERTY_KEYS = frozenset({
    "type",
    "category_id", 
    "valid_from",
    "valid_to",
    "external_id",
    "local_id",
    "tags",
    "pinned_by",
    "identifier",
    "object",
    "schema_version",
    "last_derived",
})



# Type literals for node discrimination
NodeType = Literal[
    "ENTITY",
    "STRUCTURE",
    "MEASUREMENT",
    "ASSERTION",
    "NATURAL_EVENT",
    "METRIC",
    "REAGENT",
    "PROTOCOL_EVENT",
    "EDIT_EVENT",
]

VocabNodeTypeMap: Dict[str, NodeType] = {
    vocab.Entity: "ENTITY",
    vocab.Structure: "STRUCTURE",
    vocab.NaturalEvent: "NATURAL_EVENT",
    vocab.Measurement: "MEASUREMENT",
    vocab.ProtocolEvent: "PROTOCOL_EVENT",
    vocab.Assertion: "ASSERTION",
}


# Type literals for edge discrimination
EdgeType = Literal[
    "MEASUREMENT",
    "RELATION",
    "PARTICIPANT",
    "DESCRIPTION",
    "STRUCTURE_RELATION",
    "ASSERTION",
    "EDITED",
]


@dataclass
class RetrievedVariable:
    """A single property/variable from a node."""
    key: str
    value: Any
    
    def __hash__(self):
        return hash(self.key)


@dataclass
class RetrievedNode:
    """
    A retrieved node from the AGE graph.
    
    This dataclass wraps raw AGE query results and provides convenient
    accessors for type discrimination and property access. It mirrors
    the core/age.py RetrievedEntity pattern.
    
    Attributes:
        graph_name: The name of the AGE graph
        id: The AGE vertex ID
        label: The vertex label (e.g., 'Entity', 'Structure')
        properties: Raw properties dictionary from AGE
    """
    
    
    graph_name: str
    id: int
    label: str
    properties: Dict[str, Any] = field(default_factory=dict)
    
    # === Core ID Properties ===
    
    @property
    def global_id(self) -> str:
        """Global unique identifier: 'graph_name:id'"""
        return f"{self.graph_name}:{self.id}"
    
    @property
    def local_id(self) -> int:
        """Local AGE graph ID."""
        return self.id
    
    # === Type Discrimination ===
    
    @property
    def category_id(self) -> Optional[str]:
        """Get the category ID (for linking to Django model)."""
        return self.properties.get("category_id")
    
    # === Entity Properties (when node_type == 'ENTITY') ===
    
    @property
    def kind(self) -> str:
        """The entity kind (label on category)."""
        return self.label
    
    
    @property
    def node_type(self) -> NodeType:
        """Get the node type for discrimination."""
        return VocabNodeTypeMap.get(self.label, "ENTITY")
    
    
    # === Versioning Properties ===
    @property
    def schema_version(self) -> str:
        """Schema version used to derive this node's properties."""
        return self.properties.get("schema_version", "1.0.0")
    
    @property
    def last_derived(self) -> Optional[int]:
        """Timestamp (unix ms) when properties were last derived."""
        val = self.properties.get("last_derived")
        if val is None:
            return None
        return int(val) if isinstance(val, (int, float, str)) else None
    
    # === Validity Properties ===
    
    @property
    def valid_from(self) -> Optional[datetime]:
        """When this entity became valid. This is set when a measurement is added, its the
        range of all measurements that contribute to this entity."""
        val = self.properties.get("valid_from")
        if val is None:
            return None
        return datetime.fromtimestamp(float(val))
        
    
    @property
    def valid_to(self) -> Optional[datetime]:
        """When this entity became valid. This is set when a measurement is added, its the
        range of all measurements that contribute to this entity."""
        val = self.properties.get("valid_to")
        if val is None:
            return None
        if isinstance(val, str):
            return datetime.fromisoformat(val)
        return val
    
    # === Structure Properties (when node_type == 'STRUCTURE') ===
    
    @property
    def identifier(self) -> Optional[str]:
        """Structure schema identifier (e.g., '@mikro/roi')."""
        return self.properties.get("identifier")
    
    @property
    def object(self) -> Optional[str]:
        """External object ID the structure references."""
        return self.properties.get("object")
    
    # === Assertion Properties (when node_type == 'ASSERTION') ===
    
    @property
    def subject(self) -> Optional[str]:
        """User/subject who made the assertion."""
        return self.properties.get("subject")
    
    @property
    def app_id(self) -> Optional[str]:
        """Application that made the assertion."""
        return self.properties.get("app_id")
    
    @property
    def action_id(self) -> Optional[str]:
        """Action identifier."""
        return self.properties.get("action_id")
    
    @property
    def action_name(self) -> Optional[str]:
        """Human-readable action name."""
        return self.properties.get("action_name")
    
    @property
    def action_args(self) -> Optional[Any]:
        """Action arguments as JSON."""
        return self.properties.get("action_args")
    
    
    # === Property Access Methods ===
    
    def get_property(self, key: str, default: Any = None) -> Any:
        """Get a single property value by key."""
        return self.cleaned_properties.get(key, default)
    
    @property
    def cleaned_properties(self) -> Dict[str, Any]:
        """
        Get properties with reserved keys filtered out.
        These are the user-facing properties.
        """
        return {
            k: v for k, v in self.properties.items()
            if k not in RESERVED_PROPERTY_KEYS
        }
    
    
    # === Hash/Equality ===
    
    def __hash__(self) -> int:
        """ Has based on graph_name and id """
        return hash((self.graph_name, self.id))
    
    def __eq__(self, other: Any) -> bool:
        """ Equality based on graph_name and id """
        if not isinstance(other, RetrievedNode):
            return False
        return self.graph_name == other.graph_name and self.id == other.id


@dataclass
class RetrievedEdge:
    """
    A retrieved edge from the AGE graph.
    
    This dataclass wraps raw AGE edge query results and provides convenient
    accessors for type discrimination and property access. It mirrors
    the core/age.py RetrievedRelation pattern.
    
    Attributes:
        graph_name: The name of the AGE graph
        id: The AGE edge ID
        label: The edge label (e.g., 'MEASURES', 'ASSERTS')
        left_id: The source vertex ID
        right_id: The target vertex ID  
        properties: Raw properties dictionary from AGE
    """
    graph_name: str
    id: int
    label: str
    left_id: int
    right_id: int
    properties: Dict[str, Any] = field(default_factory=dict)
    
    # === Core ID Properties ===
    
    @property
    def unique_id(self) -> str:
        """Global unique identifier: 'graph_name:id'"""
        return f"{self.graph_name}:{self.id}"
    
    @property
    def global_id(self) -> str:
        """Alias for unique_id."""
        return self.unique_id
    
    @property
    def global_left_id(self) -> str:
        """Global ID of source node."""
        return f"{self.graph_name}:{self.left_id}"
    
    @property
    def global_right_id(self) -> str:
        """Global ID of target node."""
        return f"{self.graph_name}:{self.right_id}"
    
    # === Type Discrimination ===
    
    @property
    def kind(self) -> str:
        """
        Get the edge type for discrimination.
        Returns the 'type' property value, used for matching to subtypes.
        """
        return self.label
    
    
    @property
    def category_id(self) -> Optional[str]:
        """Get the category ID (for linking to Django model)."""
        return self.properties.get("category_id")
    
    
    
    # === Validity Properties ===
    
    @property
    def valid_from(self) -> Optional[datetime]:
        """When this edge became valid."""
        val = self.properties.get("valid_from")
        if val is None:
            return None
        if isinstance(val, str):
            return datetime.fromisoformat(val)
        return val
    
    @property
    def valid_to(self) -> Optional[datetime]:
        """When this edge stopped being valid."""
        val = self.properties.get("valid_to")
        if val is None:
            return None
        if isinstance(val, str):
            return datetime.fromisoformat(val)
        return val
    
    
     # === Property Access Methods ===
    
    def get_property(self, key: str, default: Any = None) -> Any:
        """Get a single property value by key."""
        return self.cleaned_properties.get(key, default)
    
    @property
    def cleaned_properties(self) -> Dict[str, Any]:
        """
        Get properties with reserved keys filtered out.
        These are the user-facing properties.
        """
        return {
            k: v for k, v in self.properties.items()
            if k not in RESERVED_PROPERTY_KEYS
        }
    
    
    # === Hash/Equality ===
    
    def __hash__(self) -> int:
        """ Has based on graph_name and id """
        return hash((self.graph_name, self.id))
    
    def __eq__(self, other: Any) -> bool:
        """ Equality based on graph_name and id """
        if not isinstance(other, RetrievedNode):
            return False
        return self.graph_name == other.graph_name and self.id == other.id


# ==========================================
# Factory Functions for Creating from AGE Data
# ==========================================

def node_from_age_result(
    graph_name: str,
    vertex_data: Dict[str, Any],
) -> RetrievedNode:
    """
    Create a RetrievedNode from raw AGE vertex data.
    
    Args:
        graph_name: The AGE graph name
        vertex_data: Raw vertex data from AGE query result
        
    Returns:
        RetrievedNode instance
    """
    return RetrievedNode(
        graph_name=graph_name,
        id=vertex_data.get("id", 0),
        label=vertex_data.get("label", "Unknown"),
        properties=vertex_data.get("properties", {}),
    )


def edge_from_age_result(
    graph_name: str,
    edge_data: Dict[str, Any],
) -> RetrievedEdge:
    """
    Create a RetrievedEdge from raw AGE edge data.
    
    Args:
        graph_name: The AGE graph name
        edge_data: Raw edge data from AGE query result
        
    Returns:
        RetrievedEdge instance
    """
    return RetrievedEdge(
        graph_name=graph_name,
        id=edge_data.get("id", 0),
        label=edge_data.get("label", "Unknown"),
        left_id=edge_data.get("start_id", 0),
        right_id=edge_data.get("end_id", 0),
        properties=edge_data.get("properties", {}),
    )
