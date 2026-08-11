"""
Retrieved Entity and Relation Data Classes

These dataclasses wrap raw AGE graph data and provide convenient accessors
for type discrimination and property access. They follow the same pattern
as core/age.py's RetrievedEntity and RetrievedRelation.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Type, TypeVar, TYPE_CHECKING
from datetime import datetime, timezone
from graph_engine import vocab, scalars

if TYPE_CHECKING:
    from graph_engine.controller import GraphController


# Reserved property keys that should not be exposed as user properties.
#
# Two separate rules apply, and conflating them is what previously leaked internals:
#   1. These named keys carry node identity/metadata rather than user data.
#   2. Any key prefixed with `__` is written by the projection layer
#      (`__schema_version`, `__last_derived`, `__lifecycle_state`, `__measured__*`,
#      `__shadow_link_id`) and is never user data. Filtering by prefix means new
#      internal keys are excluded automatically instead of leaking until someone
#      remembers to extend this set.
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
    }
)

INTERNAL_PROPERTY_PREFIX = "__"


def _as_datetime(value: Any) -> Optional[datetime]:
    """Read a validity bound out of a node property.

    Handles both spellings because both are in the wild: the projector writes ISO
    strings, and older nodes carry epoch numbers. `valid_from` used to parse only
    numbers while `valid_to` parsed only strings, so whichever one you wrote, one
    of the pair broke.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def is_internal_property_key(key: str) -> bool:
    """Whether a raw node property key is engine-internal rather than user data."""
    return key in RESERVED_PROPERTY_KEYS or key.startswith(INTERNAL_PROPERTY_PREFIX)


# Type literals for node discrimination
NodeType = Literal[
    "ENTITY",
    "STRUCTURE",
    "MEASUREMENT",
    "ACTIVITY",
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
    "Activity": "ACTIVITY",
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

    def __hash__(self) -> int:
        """A hash"""
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

    controller: "GraphController"
    graph_name: str
    id: int
    label: str
    properties: Dict[str, Any] = field(default_factory=dict)
    row_id: Optional[str] = None
    """Primary key when this node is backed by a relational evidence row.

    Structures, metrics and assertions live in Postgres, not in AGE, so they have
    a real SQL primary key and no meaningful AGE vertex id. When this is set it
    is the node's identity and `id`/`graph_name` carry no information. Everything
    still projected into AGE — entities, events, relation edges — leaves it None
    and keeps the composite `{graph_name}:{id}` form unchanged.
    """

    # === Core ID Properties ===

    @property
    def is_row_backed(self) -> bool:
        """Whether this node came from the evidence tables rather than from AGE."""
        return self.row_id is not None

    @property
    def unique_id(self) -> str:
        """Global unique identifier.

        `{graph_name}:{id}` for projected nodes, the bare primary key for
        evidence rows — which are organization-scoped and so cannot be named by a
        graph without lying about where they live.
        """
        if self.row_id is not None:
            return self.row_id
        return f"{self.graph_name}:{self.id}"

    @property
    def lifecycle(self) -> Optional[str]:
        """Current lifecycle state of the node."""
        return self.properties.get("__lifecycle_state") or self.properties.get("lifecycle_status")

    @property
    def lifecycle_status(self) -> Optional[str]:
        """Get the lifecycle status of the node, if present."""
        return self.properties.get("lifecycle_status")

    @property
    def global_id(self) -> str:
        """A globally unique identifier for this node.

        For an evidence row the primary key already *is* globally unique, so
        there is nothing to look up. Only projected AGE nodes carry a separate
        `global_id` property.
        """
        if self.row_id is not None:
            return scalars.GlobalID(self.row_id)

        if not self.properties.get("global_id"):
            raise ValueError("Node is missing 'global_id' property")

        return scalars.GlobalID(self.properties["global_id"])

    @property
    def local_id(self) -> scalars.LocalID:
        """Local AGE graph ID."""
        return scalars.LocalID(self.id)

    @property
    def graph_id(self) -> scalars.GraphID:
        """Alias for local_id - the AGE graph ID."""
        return scalars.GraphID(self.unique_id)

    @property
    def durable_ref(self) -> str:
        """The identity evidence uses to refer to this node.

        `{graph_name}:{uuid}`, keyed on the node's own `id` property rather than
        on its Apache AGE vertex id. Vertex ids are reassigned when a graph is
        dropped and replayed, so anything stored against one dangles after a
        `reproject` — which is why every evidence link, state vector and
        lifecycle row uses this instead.

        Falls back to `unique_id` for nodes with no uuid (evidence rows, which
        already have a durable primary key of their own).
        """
        node_uuid = self.properties.get("id")
        if node_uuid is None:
            return self.unique_id
        return f"{self.graph_name}:{node_uuid}"

    # === Type Discrimination ===

    @property
    def category_id(self) -> Optional[str]:
        """Get the category ID (for linking to Django model)."""
        if self.properties.get("category_id") is None:
            raise ValueError(f"Node is missing 'category_id' property {self.properties}")
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
        """Start of the observation window this node's evidence covers."""
        return _as_datetime(self.properties.get("valid_from"))

    @property
    def valid_to(self) -> Optional[datetime]:
        """End of the observation window this node's evidence covers."""
        return _as_datetime(self.properties.get("valid_to"))

    # === Structure Properties (when node_type == 'STRUCTURE') ===

    @property
    def identifier(self) -> Optional[str]:
        """Structure schema identifier (e.g., '@mikro/roi')."""
        return self.properties.get("identifier")

    @property
    def object(self) -> Optional[str]:
        """External object ID the structure references."""
        return self.properties.get("object")

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
        return {k: v for k, v in self.properties.items() if not is_internal_property_key(k)}

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
    def from_node(cls: Type[T], controller: "GraphController", node: Dict[str, Any], graph_name: str = "default_graph") -> T:
        """Factory method to create a RetrievedNode from raw AGE node data."""
        return cls(
            controller=controller,
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
    def category_id(self) -> str:
        """Get the category ID (for linking to Django model)."""
        cat = self.properties.get("category_id")
        if cat is None:
            raise ValueError("Edge is missing 'category_id' property")
        return cat

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
        return {k: v for k, v in self.properties.items() if not is_internal_property_key(k)}

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
class RetrievedInforms(RetrievedEdge):
    """A retrieved Relation edge from the AGE graph."""

    pass


@dataclass
class RetrievedDescribes(RetrievedEdge):
    """A retrieved Metric edge from the AGE graph."""

    pass


@dataclass
class RetrievedAsserts(RetrievedEdge):
    """A retrieved Metric edge from the AGE graph."""

    pass


@dataclass
class RetrievedReifiesAsSource(RetrievedEdge):
    """A retrieved edge that reifies a structure as a source."""

    pass


@dataclass
class RetrievedEntity(RetrievedNode):
    """A retrieved Entity node from the AGE graph."""

    # NOTE: there is no `schema_hash` accessor here. The projection layer writes
    # `__schema_version`, never `schema_hash`, so the old accessor always returned
    # None. Use the inherited `schema_version` property instead.

    @property
    def entity_id(self) -> Optional[str]:
        """The entity's logical UUID (stored in properties['id'])."""
        return self.properties.get("id")


@dataclass
class RetrievedStructure(RetrievedNode):
    """A structure, read from the relational evidence base.

    Structures stopped being AGE vertices in M1. This stays a `RetrievedNode`
    rather than becoming a strawberry-django type so that `api/types.py` keeps
    working untouched — rewriting that layer is M5's job, and doing it here would
    mean doing it twice.
    """

    @classmethod
    def from_row(cls, controller: "GraphController", row: Any, graph_name: str = "") -> "RetrievedStructure":
        """Adapt an `evidence.models.Structure` row to the node-shaped API surface."""
        return cls(
            controller=controller,
            graph_name=graph_name,
            id=0,
            label=vocab.Structure,
            row_id=str(row.pk),
            properties={
                "identifier": row.identifier,
                "object": row.object,
                "category_id": str(row.category_id),
                "__lifecycle_state": row.status,
            },
        )


@dataclass
class RetrievedRelationShadowLink(RetrievedNode):
    """A retrieved RelationShadowLink node from the AGE graph."""

    pass


@dataclass
class RetrievedStructureRelationShadowLink(RetrievedNode):
    """A retrieved RelationShadowLink node from the AGE graph."""

    pass


@dataclass
class RetrievedMeasurementShadowLink(RetrievedNode):
    """A retrieved MeasurementShadowLink node from the AGE graph."""

    pass


@dataclass
class RetrievedEvent(RetrievedNode):
    """A retrieved Event node from the AGE graph."""

    pass


@dataclass
class RetrievedShadowLink(RetrievedNode):
    """A retrieved ShadowLink node from the AGE graph."""

    pass


@dataclass
class RetrievedMeasurementLink(RetrievedNode):
    """A retrieved MeasurementLink node from the AGE graph."""

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
class RetrievedMeasurement(RetrievedEdge):
    """A retrieved Measurement edge from the AGE graph."""

    pass

    @property
    def role(self) -> Optional[str]:
        """The measurement role (i.e as input to a structure, as a property of an entity, etc)."""
        return self.properties.get("role")

    @property
    def supporting_links(self) -> List[RetrievedShadowLink]:
        """List of shadow link IDs that support this measurement."""
        raise NotImplementedError("This method is not implemented yet. It would require additional queries to fetch linked shadow links based on the shadow_link_id property.")


@dataclass
class RetrievedMetric(RetrievedNode):
    """A metric, read from the relational evidence base."""

    @property
    def value(self) -> Any:
        """The metric value."""
        return self.properties.get("value")

    @property
    def measured_at(self) -> Optional[datetime]:
        """When the world was observed."""
        return self.properties.get("__measured_at")

    @property
    def asserted_at(self) -> Optional[datetime]:
        """When this measurement was claimed."""
        return self.properties.get("__asserted_at")

    @classmethod
    def from_row(cls, controller: "GraphController", row: Any, graph_name: str = "") -> "RetrievedMetric":
        """Adapt an `evidence.models.Metric` row to the node-shaped API surface."""
        properties: Dict[str, Any] = {
            "key": row.key,
            "value": row.value,
            "category_id": str(row.category_id),
            "__measured_at": row.measured_at,
            "__asserted_at": row.asserted_at,
            "__lifecycle_state": row.status,
        }
        for optional_key in ("unit", "confidence", "confidence_type"):
            value = getattr(row, optional_key, None)
            if value is not None:
                properties[optional_key] = value

        return cls(
            controller=controller,
            graph_name=graph_name,
            id=0,
            label=vocab.Metric,
            row_id=str(row.pk),
            properties=properties,
        )


@dataclass
class RetrievedActivity(RetrievedNode):
    """A retrieved Activity node from the AGE graph."""

    # === Activity Properties (formerly Assertion) ===

    @property
    def subject(self) -> Optional[str]:
        """User/subject who performed the activity."""
        return self.properties.get("subject")

    @property
    def app_id(self) -> Optional[str]:
        """Application that performed the activity."""
        return self.properties.get("app_id")

    @property
    def action_id(self) -> Optional[str]:
        """The action ID in Arkitekt/Kabinet."""
        return self.properties.get("action_id")

    @property
    def action_name(self) -> Optional[str]:
        """Human-readable action name."""
        return self.properties.get("action_name")

    @property
    def action_args(self) -> Optional[Dict[str, Any]]:
        """Action arguments as JSON/dict."""
        val = self.properties.get("action_args")
        if val is None:
            return None
        return val if isinstance(val, dict) else None


@dataclass
class RetrievedAssertion(RetrievedActivity):
    """Backward-compatible alias for activity provenance nodes."""

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

    @classmethod
    def from_row(cls, controller: "GraphController", row: Any, graph_name: str = "") -> "RetrievedAssertion":
        """Adapt an `evidence.models.Assertion` row to the node-shaped API surface."""
        return cls(
            controller=controller,
            graph_name=graph_name,
            id=0,
            label=vocab.Assertion,
            row_id=str(row.pk),
            properties={
                "subject": row.subject,
                "app_id": row.app_id,
                "action_name": row.action_name,
                "action_args": row.action_args,
                "__asserted_at": row.asserted_at,
                # Kept for the GraphQL `timestamp` surface, which still speaks ms epoch.
                "timestamp": int(row.asserted_at.timestamp() * 1000),
            },
        )


# ==========================================
# Factory Functions for Creating from AGE Data
# ==========================================


@dataclass
class RetrievedGraphNodesRender:
    """A list of retrieved nodes, with the graph name for context."""

    graph_name: str
    graph_id: int
    graph_query_id: int
    nodes: List[RetrievedNode]


@dataclass
class RetrievedGraphTableRender:
    """A list of retrieved nodes, with the graph name for context."""

    graph_name: str
    graph_id: int
    graph_query_id: int
    rows: List[Dict[str, Any]]


@dataclass
class RetrievedGraphPathRender:
    """A list of retrieved nodes, with the graph name for context."""

    graph_name: str
    graph_id: int
    graph_query_id: int
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
    graph_id: int
    graph_query_id: int
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


