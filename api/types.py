"""
GraphQL Types for the API.

These types represent the output/response types for graph entities,
structures, measurements, and related objects.

This module follows the pattern from core/types.py where:
1. Strawberry types use `strawberry.Private` to hold underlying data
2. Type matching functions convert retrieved data to appropriate subtypes
3. Fields access the private _value for their data
"""

import uuid

import strawberry
from asgiref.sync import sync_to_async
from typing import Annotated, Any, Generic, Optional, List, Type, TypeVar, Union, cast
from datetime import datetime
from api import loaders, order, pagination, filters
from datalayer.types import MediaStore
from graph_engine.scalars import AnyScalar, UnixMilliseconds, StructureIdentifier
from graph_engine.retrieved import RetrievedMetric, RetrievedNode, RetrievedEdge, RetrievedStructure, _as_datetime
from api.context import get_active_organization, get_controller
from django.db.models import Q
from graph_engine import input_models
import kante
from core import models
from evidence import claims as claims_module
from evidence import models as evidence_models
from graph_engine import results, retrieved, scalars
from api import filters
from core import enums
from stats.gen import create_stats_type


# ===========================================
# Kind dispatch
# ===========================================
# Categories, saved queries, materialized edges and datalayer stores each live in one
# table with a `kind` column, so several GraphQL types share a Django model. Two things
# follow from that, and both are what these helpers install.
#
# `is_type_of` is how an interface-typed field decides which object type a row is.
# strawberry-django's default implementation is `isinstance(obj, (cls, model))`, which
# was only ever meaningful while django-polymorphic downcast rows on the way out; with
# one shared model it would match every type against every row. `strawberry_django.type`
# only installs its default when the class does not define one, so setting it here wins.
#
# `get_queryset` is how a field typed as one concrete kind avoids returning the others.
# strawberry-django applies it on root fields, nested prefetches and pk lookups alike.


#: How each declaratively-served model reaches the organization that owns it.
#: The same lookups `stats/gen.py` already passes as its `scope` callable — that
#: module requires one, and says why, which is what made the absence here visible.
_ORG_PATH: dict[str, str] = {
    "Graph": "organization",
    "Category": "graph__organization",
    "GraphQuery": "graph__organization",
    "NodeQuery": "graph__organization",
    "EdgeQuery": "graph__organization",
}


def _organization_filter(model) -> str | None:
    """The lookup that scopes this model to a tenant, or None if it has no direct one.

    Keyed on the **concrete** model. `EntityCategory`, `GraphTableQuery` and the
    rest are Django proxies over `Category` / `GraphQuery` / `NodeQuery` /
    `EdgeQuery`, so `model.__name__` on a proxy queryset is the proxy's name and
    would miss the table above. Every `kind_type` in this module happens to
    register against the concrete model today — so `__name__` alone worked — but
    that is a coincidence of the registration, not a property of the lookup, and a
    fence that silently returns `None` fails open.
    """
    return _ORG_PATH.get(model._meta.concrete_model.__name__)


def org_scoped(cls):
    """Fence a declaratively-served type to the request's organization.

    **The read side had no tenant fence at all.** The write side closes this
    deliberately (`api/mutations/_scoped.py`), and `api/queries/kinds.py` says the
    problem out loud for the two vocabularies it resolves by hand: "their only
    tenant fence was the client happening to pass `CategoryFilter.graph`… so
    scoping has to happen here or not at all". It was done for kinds and nowhere
    else — `graphs`, the six category families, the twelve saved-query families
    and `scatterPlots` are bare `kante.django_field`s with no resolver, over
    managers that do not scope (`core/managers.py::GraphManager` is a plain
    `models.Manager`). Neither `authentikate`'s schema extension nor `kante`
    filters querysets; the extension resolves the organization onto the request
    and stops there.

    strawberry-django applies `get_queryset` to root fields, nested prefetches and
    pk lookups alike, so this covers `graph(id:)` as well as `graphs`.
    """

    previous = getattr(cls, "get_queryset", None)

    def get_queryset(cls_, queryset, info, **kwargs):
        if previous is not None:
            queryset = previous(queryset, info, **kwargs)
        lookup = _organization_filter(queryset.model)
        if lookup is None:
            return queryset
        return queryset.filter(**{lookup: get_active_organization(info)})

    cls.get_queryset = classmethod(get_queryset)
    return cls


def _kind_dispatch(cls, kinds: tuple[str, ...]):
    """Teach a GraphQL type which `kind` values of its shared table belong to it."""

    def is_type_of(obj, info, _kinds=kinds) -> bool:
        return getattr(obj, "kind", None) in _kinds

    def get_queryset(cls_, queryset, info, _kinds=kinds, **kwargs):
        # Kind *and* tenant. This filtered on kind alone, which meant the two
        # `get_queryset` overrides in this module — the only two — narrowed a
        # shared table to one category type and handed back every organization's
        # rows of it.
        queryset = queryset.filter(kind__in=_kinds)
        lookup = _organization_filter(queryset.model)
        if lookup is None:
            return queryset
        return queryset.filter(**{lookup: get_active_organization(info)})

    cls.is_type_of = staticmethod(is_type_of)
    cls.get_queryset = classmethod(get_queryset)
    return cls


def kind_type(model, kinds, **kwargs):
    """A `django_type` over a shared table, dispatching on `kind`.

    `only=["kind"]` matters: without it the optimizer defers the column and every row
    costs one extra query when `is_type_of` reads it.
    """

    kinds = kinds if isinstance(kinds, tuple) else (kinds,)

    def wrapper(cls):
        return kante.django_type(model, only=["kind"], **kwargs)(_kind_dispatch(cls, kinds))

    return wrapper


def kind_interface(model, kinds, **kwargs):
    """A `django_interface` scoped to a subset of its table's kinds."""

    kinds = kinds if isinstance(kinds, tuple) else (kinds,)

    def wrapper(cls):
        def get_queryset(cls_, queryset, info, _kinds=kinds, **kw):
            queryset = queryset.filter(kind__in=_kinds)
            lookup = _organization_filter(queryset.model)
            if lookup is None:
                return queryset
            return queryset.filter(**{lookup: get_active_organization(info)})

        cls.get_queryset = classmethod(get_queryset)
        return kante.django_interface(model, **kwargs)(cls)

    return wrapper


# ===========================================
# Schema Types
# ===========================================
@kante.pydantic_type(input_models.OntologyReferenceInput, description="An ontology reference in the graph schema")
class OntologyReference:
    """An ontology reference in the graph schema."""

    prefix: str = strawberry.field(description="The ontology prefix (e.g., 'GO', 'CL')")
    term_id: str = strawberry.field(description="The ontology term ID (e.g., '0008150')")


@kante.pydantic_type(input_models.DerivationRuleInput, all_fields=True, description="A derivation rule in the graph schema")
class DerivationRule:
    """A derivation rule in the graph schema, which defines how to derive new entities or relations based on existing ones."""


@kante.pydantic_type(input_models.PropertyDefinitionInput, all_fields=True, description="A property definition from the graph schema")
class PropertyDefinition:
    """A property definition from the graph schema."""


@kante.pydantic_type(input_models.EntityDescriptorInput, all_fields=True, description="Input type for creating a new graph query")
class EntityDescriptor:
    """Descriptor for an entity, used as input for creating new graph queries."""

    keys: Optional[List[str]] = kante.field(default=None, description="Filter by entity key/label")
    ontology_terms: Optional[List[str]] = kante.field(default=None, description="Filter by ontology references on the entity (format: 'PREFIX:TERM_ID')")
    default_category_key: Optional[str] = kante.field(default=None, description="Default category to use for this entity if we aim to create a new one based on this descriptor")


@kante.pydantic_type(input_models.StructureDescriptorInput, description="Input type for creating a new graph query")
class StructureDescriptor:
    """Descriptor for a structure, used as input for creating new graph queries."""

    keys: Optional[List[str]] = kante.field(default=None, description="REMOVED — a structure kind has no key. Always null.")
    tags: Optional[List[str]] = kante.field(default=None, description="REMOVED — tags are gone, and a structure kind never had them. Always null.")
    ontology_terms: Optional[List[str]] = kante.field(default=None, description="Filter by ontology references on the structure (format: 'PREFIX:TERM_ID')")
    default_category_key: Optional[str] = kante.field(default=None, description="Default category to use for this structure if we aim to create a new one based on this descriptor")


@kante.pydantic_type(input_models.ColumnInput, all_fields=True, description="Input type for defining a graph schema")
class Column:
    """A column definition for a graph schema."""


@kante.pydantic_type(input_models.WhereClauseInput, all_fields=True, description="Input type for defining a graph schema")
class WhereClause:
    """A column definition for a graph schema."""


@kante.pydantic_type(input_models.MatchPathInput, all_fields=True, description="Input type for creating a new graph")
class MatchPath:
    """A path definition for matching patterns in the graph."""


@kante.pydantic_type(input_models.ReturnStatementInput, all_fields=True, description="Input type for creating a new graph")
class ReturnStatement:
    """A return statement definition for a table query."""


@kante.pydantic_type(input_models.BuilderArgsInput, all_fields=True, description="Input type for creating a new graph query")
class BuilderArgs:
    """Arguments for building a graph query."""


@kante.pydantic_type(input_models.EventRoleInput, all_fields=True, description="Input type for defining roles in an event category")
class EventRole:
    """Definition of a role in an event category."""


def _event_roles(stored: Any) -> List[EventRole]:
    """Read declared event roles out of the JSON column that holds them.

    `source_entity_roles` / `target_entity_roles` are hand-written JSON on the
    category, so a row predating a field, or written by an older client, may be
    missing keys `EventRoleInput` requires. Skipping a malformed entry is better
    than failing the whole query: the point of the field is to report what the
    schema declares, and one bad role should not hide the good ones.
    """
    roles: List[EventRole] = []
    for entry in stored or []:
        try:
            roles.append(EventRole.from_pydantic(input_models.EventRoleInput(**entry)))
        except Exception:  # noqa: BLE001 - see docstring
            continue
    return roles


@org_scoped
@kante.django_type(models.Graph, filters=filters.GraphFilter, pagination=True, ordering=order.GraphOrder, description="One view over the organization's evidence log")
class Graph:
    id: strawberry.ID = strawberry.field(description="Database ID of the graph")
    age_name: str = strawberry.field(description="The name of the graph as used in AGE (e.g. 'CellGraph')")
    # No `graphId`. It was copy-pasted from `Category`, and a `Graph` has no
    # `graph` foreign key to back it — the field named a column that does not
    # exist. A graph cannot belong to a graph.
    label: str = strawberry.field(description="Label/name of the graph")
    description: Optional[str] = strawberry.field(default=None, description="Description of the graph")
    purl: Optional[str] = strawberry.field(default=None, description="Persistent URL for this graph")
    color: Optional[List[int]] = strawberry.field(default=None, description="Color as RGBA list (0-255)")
    name: str = strawberry.field(description="Name of the graph")
    image: MediaStore | None = strawberry.field(description="An image representing this graph, for visualization purposes")
    # Readable, because a flag a client can write and never observe is how
    # `archiveGraph` managed to do nothing for as long as it did.
    is_archived: bool = strawberry.field(description="Whether this graph has been archived. Archiving is the reversible alternative to deleting it — a delete destroys every rule for reading the evidence, which survives without them")

    # Schemas
    node_categories: List["NodeCategory"] = strawberry.field(default_factory=list, description="List of node categories defined in this graph")
    edge_categories: List["EdgeCategory"] = strawberry.field(default_factory=list, description="List of edge categories defined in this graph")

    measurement_categories: List["MeasurementCategory"] = strawberry.field(default_factory=list, description="List of measurement categories defined in this graph")
    entity_categories: List["EntityCategory"] = strawberry.field(default_factory=list, description="List of entity categories defined in this graph")
    protocol_event_categories: List["ProtocolEventCategory"] = strawberry.field(default_factory=list, description="List of protocol event categories defined in this graph")
    natural_event_categories: List["NaturalEventCategory"] = strawberry.field(default_factory=list, description="List of natural event categories defined in this graph")
    relation_categories: List["RelationCategory"] = strawberry.field(default_factory=list, description="List of relation categories defined in this graph")
    structure_relation_categories: List["StructureRelationCategory"] = strawberry.field(default_factory=list, description="List of structure relation categories defined in this graph")

    # Queries
    queries: List["GraphQuery"] = strawberry.field(default_factory=list, description="List of graph queries defined in this graph")

    @kante.django_field(description="Whether the requesting user has pinned this graph for quick access")
    def pinned(self, info: kante.Info) -> bool:
        """Whether this graph is pinned for quick access in the UI."""
        # In a real implementation, we would check the user's preferences or a pinned categories list.
        # For this example, we'll return False for simplicity.
        return cast(models.Graph, self).pinned_by.filter(id=info.context.request.user.id).exists()


@kante.django_interface(models.Category, description="Base interface for structure categories")
class Category:
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    label: str = strawberry.field(description="Label/name of the category")
    key: str = strawberry.field(description="The unique key/identifier for this category, used for linking to entities or structures (e.g. 'Cell', 'ROI')")
    description: Optional[str] = strawberry.field(default=None, description="Description of the category")
    age_name: str = strawberry.field(description="The name of the category as used in AGE (e.g. 'Cell', 'ROI')")
    purl: Optional[str] = strawberry.field(default=None, description="Persistent URL for this category")
    color: Optional[List[int]] = strawberry.field(default=None, description="Color as RGBA list (0-255)")
    image: MediaStore | None = strawberry.field(description="An image representing this category, for visualization purposes")
    graph: Graph = strawberry.field(description="The graph this category belongs to")
    term: Optional["Term"] = kante.django_field(description="The organization's word this category declares. Claims name the term, not this row — so a category is what the word means *here*, and another graph declaring the same word sees the same claims.")

    @kante.django_field(description="List of relevant queries that use this category as input")
    def relevant_queries(self) -> List["GraphQuery"]:
        """`Category.relevant_queries` is a method on the model, so it needs a resolver."""
        return list(cast(models.Category, self).relevant_queries())

    @kante.django_field(description="Whether the requesting user has pinned this graph for quick access")
    def pinned(self, info: kante.Info) -> bool:
        """Whether this graph is pinned for quick access in the UI."""
        # In a real implementation, we would check the user's preferences or a pinned categories list.
        # For this example, we'll return False for simplicity.
        return cast(models.Category, self).pinned_by.filter(id=info.context.request.user.id).exists()


@kind_interface(models.Category, enums.EDGE_CATEGORY_KINDS, description="Base interface for graph schemas")
class EdgeCategory:
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    graph_id: strawberry.ID = strawberry.field(description="ID of the graph this category belongs to")
    label: str = strawberry.field(description="Label/name of the category")

    description: Optional[str] = strawberry.field(default=None, description="Description of the category")
    purl: Optional[str] = strawberry.field(default=None, description="Persistent URL for this category")
    color: Optional[List[int]] = strawberry.field(default=None, description="Color as RGBA list (0-255)")
    relevant_edge_queries: List["EdgeQuery"] = strawberry.field(default_factory=list, description="List of relevant queries that use this category as input")

    # `materializableAs` used to sit here, returning `[]` unconditionally under a
    # comment admitting it. The `MaterializedEdge` rows it would have read are
    # gone — see RFC 0001 §6 — and the question it named ("which category pairs may
    # this edge category connect?") is answered by evaluating `source_definition` /
    # `target_definition`, which is what `get_matching_source_entities` already does.


@kind_interface(models.Category, enums.NODE_CATEGORY_KINDS, description="Base interface for graph schemas")
class NodeCategory:
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    label: str = strawberry.field(description="Label/name of the category")
    graph_id: strawberry.ID = strawberry.field(description="ID of the graph this category belongs to")
    description: Optional[str] = strawberry.field(default=None, description="Description of the category")
    purl: Optional[str] = strawberry.field(default=None, description="Persistent URL for this category")
    color: Optional[List[int]] = strawberry.field(default=None, description="Color as RGBA list (0-255)")
    position_x: float | None = strawberry.field(description="X coordinate")
    position_y: float | None = strawberry.field(description="Y coordinate")
    position_z: Optional[float] = strawberry.field(default=None, description="Z coordinate (optional)")
    width: Optional[float] = strawberry.field(default=None, description="Width for visualization (optional)")
    height: Optional[float] = strawberry.field(default=None, description="Height for visualization (optional)")
    relevant_node_queries: List["NodeQuery"] = strawberry.field(default_factory=list, description="List of relevant node queries that use this category as input")


@kante.interface(description="Base interface for plottable queries")
class Plottable:
    columns: List[Column] = strawberry.field(description="List of columns to return in the table query result")

    @kante.django_field(description="The graph this category belongs to")
    def scatter_plots(self) -> List["ScatterPlot"]:
        """Return a list of table queries that can be visualized as scatterplots."""
        # In a real implementation, we would check if this query is used in any GraphTableQuery with a scatterplot visualization,
        # and if so, return those queries.
        # For this example, we'll return an empty list for simplicity.
        return []


@org_scoped
@kante.django_interface(models.GraphQuery, description="Base interface for entity categories")
class GraphQuery:
    id: strawberry.ID = strawberry.field(description="Database ID of this saved query")
    graph: "Graph" = strawberry.field(description="The graph this query belongs to")
    key: str = strawberry.field(description="The key this query is referenced and pinned by, unique within its graph")
    label: str = strawberry.field(description="Human-readable name for this query")
    description: Optional[str] = strawberry.field(default=None, description="Description of this query")
    query: scalars.CypherLiteral = strawberry.field(description="The Cypher this query runs")
    relevant_for: List["NodeCategory"] = strawberry.field(default_factory=list, description="List of node categories for which this query is relevant")
    # Same reason as `Graph.is_archived`: nine `archive_*_query` mutations wrote
    # this flag and no type ever showed it back.
    archived: bool = strawberry.field(description="Whether this saved query has been archived")


@kind_type(models.GraphQuery, enums.GraphQueryKindChoices.NODES, filters=filters.GraphNodesQueryFilter, pagination=True, ordering=order.GraphNodesQueryOrder, description="Base interface for graph schemas")
class GraphNodesQuery(GraphQuery):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    node_category: "NodeCategory" = strawberry.field(description="The node category to query")


@kind_type(models.GraphQuery, enums.GraphQueryKindChoices.TABLE, filters=filters.GraphTableQueryFilter, pagination=True, ordering=order.GraphTableQueryOrder, description="Base interface for graph schemas")
class GraphTableQuery(GraphQuery, Plottable):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    query: scalars.CypherLiteral = strawberry.field(description="The Cypher query to execute for this table query")
    columns: List[Column] = strawberry.field(description="List of columns to return in the table query result")
    builder_args: Optional[BuilderArgs] = strawberry.field(default=None, description="If this graph was built using a builder function, the arguments used for building it, which can be used for debugging or rebuilding the graph with different parameters")


@kind_type(models.GraphQuery, enums.GraphQueryKindChoices.PAIRS, filters=filters.GraphPairsQueryFilter, pagination=True, ordering=order.GraphPairsQueryOrder, description="Base interface for graph schemas")
class GraphPairsQuery(GraphQuery):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    source_category: "NodeCategory" = kante.django_field(field_name="left_category", description="The source node category to query")
    target_category: "NodeCategory" = kante.django_field(field_name="right_category", description="The target node category to query")

    # `edgeCategory` used to sit here returning `None` unconditionally, with a
    # docstring conceding that pairs queries have never stored one and the field
    # has no column behind it.


@kind_type(models.GraphQuery, enums.GraphQueryKindChoices.PATH, filters=filters.GraphPathQueryFilter, pagination=True, ordering=order.GraphPathQueryOrder, description="Base interface for graph schemas")
class GraphPathQuery(GraphQuery):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    source_category: Optional["NodeCategory"] = kante.django_field(field_name="left_category", description="The node category this path starts from")
    target_category: Optional["NodeCategory"] = kante.django_field(field_name="right_category", description="The node category this path ends at")


@kind_type(models.Category, enums.CategoryKindChoices.ENTITY, filters=filters.EntityCategoryFilter, pagination=True, ordering=order.EntityCategoryOrder, description="An entity category definition")
class EntityCategory(NodeCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    graph: "Graph" = strawberry.field(description="The graph this category belongs to")
    label: str = strawberry.field(description="Label/name of the category")
    instance_kind: strawberry.auto = strawberry.field(description="What type of instance, (taking from the universe) 'LOT', 'BIOLOGICAL', 'PHYSICAL'")

    @kante.django_field(description="The entities this category draws, read from the evidence log")
    def entities(self, filters: filters.EntityFilter | None = None, ordering: list[order.EntityOrder] | None = None, pagination: pagination.EntityPaginationInput | None = None) -> List["Entity"]:
        """Every entity this category draws — the same answer `entities(entityCategoryId:)` gives.

        Through `_nodes`, so the field and the root query cannot disagree about what
        the category contains. It used to call `list_entities_for_category`, which
        matched vertices by label: an entity the rule admits but the projection has
        not drawn was missing here and present in a rebuild.
        """
        from api.queries import _nodes

        category = cast(models.EntityCategory, cast(models.Category, self).as_kind())

        controller = get_controller()
        ordering_models = [entry.to_pydantic() for entry in ordering] if ordering else []
        pagination_model = pagination.to_pydantic() if pagination else None
        filter_model = filters.to_pydantic() if filters else None

        rows = _nodes.narrow(_nodes.rows_for_category(category), filter_model, ordering_models, pagination_model)

        return [Entity(_value=node) for node in _nodes.retrieved_in(controller, category.graph, rows)]

    @kante.django_field(description="The graph this category belongs to")
    def property_definitions(self) -> List[PropertyDefinition]:
        """Return the list of property definitions for this entity category."""
        # In a real implementation, we would query the database for the property definitions associated with this entity category.
        # For this example, we'll return an empty list for simplicity.
        cat = cast(models.EntityCategory, cast(models.Category, self).as_kind())

        return cat.defined_properties


@kante.django_type(evidence_models.Term, filters=filters.TermFilter, pagination=True, description="A word this organization uses for a kind of thing")
class Term:
    """The organization's vocabulary, and what the evidence log names.

    A claim says "this node is an AIS" — it names *this*, not a graph's category
    for it. That is what lets two views declaring the same word read each other's
    claims, and it is why a term has no graph, no `age_name`, no `definition` and
    no layout: all of those are properties of one view's rule for the word, and
    they live on `Category`, which keeps them.

    Sibling of `StructureKind` and `MetricKind`, which are the same idea for
    external data and measurements respectively.
    """

    id: strawberry.ID = strawberry.field(description="Database ID of the term")
    kind: enums.TermKind = strawberry.field(description="What sort of thing this word names. Part of its identity, so 'AIS' as an entity and 'AIS' as a relation are two terms.")
    key: str = kante.django_field(description="The word itself, e.g. 'AIS'")
    label: Optional[str] = kante.django_field(description="Human-readable name")
    description: Optional[str] = kante.django_field(description="What this word means")
    purl: Optional[str] = kante.django_field(description="Persistent URL, where this corresponds to a published ontology term")
    color: Optional[List[int]] = kante.django_field(description="Display colour as RGBA")
    image: Optional[MediaStore] = kante.django_field(description="Illustrative image, if any")
    created_at: datetime = kante.django_field(description="When this organization first used this word")

    @kante.django_field(description="The categories declaring this term — one per graph that speaks the word")
    def categories(self, info: kante.Info) -> List["Category"]:
        """Every view's rule for this word.

        More than one is the normal case and the point of the design: each graph
        may define the word differently, over the same claims.
        """
        return list(models.Category.objects.filter(term_id=self.id))


@kante.django_type(evidence_models.StructureKind, filters=filters.StructureKindFilter, pagination=True, description="A kind of external datum this organization knows about")
class StructureKind:
    """Organization vocabulary, not schema.

    Deliberately does **not** implement `Category` or `NodeCategory`. It has no
    graph, no key, no tags, no ontology references and no layout coordinates —
    per-graph position is meaningless for a term shared across every projection.
    The type was renamed from `StructureCategory` rather than quietly losing ten
    inherited fields, so a client that has not been updated fails once and
    obviously instead of field by field.
    """

    id: strawberry.ID = strawberry.field(description="Database ID of the kind")
    identifier: str = kante.django_field(description="The structure identifier, e.g. '@mikro/roi'")
    label: Optional[str] = kante.django_field(description="Human-readable name")
    description: Optional[str] = kante.django_field(description="What this kind of datum is")
    purl: Optional[str] = kante.django_field(description="Persistent URL, where this corresponds to a published term")
    color: Optional[List[int]] = kante.django_field(description="Display colour as RGBA")
    image: Optional[MediaStore] = kante.django_field(description="Illustrative image, if any")
    created_at: datetime = kante.django_field(description="When this organization first saw this kind")


@kante.django_type(evidence_models.MetricKind, filters=filters.MetricKindFilter, pagination=True, description="A kind of measurement that can be made about a structure kind")
class MetricKind:
    """Organization vocabulary. Identity is (organization, structure kind, key)."""

    id: strawberry.ID = strawberry.field(description="Database ID of the kind")
    key: str = kante.django_field(description="The measurement key, e.g. 'vector_length'")
    value_kind: enums.ValueKind = strawberry.field(description="What type of value this measurement carries")
    structure_kind: StructureKind = kante.django_field(description="The kind of structure this measurement describes")
    label: Optional[str] = kante.django_field(description="Human-readable name")
    description: Optional[str] = kante.django_field(description="What this measurement is")
    purl: Optional[str] = kante.django_field(description="Persistent URL, where this corresponds to a published term")
    color: Optional[List[int]] = kante.django_field(description="Display colour as RGBA")
    created_at: datetime = kante.django_field(description="When this organization first saw this kind")


@kind_interface(models.Category, (enums.CategoryKindChoices.NATURAL_EVENT, enums.CategoryKindChoices.PROTOCOL_EVENT), description="Base interface for event categories")
class EventCategory(NodeCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    property_definitions: List[PropertyDefinition] = strawberry.field(default_factory=list, description="List of property definitions for this entity category")

    @kante.django_field(description="The roles an entity can play going into an event of this category")
    def inputs(self) -> List[EventRole]:
        """The declared input roles.

        Read off `source_entity_roles`, the column that has held them all along.
        This returned `[]` unconditionally — while `materialize()` writes the
        column and `versioning.snapshot_definition` reads it back to rebuild the
        schema definition, so the data was there and only this field could not see
        it.
        """
        return _event_roles(cast(models.Category, self).source_entity_roles)

    @kante.django_field(description="The roles an entity can play coming out of an event of this category")
    def outputs(self) -> List[EventRole]:
        """The declared output roles — see :meth:`inputs`."""
        return _event_roles(cast(models.Category, self).target_entity_roles)

    pass


@kind_type(models.Category, enums.CategoryKindChoices.PROTOCOL_EVENT, filters=filters.ProtocolEventCategoryFilter, pagination=True, ordering=order.ProtocolEventCategoryOrder, description="A relation category definition")
class ProtocolEventCategory(EventCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    """A protocol event category definition, which is a subtype of EventCategory."""

    pass


@kind_type(models.Category, enums.CategoryKindChoices.NATURAL_EVENT, filters=filters.NaturalEventCategoryFilter, pagination=True, ordering=order.NaturalEventCategoryOrder, description="A relation category definition")
class NaturalEventCategory(EventCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    """A natural event category definition, which is a subtype of EventCategory."""

    pass


@kind_type(models.Category, enums.CategoryKindChoices.MEASUREMENT, filters=filters.MeasurementCategoryFilter, pagination=True, ordering=order.MeasurementCategoryOrder, description="A measurement category definition")
class MeasurementCategory(EdgeCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    """A relation category definition, which defines the type of a relation edge between entities. It can also include property definitions for the relation."""
    property_definitions: List[PropertyDefinition] = strawberry.field(default_factory=list, description="List of property definitions for this entity category")

    @kante.django_field(description="Which nodes this edge category admits as its source")
    def source_descriptor(self) -> StructureDescriptor:
        """Return the source node category definition if this edge category is used in a pairs query."""
        # In a real implementation, we would check if this edge category is used as a filter in any EdgePairsQuery,
        # and if so, return the source node category from that query.
        # For this example, we'll return None for simplicity.
        return StructureDescriptor.from_pydantic(cast(models.MeasurementCategory, cast(models.Category, self).as_kind()).source_definition_model)

    @kante.django_field(description="Which nodes this edge category admits as its target")
    def target_descriptor(self) -> EntityDescriptor:
        """Return the target node category definition if this edge category is used in a pairs query."""
        # In a real implementation, we would check if this edge category is used as a filter in any EdgePairsQuery,
        # and if so, return the target node category from that query.
        # For this example, we'll return None for simplicity.
        return EntityDescriptor.from_pydantic(cast(models.MeasurementCategory, cast(models.Category, self).as_kind()).target_definition_model)

    pass


@kind_type(models.Category, enums.CategoryKindChoices.RELATION, filters=filters.RelationCategoryFilter, pagination=True, ordering=order.RelationCategoryOrder, description="A relation category definition")
class RelationCategory(EdgeCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    """A relation category definition, which defines the type of a relation edge between entities. It can also include property definitions for the relation."""
    property_definitions: List[PropertyDefinition] = strawberry.field(default_factory=list, description="List of property definitions for this entity category")

    @kante.django_field(description="Which nodes this edge category admits as its source")
    def source_descriptor(self) -> EntityDescriptor:
        """Return the source node category definition if this edge category is used in a pairs query."""
        # In a real implementation, we would check if this edge category is used as a filter in any EdgePairsQuery,
        # and if so, return the source node category from that query.
        # For this example, we'll return None for simplicity.
        return EntityDescriptor.from_pydantic(cast(models.RelationCategory, cast(models.Category, self).as_kind()).source_definition_model)

    @kante.django_field(description="Which nodes this edge category admits as its target")
    def target_descriptor(self) -> EntityDescriptor:
        """Return the target node category definition if this edge category is used in a pairs query."""
        # In a real implementation, we would check if this edge category is used as a filter in any EdgePairsQuery,
        # and if so, return the target node category from that query.
        # For this example, we'll return None for simplicity.
        return EntityDescriptor.from_pydantic(cast(models.RelationCategory, cast(models.Category, self).as_kind()).target_definition_model)

    pass


@kind_type(models.Category, enums.CategoryKindChoices.STRUCTURE_RELATION, filters=filters.StructureRelationCategoryFilter, pagination=True, ordering=order.StructureRelationCategoryOrder, description="A relation category definition")
class StructureRelationCategory(EdgeCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    """A relation category definition, which defines the type of a relation edge between entities. It can also include property definitions for the relation."""
    property_definitions: List[PropertyDefinition] = strawberry.field(default_factory=list, description="List of property definitions for this entity category")

    @kante.django_field(description="Which nodes this edge category admits as its source")
    def source_descriptor(self) -> StructureDescriptor:
        """Return the source node category definition if this edge category is used in a pairs query."""
        # In a real implementation, we would check if this edge category is used as a filter in any EdgePairsQuery,
        # and if so, return the source node category from that query.
        # For this example, we'll return None for simplicity.
        return StructureDescriptor.from_pydantic(cast(models.StructureRelationCategory, cast(models.Category, self).as_kind()).source_definition_model)

    @kante.django_field(description="Which nodes this edge category admits as its target")
    def target_descriptor(self) -> StructureDescriptor:
        """Return the target node category definition if this edge category is used in a pairs query."""
        # In a real implementation, we would check if this edge category is used as a filter in any EdgePairsQuery,
        # and if so, return the target node category from that query.
        # For this example, we'll return None for simplicity.
        return StructureDescriptor.from_pydantic(cast(models.StructureRelationCategory, cast(models.Category, self).as_kind()).target_definition_model)


@org_scoped
@kante.django_interface(models.NodeQuery, description="Base interface for entity categories")
class NodeQuery:
    id: strawberry.ID = strawberry.field(description="Database ID of this saved query")
    graph: "Graph" = strawberry.field(description="The graph this query belongs to")
    key: str = strawberry.field(description="The key this query is referenced and pinned by, unique within its graph")
    label: str = strawberry.field(description="Human-readable name for this query")
    description: Optional[str] = strawberry.field(default=None, description="Description of this query")
    query: scalars.CypherLiteral = strawberry.field(description="The Cypher this query runs")
    relevant_for: List["NodeCategory"] = strawberry.field(default_factory=list, description="List of node categories for which this query is relevant")
    # Same reason as `Graph.is_archived`: nine `archive_*_query` mutations wrote
    # this flag and no type ever showed it back.
    archived: bool = strawberry.field(description="Whether this saved query has been archived")


@kind_type(models.NodeQuery, enums.NodeQueryKindChoices.TABLE, filters=filters.NodeTableQueryFilter, pagination=True, ordering=order.NodeTableQueryOrder, description="Base interface for graph schemas")
class NodeTableQuery(NodeQuery, Plottable):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    query: scalars.CypherLiteral = strawberry.field(description="The Cypher query to execute for this table query")
    columns: List[Column] = strawberry.field(description="List of columns to return in the table query result")
    builder_args: Optional[BuilderArgs] = strawberry.field(default=None, description="If this graph was built using a builder function, the arguments used for building it, which can be used for debugging or rebuilding the graph with different parameters")


@kind_type(models.NodeQuery, enums.NodeQueryKindChoices.PAIRS, filters=filters.NodePairsQueryFilter, pagination=True, ordering=order.NodePairsQueryOrder, description="Base interface for graph schemas")
class NodePairsQuery(NodeQuery):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    source_category: "NodeCategory" = strawberry.field(description="The source node category to query")
    target_category: "NodeCategory" = strawberry.field(description="The target node category to query")
    edge_category: Optional["EdgeCategory"] = strawberry.field(default=None, description="Optional edge category to filter pairs by")


@kind_type(models.NodeQuery, enums.NodeQueryKindChoices.PATH, filters=filters.NodePathQueryFilter, pagination=True, ordering=order.NodePathQueryOrder, description="Base interface for graph schemas")
class NodePathQuery(NodeQuery):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")


@org_scoped
@kante.django_interface(models.EdgeQuery, description="Base interface for entity categories")
class EdgeQuery:
    id: strawberry.ID = strawberry.field(description="Database ID of this saved query")
    graph: "Graph" = strawberry.field(description="The graph this query belongs to")
    key: str = strawberry.field(description="The key this query is referenced and pinned by, unique within its graph")
    label: str = strawberry.field(description="Human-readable name for this query")
    description: Optional[str] = strawberry.field(default=None, description="Description of this query")
    query: scalars.CypherLiteral = strawberry.field(description="The Cypher this query runs")
    relevant_for: List["NodeCategory"] = strawberry.field(default_factory=list, description="List of node categories for which this query is relevant")
    # Same reason as `Graph.is_archived`: nine `archive_*_query` mutations wrote
    # this flag and no type ever showed it back.
    archived: bool = strawberry.field(description="Whether this saved query has been archived")


@kind_type(models.EdgeQuery, enums.EdgeQueryKindChoices.TABLE, filters=filters.EdgeTableQueryFilter, pagination=True, ordering=order.EdgeTableQueryOrder, description="Base interface for graph schemas")
class EdgeTableQuery(EdgeQuery, Plottable):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    query: scalars.CypherLiteral = strawberry.field(description="The Cypher query to execute for this table query")
    columns: List[Column] = strawberry.field(description="List of columns to return in the table query result")
    builder_args: Optional[BuilderArgs] = strawberry.field(default=None, description="If this graph was built using a builder function, the arguments used for building it, which can be used for debugging or rebuilding the graph with different parameters")


@kind_type(models.EdgeQuery, enums.EdgeQueryKindChoices.PAIRS, filters=filters.EdgePairsQueryFilter, pagination=True, ordering=order.EdgePairsQueryOrder, description="Base interface for graph schemas")
class EdgePairsQuery(EdgeQuery):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    source_category: "NodeCategory" = strawberry.field(description="The source node category to query")
    target_category: "NodeCategory" = strawberry.field(description="The target node category to query")
    edge_category: Optional["EdgeCategory"] = strawberry.field(default=None, description="Optional edge category to filter pairs by")


@kind_type(models.EdgeQuery, enums.EdgeQueryKindChoices.PATH, filters=filters.EdgePathQueryFilter, pagination=True, ordering=order.EdgePathQueryOrder, description="Base interface for graph schemas")
class EdgePathQuery(EdgeQuery):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")


# ===========================================
# PROPERTY TYPE
# ===========================================


def _scatter_plot_scoped(cls):
    """Fence `ScatterPlot` to the request's organization.

    Its own fence rather than `org_scoped`, because a scatter plot has no
    `organization` and no `graph`: it reaches a tenant only through whichever of
    its three query foreign keys is set. All three are nullable, so the filter is
    a disjunction and a plot referencing no query at all is visible to nobody —
    which is the safe direction, and such a row cannot render anyway.
    """

    def get_queryset(cls_, queryset, info, **kwargs):
        organization = get_active_organization(info)
        return queryset.filter(
            Q(graph_query__graph__organization=organization) | Q(node_query__graph__organization=organization) | Q(path_query__graph__organization=organization)
        ).distinct()

    cls.get_queryset = classmethod(get_queryset)
    return cls


@_scatter_plot_scoped
@kante.django_type(models.ScatterPlot, filters=filters.ScatterPlotFilter, pagination=True, ordering=order.ScatterPlotOrder, description="A saved scatter-plot configuration over a graph query")
class ScatterPlot:
    label: str = strawberry.field(description="Label/name of the scatter plot definition")
    description: Optional[str] = strawberry.field(default=None, description="Description of the scatter plot definition")
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    id_column: str = strawberry.field(description="The name of the column to use for point identifiers (e.g. structure ID, or entity id)")
    x_column: str = strawberry.field(description="The name of the column to use for x values")
    y_column: str = strawberry.field(description="The name of the column to use for y values")
    color_column: Optional[str] = strawberry.field(default=None, description="The name of the column to use for color values (optional)")
    size_column: Optional[str] = strawberry.field(default=None, description="The name of the column to use for size values (optional)")
    shape_column: Optional[str] = strawberry.field(default=None, description="The name of the column to use for shape values (optional)")

    @kante.django_field(description="The graph this category belongs to")
    def query(self) -> Plottable:
        """Fetch the data points for this scatter plot."""
        # In a real implementation, we would query the graph for the data points linked to this structure and entity.
        # For this example, we'll return an empty list for simplicity.
        model = cast(models.ScatterPlot, self)
        if model.graph_query:
            return model.graph_query
        elif model.node_query:
            return model.node_query
        elif model.path_query:
            return model.path_query
        else:
            raise ValueError("ScatterPlot must have either a graph_query, node_query, or path_query")


@strawberry.type(description="A rich property with metadata from schema and graph")
class RichProperty:
    # Both NodeCategory and EdgeCategory expose `property_map`; the base Category does not.
    _entity: strawberry.Private[RetrievedNode | RetrievedEdge]
    _key: strawberry.Private[str]
    _category: strawberry.Private["models.NodeCategory | models.EdgeCategory"]

    # `graphId` used to sit here and meant two different things: `RetrievedNode`
    # returned the node's uuid, `RetrievedEdge` returned an int that was `0` for
    # every row-backed edge. One field name, two answers, neither a graph id.

    @strawberry.field(description="The schema definition this property was derived under")
    async def definition(self) -> Optional[PropertyDefinition]:
        """Fetch the property definition for this key from the category's schema."""
        # `property_definitions` is a JSON list, not a related manager — `property_map`
        # rehydrates it into pydantic models keyed by property key. No DB access here,
        # which is what keeps this safe to call from an async resolver.
        definition = self._category.property_map.get(self._key)
        if definition is None:
            return None
        return PropertyDefinition.from_pydantic(definition)

    @strawberry.field(description="The property key/name")
    async def key(self) -> Optional[str]:
        """Return the property key/name."""
        return self._key

    @strawberry.field(description="The property value")
    def value(self) -> AnyScalar | None:
        """The property's current value, read off the vertex.

        No fallback, and no `async`. Every derived property is written at
        materialization, so if it is not on the node it is not derivable — the
        projection is behind the log, and `manage.py reproject` is the answer.
        Silently folding state here instead is what made a read into N × (1 + 3P)
        Postgres round-trips.
        """
        return self._entity.get_property(self._key)

    def _statistic(self, statistic: str) -> Any:
        """One materialized statistic about this property. See `projector._property_statistics`."""
        from graph_engine import projector

        return self._entity.properties.get(projector.statistic_key(self._key, statistic))

    @strawberry.field(description="How many measurements contribute to this value")
    def n_evidence(self) -> Optional[int]:
        """The number of metrics folded into this property's value."""
        value = self._statistic("n")
        return int(value) if value is not None else None

    @strawberry.field(description="Spread of the contributing measurements (max - min), where numeric")
    def spread(self) -> Optional[float]:
        """How far apart the supporting measurements are.

        A mean of 45.2 derived from three measurements spanning 2µm means
        something different from the same mean spanning 40µm, and the difference
        is invisible in the value alone.
        """
        value = self._statistic("spread")
        return float(value) if value is not None else None

    @strawberry.field(description="When the earliest contributing measurement was observed")
    def measured_from(self) -> Optional[datetime]:
        """Start of the observation window this value summarises."""
        return _as_datetime(self._statistic("from"))

    @strawberry.field(description="When the latest contributing measurement was observed")
    def measured_to(self) -> Optional[datetime]:
        """End of the observation window this value summarises."""
        return _as_datetime(self._statistic("to"))

    @strawberry.field(description="The assertions whose measurements contribute to this value")
    async def contributing_assertions(self) -> List["Assertion"]:
        """Who claimed the measurements behind this number.

        The provenance half of the BIOLOGIST.md sentence: not just "45.2µm" but
        "derived from ROI #555, asserted by AI_Model_X on Jan 15th".
        """
        rows = await self._contributing_metrics()
        seen: dict[str, Any] = {}
        for metric in rows:
            seen.setdefault(str(metric.assertion_id), metric.assertion)
        # The rows themselves. These used to be wrapped in
        # `RetrievedAssertion.from_row` and handed to an `Edge` subclass, so
        # selecting `sourceId` here raised `AttributeError` — the wrapper is a
        # `RetrievedNode` and has no edge endpoints. `Assertion` is the Django row
        # now, so there is nothing to adapt.
        return list(cast(List[Assertion], list(seen.values())))

    @strawberry.field(description="Supporting evidence for this property, in form of metrics derived from observations/measurements")
    async def supporting_evidence(self) -> List["Metric"]:
        """The measurements this property's value was derived from.

        Previously a hardcoded empty list, which made every derived value
        unexplainable — you could see the number but never what produced it.
        """
        rows = await self._contributing_metrics()
        controller = self._entity.controller
        return [Metric(_value=retrieved.RetrievedMetric.from_row(controller, row)) for row in rows]

    # --- internals ---

    def _rule(self) -> Any:
        definition = self._category.property_map.get(self._key)
        return getattr(definition, "rule", None) if definition else None

    @sync_to_async
    def _contributing_metrics(self) -> list:
        """Every active metric folded into this property's value."""
        from evidence import models as evidence_models
        from graph_engine import projector

        rule = self._rule()
        graph = self._category.graph
        source = _structure_kind_for(graph, rule)
        if source is None:
            return []

        key = rule.key if rule and rule.key else self._key
        # Narrowed the same way the value itself was derived. Listing metrics the
        # fold never counted would make the explanation disagree with the number
        # it is supposed to explain.
        value_kinds = projector._value_kinds_for_rule(graph, source, key, rule)
        if value_kinds is None:
            return []

        structure_ids = list(
            claims_module.standing(
                evidence_models.Link.objects.for_organization(graph.organization).filter(
                    kind=evidence_models.Link.Kind.INFORMS,
                    target_ref=self._entity.durable_ref,
                ),
                "link",
            ).values_list("source_ref", flat=True)
        )
        parsed = []
        for ref in structure_ids:
            try:
                parsed.append(uuid.UUID(str(ref)))
            except ValueError:
                continue

        return list(
            claims_module.standing(
                evidence_models.Metric.objects.for_organization(graph.organization).filter(
                    structure_id__in=parsed,
                    structure__kind=source,
                    key=key,
                    value_kind__in=list(value_kinds),
                ),
                "metric",
            )
            .select_related("assertion", "structure")
            .order_by("measured_at")
        )


def _structure_kind_for(graph: Any, rule: Any) -> Any:
    """Resolve a derivation rule's source to one of the organization's structure kinds."""
    if rule is None or not getattr(rule, "source_node", None):
        return None
    return evidence_models.StructureKind.objects.for_organization(graph.organization).filter(identifier=rule.source_node).first()


# ===========================================
# BASE NODE INTERFACE
# ===========================================

T = TypeVar("T", bound="Node")
V = TypeVar("V", bound=RetrievedNode)


@strawberry.interface(description="A domain event drawn in a graph — something that happened to the sample, never an entry of the assertion log")
class Event:
    """The interface `NaturalEvent` and `ProtocolEvent` share.

    Its shipped description used to read "Interface for edges that track schema
    version and derivation time" — it is not an edge and tracks neither. Naming
    care is warranted here: in an event-sourced system "event" is the log's
    unit, but the log's unit is `Assertion`, and these are *domain* events —
    mitosis, a fixation step — that exist as claims like any entity.
    """

    kind: str = strawberry.field(description="The event's word, e.g. 'Mitosis' — what the claim says happened")


@strawberry.interface(description="Base interface for all graph nodes")
class Node(Generic[V]):
    """
    Base interface that all graph nodes implement.
    Uses strawberry.Private to hold the underlying RetrievedNode data.
    """

    _value: strawberry.Private[V]

    def __hash__(self):
        return hash(self._value)

    # Five fields used to sit here and all five were about the **vertex** rather
    # than the thing:
    #
    # - `graphId` was the Apache AGE vertex id, which is reassigned by every
    #   reproject — an identifier that stops meaning anything after the one
    #   operation this layer exists to support.
    # - `graph` asked which graph a node belongs to. A node may be drawn by
    #   several, and which one you read it through is not a property of it.
    #   `Entity.drawnIn` answers the honest form: every view that draws it, and
    #   under which category.
    # - `globalId` **raised** for every node read out of a projection.
    #   `RetrievedNode.global_id` requires a `global_id` vertex property and
    #   `projector.create_vertex` writes exactly `{id, category_id}`, so nothing
    #   ever set one. Only the row-backed branch worked, which is why the one test
    #   covering the field — asking a structure — stayed green.
    # - `localId` returned "0" for every row-backed node and a reassigned vertex
    #   id otherwise.
    # - `pinned` was hardcoded `False`; `pinNode` was removed, so nothing could
    #   set it.
    #
    # `id` is the identity, and it is a bare uuid.

    @strawberry.field(description="The AGE graph label as recently materialized (e.g. 'Cell IAC100', 'ROI 1')")
    def label(self) -> str:
        """Should return the most specific label for this node (e.g. 'Cell' instead of 'Entity') Composed by its propetries"""
        return self._value.label

    @strawberry.field(description="This node's durable identity — a bare uuid, world-unique and stable across reprojects")
    def id(self) -> strawberry.ID:
        return strawberry.ID(self._value.unique_id)

    # `externalId` is gone, and it is the sixth vertex-shaped field to go. It read
    # an `external_id` vertex property that **nothing in this repo has ever
    # written** — `projector.create_vertex` writes `{id, category_id, type}`, and
    # `external_id` appears only in `RESERVED_PROPERTY_KEYS` and the two readers
    # that are now deleted. So it answered null for every node ever returned,
    # exactly like the `globalId` removed above, and a field that is structurally
    # always null is a question the schema cannot answer rather than one whose
    # answer happens to be absent.

    @strawberry.field(description="Schema version the properties were derived under. Null when this reading came from the log rather than from a projection — a claim no view draws has no derived properties, so there is no version to name")
    def schema_version(self) -> Optional[str]:
        """Nullable, and it was `String!`.

        `RetrievedNode.from_row` writes no `__schema_version`, so every row-backed
        reading returned null on a non-null field — a hard error on the exact case
        the shape exists for. The row-backed reading is how a node the view admits
        but has not drawn yet answers, through `nodes(graph:)` and
        `entity(id:, graph:)` alike.

        **This lived on a `VersionedNode` interface until it was merged here.**
        `VersionedNode` extended `Node` and was implemented by `Entity`,
        `NaturalEvent` and `ProtocolEvent` — which is *exactly* `Node`'s own
        implementor set — and no field anywhere returned it. An interface whose
        members are its parent's members and which nothing is typed as draws no
        line; it only asks a client to choose between two fragment targets that
        select the same things.
        """
        return self._value.schema_version

    @strawberry.field(description="Timestamp when properties were last derived (unix ms)")
    def last_derived(self) -> Optional[UnixMilliseconds]:
        return self._value.last_derived

    # =======================================
    # THE PANEL — what the log knows about this thing
    #
    # Every field below is asked about the whole **component**, not about this
    # one node. Every observation mints its own instance — "this is an AIS"
    # writes a fresh node rather than reusing one — so what is known about a
    # thing is spread across the instances somebody has claimed are one. Asking
    # about the bare node would show one observation's half of the story and call
    # it the answer. See `evidence/identity.py`.
    #
    # All five share one batched read (`loaders.known_about_node`), so selecting
    # every section on a page of nodes costs a constant number of queries rather
    # than five per node.
    # =======================================

    @strawberry.field(description="Every instance claimed to be this same thing, this one included. A component of one means nobody has merged it")
    async def component(self) -> List[strawberry.ID]:
        known = await loaders.known_about_node_loader.load(self._value.unique_id)
        return [cast(strawberry.ID, ref) for ref in known.component]

    @strawberry.field(description="What anyone has called this thing, with how many assertions say so. Two words means two people disagreed; one word with a count of two means they agreed")
    async def labels(self) -> List["Label"]:
        known = await loaders.known_about_node_loader.load(self._value.unique_id)
        return [Label(_value=label) for label in known.labels]

    @strawberry.field(description="The standing claims that this instance and another are one thing, with who said so. Exposed so a merge is visible and contestable rather than silent")
    async def same_as(self) -> List["Sameness"]:
        known = await loaders.known_about_node_loader.load(self._value.unique_id)
        return [Sameness(_value=RetrievedEdge.from_link(get_controller(), link)) for link in known.sameness]

    @strawberry.field(description="Every standing claim connecting this thing to something else — relations, participations and the structures that inform it. Needs no graph query: they are all evidence rows, and the drawing of them is a projection")
    async def connections(self) -> List["Edge"]:
        known = await loaders.known_about_node_loader.load(self._value.unique_id)
        return [cast(Edge, cast_edge_to_graphql_type(RetrievedEdge.from_link(get_controller(), link))) for link in known.connections]

    @kante.django_field(description="Every view that actually draws this thing, and the category it draws it under. Read back from each projection, so a graph that declares the word but whose definition refuses the node is not listed")
    async def drawn_in(self, info: kante.Info) -> List["NodeDrawing"]:
        drawings = await _drawings_for_ref(self._value.unique_id, info)
        return [NodeDrawing(_value=drawing) for drawing in drawings]

    @classmethod
    def to_subtype(cls, value: RetrievedNode) -> "Node":
        """Factory method to create the appropriate Node subtype based on the value."""
        return cast_node_to_graphql_type(value)

    @classmethod
    def from_specific(cls: Type[T], subtype: V) -> T:
        """Factory method to convert a Node subtype back to the base Node interface."""
        return cls(_value=subtype)


# ===========================================
# `VersionedNode` is gone; `schemaVersion` and `lastDerived` moved onto `Node`.
#
# It was an interface extending `Node`, implemented by `Entity`, `NaturalEvent`
# and `ProtocolEvent` — which is every implementor `Node` has — and returned by no
# field in the schema. So the SDL carried two interfaces with identical member
# sets, one of which nothing was typed as: a distinction that cost a client a
# choice between fragment targets and told it nothing.
#
# **No `lifecycle` field, deliberately**, and that rationale outlives the
# interface it was written on. It could not mean anything: these are the node
# kinds that live in a graph, and a node read out of a graph is one the evidence
# says exists — the graph holds nothing else. So the field answered "active"
# whenever it was read from a projection and "retracted" only when built from a
# row with no projection, which is two different questions wearing one name.
#
# Where a claim stands is `drawings` on a write result: a list of the views that
# draw it, empty when none do. That says *where*, which is the only form the
# answer has — two annotators may disagree about whether a thing exists, and each
# graph's selector decides whose word it counts.

# ===========================================
# ENTITY TYPE
# ===========================================


@strawberry.type(description="An entity in the knowledge graph with derived properties")
class Entity(Node[RetrievedNode]):
    """
    An entity represents a domain object (e.g. AIS, Cell, Soma) with properties
    derived from supporting evidence structures.
    """

    @strawberry.field(description="The entity type/kind (e.g. 'AIS', 'Cell')")
    def kind(self) -> str:
        return self._value.kind or self._value.label

    @strawberry.field(description="Category ID linking to EntityCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id

    @kante.django_field(description="How the view this was read through draws it, if any view does")
    def category(self) -> Optional[EntityCategory]:
        """This entity's category in the view it was read through.

        Nullable, because a node names one of the organization's words and a
        category is one view's rule for that word — so an entity claimed under a
        word no view declares has none. `assertEntityExists` names a term, which makes
        that a state one mutation can reach.
        """
        if self._value.category_id is None:
            return None
        return cast(EntityCategory, models.EntityCategory.objects.get(id=self._value.category_id))

    @strawberry.field(description="When this entity became valid. When did it start existing?")
    def valid_from(self) -> Optional[datetime]:
        return self._value.valid_from

    @strawberry.field(description="When this entity stopped being valid. . When did it stop existing?")
    def valid_to(self) -> Optional[datetime]:
        return self._value.valid_to

    @strawberry.field(description="List of properties derived for this entity. Empty when this reading has no category — a property definition is one view's rule, and a claim no view draws has none")
    async def rich_properties(self) -> List[RichProperty]:
        """Combine raw properties with schema definitions for a rich view.

        The empty answer used to be an `assert category_id is not None`, which made
        an ordinary state — a claim under a word no view declares — an
        `AssertionError`. What explains a property is a category, so with no category
        there is nothing to explain and nothing to raise about.
        """
        if self._value.category_id is None:
            return []
        category = await loaders.entity_category_loader.load(self._value.category_id)

        # Enumerated from the schema, not from the node's stored keys. Only
        # indexed properties live on the node now, so iterating those would hide
        # every derived-on-read property — exactly the ones this type exists to
        # explain.
        declared = list(category.property_map.keys())
        stored = [key for key in self._value.cleaned_properties if key not in declared]
        return [RichProperty(_entity=self._value, _key=key, _category=category) for key in declared + stored]

    @strawberry.field(description="The current derived properties for this entity")
    async def properties(self) -> AnyScalar:
        """Every derived property, read off the vertex.

        Nothing is computed here. Applying a graph's rules to the log is what
        writes these values (`projector.project`), and a query afterwards is a
        traversal over the result. This resolver used to fold state per node for
        every property not marked `index=True` — which, since `index` defaults to
        `False`, was almost all of them, on every node of every list.
        """
        return self._value.cleaned_properties

    # =======================================
    # What is known about this thing
    #
    # Every field below is asked about the whole **component**, not about this
    # one node. Every observation mints its own instance — "this is an AIS"
    # writes a fresh node rather than reusing one — so what is known about a
    # thing is spread across the instances somebody has claimed are one. Asking
    # about the bare node would show one observation's half of the story and call
    # it the answer. See `evidence/identity.py`.
    #
    # All four share one batched read (`loaders.known_about_node`), so selecting
    # every section on a page of entities costs a constant number of queries
    # rather than four per entity.
    # =======================================

    # The panel — `component`, `labels`, `sameAs`, `connections`, `drawnIn` —
    # moved to the `Node` interface. It answers about an `Instance`, and an
    # instance is any of the three node kinds: events are classified, merged
    # (`assertSameInstance` takes "entities or events alike") and connected
    # exactly as entities are, and `known_about_node_loader` keys on a bare
    # instance pk without caring which kind it got. Sitting only on `Entity`
    # meant an event could not answer questions the evidence layer answers for
    # it identically — and it made `Structure.informs`, which returns whatever
    # kind the INFORMS claim names, unable to select any of them.

    # `measuredBy`, `participatedIn` and `resultedOut` used to sit here, each
    # returning `[]` under a comment saying a real implementation would do
    # otherwise. They are the pre-evidence-table spelling of a question
    # `connections` above now answers from the log — and over the whole component
    # rather than one instance.


# ===========================================
# STRUCTURE TYPE
# ===========================================


@strawberry.type(description="A pointer to an external datum — a claim, not a graph node")
class Structure:
    """
    A structure represents an evidence source (e.g. ROI, Image) that
    can have measurements attached and inform entities.

    **Not a `Node`.** A structure is a Postgres evidence row with no Apache AGE
    presence — no view ever draws one (see `AssertedStructure`) — so implementing
    the projection interface meant inheriting `label` ("The AGE graph label as
    recently materialized", actually the hard-coded word "Structure") and
    `externalId` (a vertex property nothing writes, so always null). The fields
    below are the ones a structure can answer.
    """

    _value: strawberry.Private[RetrievedStructure]

    def __hash__(self):
        return hash(self._value)

    @strawberry.field(description="This claim's durable identity — the `Structure` primary key, a bare uuid")
    def id(self) -> strawberry.ID:
        return strawberry.ID(self._value.unique_id)

    @strawberry.field(description="Schema identifier (e.g. '@mikro/roi')")
    def identifier(self) -> StructureIdentifier:
        return self._value.identifier or ""

    @strawberry.field(description="External object ID this structure references")
    def object(self) -> str:
        return self._value.object or ""

    @strawberry.field(description="ID of the structure kind this instantiates")
    def kind_id(self) -> str:
        return self._value.category_id

    @kante.django_field(description="The organization's term for this kind of structure")
    async def kind(self) -> Optional["StructureKind"]:
        """The structure kind, resolved through the per-operation loader."""
        return await loaders.structure_kind_loader.load(self._value.category_id)

    @kante.django_field(description="Every un-retracted measurement of this structure, in observation order")
    async def metrics(self) -> List["Metric"]:
        """What has been measured here.

        Hardcoded `return []` until now, while `metricsForStructure(structureId:)`
        answered the same question at the top level — so the field existed, was
        selectable, and silently said there were no measurements.

        Batched: a page of structures is one query, not one per structure. The
        loader has to group rather than index by key, because a structure has many
        metrics — see `loaders._batch_grouped_by`.
        """
        rows = await loaders.metrics_by_structure_loader.load(self._value.unique_id)
        controller = get_controller()
        return [Metric(_value=RetrievedMetric.from_row(controller, row)) for row in rows]

    @kante.django_field(description="The discussion this datum carries: every remark recorded about it, newest first, resolved ones included — resolution is shown, not hidden. Threading is on each comment (`parent`/`replies`)")
    async def comments(self) -> List["Comment"]:
        """The structure carries the thread — the reason a comment points at a
        `Structure` rather than repeating `(identifier, object)`: the same ROI
        discussed from two experiments is one conversation. Batched like
        `metrics`, and for the same reason."""
        return cast(List["Comment"], await loaders.comments_by_structure_loader.load(self._value.unique_id))

    @kante.django_field(description="The nodes this structure is evidence for. Where its labels, merges and connections live — a structure is a pointer to an external datum and is never itself claimed to be an AIS")
    async def informs(self) -> List["Node"]:
        """The entities this structure informs.

        The hop the panel takes to reach everything else. Structures are never
        "the same" as one another — a structure is idempotent by
        `(identifier, object)`, so two of them are either one row or two different
        data — which is why identity, labels and connections all live on the
        entity and are reached from here.

        Batched, and that is load-bearing beyond this field: a DataLoader
        dispatches once per event-loop tick, so resolving this per structure would
        stagger every `Entity` below it into a batch of one.

        Structure → informed node already existed three times over
        (`controller.py`, `selector.py`, `projector.py`) and was exposed nowhere.

        **`Node`, and dispatched rather than constructed.** This built `Entity`
        directly over every row, but `panel.informed_nodes` filters
        `Instance.all_objects` by pk with no `kind` filter, and
        `controller.create_event` writes `INFORMS` links against an event ref —
        so a structure informing a protocol event reported it as an entity. The
        field's own description said "nodes" while its type said `Entity`.
        """
        controller = get_controller()
        rows = await loaders.informed_nodes_by_structure_loader.load(self._value.unique_id)
        return [cast(Node, cast_node_to_graphql_type(retrieved.RetrievedNode.from_row(controller, node))) for node in rows]


# ===========================================
# NATURAL EVENT TYPE
# ===========================================


@strawberry.type(description="A natural event in the knowledge graph")
class NaturalEvent(Node[RetrievedNode], Event):
    """
    A natural event represents a biological/natural occurrence (e.g. Mitosis)
    with properties derived from supporting evidence.
    """

    _value: strawberry.Private[RetrievedNode]

    @strawberry.field(description="The event type/kind")
    def kind(self) -> str:
        return self._value.kind or self._value.label

    @strawberry.field(description="Category ID linking to NaturalEventCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id

    # `measuredFrom` and `measuredTo` used to sit here. Both were annotated
    # `-> datetime` and returned `cleaned_properties`, a **dict** — so selecting
    # either failed serialization rather than returning a wrong value. An event
    # node carries no observation window; the metrics informing it do, and those
    # are reachable through `richProperties { contributingAssertions }`.

    @kante.django_field(description="How the view this was read through draws it, if any view does")
    def category(self) -> Optional[NaturalEventCategory]:
        """This event's category in the view it was read through — see `Entity.category`."""
        if self._value.category_id is None:
            return None
        return cast(NaturalEventCategory, models.NaturalEventCategory.objects.get(id=self._value.category_id))

    @strawberry.field(description="List of properties derived for this entity")
    async def rich_properties(self) -> List[RichProperty]:
        """Combine raw properties with schema definitions for a rich view.

        Empty when no view declares the word: a rich property is a raw value read
        against a category's declared shape, and with no category there is no shape
        to read it against.
        """
        if self._value.category_id is None:
            return []
        category = await loaders.natural_event_category_loader.load(self._value.category_id)

        return [RichProperty(_entity=self._value, _key=var, _category=category) for var in self._value.cleaned_properties]

    @strawberry.field(description="List of the current derived properties for this entity")
    async def properties(self) -> AnyScalar:
        """Every derived property, read off the vertex — see `Entity.properties`.

        Events and relations derive properties exactly as entities do; the bio
        schema's `Mitosis.cell_count` is one. They are materialized the same way,
        so reading the stored keys is now the whole answer rather than half of it.
        """
        return self._value.cleaned_properties


# ===========================================
# METRIC TYPE
# ===========================================


@strawberry.type(description="A measured value about a structure — a claim, not a graph node")
class Metric:
    """
    A metric represents a measured value recorded against a structure.

    **Not a `Node`.** A metric is a Postgres evidence row with no Apache AGE
    presence — its value is *folded into* vertices as derived properties, it is
    never a vertex itself — so implementing the projection interface put a
    hard-coded `label` and an always-null `externalId` beside `assertion` and
    `kind`, which are evidence-grain and the point of the type.
    """

    _value: strawberry.Private[RetrievedMetric]

    def __hash__(self):
        return hash(self._value)

    @strawberry.field(description="This claim's durable identity — the `Metric` primary key, a bare uuid")
    def id(self) -> strawberry.ID:
        return strawberry.ID(self._value.unique_id)

    @strawberry.field(description="ID of the metric kind this instantiates")
    def kind_id(self) -> Optional[str]:
        return self._value.category_id

    @strawberry.field(description="The metric value")
    def value(self) -> AnyScalar:
        return self._value.value

    @strawberry.field(description="The measurement key")
    def key(self) -> Optional[str]:
        return self._value.properties.get("key")

    @strawberry.field(description="Unit of measurement, where the source gave one")
    def unit(self) -> Optional[str]:
        return self._value.properties.get("unit")

    @strawberry.field(description="How confident the source is in this measurement")
    def confidence(self) -> Optional[float]:
        return self._value.properties.get("confidence")

    @strawberry.field(description="What kind of confidence this is")
    def confidence_type(self) -> Optional[str]:
        return self._value.properties.get("confidence_type")

    @strawberry.field(description="When the world was observed")
    def measured_at(self) -> Optional[datetime]:
        return self._value.properties.get("__measured_at")

    @strawberry.field(description="When this measurement was claimed")
    def asserted_at(self) -> Optional[datetime]:
        return self._value.properties.get("__asserted_at")

    @kante.django_field(description="The organization's term for this kind of measurement")
    async def kind(self) -> Optional["MetricKind"]:
        """The metric kind, resolved through the per-operation loader.

        Previously a synchronous `.objects.get()` inside an async resolver, which
        is both a `SynchronousOnlyOperation` waiting to happen and — now that
        kinds use a raising default manager — an unscoped access.
        """
        return await loaders.metric_kind_loader.load(self._value.category_id)

    @kante.django_field(description="Who measured this, and when they claimed it")
    async def assertion(self) -> Optional["Assertion"]:
        """The act that recorded this measurement.

        Unanswerable until now: `RetrievedMetric.from_row` kept the value, the
        key and both timestamps and dropped the row, so a metric could say *when*
        it was claimed but never by whom — with provenance being half of what the
        evidence model is for.
        """
        assertion_id = self._value.properties.get("__assertion_id")
        if assertion_id is None:
            return None
        return cast(Optional["Assertion"], await loaders.assertion_by_id_loader.load(assertion_id))


# ===========================================
# REAGENT TYPE
# ===========================================


# ===========================================
# PROTOCOL EVENT TYPE
# ===========================================


@strawberry.type(description="A protocol event in the graph")
class ProtocolEvent(Node[RetrievedNode], Event):
    """
    A protocol event represents a step in an experimental protocol.
    """

    _value: strawberry.Private[RetrievedNode]

    @strawberry.field(description="The event type/kind")
    def kind(self) -> str:
        return self._value.kind or self._value.label

    @strawberry.field(description="Category ID linking to ProtocolEventCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id

    # `measuredFrom` and `measuredTo` used to sit here. Both were annotated
    # `-> datetime` and returned `cleaned_properties`, a **dict** — so selecting
    # either failed serialization rather than returning a wrong value. An event
    # node carries no observation window; the metrics informing it do, and those
    # are reachable through `richProperties { contributingAssertions }`.

    @kante.django_field(description="How the view this was read through draws it, if any view does")
    def category(self) -> Optional[ProtocolEventCategory]:
        """This event's category in the view it was read through — see `Entity.category`."""
        if self._value.category_id is None:
            return None
        return cast(ProtocolEventCategory, models.ProtocolEventCategory.objects.get(id=self._value.category_id))

    @strawberry.field(description="List of properties derived for this entity")
    async def rich_properties(self) -> List[RichProperty]:
        """Combine raw properties with schema definitions for a rich view.

        Empty when no view declares the word — see `NaturalEvent.rich_properties`.
        """
        if self._value.category_id is None:
            return []
        category = await loaders.protocol_event_category_loader.load(self._value.category_id)

        return [RichProperty(_entity=self._value, _key=var, _category=category) for var in self._value.cleaned_properties]

    @strawberry.field(description="List of the current derived properties for this entity")
    async def properties(self) -> AnyScalar:
        """Every derived property, read off the vertex — see `Entity.properties`.

        Events and relations derive properties exactly as entities do; the bio
        schema's `Mitosis.cell_count` is one. They are materialized the same way,
        so reading the stored keys is now the whole answer rather than half of it.
        """
        return self._value.cleaned_properties


# ===========================================
# BASE EDGE INTERFACE
# ===========================================
T = TypeVar("T", bound="Edge")
V = TypeVar("V", bound=RetrievedEdge)


@strawberry.interface(description="A claim relating two things — one `evidence.Link` row, typed by its kind. Not a drawing: several kinds are never projected to an AGE edge at all")
class Edge(Generic[V]):
    """Base interface that every link claim implements.

    Its description used to read "Base interface for all graph edges", and the
    word *graph* is what made it look like a drawing type — which invites the
    question of why `Measurement` and `StructureRelation` implement it when
    `assertMeasurementExists` says in as many words that their drawings are
    "always empty, and structurally so".

    **They implement it because `Edge` means `Link`, not "drawn".** The two node
    and edge interfaces are the same shape: `Node`'s subtypes are exactly
    `Instance.Kind`'s three values, and `Edge`'s are exactly `Link.Kind`'s eight.
    Each is "one row of my table, discriminated by kind". `Structure` and `Metric`
    are outside `Node` because they are rows of `evidence_structure` and
    `evidence_metric` — different tables, not instances — and not because nothing
    draws them.

    That distinction is load-bearing rather than pedantic: `Node.connections`
    returns `[Edge!]!` over every link kind a component touches, so an `Edge` that
    meant "drawn" could not answer it.

    Uses strawberry.Private to hold the underlying RetrievedEdge data.
    """

    _value: strawberry.Private[V]

    def __hash__(self):
        return hash(self._value)

    # `graphId` and `globalId` used to sit here, and both named the drawing rather
    # than the claim. `graphId` was the Apache AGE edge id, reassigned by every
    # reproject; `globalId` was `{graph_name}:{age_edge_id}` for anything built
    # from Cypher, which is an id the singular fetchers could not accept. `id` is
    # the `Link` primary key and round-trips.

    @strawberry.field(description="This claim's durable identity — the `Link` primary key, a bare uuid")
    def id(self) -> strawberry.ID:
        return strawberry.ID(self._value.unique_id)

    @strawberry.field(description="The edge label/type")
    def label(self) -> str:
        return self._value.label

    @strawberry.field(description="The source endpoint, as evidence names it — a bare uuid")
    def source_id(self) -> strawberry.ID:
        return strawberry.ID(self._value.unique_left_id)

    @strawberry.field(description="The target endpoint, as evidence names it — a bare uuid")
    def target_id(self) -> strawberry.ID:
        return strawberry.ID(self._value.unique_right_id)

    @kante.django_field(description="Who claimed this, and when")
    async def assertion(self) -> "Assertion":
        """The act that recorded this claim.

        Non-null: every edge the API builds is row-backed (`from_link`), and a
        `Link` row cannot exist without its assertion. This was nullable for an
        edge built from Apache AGE, a branch nothing can produce any more — the
        one Cypher-built edge shape, `RetrievedGraphPathRender`, has no producer.
        """
        assert self._value.assertion_id is not None, "every edge is built from a Link row, which carries its assertion"
        return cast("Assertion", await loaders.assertion_by_id_loader.load(self._value.assertion_id))

    @classmethod
    def to_subtype(cls, value: RetrievedEdge) -> "Edge":
        """Factory method to create the appropriate Edge subtype based on the value."""
        return cast_edge_to_graphql_type(value)

    @classmethod
    def from_specific(cls: Type[T], subtype: V) -> T:
        """Factory method to convert an Edge subtype back to the base Edge interface."""
        return cls(_value=subtype)


# `Activity` used to be here, with `activity(id:)` and `activities(graph:)`.
# Both matched `n:Activity` or `n.type = 'ACTIVITY'`, and `projector.create_vertex`
# labels a vertex with its *category's* `age_name` and writes exactly
# `{id, category_id}` — so neither the label nor the property has ever been
# written. `activity(id:)` therefore always raised "is not an activity", and
# `activities(graph:)` always returned empty: the same guaranteed-empty shape the
# `assertion`/`assertions` queries were deleted for.
#
# Provenance is an `Assertion` row and is reachable as such: every write payload
# carries one, `Edge.assertion` and `Metric.assertion` resolve one, and
# `richProperties { contributingAssertions }` lists them.


# ===========================================
# RELATION TYPE
# ===========================================


@strawberry.type(description="A relation edge between two entities")
class Relation(Edge[retrieved.RetrievedEdge]):
    """
    A relation is an edge between two entities that establishes a
    non-measurement relationship (e.g., parent-child, part-of).
    """

    _value: strawberry.Private[RetrievedEdge]

    @kante.django_field(description="The node this relation runs from")
    async def source(self, info: kante.Info) -> "Node":
        """The node this relation was claimed about, as the log has it.

        Typed `Node`, and dispatched through `cast_node_to_graphql_type`, because
        `_ENDPOINT_TABLES` says a relation's source is an **instance** — which is
        all three of `Instance.Kind`, not just `ENTITY`. This used to be
        `Entity(_value=...)` over an unfiltered `Instance` fetch, so a relation
        claimed about an event reported it as an entity: the same defect
        `VocabNodeTypeMap` was deleted for, reached through a hardcoded
        constructor instead of a label map.
        """
        return cast(Node, cast_node_to_graphql_type(await _endpoint_node(self._value.source_ref, info)))

    @kante.django_field(description="The node this relation runs to")
    async def target(self, info: kante.Info) -> "Node":
        """The node this relation was claimed to reach. See `source`."""
        return cast(Node, cast_node_to_graphql_type(await _endpoint_node(self._value.target_ref, info)))

    @strawberry.field(description="When this relation was created")
    def created_at(self) -> Optional[datetime]:
        return self._value.created_at

    @kante.django_field(description="How the view this was read through draws it, if any view does")
    async def category(self) -> Optional["RelationCategory"]:
        """This relation's category in the view it was read through — see `Entity.category`."""
        if self._value.category_id is None:
            return None
        return await loaders.relation_category_loader.load(self._value.category_id)

    # `properties`, `richProperties`, `measuredFrom` and `measuredTo` used to sit
    # here, and all four were structurally empty: every edge the API builds comes
    # from `RetrievedEdge.from_link`, which writes only `type` and `category_id` —
    # both reserved keys — so `cleaned_properties` was always `{}` and
    # `valid_from`/`valid_to` always null. Edges derive nothing (docs/LOG.md); the
    # temporal claim fields live on `Metric`, not here.


# ===========================================
# STRUCTURE RELATION TYPE
# ===========================================


@strawberry.type(description="A relation edge between two structures")
class StructureRelation(Edge):
    """
    A structure relation connects two structures (e.g., containment, adjacency).
    """

    _value: strawberry.Private[RetrievedEdge]

    @kante.django_field(description="The structure this relation runs from")
    async def source(self, info: kante.Info) -> Structure:
        """The structure this relation was claimed about."""
        return Structure(_value=await _endpoint_structure(self._value.source_ref, info))

    @kante.django_field(description="The structure this relation runs to")
    async def target(self, info: kante.Info) -> Structure:
        """The structure this relation was claimed to reach."""
        return Structure(_value=await _endpoint_structure(self._value.target_ref, info))

    @strawberry.field(description="When this relation was created")
    def created_at(self) -> Optional[datetime]:
        return self._value.created_at

    @strawberry.field(description="Category ID linking to StructureRelationCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id

    @kante.django_field(description="How the view this was read through draws it, if any view does")
    async def category(self) -> Optional["StructureRelationCategory"]:
        """This claim's category in some view — see `Entity.category`.

        A structure relation has no projection at all, so "some view" is whichever
        declares the word; `None` when none does.
        """
        if self._value.category_id is None:
            return None
        return await loaders.structure_relation_category_loader.load(self._value.category_id)


@kante.type(description="An INFORMS claim: a structure that is evidence for a node")
class Description(Edge):
    pass

    @kante.django_field(description="The structure that is evidence here")
    async def source(self, info: kante.Info) -> Structure:
        """The structure doing the informing.

        Declared as `Metric` before, which was wrong in both halves: an INFORMS
        claim runs structure → node, so the source is a structure and the target
        is the node it is evidence for.
        """
        return Structure(_value=await _endpoint_structure(self._value.source_ref, info))

    @kante.django_field(description="What this structure is evidence for — a node, or another claim")
    async def target(self, info: kante.Info) -> "InformsTarget":
        """What the structure informs. Declared as `Structure` before, then `Entity`.

        `Entity` was wrong twice over. `_ENDPOINT_TABLES` types an `INFORMS`
        target as `instance_or_link`: it is any of the three instance kinds, or a
        `Link` when the evidence informs an edge — which is what
        `_attach_supporting_evidence` writes for a relation asserted with
        `supporting_evidence`. Resolving that through `_endpoint_node`, which
        only looks in `Instance`, raised "No node for endpoint" on a non-null
        field for a claim the write API produces on an ordinary path.
        """
        return cast("InformsTarget", await _resolve_informs_target(str(self._value.target_ref), info))


@kante.type(description="A MEASUREMENT claim: a structure measuring an entity")
class Measurement(Edge):
    pass

    @kante.django_field(description="How the view this was read through draws it, if any view does")
    async def category(self) -> Optional["MeasurementCategory"]:
        """This claim's category in some view — see `StructureRelation.category`."""
        if self._value.category_id is None:
            return None
        return await loaders.measurement_category_loader.load(self._value.category_id)

    @kante.django_field(description="The structure that does the measuring")
    async def source(self, info: kante.Info) -> Structure:
        """The structure this measurement was taken from."""
        return Structure(_value=await _endpoint_structure(self._value.source_ref, info))

    @kante.django_field(description="The node being measured")
    async def target(self, info: kante.Info) -> Node:
        """The node this measurement is about.

        `Node`: `_ENDPOINT_TABLES` types a measurement's target as an instance,
        and an event can be measured as readily as an entity.
        """
        return cast(Node, cast_node_to_graphql_type(await _endpoint_node(self._value.target_ref, info)))


@kante.django_type(evidence_models.Assertion, description="Who claimed something, with what tool, and when — one row of the append-only log")
class Assertion:
    """One act of claiming: the provenance half of the BIOLOGIST.md sentence.

    **This is the `evidence.Assertion` row itself.** It used to be an *AGE edge*
    type — `class Assertion(Edge)` — served out of Cypher by `assertion(id:)` and
    `assertions(graph:)`. That surface was vestigial and provably so: nothing in
    the codebase ever wrote an `Assertion` vertex or an `ASSERTED` / `GENERATED`
    relationship, so both queries matched a pattern the projector never creates
    and could only ever return empty.

    It was also broken. Inheriting `Edge` brought `sourceId` / `targetId`, which
    read `unique_left_id` / `unique_right_id` — attributes that live on
    `RetrievedEdge`, while the only thing ever passed in was a
    `RetrievedAssertion` (a `RetrievedNode`). Selecting
    `contributingAssertions { sourceId }` raised `AttributeError`.

    Backed by the Django row directly rather than through a `Retrieved*` adapter,
    because there is no projection to adapt: an assertion is evidence, and
    evidence is the source of truth. That also means `seq` — the log's total
    order — is reachable for the first time.
    """

    id: strawberry.ID = strawberry.field(description="The assertion's durable identity")
    subject: str = strawberry.field(description="Who made the claim — a user id, or the identity of an automated agent")
    app_id: Optional[str] = strawberry.field(description="Which application made the claim")
    action_id: Optional[str] = strawberry.field(description="Which action within that application made the claim")
    action_name: Optional[str] = strawberry.field(description="Human-readable name of the action that produced this assertion")
    asserted_at: datetime = strawberry.field(description="When the claim was made — belief time, the axis `as_of` filters on")
    recorded_at: datetime = strawberry.field(description="When the claim was durably stored — arrival time. Never equal to assertedAt, and for debugging ingest rather than for answering questions")

    @strawberry.field(description="Position in the organization-spanning log. Monotonic, assigned by the database, and the order a replay runs in")
    def seq(self) -> int:
        return int(cast(evidence_models.Assertion, self).seq)


# ===========================================
# THE CLAIMS
#
# `Instance`, `Link` and `Standing` are the recorded statements and the positions
# taken on them — the evidence rows themselves, served the way `Assertion` above
# is, with no projection adapted in between.
#
# **These are what a write returns.** They used to be answered with `Entity` /
# `Relation` / the rest of the `Node` and `Edge` families, which are *drawing*
# shapes: a label, a category, derived properties, a schema version. For a claim no
# view draws — the ordinary outcome of naming a word no graph declares — two of
# those fields could not answer at all (`schemaVersion` is non-null and had no value
# to give; `richProperties` asserted on a category that does not exist) and six more
# were structurally empty. RFC 0003 §1 named the mismatch and fixed only the
# `drawings` half of it.
#
# So: the claim here, the drawing in `NodeDrawing` / `EdgeDrawing`, and nothing
# pretending to be both.
# ===========================================


@kante.django_type(evidence_models.Standing, description="Somebody's position on whether a claim still holds")
class Standing:
    """One vote on a claim: attesting it, or retracting it.

    Not the claim — the claims are `Instance`, `Link`, `Structure` and `Metric`.
    `stands=True` attests and `stands=False` retracts, and both are evidence of the
    same kind: there is no "reinstate" operation, only somebody newly claiming the
    thing is there.

    Neither `targetType` nor `targetId` is exposed. Whatever you reached this
    through *is* the target, and a pair of columns addressing four tables is an
    implementation detail of the log rather than something a client should join on.
    `recordedAt` is absent for the reason its own `help_text` gives: it is arrival
    time, kept for debugging ingest and not for answering questions.
    """

    id: strawberry.ID = strawberry.field(description="This position's own identity")
    stands: bool = kante.django_field(description="Whether the claimant says the claim holds. True attests, False retracts")
    at: datetime = kante.django_field(description="When the position took effect — world time, the axis that decides which claim is newest")
    assertion: Assertion = kante.django_field(description="Who took this position, with what tool, and when they recorded it")


@kante.django_type(evidence_models.Instance, description="A claimed individual — an entity or an event, as the log has it")
class Instance:
    """What somebody claimed exists, independent of any view.

    An `Entity` is how *one graph* draws this; a `NodeDrawing` pairs the two. The
    difference matters most at the moment of writing, when a claim may be drawn
    nowhere: an instance is fully addressable then, and its `id` is the identity a
    client holds afterwards.

    The four "what is known about this thing" fields are asked over the whole
    **component** — every instance somebody has claimed is the same thing — for the
    reason `evidence/identity.py` gives: every observation mints its own instance, so
    asking about the bare row would show one observation's half of the story.

    **There is no `stands` field, and that is the point.** Whether an instance exists
    has no organization-wide answer: `CurrentStanding` deliberately holds no row for
    one, because a graph's selector decides whose claims it counts and two views may
    legitimately disagree. A folded boolean here would have had to be the *unscoped*
    answer — true of nobody's view in particular — sitting next to `drawnIn`, which is
    the real one. So the positions are reported and the folding is left to whoever
    knows which of them they count: `standings` is newest-first, and an empty list
    means nobody has disputed it.
    """

    id: strawberry.ID = strawberry.field(description="The claim's durable identity — a bare uuid, world-unique and stable across reprojects")
    term: "Term" = kante.django_field(description="The organization's word this was first claimed under. Which view draws it, and as what, is decided from the claims")
    created_at: datetime = kante.django_field(description="When the claim was recorded")
    assertion: Assertion = kante.django_field(description="The act that first claimed this exists. Not the latest — for that, read `standings`")

    @strawberry.field(description="What sort of individual this is. Entities and events are told apart here, not by a vertex label — a label is one view's rename of a word")
    def kind(self) -> enums.InstanceKind:
        return enums.InstanceKind(str(cast(evidence_models.Instance, self).kind).upper())

    @strawberry.field(
        description=(
            "Every position anyone has taken on whether this exists, **newest first** by the order "
            "the fold uses. An empty list means nobody has disputed it, which is not the same as "
            "nobody having attested it: silence is not dissent. Two rows disagreeing is an ordinary "
            "state rather than a conflict to resolve. "
            "There is no folded `stands` beside this, deliberately — see the class docstring."
        )
    )
    async def standings(self) -> List[Standing]:
        return cast(List[Standing], await loaders.standings_by_target_loader.load(str(cast(evidence_models.Instance, self).pk)))

    @strawberry.field(description="Every instance claimed to be this same thing, this one included. A component of one means nobody has merged it")
    async def component(self) -> List[strawberry.ID]:
        known = await loaders.known_about_node_loader.load(str(cast(evidence_models.Instance, self).pk))
        return [cast(strawberry.ID, ref) for ref in known.component]

    @strawberry.field(description="What anyone has called this thing, with how many assertions say so. Two words means two people disagreed; one word with a count of two means they agreed")
    async def labels(self) -> List["Label"]:
        known = await loaders.known_about_node_loader.load(str(cast(evidence_models.Instance, self).pk))
        return [Label(_value=label) for label in known.labels]

    @strawberry.field(description="The standing claims that this instance and another are one thing, with who said so")
    async def same_as(self) -> List["Link"]:
        known = await loaders.known_about_node_loader.load(str(cast(evidence_models.Instance, self).pk))
        return cast(List["Link"], list(known.sameness))

    @strawberry.field(description="Every standing claim connecting this thing to something else — relations, participations, classifications and the structures that inform it")
    async def connections(self) -> List["Link"]:
        known = await loaders.known_about_node_loader.load(str(cast(evidence_models.Instance, self).pk))
        return cast(List["Link"], list(known.connections))

    @kante.django_field(description="Every view that actually draws this claim, and the category it draws it under. Empty means no view does, which is an ordinary answer")
    async def drawn_in(self, info: kante.Info) -> List["NodeDrawing"]:
        drawings = await _drawings_for_ref(str(cast(evidence_models.Instance, self).pk), info)
        return [NodeDrawing(_value=drawing) for drawing in drawings]


@kante.django_type(evidence_models.Link, description="A claim relating two things — as the log has it, whether or not any view draws it")
class Link:
    """One row of `evidence.Link`: eight kinds of claim, one shape.

    A `Relation` or a `Measurement` is how a graph *draws* one of these, and three
    of the eight kinds are never drawn at all (measurements and structure relations
    have no AGE edge; `INFORMS` drives derivation instead). So the claim is what a
    write returns, and the drawings say where it went.

    `sourceRef` and `targetRef` are the refs as the log holds them: opaque uuids
    addressing four different tables, which is why `evidence/models.py` says not to
    infer from their shape what they point at. `source` and `target` resolve them —
    by reading `kind`, the only thing that says which end is which.
    """

    id: strawberry.ID = strawberry.field(description="The claim's durable identity — the `Link` primary key")
    term: Optional["Term"] = kante.django_field(description="The organization's word this claim is stated in. Null for a plain INFORMS link, which names no word")
    role: Optional[str] = kante.django_field(description="Which role the source plays, for participation claims — the asserter's own word; the claim names no graph, so no schema names this")
    created_at: datetime = kante.django_field(description="When the claim was recorded")
    assertion: Assertion = kante.django_field(description="The act that made this claim")

    @strawberry.field(description="What this claim says — and therefore what each of its two refs points at")
    def kind(self) -> enums.LinkKind:
        return enums.LinkKind(str(cast(evidence_models.Link, self).kind).upper())

    @strawberry.field(description="The source ref, as the log holds it: an opaque uuid. `source` resolves it")
    def source_ref(self) -> strawberry.ID:
        return cast(strawberry.ID, str(cast(evidence_models.Link, self).source_ref))

    @strawberry.field(description="The target ref, as the log holds it: an opaque uuid. `target` resolves it")
    def target_ref(self) -> strawberry.ID:
        return cast(strawberry.ID, str(cast(evidence_models.Link, self).target_ref))

    @strawberry.field(description="Every position anyone has taken on whether this claim holds, newest first. Empty means nobody has disputed it — see `Instance.standings`, which is the same field asked of a different claim")
    async def standings(self) -> List[Standing]:
        return cast(List[Standing], await loaders.standings_by_target_loader.load(str(cast(evidence_models.Link, self).pk)))

    @strawberry.field(description="What this claim is about, resolved. Null when the ref names a row a redaction has since removed — history rather than an error")
    async def source(self) -> Optional["ClaimEndpoint"]:
        link = cast(evidence_models.Link, self)
        return await _resolve_claim_endpoint(_endpoint_tables(link)[0], str(link.source_ref))

    @strawberry.field(description="What this claim relates it to, resolved. A classification's target is a `Term`, a measurement's is an `Instance`, and an INFORMS link may name another claim")
    async def target(self) -> Optional["ClaimEndpoint"]:
        link = cast(evidence_models.Link, self)
        return await _resolve_claim_endpoint(_endpoint_tables(link)[1], str(link.target_ref))

    @kante.django_field(description="Every view that draws this claim as an edge. Empty for the three kinds that are never drawn, and for a claim whose endpoints no view holds")
    async def drawn_in(self, info: kante.Info) -> List["EdgeDrawing"]:
        drawings = await _drawings_for_link(cast(evidence_models.Link, self), info)
        return [EdgeDrawing(_value=drawing) for drawing in drawings]


#: What a `Link`'s refs can point at. Four members because the two ref columns
#: address four tables — `evidence.Link`'s own docstring says so — and one of them
#: is `Link` itself, since evidence can inform an edge.
ClaimEndpoint = Annotated[
    Union[Instance, "Structure", Link, "Term"],
    strawberry.union("ClaimEndpoint", description="Either end of a claim: another claim, an external datum, or one of the organization's words"),
]

#: What an `INFORMS` claim's target can be — a node, or another claim.
#:
#: `_attach_supporting_evidence` writes an `INFORMS` link against a `Link` pk when
#: the evidence informs an *edge* rather than a node, which is the ordinary result
#: of asserting a relation with `supporting_evidence`. `Description.target` was
#: typed `Entity!` and resolved through `_endpoint_node`, which looks only in
#: `Instance` — so that perfectly good claim raised "No node for endpoint" on a
#: non-null field. `Link.target` already handled the case correctly through
#: `ClaimEndpoint`; this is the same treatment, narrowed to the two tables
#: `_ENDPOINT_TABLES` actually names for `INFORMS`.
InformsTarget = Annotated[
    Union["Entity", "NaturalEvent", "ProtocolEvent", Link],
    strawberry.union("InformsTarget", description="What a structure is evidence for: a node, or another claim"),
]

#: Which table each end of a link names, by kind. The same table `docs/LOG.md`
#: prints, and the reason `source`/`target` never guess from the ref: every kind of
#: ref looks alike, so `kind` is the discriminator.
#:
#: `INFORMS` is the one with two possible targets — `_attach_supporting_evidence`
#: writes it against a `Link` pk when the evidence informs an edge rather than a
#: node — so its target is tried as an instance and then as a link.
_ENDPOINT_TABLES: dict[str, tuple[str, str]] = {
    evidence_models.Link.Kind.RELATION: ("instance", "instance"),
    evidence_models.Link.Kind.SAME_AS: ("instance", "instance"),
    evidence_models.Link.Kind.PARTICIPATES_AS_INPUT: ("instance", "instance"),
    evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT: ("instance", "instance"),
    evidence_models.Link.Kind.MEASUREMENT: ("structure", "instance"),
    evidence_models.Link.Kind.STRUCTURE_RELATION: ("structure", "structure"),
    evidence_models.Link.Kind.CLASSIFIES: ("instance", "term"),
    evidence_models.Link.Kind.INFORMS: ("structure", "instance_or_link"),
}


def _endpoint_tables(link: evidence_models.Link) -> tuple[str, str]:
    """Which table each end of this link names."""
    return _ENDPOINT_TABLES.get(str(link.kind), ("instance", "instance"))


async def _resolve_claim_endpoint(table: str, ref: str) -> Optional[Any]:
    """Load one end of a link out of the table its kind names.

    Through the per-pk loaders, so selecting both ends of a page of claims costs one
    query per table rather than two per claim. A `Structure` is wrapped on the way
    out because that type is a reading of a row rather than the row itself — the one
    member of `ClaimEndpoint` that is not served directly.
    """
    if table == "term":
        return await loaders.term_by_id_loader.load(ref)
    if table == "structure":
        row = await loaders.structure_by_id_loader.load(ref)
        return Structure(_value=RetrievedStructure.from_row(get_controller(), row)) if row is not None else None
    if table == "instance_or_link":
        return await loaders.instance_by_id_loader.load(ref) or await loaders.link_by_id_loader.load(ref)
    return await loaders.instance_by_id_loader.load(ref)


async def _resolve_informs_target(ref: str, info: kante.Info) -> Any:
    """What an `INFORMS` claim points at: a node if the ref names one, else a claim.

    The drawing-typed counterpart of `_resolve_claim_endpoint`'s
    `instance_or_link` branch. A node comes back as its `Node` subtype — through
    `cast_node_to_graphql_type`, so an event is an event — while a link comes back
    as the `Link` row, which is what `Link.target` already serves for this case.

    Tries the instance first because that is the common shape; the `Link` branch
    is reached only for evidence attached to an edge.
    """
    node = await loaders.instance_by_id_loader.load(ref)
    if node is not None:
        return cast_node_to_graphql_type(await _endpoint_node(ref, info))

    link = await loaders.link_by_id_loader.load(ref)
    if link is None:
        raise ValueError(f"No node or claim for endpoint '{ref}'")
    get_controller()._assert_can_access(link.organization, info)
    return link


# ===========================================
# COMMENTS
#
# A `Comment` is a claim — a remark somebody made about a structure — served the
# way `Instance` and `Link` are: the evidence row itself, with the assertion as
# its provenance. The rich body is lok's descendant tree, stored verbatim; the
# types below are how a client renders it, and they mirror lok's komment types
# so a lok frontend can move to this API without reshaping anything but the
# mention field, which names a subject rather than a user row.
# ===========================================


@strawberry.interface(description="One node of a comment's rich body. The tree lok's komment app renders: paragraphs holding leaves and mentions")
class Descendant:
    _value: strawberry.Private[dict]

    @strawberry.field(description="The kind of this node")
    def kind(self) -> enums.DescendantKind:
        return enums.DescendantKind(str(self._value.get("kind")))

    @strawberry.field(description="The children of this node. Always empty for leafs")
    def children(self) -> Optional[List["Descendant"]]:
        raw = self._value.get("children")
        if raw is None:
            return None
        return [cast_descendant(child) for child in raw]

    @strawberry.field(description="The subtree as raw JSON, for clients that render it themselves rather than selecting the typed tree")
    def unsafe_children(self) -> Optional[AnyScalar]:
        return self._value.get("children")


@strawberry.type(description="A leaf of styled text. Ends a branch of the tree")
class LeafDescendant(Descendant):
    @strawberry.field(description="The text of the leaf")
    def text(self) -> Optional[str]:
        return self._value.get("text")

    @strawberry.field(description="Render this text bold")
    def bold(self) -> Optional[bool]:
        return self._value.get("bold")

    @strawberry.field(description="Render this text italic")
    def italic(self) -> Optional[bool]:
        return self._value.get("italic")

    @strawberry.field(description="Render this text underlined")
    def underline(self) -> Optional[bool]:
        return self._value.get("underline")

    @strawberry.field(description="Render this text as code")
    def code(self) -> Optional[bool]:
        return self._value.get("code")


@strawberry.type(description="A mention of a subject — the same id `Assertion.subject` carries, never a user row: a comment is evidence, and the evidence layer knows actors by subject")
class MentionDescendant(Descendant):
    @strawberry.field(description="The mentioned subject id")
    def subject(self) -> Optional[str]:
        return self._value.get("user")


@strawberry.type(description="A paragraph of the comment body")
class ParagraphDescendant(Descendant):
    @strawberry.field(description="The size of the paragraph")
    def size(self) -> Optional[str]:
        return self._value.get("size")


def cast_descendant(node: dict) -> Descendant:
    """Pick the GraphQL type for one stored tree node, from its own `kind`.

    Total over `DescendantKind` because `evidence.comments.validate_descendants`
    refused anything else at write time — a stored tree is forever, so the write
    is where the shape is enforced and this dispatch gets to be simple.
    """
    match node.get("kind"):
        case "LEAF":
            return LeafDescendant(_value=node)
        case "MENTION":
            return MentionDescendant(_value=node)
        case "PARAGRAPH":
            return ParagraphDescendant(_value=node)
        case unknown:
            raise ValueError(f"Stored descendant has unknown kind '{unknown}' — the write-time validation should have refused it")


@kante.django_type(evidence_models.Comment, description="A remark somebody made about a structure — a claim, as the log has it")
class Comment:
    """One row of `evidence.Comment`, served like `Instance` and `Link`.

    What lok kept as mutable state is read as evidence here: the author and time
    are the `assertion`, and `resolved` is the fold over `standings` — a
    retraction is a withdrawal or a resolution, and the standing's own assertion
    says whose position it was. Unlike an instance, a comment's fold is honest
    at organization grain: no graph selector ever scopes whether a remark
    stands, so one boolean is everyone's answer.
    """

    id: strawberry.ID = strawberry.field(description="The claim's durable identity — a bare uuid")
    created_at: datetime = kante.django_field(description="When the remark was recorded")
    text: str = kante.django_field(description="The plain-text rendering of the body's leaves. Searchable; the body itself is `descendants`")
    assertion: Assertion = kante.django_field(description="The act of commenting: who said it, with which app, and when")

    @kante.django_field(description="The external datum this remark is about. The structure carries the thread")
    async def structure(self) -> "Structure":
        row = await loaders.structure_by_id_loader.load(str(cast(evidence_models.Comment, self).structure_id))
        return Structure(_value=RetrievedStructure.from_row(get_controller(), row))

    @kante.django_field(description="The comment this replies to, for threading. Null for a top-level remark")
    async def parent(self) -> Optional["Comment"]:
        parent_id = cast(evidence_models.Comment, self).parent_id
        if parent_id is None:
            return None
        return cast(Optional["Comment"], await loaders.comment_by_id_loader.load(str(parent_id)))

    @strawberry.field(description="The direct replies to this comment, oldest first — a thread reads downward")
    async def replies(self) -> List["Comment"]:
        return cast(List["Comment"], await loaders.replies_by_comment_loader.load(str(cast(evidence_models.Comment, self).pk)))

    @strawberry.field(description="The rich body — the tree of paragraphs, leaves and mentions, as it was posted")
    def descendants(self) -> List[Descendant]:
        return [cast_descendant(node) for node in cast(evidence_models.Comment, self).descendants]

    @strawberry.field(description="The subjects mentioned in the body, extracted at write time")
    def mentions(self) -> List[str]:
        return [str(subject) for subject in cast(evidence_models.Comment, self).mentions]

    @strawberry.field(description="Every position anyone has taken on whether this remark still stands, newest first. Empty means nobody has withdrawn or resolved it")
    async def standings(self) -> List[Standing]:
        return cast(List[Standing], await loaders.standings_by_target_loader.load(str(cast(evidence_models.Comment, self).pk)))

    @strawberry.field(description="Whether the winning position says this remark no longer stands — resolved by a reviewer or withdrawn by its author; `standings` says which and by whom. The fold a comment can honestly carry, because nothing scopes it per view")
    async def resolved(self) -> bool:
        rows = await loaders.standings_by_target_loader.load(str(cast(evidence_models.Comment, self).pk))
        newest = rows[0] if rows else None
        return newest is not None and not newest.stands


@sync_to_async
def _drawings_for_link(link: evidence_models.Link, info: kante.Info) -> List[results.EdgeDrawing]:
    """Every view that draws this claim as an edge, read back from the projections.

    The edge counterpart of `_drawings_for_ref`, and it authorizes the same way: the
    row says which organization it belongs to, and the caller is checked against it.
    """
    controller = get_controller()
    controller._assert_can_access(link.organization, info)
    return list(controller.drawings_for_edge(link))


@kante.type(description="A claim that two instances are one thing")
class Sameness(Edge):
    """An equivalence claim between two entities.

    Every observation mints its own instance, so identity between observations is
    a claim like any other — contestable, retractable, and carrying the assertion
    of whoever made it.
    """

    pass

    @kante.django_field(description="One of the two instances claimed to be the same")
    async def source(self, info: kante.Info) -> Node:
        """Either end; sameness has no primary, so neither is 'the' node.

        `Node`, not `Entity`: `assertSameInstance` accepts "entities or events
        alike", so a sameness claim over two protocol events is an ordinary
        write — and this used to report both ends as entities.
        """
        return cast(Node, cast_node_to_graphql_type(await _endpoint_node(self._value.source_ref, info)))

    @kante.django_field(description="The other instance claimed to be the same")
    async def target(self, info: kante.Info) -> Node:
        """See `source` — the order records who was named first, nothing more."""
        return cast(Node, cast_node_to_graphql_type(await _endpoint_node(self._value.target_ref, info)))


@kante.type(description="A CLASSIFIES claim: somebody's word for what a node is")
class Classification(Edge):
    """ "This node is an AIS", as a claim rather than a column.

    It had no type of its own, and `cast_edge_to_graphql_type` reported one as a
    `Relation` — the same fails-green defect participations had, where a shape
    the dispatch did not recognise came back wearing a plausible type instead of
    failing. `retractLinks` can retract a classification, so the case was
    reachable and `tests/api/test_batch_claims.py` already documented the answer
    as wrong.

    The target is a **term**, not a node: a classification runs node → word. That
    is what makes it readable by every view declaring the same word, and it is
    why this type has `term` rather than the `target` its siblings carry.
    """

    pass

    @kante.django_field(description="The node this word was claimed about")
    async def source(self, info: kante.Info) -> Node:
        """Whatever was classified.

        The interface rather than `Entity`: events are classified too, and a
        narrower annotation would fail to resolve for every one of them — the
        mistake `OutputParticipation.source` records having already made.
        """
        return cast(Node, cast_node_to_graphql_type(await _endpoint_node(self._value.source_ref, info)))

    @kante.django_field(description="The organization's word that was claimed")
    async def term(self) -> Optional["Term"]:
        """The word itself.

        Nullable because the claim names a term by id and a term can, in
        principle, have been removed by a redaction; a claim whose word is gone is
        history rather than an error.
        """
        return cast(Optional["Term"], await loaders.term_by_id_loader.load(self._value.target_ref))


@kante.type(description="A claim that an entity went into an event")
class InputParticipation(Edge):
    pass

    @kante.django_field(description="The role the node played going in, if the claim recorded one")
    async def role(self) -> Optional[str]:
        """The caller's own word for how this node took part.

        Nullable, because `Link.role` is: a participation claim need not name a
        role, and this used to answer `"participant"` for one that did not —
        inventing a word nobody claimed, on a column whose own `Link.role` field
        reports the absence honestly.
        """
        return self._value.role

    @kante.django_field(description="The event the node went into")
    async def target(self, info: kante.Info) -> Event:
        """The event this participation names.

        `participation_key` stores the node as `source_ref` and the event as
        `target_ref` on **both** sides, so the event is always the target ref
        regardless of which way the drawn edge runs.
        """
        return cast(Event, cast_node_to_graphql_type(await _endpoint_node(self._value.target_ref, info)))

    @kante.django_field(description="The node that took part")
    async def source(self, info: kante.Info) -> Node:
        """The node this participation is about.

        `Node`, not `Entity`: the ref names an instance, and nothing stops an
        event from participating in another event.
        """
        return cast(Node, cast_node_to_graphql_type(await _endpoint_node(self._value.source_ref, info)))


@kante.type(description="A claim that an entity came out of an event")
class OutputParticipation(Edge):
    pass

    @kante.django_field(description="The role the node played coming out, if the claim recorded one")
    async def role(self) -> Optional[str]:
        """The caller's own word for how this node came out. See `InputParticipation.role`."""
        return self._value.role

    @kante.django_field(description="The node that came out")
    async def source(self, info: kante.Info) -> Node:
        """The node this participation is about.

        **This used to be `target`, and that was the bug.** An output edge is
        *drawn* event → node, so naming the node "target" described the drawing;
        but `Edge.sourceId`, which every `Edge` inherits, reports `source_ref` and
        is documented as "the source endpoint, as evidence names it". So
        `sourceId` and `source` named opposite ends of the same edge, and nothing
        on the type said so.

        The claim is what the API reports, so both now follow the refs:
        `source`/`sourceId` are the node, `target`/`targetId` the event, exactly
        as on `InputParticipation`. Which way a view *draws* it is a property of
        the drawing — see `projector.edge_pattern_for` — and is not a thing one
        word pair can carry alongside the claim's own direction.
        """
        return cast(Node, cast_node_to_graphql_type(await _endpoint_node(self._value.source_ref, info)))

    @kante.django_field(description="The event the node came out of")
    async def target(self, info: kante.Info) -> Event:
        """The event this participation names.

        Typed `Event`, not `NaturalEvent`: a protocol event has outputs too, and
        the narrower annotation would have failed to resolve for every one of
        them. Reads `target_ref` — see `source` for why this is no longer the
        drawn direction.
        """
        return cast(Event, cast_node_to_graphql_type(await _endpoint_node(self._value.target_ref, info)))


# Union type for all node subtypes
# `Reagent` and the three `*ShadowLink`s used to be here. None was in the SDL and
# none was constructed anywhere: nothing has ever produced a node typed "REAGENT",
# and `evidence/models.py` records that `Link` "Replaces the `ShadowLink` vertex".
# `Structure` and `Metric` left next: the three members are exactly
# `Instance.Kind`'s three values, which is what a vertex's `type` is written
# from — structures and metrics are evidence rows with no AGE presence, so no
# vertex can carry their type and the cast could never produce them. Both are
# constructed directly (`Structure(_value=…)`) everywhere they surface.
NodeSubtype = Union[Entity, NaturalEvent, ProtocolEvent]

# Union type for all edge subtypes
# `Assertion` is deliberately absent: it is the evidence row now, not an AGE edge.
# `ReifiesAsSource`/`ReifiesAsTarget` used to be here. `RetrievedEdge.from_link`
# sets `type` from `Link.Kind`, whose seven values map onto the seven cases in
# `cast_edge_to_graphql_type` — neither reifies branch was reachable.
EdgeSubtype = Union[Relation, StructureRelation, Description, Measurement, InputParticipation, OutputParticipation, Sameness, Classification]


def cast_node_to_graphql_type(node: RetrievedNode) -> NodeSubtype:
    """Pick the GraphQL type for a node, from what the claim says it is.

    `node_type` is the `type` property, written from `Instance.kind` — so this
    dispatches on the claim's own account of the thing, never on a vertex label,
    which is one view's rename of a word. The `case None` branch that used to sit
    at the bottom guessed from the label and defaulted to `Entity`, which is what
    every drawn event resolved to.

    Args:
        node: The retrieved node, from a projection or from a row

    Returns:
        The appropriate Strawberry type instance (Entity, Structure, etc.)

    Raises:
        ValueError: If the node carries no type, or one nothing can be
    """
    match node.node_type:
        case "ENTITY":
            return Entity(_value=node)
        case "NATURAL_EVENT":
            return NaturalEvent(_value=node)
        case "PROTOCOL_EVENT":
            return ProtocolEvent(_value=node)
        # No `ASSERTION` / `ACTIVITY` branch. Both mapped to `Activity`, a type
        # for a vertex the projector has never written; an assertion is served as
        # the Django row now. No `STRUCTURE` / `METRIC` branch either: `type` is
        # written from `Instance.Kind`, which has exactly the three values above —
        # a structure or metric is never a vertex, so those cases were unreachable.
        case _:
            raise ValueError(f"Unknown node type: {node.node_type}")


def cast_edge_to_graphql_type(edge: RetrievedEdge) -> EdgeSubtype:
    """
    Convert a RetrievedEdge to the appropriate Strawberry type based on its edge_type.

    This matches the pattern from core/types.py's relation_to_edge_subtype function.

    Args:
        edge: The retrieved edge from AGE

    Returns:
        The appropriate Strawberry type instance (Measurement, Assertion edge, etc.)

    Raises:
        ValueError: If the edge type is unknown
    """
    match edge.edge_type:
        case "MEASUREMENT":
            return Measurement(_value=edge)
        case "RELATION":
            return Relation(_value=edge)
        case "STRUCTURE_RELATION":
            return StructureRelation(_value=edge)
        case "SAME_AS":
            return Sameness(_value=edge)
        case "PARTICIPATES_AS_INPUT":
            return InputParticipation(_value=edge)
        case "PARTICIPATES_AS_OUTPUT":
            return OutputParticipation(_value=edge)
        case "INFORMS":
            return Description(_value=edge)
        case "CLASSIFIES":
            return Classification(_value=edge)
        # No `case None` guessing from the label. It read
        # `if "MEASURE" in edge.label.upper()` and otherwise returned `Relation`,
        # which is the defect deleted from `cast_node_to_graphql_type` — "what a
        # thing is comes from the claim, never from the label", because a label is
        # one view's rename of a word. It was also unreachable: every
        # `RetrievedEdge` the API builds comes from `from_link`, which always
        # writes `type` from `Link.Kind`, and no bare constructor call exists.
        # An edge with no type is one an older projector drew — `manage.py
        # reproject`, not a fallback guess.
        case _:
            raise ValueError(f"Unknown edge type: {edge.edge_type}")


# ===========================================
# EDGE ENDPOINTS
# ===========================================


@sync_to_async
def _endpoint_node(ref: Optional[str], info: kante.Info) -> RetrievedNode:
    """The node an edge points at, as the log has it.

    Every `source`/`target` on every edge type used to be
    `raise NotImplementedError("Source fetching not implemented")`, and those
    fields are **non-null in the SDL** — so `relation { source { id } }` was a
    guaranteed error on a query the schema advertised as valid. Relations are
    genuinely projected, so that one was reachable through `relations(...)`; the
    rest were reachable through their by-id fetchers.

    Row-backed rather than read out of a projection, for the reason
    `graph_engine/results.py` gives: an edge is drawn in every view declaring its
    word, so there is no single projection to prefer, and the endpoint's identity
    is the uuid either way.
    """
    from evidence import models as evidence_models

    if ref is None:
        raise ValueError("This edge has no recorded endpoint")

    controller = get_controller()
    # `all_objects` because the organization is what we are looking *up* — the
    # same reason `controller._resolve_instance` uses it — so the tenancy check has
    # to come from the row that was found, and `info` has to reach it. Passing
    # `None` here would skip the check entirely: `_assert_can_access` returns
    # early when it has no request to check against.
    node = evidence_models.Instance.all_objects.filter(pk=str(ref)).select_related("term").first()
    if node is None:
        raise ValueError(f"No node for endpoint '{ref}'")
    controller._assert_can_access(node.organization, info)
    return retrieved.RetrievedNode.from_row(controller, node)


@strawberry.type(description="A word somebody has called this thing, and how much agreement there is")
class Label:
    """One folded classification claim over a thing's whole component.

    Two annotators claiming **different** words give two of these — the conflict
    represented rather than resolved. Two claiming the **same** word give one with
    `assertionCount == 2` — the agreement counted, which is the same distinction
    `__assertionCount` draws on a projected edge.

    Not a `Classification`, deliberately: that is one claim, and this is what
    several of them add up to. A client wanting the individual claims with their
    provenance asks the node's `connections` or the log.
    """

    _value: strawberry.Private[Any]

    @strawberry.field(description="Which instance in the component was called this. Every observation mints its own, so a component's labels may name different ones")
    def node_id(self) -> strawberry.ID:
        return cast(strawberry.ID, self._value.node_ref)

    @kante.django_field(description="The organization's word that was claimed")
    async def term(self) -> Optional["Term"]:
        return cast(Optional["Term"], await loaders.term_by_id_loader.load(str(self._value.term_id)))

    @strawberry.field(description="How many separate assertions say this. Concurrence, not repetition — the log records a claim that restates a position already held precisely so this is countable")
    def assertion_count(self) -> int:
        return self._value.assertion_count

    @kante.django_field(description="The most recent act that claimed this word. Ordered by the log's `seq`, which cannot tie")
    async def latest_assertion(self) -> Optional["Assertion"]:
        if self._value.latest_assertion_id is None:
            return None
        return cast(Optional["Assertion"], await loaders.assertion_by_id_loader.load(str(self._value.latest_assertion_id)))


@sync_to_async
def _drawings_for_ref(ref: str, info: kante.Info) -> List[results.NodeDrawing]:
    """Every view that actually draws this node, read back from the projections.

    **Read back, not approximated.** `projector.graphs_for_refs` answers which
    graphs declare a word admitting this node — a superset, because a graph whose
    category carries a `definition` can still refuse it. `drawings_for_instance` asks
    each candidate view for the vertex and reports only the ones that answer,
    which is what "drawn in" means. Shipping the cheap answer would over-report
    exactly the case defined categories exist for.
    """
    from evidence import models as evidence_models

    controller = get_controller()
    node = evidence_models.Instance.all_objects.filter(pk=str(ref)).first()
    if node is None:
        return []
    controller._assert_can_access(node.organization, info)
    return list(controller.drawings_for_instance(node))


@sync_to_async
def _endpoint_structure(ref: Optional[str], info: kante.Info) -> RetrievedStructure:
    """The structure an edge points at.

    `info` is not optional, and that is the point: `get_structure_by_id` takes it
    as `info: Info | None = None`, and with `None` the tenancy check inside
    `_resolve_structure` short-circuits — so a resolver that omitted it would
    read another tenant's structure through any edge id.
    """
    if ref is None:
        raise ValueError("This edge has no recorded endpoint")
    return get_controller().get_structure_by_id(str(ref), info)


# ===========================================
# ASSERTION RESULTS — what a write hands back
#
# A write is an act of claiming, and where the claim materializes is a *list*:
# possibly empty, possibly long. These types are that shape. See
# `graph_engine/results.py` for the reasoning and
# `docs/rfcs/0003-undrawn-nodes.md` for what they replace.
# ===========================================


@strawberry.type(description="One view that draws a claimed node, and how it draws it")
class NodeDrawing:
    _value: strawberry.Private[results.NodeDrawing]

    @strawberry.field(description="The view this drawing belongs to")
    def graph(self) -> Graph:
        return cast(Graph, self._value.graph)

    @strawberry.field(description="The category this view draws the claim under — what the word means here")
    def category(self) -> "Category":
        return cast(Category, self._value.category)

    @strawberry.field(description="The node as this view holds it, with the properties this view derives. Its graph and label are true here, which they cannot be on a result that stands for every view at once")
    def node(self) -> Node:
        return cast(Node, cast_node_to_graphql_type(self._value.node))


@strawberry.type(description="One view that draws a claimed edge, and how it draws it")
class EdgeDrawing:
    _value: strawberry.Private[results.EdgeDrawing]

    @strawberry.field(description="The view this drawing belongs to")
    def graph(self) -> Graph:
        return cast(Graph, self._value.graph)

    @strawberry.field(description="The category this view draws the claim under. A participation names the *event's* category, which is a node category — hence the base interface rather than EdgeCategory")
    def category(self) -> "Category":
        return cast(Category, self._value.category)

    @strawberry.field(description="The edge as this view holds it")
    def edge(self) -> Edge:
        return cast(Edge, cast_edge_to_graphql_type(self._value.edge))


_DRAWINGS_DESCRIPTION = (
    "Every view that draws this claim, after this assertion. Empty means no view does — "
    "which is an ordinary answer, not an error: a claim names a word the organization owns, "
    "and a view that declares no category for that word simply will not draw it. "
    "For a retraction this is usually empty and deliberately not hardcoded so: existence is "
    "folded under each view's own selector, so a view that does not count the retracting "
    "subject still draws the node."
)

_CLAIM_DESCRIPTION = "What was claimed, as the log has it. Not a drawing of it: derived properties, a label and a category are one view's account and live on each entry in `drawings`. This is addressable whether or not any view draws it, which is the case a write has to answer for."

_ASSERTION_DESCRIPTION = "The claim this call recorded. Not the subject's original assertion — for an attestation or a retraction those are different acts, possibly years apart."


@strawberry.type(description="An assertion about an entity: the act, the claim it recorded, and everywhere that claim is now drawn")
class AssertedEntity:
    """Three fields, and none of them a drawing of the thing claimed.

    `instance` used to be `entity: Entity!` — a graph-shaped type standing for a
    claim that may be in no graph at all. Two of its fields could not answer for
    that case (`schemaVersion` is non-null with no value to give, `richProperties`
    asserted on a category that does not exist), six more were empty by
    construction, and `drawnIn` said what `drawings` already says. The claim is an
    `Instance`; how a view holds it is a `NodeDrawing`.
    """

    _value: strawberry.Private[results.Asserted]

    @strawberry.field(description=_ASSERTION_DESCRIPTION)
    def assertion(self) -> Assertion:
        return cast(Assertion, self._value.assertion)

    @strawberry.field(description=_CLAIM_DESCRIPTION)
    def instance(self) -> Instance:
        return cast(Instance, self._value.subject)

    @strawberry.field(description=_DRAWINGS_DESCRIPTION)
    def drawings(self) -> List[NodeDrawing]:
        return [NodeDrawing(_value=drawing) for drawing in self._value.drawings]


@strawberry.type(description="An assertion about a natural event, and everywhere it is now drawn")
class AssertedNaturalEvent:
    _value: strawberry.Private[results.Asserted]

    @strawberry.field(description=_ASSERTION_DESCRIPTION)
    def assertion(self) -> Assertion:
        return cast(Assertion, self._value.assertion)

    @strawberry.field(description=_CLAIM_DESCRIPTION)
    def instance(self) -> Instance:
        return cast(Instance, self._value.subject)

    @strawberry.field(description=_DRAWINGS_DESCRIPTION)
    def drawings(self) -> List[NodeDrawing]:
        return [NodeDrawing(_value=drawing) for drawing in self._value.drawings]


@strawberry.type(description="An assertion about a protocol event, and everywhere it is now drawn")
class AssertedProtocolEvent:
    _value: strawberry.Private[results.Asserted]

    @strawberry.field(description=_ASSERTION_DESCRIPTION)
    def assertion(self) -> Assertion:
        return cast(Assertion, self._value.assertion)

    @strawberry.field(description=_CLAIM_DESCRIPTION)
    def instance(self) -> Instance:
        return cast(Instance, self._value.subject)

    @strawberry.field(description=_DRAWINGS_DESCRIPTION)
    def drawings(self) -> List[NodeDrawing]:
        return [NodeDrawing(_value=drawing) for drawing in self._value.drawings]


@strawberry.type(description="An assertion about several instances made as one act, and everywhere they are now drawn")
class AssertedInstances:
    """A batch, and one type covers it.

    It needed a polymorphic `[Node!]!` while the payload was drawing-shaped, because
    an entity and an event are different GraphQL types. An `Instance` carries its
    own `kind`, so the caller reads it off the claim instead of writing
    `... on NaturalEvent`.

    **Named `AssertedInstances`, and it was `AssertedNodes`.** A `Node` is what a
    *graph* has — the drawing shape — while this payload is an organization-scoped
    claim write that mints `Instance` rows and names no graph. Its own field has
    always been `instances`; only the type name still said "nodes", which is the
    word the vocabulary work separated. The singular payloads (`AssertedEntity`,
    `AssertedRelation`, …) were already right; this was the batch form's leftover.
    """

    _value: strawberry.Private[results.Asserted]

    @strawberry.field(description="The single claim covering the whole batch. One act by one actor is one assertion, which is why this is not a list")
    def assertion(self) -> Assertion:
        return cast(Assertion, self._value.assertion)

    @strawberry.field(description="The instances this act was about, as the log has them")
    def instances(self) -> List[Instance]:
        return [cast(Instance, subject) for subject in self._value.subjects]

    @strawberry.field(description=_DRAWINGS_DESCRIPTION)
    def drawings(self) -> List[NodeDrawing]:
        return [NodeDrawing(_value=drawing) for drawing in self._value.drawings]


@strawberry.type(description="An assertion about a relation, and everywhere that relation is now drawn")
class AssertedRelation:
    _value: strawberry.Private[results.Asserted]

    @strawberry.field(description=_ASSERTION_DESCRIPTION)
    def assertion(self) -> Assertion:
        return cast(Assertion, self._value.assertion)

    @strawberry.field(description=_CLAIM_DESCRIPTION)
    def link(self) -> Link:
        return cast(Link, self._value.subject)

    @strawberry.field(description=_DRAWINGS_DESCRIPTION)
    def drawings(self) -> List[EdgeDrawing]:
        return [EdgeDrawing(_value=drawing) for drawing in self._value.drawings]


@strawberry.type(description="An assertion about a measurement — a structure measuring a node")
class AssertedMeasurement:
    """No `drawings`, and the absence is structural, exactly as on `AssertedStructure`.

    Nothing projects a measurement to an AGE edge, so the list could only ever be
    empty — and `AssertedStructure` already gives the argument for omitting rather
    than always-emptying such a field: "an always-empty list would imply it might
    not be". The two shipped opposite answers to the same question; this is the
    one with the reasoning attached.
    """

    _value: strawberry.Private[results.Asserted]

    @strawberry.field(description=_ASSERTION_DESCRIPTION)
    def assertion(self) -> Assertion:
        return cast(Assertion, self._value.assertion)

    @strawberry.field(description=_CLAIM_DESCRIPTION)
    def link(self) -> Link:
        return cast(Link, self._value.subject)


@strawberry.type(description="An assertion about a structure relation — a claim between two external data")
class AssertedStructureRelation:
    """No `drawings`: both endpoints are structures, which have no vertex for an
    edge to run between. Omitted rather than always-empty — see
    `AssertedMeasurement`."""

    _value: strawberry.Private[results.Asserted]

    @strawberry.field(description=_ASSERTION_DESCRIPTION)
    def assertion(self) -> Assertion:
        return cast(Assertion, self._value.assertion)

    @strawberry.field(description=_CLAIM_DESCRIPTION)
    def link(self) -> Link:
        return cast(Link, self._value.subject)


@strawberry.type(description="An assertion about one participation, and everywhere it is now drawn")
class AssertedParticipation:
    """Polymorphic in the payload, because which side of the event a claim is about
    decides its type — `InputParticipation` or `OutputParticipation`."""

    _value: strawberry.Private[results.Asserted]

    @strawberry.field(description=_ASSERTION_DESCRIPTION)
    def assertion(self) -> Assertion:
        return cast(Assertion, self._value.assertion)

    @strawberry.field(description=_CLAIM_DESCRIPTION)
    def link(self) -> Link:
        return cast(Link, self._value.subject)

    @strawberry.field(description=_DRAWINGS_DESCRIPTION)
    def drawings(self) -> List[EdgeDrawing]:
        return [EdgeDrawing(_value=drawing) for drawing in self._value.drawings]


@strawberry.type(description="An assertion about several link claims made as one act, and everywhere they are now drawn")
class AssertedLinks:
    """A batch of link claims — `retractLinks` takes classifications, relations,
    participations and INFORMS links alike, and each one reports its own `kind`.

    **Named `AssertedLinks`, and it was `AssertedEdges`** — see
    `AssertedInstances` for the same correction on the node side. `retractLinks`
    was the sharpest case: its own description says it takes "`Link` ids", and it
    returned a payload named for the drawing.
    """

    _value: strawberry.Private[results.Asserted]

    @strawberry.field(description="The single claim covering the whole batch")
    def assertion(self) -> Assertion:
        return cast(Assertion, self._value.assertion)

    @strawberry.field(description="The claims this act was about, as the log has them")
    def links(self) -> List[Link]:
        return [cast(Link, subject) for subject in self._value.subjects]

    @strawberry.field(description=_DRAWINGS_DESCRIPTION)
    def drawings(self) -> List[EdgeDrawing]:
        return [EdgeDrawing(_value=drawing) for drawing in self._value.drawings]


@strawberry.type(description="An assertion that a structure is evidence for a node. Drawings are always empty: an INFORMS claim has no AGE edge")
class AssertedDescription:
    """The payload for `linkStructureToEntity`, which used to return `AssertedStructure`.

    The act records an `INFORMS` `Link` about a structure that already exists — it
    creates no structure — so reporting `structure` named the one thing the write
    did not produce and left the claim it did produce unaddressable. The claim is
    what `description(id:)` reads back as a `Description`.
    """

    _value: strawberry.Private[results.Asserted]

    @strawberry.field(description=_ASSERTION_DESCRIPTION)
    def assertion(self) -> Assertion:
        return cast(Assertion, self._value.assertion)

    @strawberry.field(description=_CLAIM_DESCRIPTION)
    def link(self) -> Link:
        return cast(Link, self._value.subject)


@strawberry.type(description="An assertion that instances are one thing, and the claims it recorded")
class AssertedSameness:
    """No `drawings`, and structurally so: nothing projects a sameness claim.

    What it changes is which nodes a *component* contains, and that shows up in
    every view drawing any member — which is why the controller reprojects them
    all rather than reporting a drawing here.
    """

    _value: strawberry.Private[results.Asserted]

    @strawberry.field(description=_ASSERTION_DESCRIPTION)
    def assertion(self) -> Assertion:
        return cast(Assertion, self._value.assertion)

    @strawberry.field(description="The sameness claims this act recorded. Asserting that three instances are one records every pair among them, under one assertion")
    def links(self) -> List[Link]:
        return [cast(Link, subject) for subject in self._value.subjects]


@strawberry.type(description="An assertion about a structure — a pointer to an external datum")
class AssertedStructure:
    """No `drawings`, and the absence is structural rather than circumstantial.

    A structure lives only in the relational evidence base and has no Apache AGE
    presence at all, so no view can ever draw one. An always-empty list would
    imply it might not be.
    """

    _value: strawberry.Private[results.Asserted]

    @strawberry.field(description=_ASSERTION_DESCRIPTION)
    def assertion(self) -> Assertion:
        return cast(Assertion, self._value.assertion)

    @strawberry.field(description="The structure this act was about")
    def structure(self) -> "Structure":
        # Adapted here rather than in the controller: `Asserted.subjects` carries
        # evidence rows, and `Structure` is a reading of one.
        return Structure(_value=RetrievedStructure.from_row(get_controller(), self._value.subject))


@strawberry.type(description="An assertion about a comment — a remark recorded about a structure")
class AssertedComment:
    """No `drawings`, for the same reason `AssertedStructure` has none: a
    structure has no AGE presence, so neither does its discussion."""

    _value: strawberry.Private[results.Asserted]

    @strawberry.field(description=_ASSERTION_DESCRIPTION)
    def assertion(self) -> Assertion:
        return cast(Assertion, self._value.assertion)

    @strawberry.field(description="The remark this act was about — recorded it, withdrew it, or reopened it; the assertion says which")
    def comment(self) -> Comment:
        return cast(Comment, self._value.subject)


@strawberry.type(description="An assertion about a metric — a measured value about a structure")
class AssertedMetric:
    """No `drawings`, for the same reason `AssertedStructure` has none."""

    _value: strawberry.Private[results.Asserted]

    @strawberry.field(description=_ASSERTION_DESCRIPTION)
    def assertion(self) -> Assertion:
        return cast(Assertion, self._value.assertion)

    @strawberry.field(description="The metric this act was about")
    def metric(self) -> "Metric":
        return Metric(_value=RetrievedMetric.from_row(get_controller(), self._value.subject))


# ===========================================
# RESULT TYPES
# ===========================================
@strawberry.type(description="A rendered node-list result for a saved graph nodes query")
class GraphNodesRender:
    _value: strawberry.Private[retrieved.RetrievedGraphNodesRender]

    @strawberry.field(description="The graph name used for this render")
    def graph_name(self) -> str:
        return self._value.graph_name

    @strawberry.field(description="The graph rendered by this query")
    async def graph(self) -> Graph:
        return await loaders.graph_by_id_loader.load(self._value.graph_id)

    @strawberry.field(description="The graph query used for this render")
    async def query(self) -> GraphNodesQuery:
        return await loaders.graph_nodes_query_by_id_loader.load(self._value.graph_query_id)


@strawberry.interface(description="Base interface for graph render results")
class PathLike:
    nodes: List[Node] = strawberry.field(description="Nodes in the path")
    edges: List[Edge] = strawberry.field(description="Edges in the path")


@strawberry.type(description="A rendered path result for a saved graph path query")
class GraphPathRender(PathLike):
    _value: strawberry.Private[retrieved.RetrievedGraphPathRender]

    @strawberry.field(description="Nodes in the rendered path")
    def nodes(self) -> List[Node]:
        return [cast_node_to_graphql_type(node) for node in self._value.nodes]

    @strawberry.field(description="Edges in the rendered path")
    def edges(self) -> List[Edge]:
        return [cast_edge_to_graphql_type(edge) for edge in self._value.edges]

    @strawberry.field(description="The graph name used for this render")
    def graph_name(self) -> str:
        return self._value.graph_name

    @strawberry.field(description="The graph rendered by this query")
    async def graph(self) -> Graph:
        return await loaders.graph_by_id_loader.load(self._value.graph_id)

    @strawberry.field(description="The graph query used for this render")
    async def query(self) -> GraphPathQuery:
        return await loaders.graph_path_query_by_id_loader.load(self._value.graph_query_id)


@strawberry.type(description="A rendered pairs result for a saved graph pairs query")
class GraphPairsRender:
    _value: strawberry.Private[retrieved.RetrievedGraphPairsRender]

    @strawberry.field(description="The graph name used for this render")
    def graph_name(self) -> str:
        return self._value.graph_name

    @strawberry.field(description="The graph rendered by this query")
    async def graph(self) -> Graph:
        return await loaders.graph_by_id_loader.load(self._value.graph_id)

    @strawberry.field(description="The graph query used for this render")
    async def query(self) -> GraphPairsQuery:
        return await loaders.graph_pairs_query_by_id_loader.load(self._value.graph_query_id)


@strawberry.type(description="A rendered table result for a saved graph table query")
class GraphTableRender:
    _value: strawberry.Private[retrieved.RetrievedGraphTableRender]

    @strawberry.field(description="The graph name used for this render")
    def graph_name(self) -> str:
        return self._value.graph_name

    @strawberry.field(description="The graph rendered by this query")
    async def graph(self) -> Graph:
        return await loaders.graph_by_id_loader.load(self._value.graph_id)

    @strawberry.field(description="The query used to generate this table")
    async def query(self) -> GraphTableQuery:
        return await loaders.graph_table_query_by_id_loader.load(self._value.graph_query_id)

    @strawberry.field(description="Rows of the rendered table")
    def rows(self) -> List[AnyScalar]:
        return self._value.rows


# `LinkStructureResult` used to sit here — `success` + view-grain `Entity` +
# `Structure`, the exact write-payload shape the `Asserted*` family replaced. It
# was referenced by nothing and registered in no schema; `linkStructureToEntity`
# returns `AssertedDescription`.


# ===========================================
# SCHEMA TYPES
# ===========================================


@strawberry.type(description="A validation error from schema validation")
class SchemaValidationError:
    """A single validation error."""

    location: List[str] = strawberry.field(description="Path to the error (e.g., ['extensions', 'entities', 'Neuron'])")
    message: str = strawberry.field(description="Human-readable error message")
    type: str = strawberry.field(default="validation_error", description="Error type")


@strawberry.type(description="Result of validating a schema")
class SchemaValidationResult:
    """Result of schema validation."""

    is_valid: bool = strawberry.field(description="Whether the schema is valid")
    errors: List[SchemaValidationError] = strawberry.field(description="List of validation errors")
    warnings: List[SchemaValidationError] = strawberry.field(description="List of warnings (non-fatal)")


@strawberry.type(description="A graph schema version")
class GraphSchemaType:
    """A versioned schema for a graph."""

    id: int = strawberry.field(description="Database ID of this schema")
    version: str = strawberry.field(description="Semantic version (e.g., '1.0.0')")
    index: int = strawberry.field(description="Sequential index of this version")
    is_active: bool = strawberry.field(description="Whether this is the active schema")
    created_at: datetime = strawberry.field(description="When this schema was created")
    description: Optional[str] = strawberry.field(default=None, description="Description of this version")
    definition: AnyScalar = strawberry.field(description="The full schema definition as JSON")


@strawberry.type(description="Result of setting a new schema")
class SetSchemaResult:
    """Result of setting a new schema version."""

    schema: GraphSchemaType = strawberry.field(description="The created schema")
    activated: bool = strawberry.field(description="Whether the schema was activated")
    migration_required: bool = strawberry.field(default=False, description="Whether existing nodes may need migration")


GraphStats, GraphStatsResolver = create_stats_type(
    model=models.Graph,
    scope=lambda info: models.Graph.objects.filter(organization=get_active_organization(info)),
    filters=filters.GraphFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


EntityCategoryStats, EntityCategoryStatsResolver = create_stats_type(
    model=models.EntityCategory,
    scope=lambda info: models.EntityCategory.objects.filter(graph__organization=get_active_organization(info)),
    filters=filters.EntityCategoryFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


StructureKindStats, StructureKindStatsResolver = create_stats_type(
    model=evidence_models.StructureKind,
    scope=lambda info: evidence_models.StructureKind.objects.for_organization(get_active_organization(info)),
    filters=filters.StructureKindFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


MetricKindStats, MetricKindStatsResolver = create_stats_type(
    model=evidence_models.MetricKind,
    scope=lambda info: evidence_models.MetricKind.objects.for_organization(get_active_organization(info)),
    filters=filters.MetricKindFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


MeasurementCategoryStats, MeasurementCategoryStatsResolver = create_stats_type(
    model=models.MeasurementCategory,
    scope=lambda info: models.MeasurementCategory.objects.filter(graph__organization=get_active_organization(info)),
    filters=filters.MeasurementCategoryFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


RelationCategoryStats, RelationCategoryStatsResolver = create_stats_type(
    model=models.RelationCategory,
    scope=lambda info: models.RelationCategory.objects.filter(graph__organization=get_active_organization(info)),
    filters=filters.RelationCategoryFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


StructureRelationCategoryStats, StructureRelationCategoryStatsResolver = create_stats_type(
    model=models.StructureRelationCategory,
    scope=lambda info: models.StructureRelationCategory.objects.filter(graph__organization=get_active_organization(info)),
    filters=filters.StructureRelationCategoryFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


ProtocolEventCategoryStats, ProtocolEventCategoryStatsResolver = create_stats_type(
    model=models.ProtocolEventCategory,
    scope=lambda info: models.ProtocolEventCategory.objects.filter(graph__organization=get_active_organization(info)),
    filters=filters.ProtocolEventCategoryFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


NaturalEventCategoryStats, NaturalEventCategoryStatsResolver = create_stats_type(
    model=models.NaturalEventCategory,
    scope=lambda info: models.NaturalEventCategory.objects.filter(graph__organization=get_active_organization(info)),
    filters=filters.NaturalEventCategoryFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)
