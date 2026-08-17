"""The node- and edge-shaped surface `api/types.py` reads.

One shape per side — `RetrievedNode` and `RetrievedEdge` — whether the thing came
out of an Apache AGE projection or was adapted from an evidence row. That is the
point: a claim no view draws still has to be answerable, so `from_row` /
`from_link` build the same shape `from_node` does and `row_id` says which it was.

**Nothing here is an `Instance`.** These are readings, not claims: they carry a
`label` and a `vertex_id` that belong to one view's drawing, and `unique_id` — the
claim's uuid — is the only field that means anything in every case.
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
#      (`__schema_version`, `__last_derived`, `__measured__*`) and is never user
#      data. Filtering by prefix means new
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


# Type literals for node discrimination. Exactly the five kinds something
# node-shaped can be: the three `evidence.Node.Kind` values a claim can name, plus
# the two Postgres row shapes that are adapted into this surface without ever
# being drawn.
#
# `ACTIVITY`, `ASSERTION`, `REAGENT`, `MEASUREMENT` and `EDIT_EVENT` used to be
# here. Nothing could produce any of them — `Instance.Kind` has three members, and the
# GraphQL union has five — so they were five ways to name a node that cannot exist.
NodeType = Literal[
    "ENTITY",
    "NATURAL_EVENT",
    "PROTOCOL_EVENT",
    "STRUCTURE",
    "METRIC",
]

# `VocabNodeTypeMap` used to sit here, mapping a vertex *label* to one of these.
# It could not work and did not: a drawn vertex is labelled `category.age_name`
# ("Cell", "Mitosis"), which is one view's rename of a word, so it matched none of
# the five fixed vocabulary words and every drawn node fell through to the
# `"ENTITY"` default — `cast_node_to_graphql_type` reported a protocol event as an
# `Entity`. What a thing *is* is a fact about the claim, so it is read from the
# claim: `create_vertex` writes `type` from `Instance.kind`, and the `from_row`
# adapters write it from the row they adapt.


# Type literals for edge discrimination. Exactly the eight `Link.Kind` values,
# uppercased — `from_link` writes `type` as `str(link.kind).upper()` and every
# edge the API builds goes through it, so these are the values `edge_type` can
# actually hold and the eight cases `cast_edge_to_graphql_type` dispatches on.
#
# `PARTICIPANT`, `DESCRIPTION`, `ASSERTION` and `EDITED` used to be here and
# five of the producible kinds were not — the same defect `NodeType` above was
# cleaned of: names for edges that cannot exist, missing the ones that do.
EdgeType = Literal[
    "INFORMS",
    "RELATION",
    "STRUCTURE_RELATION",
    "MEASUREMENT",
    "PARTICIPATES_AS_INPUT",
    "PARTICIPATES_AS_OUTPUT",
    "CLASSIFIES",
    "SAME_AS",
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
    """A node as some view holds it — or as the log has it, when no view does.

    Attributes:
        graph_name: The AGE graph this was read from; empty for a row-backed shape
        vertex_id: The AGE vertex id. Not the identity — see `unique_id`
        label: The vertex label, which is the drawing category's `age_name`
        properties: Raw properties from AGE, including the derived ones
        row_id: The evidence primary key, when this was built from a row
    """

    controller: "GraphController"
    graph_name: str
    #: The Apache AGE vertex id, and **not the identity** — it is reassigned every
    #: time a graph is dropped and replayed. `unique_id` is the identity. Named for
    #: what it is because `id` invited exactly the confusion the name now prevents:
    #: three different things were called a node's id, and only one of them is
    #: stable. Zero for a row-backed shape, which has no vertex.
    vertex_id: int
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
        """Global unique identifier — a bare uuid.

        For a projected node this is the uuid carried on the vertex as its `id`
        property, which is the same uuid its `Instance` row is keyed on. For an
        evidence row it is the primary key. Both are world-unique, so neither
        needs qualifying by a graph.

        It used to be `{graph_name}:{id}`, where `id` was the **Apache AGE vertex
        id**. Two things were wrong with that. The vertex id is reassigned every
        time a graph is dropped and replayed, so the identity a client held
        stopped meaning anything after a reproject. And the graph name asserted
        that a node belongs to one view, when a view is only a reconstruction —
        and one vertex may stand for several nodes once merging exists.

        There is no composite fallback any more. It used to return
        `{graph_name}:{vertex_id}` for a shape read straight out of Cypher without
        an `id` property, on the grounds that *something* addressable beats
        raising — but an id that cannot be handed back to the fetcher that issued
        it is not addressable, it only looks it. `create_vertex` writes `id` on
        every vertex it draws, so a node without one did not come from this
        projector and has no identity to invent.
        """
        if self.row_id is not None:
            return self.row_id
        node_uuid = self.properties.get("id")
        if node_uuid is None:
            raise ValueError(f"Node {self.label!r} in graph {self.graph_name!r} carries no 'id' property, so it has no durable identity. Every vertex `projector.create_vertex` draws has one.")
        return str(node_uuid)

    # `lifecycle` and `lifecycle_status` are gone, and there is nothing left to
    # replace them with — which is the point.
    #
    # **If it is in the graph, it is.** A vertex read out of a projection could
    # only ever report "active", because the graph holds what the evidence says
    # exists; a flag beside it could not disagree with its own presence. And a
    # node with no vertex was reporting "retracted" from the claims, which made
    # the field mean two different things depending on which branch built it.
    #
    # The honest form of the question is now the shape of the answer: a write
    # returns `drawings`, and a claim stands exactly where a view draws it. Empty
    # means no view does — a count, not a flag, and one that says *where* rather
    # than pretending there is a single global answer. Two annotators may
    # disagree about whether a thing exists, and each graph's selector decides
    # whose word it counts, so a single "lifecycle" was never expressible.

    # `global_id`, `local_id` and `graph_id` are gone, with the GraphQL fields that
    # read them. `global_id` required a `global_id` vertex property that **nothing
    # ever wrote** — `create_vertex` writes `{id, category_id}` — so it raised for
    # every node read out of a projection and worked only on the row-backed
    # branch. `local_id` and `graph_id` returned the Apache AGE vertex id, which
    # is reassigned by every reproject. `unique_id` is the identity.

    @classmethod
    def from_row(cls: Type[T], controller: "GraphController", row: Any, graph_name: str = "") -> T:
        """Adapt an `evidence.models.Node` row to the node-shaped API surface.

        The claim as **the log has it**, with no view's opinion mixed in. It
        cannot come from Apache AGE: this is what a write returns before anything
        is drawn, and what a retraction returns after the vertex is gone. The
        same move `RetrievedStructure.from_row` and `RetrievedEdge.from_link`
        already make.

        **It borrows no category, and that is the point.** This used to do
        `Category.objects.filter(term_id=row.term_id).first()` — unordered, and
        against *every* graph rather than one that had drawn the node — so the
        label and `category_id` on a node in no projection came from a view that
        had refused it or never seen it, and two identical writes could disagree.
        A category is one view's rule for a word; a row in no view has none. The
        label is therefore the **word itself**, which is the only name that is
        true independently of any graph.

        Every real category now reaches the caller through
        `controller.drawings_for_instance`, where it arrives attached to the graph
        that actually drew it. See `docs/rfcs/0003-undrawn-nodes.md`.

        No lifecycle property, on this or on any other shape. The graph holds what
        the evidence says exists, so a vertex that is there is one that stands and
        a flag beside it could only ever contradict it — and a row with no vertex
        does not need one either, because `drawings` already says which views draw
        the claim and empty already says none do.
        """
        return cls(
            controller=controller,
            graph_name=graph_name,
            vertex_id=0,
            label=str(row.term.key),
            row_id=str(row.pk),
            properties={
                "id": str(row.pk),
                "category_id": None,
                # From the row's own kind, so `node_type` discriminates correctly
                # without a category to read a label off. Without this, dispatch
                # falls back to `VocabNodeTypeMap.get(self.label, "ENTITY")` — and
                # the label here is the *word* ("AIS", "Mitosis"), which is in no
                # such map, so **every** row-backed event was reported as an
                # entity by `cast_node_to_graphql_type`.
                "type": str(row.kind).upper(),
            },
        )

    @property
    def durable_ref(self) -> str:
        """The identity evidence uses to refer to this node — the same uuid.

        Kept as a distinct name from :attr:`unique_id` because the two answer
        different questions ("what do I call this to a client" and "what does the
        log key on"), and it is worth being able to see at a call site which one
        is meant. They happen to coincide now that identity is a bare uuid, which
        is the point: there is one identity, not a projection-facing one and an
        evidence-facing one that have to be translated between.
        """
        return self.unique_id

    # === Type Discrimination ===

    @property
    def category_id(self) -> Optional[str]:
        """This node's category in the view it was read through, if there is one.

        `None` is an ordinary answer, and used to raise. A node names a *word*, and
        a category is one view's rule for that word — so a node claimed under a
        word no view declares has no category, and since writes name terms that is
        a state a client can reach with one mutation. Raising here turned a
        perfectly recorded claim into an error on read.
        """
        return self.properties.get("category_id")

    @property
    def node_type(self) -> NodeType:
        """What kind of thing this is, for GraphQL discrimination.

        The `type` property and nothing else. There is no label fallback: a
        vertex's label is `category.age_name`, one view's rename of a word, and
        matching it against a fixed vocabulary is how every drawn event came back
        as an `Entity`.

        Every shape that reaches this reads it off the claim — `create_vertex` from
        `Instance.kind`, `RetrievedNode.from_row` from the same column, the structure
        and metric adapters from the row they adapt. So a missing `type` means the
        vertex was drawn by an older projector, and the answer is to redraw it
        rather than to guess: `manage.py reproject`.
        """
        node_type = self.properties.get("type")
        if node_type is None:
            raise ValueError(f"Node {self.label!r} in graph {self.graph_name!r} carries no 'type' property, so nothing says what kind of thing it is. Every vertex `projector.create_vertex` draws has one — run `manage.py reproject` to redraw one that does not.")
        return node_type

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
        """Hashed on the graph and the vertex it was read from"""
        return hash((self.graph_name, self.vertex_id))

    def __eq__(self, other: Any) -> bool:
        """Equality on the graph and the vertex it was read from"""
        if not isinstance(other, RetrievedNode):
            return False
        return self.graph_name == other.graph_name and self.vertex_id == other.vertex_id

    @classmethod
    def from_node(cls: Type[T], controller: "GraphController", node: Dict[str, Any], graph_name: str = "default_graph") -> T:
        """Factory method to create a RetrievedNode from raw AGE node data."""
        return cls(
            controller=controller,
            graph_name=graph_name,
            vertex_id=node.get("id", 0),
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
    #: The Apache AGE edge id, reassigned by every reproject — see
    #: `RetrievedNode.vertex_id`. `unique_id` is the identity.
    edge_id: int
    label: str
    left_id: int
    right_id: int
    properties: Dict[str, Any] = field(default_factory=dict)

    #: Set when this edge came from an `evidence.Link` row. Mirrors
    #: `RetrievedNode.row_id`: an edge is a claim first and a projection second,
    #: and structure relations and measurements are *only* claims — neither has
    #: an AGE edge to carry a vertex id, because structures stopped being
    #: vertices in M1.
    row_id: Optional[str] = None
    #: The endpoints as evidence names them. Durable across a rebuild, unlike
    #: `left_id`/`right_id`, which are AGE vertex ids reassigned on every replay.
    source_ref: Optional[str] = None
    target_ref: Optional[str] = None
    created_at: Optional[datetime] = None
    #: Which role the source plays, for participation edges. `InputParticipation`
    #: and `OutputParticipation` both read it and neither could have worked —
    #: `RetrievedEdge` had no such attribute, which went unnoticed because
    #: nothing ever built one of those types.
    role: Optional[str] = None
    #: Who claimed this, as an id rather than a row. An edge read out of Apache
    #: AGE has no assertion at all — the projection does not carry provenance —
    #: so this is None there and the API reports null. An id and not the object
    #: because resolving it eagerly would be a query per edge on every listing,
    #: and a synchronous one inside an async resolver; `api/loaders.py` batches it.
    assertion_id: Optional[str] = None

    # === Core ID Properties ===

    @property
    def is_row_backed(self) -> bool:
        """Whether this edge came from the evidence tables rather than from AGE."""
        return self.row_id is not None

    @property
    def unique_id(self) -> str:
        """Global unique identifier.

        The bare `Link` primary key — where an edge's identity actually lives. The
        Apache AGE edge is a projection of the claim and its id does not survive a
        `reproject`.

        Every edge the API builds is row-backed now: the plural queries read
        `evidence.Link` (`api/queries/_edges.py`) rather than Cypher, so the
        `{graph_name}:{age_edge_id}` fallback that used to live here has no
        remaining producer — and it was the reason the ids those queries returned
        could not be fed back to the singular fetchers.
        """
        if self.row_id is None:
            raise ValueError(f"Edge {self.label!r} in graph {self.graph_name!r} has no claim behind it, so it has no identity. Edges are read from `evidence.Link`; see `api/queries/_edges.py`.")
        return self.row_id

    @classmethod
    def from_link(
        cls,
        controller: "GraphController",
        link: Any,
        graph_name: str = "",
        category: Any = None,
    ) -> "RetrievedEdge":
        """Adapt an `evidence.models.Link` row to the edge-shaped API surface.

        The same move `RetrievedStructure.from_row` makes for nodes, for the same
        reason: it keeps `api/types.py` reading one shape whether the edge has a
        projection behind it or not.
        """
        return cls(
            graph_name=graph_name,
            # No AGE edge for structure relations and measurements, and for a
            # relation the caller fills this in from the projection if it wants
            # to traverse. Identity is `row_id` either way.
            edge_id=0,
            label=category.age_name if category is not None else str(link.kind),
            left_id=0,
            right_id=0,
            row_id=str(link.pk),
            source_ref=str(link.source_ref),
            target_ref=str(link.target_ref),
            created_at=link.created_at,
            role=link.role,
            assertion_id=str(link.assertion_id),
            properties={
                # What kind of claim this is, from the row rather than from the
                # label. The label is the *category's* `age_name`, and for a
                # participation the category is the **event's** — so a
                # participation edge is labelled "Mitosis", which no dispatch
                # could ever read as a participation. Without this,
                # `cast_edge_to_graphql_type` fell through its label heuristic and
                # typed every participation as a `Relation`; the old
                # `_as_participation` helper had the same defect from the other
                # side, comparing `label` against a `Link.Kind` and so always
                # answering `InputParticipation`.
                "type": str(link.kind).upper(),
                # A `Category` pk, not the link's term. `api/types.py` resolves
                # this through the per-graph category loaders, and the AGE edge
                # carries the same thing in the same slot — so the two ways of
                # building an edge agree. The link itself names only the word;
                # which category draws it is the caller's graph to know, which is
                # why it is passed in rather than read off the row.
                "category_id": str(category.pk) if category is not None else None,
                # From the projection, not from a column on the link. `Link` no
                # longer carries its own answer — that boolean was an `UPDATE` on
                # a log table, which is what stopped the log from being immutable.
            },
        )

    # `global_id` and `graph_id` are gone with the GraphQL fields that read them:
    # one aliased `unique_id`, the other returned the Apache AGE edge id, which is
    # reassigned by every reproject.

    @property
    def unique_left_id(self) -> str:
        """The source endpoint, as evidence names it — a bare uuid.

        No `{graph_name}:{vertex_id}` fallback. It fired for every edge built from
        Cypher, naming a vertex id that a reproject reassigns; nothing builds an
        edge that way now.
        """
        if self.source_ref is None:
            raise ValueError("This edge has no recorded source endpoint")
        return self.source_ref

    @property
    def unique_right_id(self) -> str:
        """The target endpoint, as evidence names it. See :attr:`unique_left_id`."""
        if self.target_ref is None:
            raise ValueError("This edge has no recorded target endpoint")
        return self.target_ref

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
        """This edge's category in the view it was read through, if there is one.

        `None` is an ordinary answer, for the reason `RetrievedNode.category_id`
        gives: the claim names a word, and a view may have no rule for that word.
        Structure relations and measurements have no projection at all, so they
        reach this through `from_link` with whatever `_category_for_term` found.
        """
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

    # The "Assertion Properties" accessor block (`subject`, `app_id`,
    # `action_name`) used to sit here, guarded by a comment saying "when
    # edge_type == 'ASSERTION'" — an edge type nothing can produce. An assertion
    # is the `evidence.Assertion` row, reachable through `assertion_id` below.

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

    # === Hash/Equality ===

    def __hash__(self) -> int:
        """Hashed on the graph and the edge it was read from"""
        return hash((self.graph_name, self.edge_id))

    def __eq__(self, other: Any) -> bool:
        """Equality on the graph and the edge it was read from"""
        if not isinstance(other, RetrievedEdge):
            return False
        return self.graph_name == other.graph_name and self.edge_id == other.edge_id


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


# `RetrievedEntity` used to sit here, a `RetrievedNode` subclass adding one property:
# `entity_id`, which returned `properties["id"]` — the same value `unique_id` returns,
# under a name that says "entity" about a class also constructed for events. It
# carried no other behaviour, so the two names were a distinction without one. Every
# caller takes `RetrievedNode`.
#
# There was never a `schema_hash` accessor either, deliberately: the projection layer
# writes `__schema_version`, so use the inherited `schema_version`.


@dataclass
class RetrievedStructure(RetrievedNode):
    """A structure, read from the relational evidence base.

    Structures stopped being AGE vertices in M1. This stays a `RetrievedNode`
    rather than becoming a strawberry-django type so that `api/types.py` keeps
    working untouched — rewriting that layer is M5's job, and doing it here would
    mean doing it twice.
    """

    @classmethod
    def from_row(cls, controller: "GraphController", row: Any, graph_name: str = "", stands: Optional[bool] = None) -> "RetrievedStructure":
        """Adapt an `evidence.models.Structure` row to the node-shaped API surface.

        ``stands`` is passed in rather than looked up. It used to be read off a
        `Structure.stands` column; that column is gone, and resolving it here
        instead would be a query per row — an N+1 on every structure listing, and
        one that breaks callers in an async context, since `supporting_evidence`
        converts rows outside its `sync_to_async` block.

        ``stands`` is accepted and ignored. It fed a lifecycle property that
        nothing read even before lifecycle was removed — `Structure` is a
        plain `Node` in the GraphQL schema, never a `VersionedNode`, so it never
        exposed the field. The parameter stays so the call sites that pass it keep
        working; whether a structure still stands is a claims question, answered
        by `evidence.claims`.
        """
        properties: Dict[str, Any] = {
            "identifier": row.identifier,
            "object": row.object,
            "category_id": str(row.kind_id),
            # Stated, not inferred from the label. `node_type` has no label
            # fallback any more — see its docstring.
            "type": "STRUCTURE",
        }
        return cls(
            controller=controller,
            graph_name=graph_name,
            vertex_id=0,
            label=vocab.Structure,
            row_id=str(row.pk),
            properties=properties,
        )


@dataclass
class RetrievedEvent(RetrievedNode):
    """A retrieved Event node from the AGE graph."""

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
    def from_row(cls, controller: "GraphController", row: Any, graph_name: str = "", stands: Optional[bool] = None) -> "RetrievedMetric":
        """Adapt an `evidence.models.Metric` row to the node-shaped API surface.

        ``stands`` is accepted and ignored, for the same reason it is on
        `RetrievedStructure.from_row`.
        """
        properties: Dict[str, Any] = {
            "key": row.key,
            "value": row.value,
            "category_id": str(row.kind_id),
            # Stated, not inferred from the label — see `node_type`.
            "type": "METRIC",
            "__measured_at": row.measured_at,
            "__asserted_at": row.asserted_at,
            # Who measured this. The row was dropped here entirely, so a metric
            # could report *when* it was claimed and never *by whom* — and the
            # assertion is the whole provenance half of the evidence model. An id
            # rather than the row, for the reason `RetrievedEdge.assertion_id`
            # gives: eager resolution is a query per metric on every listing.
            "__assertion_id": str(row.assertion_id),
        }
        for optional_key in ("unit", "confidence", "confidence_type"):
            value = getattr(row, optional_key, None)
            if value is not None:
                properties[optional_key] = value

        return cls(
            controller=controller,
            graph_name=graph_name,
            vertex_id=0,
            label=vocab.Metric,
            row_id=str(row.pk),
            properties=properties,
        )


# `RetrievedActivity` and `RetrievedAssertion` used to be here. They adapted an
# `Assertion` row into the node-shaped surface for the `Activity` GraphQL type,
# which read a vertex the projector has never written — so the type and its two
# queries always came back empty. `Assertion` is served as the Django row now
# (`api/types.py`), which is what makes `seq`, the log's total order, reachable
# at all.


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
