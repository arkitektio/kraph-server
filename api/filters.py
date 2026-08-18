from typing import List, Optional
import strawberry
from core import models, enums
from evidence import models as evidence_models
from django.db.models import Q
import kante
from graph_engine import input_models
from api import inputs


@kante.pydantic_input(input_models.PropertyMatch, all_fields=True, description="A property match condition for filtering structures")
class PropertyMatch:
    """The condition to match for a specific property when filtering structures."""


# `EntityPaginationInput` and `NodePaginationInput` used to be declared here as
# well as in `api/pagination.py`, over the same two pydantic models — empty bodies
# with `all_fields=True` here, explicit `limit`/`offset` there. Nothing imported
# these copies; every resolver takes `pagination.EntityPaginationInput`. Two
# declarations of one input in a module whose own header is about pruning dead
# filter surface.
#
# The node and edge filters below carry `ids` and nothing else, deliberately.
# They used to advertise `hasProperty`, `search` and `matches` — questions about
# a drawn vertex's derived properties — and every node and edge resolver refused
# them at runtime (`_nodes.refuse_drawing_filters`, `_edges.refuse_vertex_filters`),
# so a schema-driven client saw three valid arguments that were guaranteed errors.
# The schema says what the resolvers answer now. `StructureFilter` keeps all
# three because `structures` genuinely honors them, over `Metric` rows.


@kante.pydantic_input(input_models.EntityFilters, description="Filter options for querying entities")
class EntityFilter:
    """Filter options for entity queries."""

    ids: Optional[List[strawberry.ID]] = kante.field(default=None, description="Filter by specific entity IDs")


@kante.pydantic_input(input_models.NodeFilters, description="Filter options for querying nodes")
class NodeFilters:
    """Filter options for node queries."""

    ids: Optional[List[strawberry.ID]] = kante.field(default=None, description="Filter by specific node IDs")


@kante.pydantic_input(input_models.StructureFilters, description="Filter options for querying structures")
class StructureFilter:
    """Filter options for structure queries."""

    ids: Optional[List[strawberry.ID]] = kante.field(default=None, description="Filter by specific structure IDs")
    has_property: Optional[str] = kante.field(default=None, description="Filter structures that have a specific property")
    search: Optional[str] = kante.field(default=None, description="Substring match on the structure's `object` — the external datum it points at. Not its properties: `hasProperty` and `matches` are the ones that go over metrics")
    matches: Optional[List[PropertyMatch]] = kante.field(default=None, description="Filter structures that match specific property conditions")


# `MetricFilter` used to sit here — four fields, referenced by no root field:
# `metrics(metricKindId:)` removed its filter arguments with the note recorded in
# `api/queries/metric.py`, and nothing else ever took one.


@kante.pydantic_input(input_models.NaturalEventFilters, description="Filter options for querying natural events")
class NaturalEventFilter:
    """Filter options for natural event queries."""

    ids: Optional[List[strawberry.ID]] = kante.field(default=None, description="Filter by specific natural event IDs")


@kante.pydantic_input(input_models.ProtocolEventFilters, description="Filter options for querying protocol events")
class ProtocolEventFilter:
    """Filter options for protocol event queries."""

    ids: Optional[List[strawberry.ID]] = kante.field(default=None, description="Filter by specific protocol event IDs")


@kante.pydantic_input(input_models.MeasurementFilters, description="Filter options for querying measurements")
class MeasurementFilter:
    """Filter options for measurement queries."""

    ids: Optional[List[strawberry.ID]] = kante.field(default=None, description="Filter by specific measurement IDs")


@kante.pydantic_input(input_models.StructureRelationFilters, description="Filter options for querying structure relations")
class StructureRelationFilter:
    """Filter options for structure relation queries."""

    ids: Optional[List[strawberry.ID]] = kante.field(default=None, description="Filter by specific structure relation IDs")


@kante.pydantic_input(input_models.RelationFilters, description="Filter options for querying relations")
class RelationFilter:
    """Filter options for relation queries."""

    ids: Optional[List[strawberry.ID]] = kante.field(default=None, description="Filter by specific relation IDs")


@kante.filter_type(models.Graph)
class GraphFilter:
    id: strawberry.auto
    name: strawberry.auto
    description: strawberry.auto

    @kante.filter_field(description="Filter by list of IDs")
    def pinned(self, info: kante.Info, value: bool, prefix: str) -> Q:
        return Q(**{f"{prefix}pinned_by": info.context.request.user})

    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @kante.filter_field(description="Filter by list of IDs")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}name__search": value}) | Q(**{f"{prefix}description__search": value})

    @kante.filter_field(description="Only archived graphs, or only live ones. Omitted shows both")
    def is_archived(self, value: bool, prefix: str) -> Q:
        """The read half of archiving.

        Opt-in rather than excluded by default, matching `pinned` and every other
        filter here. A default exclusion would also hide an archived graph from
        the by-id field, and nothing else could bring it back — the only way to
        unarchive is `updateGraph(archived: false)`, which needs the client to be
        able to find it first.
        """
        return Q(**{f"{prefix}is_archived": value})


@kante.filter_type(models.Category)
class CategoryFilter:
    graph: GraphFilter | None
    id: strawberry.auto
    label: strawberry.auto

    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @kante.filter_field(description="Filter by list of IDs")
    def pinned(self, info: kante.Info, value: bool, prefix: str) -> Q:
        return Q(**{f"{prefix}pinned_by": info.context.request.user})

    @kante.filter_field(description="Filter by list of IDs")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}label__search": value})


@kante.filter_type(models.Category)
class EntityCategoryFilter(CategoryFilter):
    pass

    @kante.filter_field(description="Filter by list of IDs")
    def matches_descriptor(self, info: kante.Info, value: inputs.EntityDescriptorInput, prefix: str) -> Q:
        """Filter entity categories by whether they match a specific identifier pattern."""
        return Q(**{f"{prefix}key__in": value.keys})


@kante.filter_type(evidence_models.MetricKind)
class MetricKindFilter:
    """Filter options for metric kind queries.

    Standalone, deliberately not a `CategoryFilter`: subclassing would re-introduce
    `graph` and `pinned`, neither of which a kind has, and `graph` in particular
    was the only tenant fence the old root fields had. Scoping is now the
    resolver's job.
    """

    ids: Optional[List[strawberry.ID]] = kante.filter_field(default=None, description="Filter by list of IDs")
    search: Optional[str] = kante.filter_field(default=None, description="Search label and key")

    @kante.filter_field(description="Filter by the kind of value this measurement carries")
    def value_kind(self, info: kante.Info, value: enums.ValueKind, prefix: str) -> Q:
        """Filter metric kinds by the kind of value they represent."""
        return Q(**{f"{prefix}value_kind": value})

    @kante.filter_field(description="Filter by the structure kind this describes")
    def structure_kind(self, info: kante.Info, value: strawberry.ID, prefix: str) -> Q:
        """Filter metric kinds by the structure kind they describe."""
        return Q(**{f"{prefix}structure_kind_id": value})


@kante.filter_type(models.Category)
class RelationCategoryFilter(CategoryFilter):
    pass


@kante.filter_type(models.Category)
class MeasurementCategoryFilter(CategoryFilter):
    @kante.filter_field(description="Filter by the structure identifier this measurement's source selects")
    def source_identifier(self, info: kante.Info, value: str, prefix: str) -> Q:
        """Filter measurement categories by the structure identifier they measure.

        This used to read `source__identifier`, a field a measurement category has
        never had, so the filter raised `FieldError` on every use. The source is a
        `StructureDescriptorInput` stored as JSON, so match its `identifiers` list.
        """
        return Q(**{f"{prefix}source_definition__identifiers__contains": [value]})


@kante.filter_type(models.Category)
class NaturalEventCategoryFilter(CategoryFilter):
    pass


@kante.filter_type(models.Category)
class ProtocolEventCategoryFilter(CategoryFilter):
    pass


@kante.filter_type(evidence_models.Term)
class TermFilter:
    """Filter options for the organization's vocabulary.

    Standalone, like `StructureKindFilter`: a term has no graph to filter on, so
    the tenant fence is the resolver's, not the client's.
    """

    ids: Optional[List[strawberry.ID]] = kante.filter_field(default=None, description="Filter by list of IDs")
    search: Optional[str] = kante.filter_field(default=None, description="Search key, label and description")

    @kante.filter_field(description="Filter by what sort of thing the word names")
    def kinds(self, info: kante.Info, value: List[enums.TermKind], prefix: str) -> Q:
        """Narrow to terms of these kinds."""
        return Q(**{f"{prefix}kind__in": [str(kind.value) for kind in value]})

    @kante.filter_field(description="Filter by the words themselves")
    def keys(self, info: kante.Info, value: List[str], prefix: str) -> Q:
        """Narrow to these exact words."""
        return Q(**{f"{prefix}key__in": value})

    @kante.filter_field(description="Filter to terms at least one graph declares a category for")
    def declared(self, info: kante.Info, value: bool, prefix: str) -> Q:
        """Whether any view speaks this word.

        A term with no category is not an error — it is a word somebody described
        before wiring a graph to it, or one whose last view was deleted.
        """
        return Q(**{f"{prefix}categories__isnull": not value})


@kante.filter_type(evidence_models.StructureKind)
class StructureKindFilter:
    """Filter options for structure kind queries. Standalone — see `MetricKindFilter`."""

    ids: Optional[List[strawberry.ID]] = kante.filter_field(default=None, description="Filter by list of IDs")
    search: Optional[str] = kante.filter_field(default=None, description="Search label and identifier")

    @kante.filter_field(description="Filter by structure identifiers")
    def identifiers(self, info: kante.Info, value: List[str], prefix: str) -> Q:
        """Filter structure kinds by identifier."""
        return Q(**{f"{prefix}identifier__in": value})

    @kante.filter_field(description="Filter by whether the kind matches a descriptor")
    def matches_descriptor(self, info: kante.Info, value: inputs.StructureDescriptorInput, prefix: str) -> Q:
        """Filter structure kinds by identifier pattern."""
        return Q(**{f"{prefix}identifier__in": value.identifiers})


@kante.filter_type(models.Category)
class StructureRelationCategoryFilter(CategoryFilter):
    pass


@kante.pydantic_input(input_models.RelationFilters, description="Filter options for querying participation claims")
class ParticipationFilter:
    """Filter options for participation queries.

    Its own type, and it was `RelationFilter`. `inputParticipations` and
    `outputParticipations` list `PARTICIPATES_AS_*` links — a claim that a node
    took part in an event, which is not a relation — so a client reading the
    schema was told to reach for the relation vocabulary to filter something else.
    Backed by the same pydantic model, because the narrowing this actually does
    (`_edges.narrow`) reads `ids` and nothing else on any of them.
    """

    ids: Optional[List[strawberry.ID]] = kante.field(default=None, description="Filter by specific participation IDs")


@kante.filter_type(models.GraphQuery)
class GraphQueryFilter:
    pass

    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @kante.filter_field(description="Full-text search over label and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}label__search": value}) | Q(**{f"{prefix}description__search": value})

    @kante.filter_field(description="Only archived queries, or only live ones. Omitted shows both")
    def archived(self, value: bool, prefix: str) -> Q:
        """Opt-in, for the same reason as `GraphFilter.is_archived`."""
        return Q(**{f"{prefix}archived": value})


@kante.filter_type(models.GraphQuery)
class GraphTableQueryFilter(GraphQueryFilter):
    """Adds nothing to `GraphQueryFilter`; the subclass exists to name the field's type.

    It used to re-declare `search` verbatim — the same two-`Q` body the parent
    already defines — as did its three siblings. The parallel `NodeQuery` and
    `EdgeQuery` families just `pass`, which is what showed the four overrides were
    copy-paste rather than intent.
    """

    pass


@kante.filter_type(models.GraphQuery)
class GraphNodesQueryFilter(GraphQueryFilter):
    """Adds nothing to `GraphQueryFilter`; the subclass exists to name the field's type.

    It used to re-declare `search` verbatim — the same two-`Q` body the parent
    already defines — as did its three siblings. The parallel `NodeQuery` and
    `EdgeQuery` families just `pass`, which is what showed the four overrides were
    copy-paste rather than intent.
    """

    pass


@kante.filter_type(models.GraphQuery)
class GraphPairsQueryFilter(GraphQueryFilter):
    """Adds nothing to `GraphQueryFilter`; the subclass exists to name the field's type.

    It used to re-declare `search` verbatim — the same two-`Q` body the parent
    already defines — as did its three siblings. The parallel `NodeQuery` and
    `EdgeQuery` families just `pass`, which is what showed the four overrides were
    copy-paste rather than intent.
    """

    pass


@kante.filter_type(models.GraphQuery)
class GraphPathQueryFilter(GraphQueryFilter):
    """Adds nothing to `GraphQueryFilter`; the subclass exists to name the field's type.

    It used to re-declare `search` verbatim — the same two-`Q` body the parent
    already defines — as did its three siblings. The parallel `NodeQuery` and
    `EdgeQuery` families just `pass`, which is what showed the four overrides were
    copy-paste rather than intent.
    """

    pass


@kante.filter_type(models.NodeQuery)
class NodeQueryFilter:
    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @kante.filter_field(description="Full-text search over label and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}label__search": value}) | Q(**{f"{prefix}description__search": value})

    @kante.filter_field(description="Only archived queries, or only live ones. Omitted shows both")
    def archived(self, value: bool, prefix: str) -> Q:
        """Opt-in, for the same reason as `GraphFilter.is_archived`."""
        return Q(**{f"{prefix}archived": value})


@kante.filter_type(models.NodeQuery)
class NodeTableQueryFilter(NodeQueryFilter):
    pass


@kante.filter_type(models.NodeQuery)
class NodePairsQueryFilter(NodeQueryFilter):
    pass


@kante.filter_type(models.NodeQuery)
class NodePathQueryFilter(NodeQueryFilter):
    pass


@kante.filter_type(models.EdgeQuery)
class EdgeQueryFilter:
    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @kante.filter_field(description="Full-text search over label and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}label__search": value}) | Q(**{f"{prefix}description__search": value})

    @kante.filter_field(description="Only archived queries, or only live ones. Omitted shows both")
    def archived(self, value: bool, prefix: str) -> Q:
        """Opt-in, for the same reason as `GraphFilter.is_archived`."""
        return Q(**{f"{prefix}archived": value})


@kante.filter_type(models.EdgeQuery)
class EdgeTableQueryFilter(EdgeQueryFilter):
    pass


@kante.filter_type(models.EdgeQuery)
class EdgePairsQueryFilter(EdgeQueryFilter):
    pass


@kante.filter_type(models.EdgeQuery)
class EdgePathQueryFilter(EdgeQueryFilter):
    pass


@kante.filter_type(models.ScatterPlot)
class ScatterPlotFilter:
    id: strawberry.auto
    name: strawberry.auto

    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @kante.filter_field(description="Full-text search over label and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}name__search": value}) | Q(**{f"{prefix}description__search": value})
