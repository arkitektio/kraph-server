"""
Retrieved Entity and Relation Data Classes

These dataclasses wrap raw AGE graph data and provide convenient accessors
for type discrimination and property access. They follow the same pattern
as core/age.py's RetrievedEntity and RetrievedRelation.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Type, TypeVar
from datetime import datetime
from graph_engine import vocab

# Reserved property keys that should not be exposed as user properties
RESERVED_PROPERTY_KEYS = frozenset(
    {
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
    }
)


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
    vocab.Metric: "METRIC",
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


T = TypeVar("T", bound="RetrievedNode")


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
    def unique_id(self) -> str:
        """Global unique identifier: 'graph_name:id'"""
        return f"{self.graph_name}:{self.id}"

    @property
    def global_id(self) -> str:
        """Alias for unique_id."""
        return self.unique_id

    @property
    def local_id(self) -> int:
        """Local AGE graph ID."""
        return self.id

    @property
    def graph_id(self) -> int:
        """Alias for local_id - the AGE graph ID."""
        return self.id

    # === Type Discrimination ===

    @property
    def category_id(self) -> Optional[str]:
        """Get the category ID (for linking to Django model)."""
        return self.properties.get("category_id")

    @property
    def node_type(self) -> NodeType:
        """Get the node type for discrimination.

        First checks properties['type'], then falls back to label mapping.
        """
        # Check for explicit type in properties
        if "type" in self.properties:
            return self.properties["type"]
        # Fall back to label-based mapping
        return VocabNodeTypeMap.get(self.label, "ENTITY")

    @property
    def category_type(self) -> NodeType:
        """Alias for node_type - the type for discrimination."""
        return self.node_type

    # === Entity Properties (when node_type == 'ENTITY') ===

    @property
    def kind(self) -> str:
        """The entity kind (label on category)."""
        return self.label

    @property
    def external_id(self) -> Optional[str]:
        """External ID if set (from properties)."""
        return self.properties.get("external_id")

    # === Versioning Properties ===
    @property
    def schema_version(self) -> Optional[str]:
        """Schema version used to derive this node's properties."""
        # Check both prefixed and non-prefixed keys
        return self.properties.get("__schema_version") or self.properties.get("schema_version")

    @property
    def last_derived(self) -> Optional[int]:
        """Timestamp (unix ms) when properties were last derived."""
        # Check both prefixed and non-prefixed keys
        val = self.properties.get("__last_derived") or self.properties.get("last_derived")
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

    def get_all_variables(self) -> List["RetrievedVariable"]:
        """Get all user-facing properties as RetrievedVariable objects."""
        return [RetrievedVariable(key=k, value=v) for k, v in self.cleaned_properties.items()]

    @property
    def cleaned_properties(self) -> Dict[str, Any]:
        """
        Get properties with reserved keys filtered out.
        These are the user-facing properties.
        """
        return {k: v for k, v in self.properties.items() if k not in RESERVED_PROPERTY_KEYS}

    # === Hash/Equality ===

    def __hash__(self) -> int:
        """Has based on graph_name and id"""
        return hash((self.graph_name, self.id))

    def __eq__(self, other: Any) -> bool:
        """Equality based on graph_name and id"""
        if not isinstance(other, RetrievedNode):
            return False
        return self.graph_name == other.graph_name and self.id == other.id

    @classmethod
    def from_node(cls: Type[T], node: Dict[str, Any], graph_name: str = "default_graph") -> T:
        """Factory method to create a RetrievedNode from raw AGE node data."""
        return cls(
            graph_name=graph_name,
            id=node.get("id", 0),
            label=node.get("label", "Unknown"),
            properties=node.get("properties", {}),
        )


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
    def graph_id(self) -> int:
        """Alias for id - the AGE graph ID."""
        return self.id

    @property
    def global_left_id(self) -> str:
        """Global ID of source node."""
        return f"{self.graph_name}:{self.left_id}"

    @property
    def global_right_id(self) -> str:
        """Global ID of target node."""
        return f"{self.graph_name}:{self.right_id}"

    @property
    def unique_left_id(self) -> str:
        """Alias for global_left_id."""
        return self.global_left_id

    @property
    def unique_right_id(self) -> str:
        """Alias for global_right_id."""
        return self.global_right_id

    # === Type Discrimination ===

    @property
    def kind(self) -> str:
        """
        Get the edge type for discrimination.
        Returns the 'type' property value, used for matching to subtypes.
        """
        return self.label

    @property
    def edge_type(self) -> Optional[str]:
        """Get the edge type from properties."""
        return self.properties.get("type")

    @property
    def category_id(self) -> Optional[str]:
        """Get the category ID (for linking to Django model)."""
        return self.properties.get("category_id")

    # === Measurement Properties (when edge_type == 'MEASUREMENT') ===

    @property
    def key(self) -> Optional[str]:
        """The measurement key/name."""
        return self.properties.get("key")

    @property
    def value(self) -> Any:
        """The measurement value."""
        return self.properties.get("value")

    @property
    def unit(self) -> Optional[str]:
        """The measurement unit (if any)."""
        return self.properties.get("unit")

    @property
    def confidence(self) -> Optional[float]:
        """The measurement confidence (if any)."""
        return self.properties.get("confidence")

    @property
    def confidence_type(self) -> Optional[str]:
        """The type of confidence measure (if any)."""
        return self.properties.get("confidence_type")

    @property
    def timestamp(self) -> Optional[int]:
        """The timestamp of the measurement (unix ms, if any)."""
        return self.properties.get("timestamp")

    # === Assertion Properties (when edge_type == 'ASSERTION') ===

    @property
    def subject(self) -> Optional[str]:
        """The subject who made the assertion."""
        return self.properties.get("subject")

    @property
    def app_id(self) -> Optional[str]:
        """The application ID that created the assertion."""
        return self.properties.get("app_id")

    @property
    def action_name(self) -> Optional[str]:
        """The name of the action that created the assertion."""
        return self.properties.get("action_name")

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
        return {k: v for k, v in self.properties.items() if k not in RESERVED_PROPERTY_KEYS}

    @property
    def shadow_link_id(self) -> Optional[int]:
        """Get the shadow link ID if present (used for structure-entity links)."""
        val = self.properties.get("__shadow_link_id")
        if val is None:
            return None
        return int(val) if isinstance(val, (int, float, str)) else None

    # === Hash/Equality ===

    def __hash__(self) -> int:
        """Has based on graph_name and id"""
        return hash((self.graph_name, self.id))

    def __eq__(self, other: Any) -> bool:
        """Equality based on graph_name and id"""
        if not isinstance(other, RetrievedNode):
            return False
        return self.graph_name == other.graph_name and self.id == other.id


# ==========================================
# Specialized Retrieved Node Types, for type discrimination
# ==========================================
@dataclass
class RetrievedRelation(RetrievedEdge):
    """A retrieved Relation edge from the AGE graph."""

    pass


@dataclass
class RetrievedReifiesAsSource(RetrievedEdge):
    """A retrieved edge that reifies a structure as a source."""

    pass


@dataclass
class RetrievedEntity(RetrievedNode):
    """A retrieved Entity node from the AGE graph."""

    @property
    def schema_hash(self) -> Optional[str]:
        """The schema hash of the entity."""
        return self.properties.get("schema_hash")

    @property
    def entity_id(self) -> Optional[str]:
        """The entity's logical UUID (stored in properties['id'])."""
        return self.properties.get("id")


@dataclass
class RetrievedStructure(RetrievedNode):
    """A retrieved Structure node from the AGE graph."""

    pass


@dataclass
class RetrievedEvent(RetrievedNode):
    """A retrieved Event node from the AGE graph."""

    pass


@dataclass
class RetrievedNaturalEvent(RetrievedNode):
    """A retrieved Event node from the AGE graph."""

    pass


@dataclass
class RetrievedProtocolEvent(RetrievedNode):
    """A retrieved Event node from the AGE graph."""

    pass


@dataclass
class RetrievedMetric(RetrievedNode):
    """A retrieved Metric node from the AGE graph."""

    pass


@dataclass
class RetrievedAssertion(RetrievedNode):
    """A retrieved Assertion node from the AGE graph."""

    pass


# ==========================================
# Factory Functions for Creating from AGE Data
# ==========================================


@dataclass
class RetrievedGraphNodesRender:
    """A list of retrieved nodes, with the graph name for context."""

    graph_name: str
    nodes: List[RetrievedNode]


@dataclass
class RetrievedGraphTableRender:
    """A list of retrieved nodes, with the graph name for context."""

    graph_name: str
    rows: List[Dict[str, Any]]


@dataclass
class RetrievedGraphPathRender:
    """A list of retrieved nodes, with the graph name for context."""

    graph_name: str
    nodes: List[RetrievedNode]
    edges: List[RetrievedEdge]


@dataclass
class Pairs:
    left: RetrievedNode
    right: RetrievedNode
    edge: Optional[RetrievedEdge] = None


@dataclass
class RetrievedGraphPairsRender:
    """A list of retrieved node pairs, with the graph name for context."""

    graph_name: str
    pairs: List[Pairs]


@dataclass
class RetrievedNodePathRender:
    """A list of retrieved nodes, with the graph name for context."""

    graph_name: str
    paths: List[List[RetrievedNode]]


@dataclass
class RetrievedNodeTableRender:
    """A list of retrieved nodes, with the graph name for context."""

    graph_name: str
    rows: List[Dict[str, Any]]


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
