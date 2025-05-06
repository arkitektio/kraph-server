from core.utils import paginate_querysets
import strawberry
import strawberry_django
from strawberry import auto
from typing import List, Optional, Annotated, Union, cast
import strawberry_django
from core import models, scalars, filters, enums, loaders
from django.contrib.auth import get_user_model
from kante.types import Info
import datetime
from asgiref.sync import sync_to_async
from itertools import chain
from enum import Enum
from core.datalayer import get_current_datalayer
from strawberry.experimental import pydantic
from typing import Union
from strawberry import LazyType
from core import age, pagination as p, filters as f
from strawberry_django.pagination import OffsetPaginationInput
from django.db.models import Q
from authentikate.strawberry.types import Client, User

@strawberry.type(
    description="Temporary Credentials for a file upload that can be used by a Client (e.g. in a python datalayer)"
)
class Credentials:
    """Temporary Credentials for a a file upload."""

    status: str
    access_key: str
    secret_key: str
    session_token: str
    datalayer: str
    bucket: str
    key: str
    store: str


@strawberry.type(
    description="Temporary Credentials for a file upload that can be used by a Client (e.g. in a python datalayer)"
)
class PresignedPostCredentials:
    """Temporary Credentials for a a file upload."""

    key: str
    x_amz_algorithm: str
    x_amz_credential: str
    x_amz_date: str
    x_amz_signature: str
    policy: str
    datalayer: str
    bucket: str
    store: str


@strawberry.type(
    description="Temporary Credentials for a file download that can be used by a Client (e.g. in a python datalayer)"
)
class AccessCredentials:
    """Temporary Credentials for a a file upload."""

    access_key: str
    secret_key: str
    session_token: str
    bucket: str
    key: str
    path: str


@strawberry.type(description="A column definition for a table view.")
class Column:
    name: str
    kind: enums.ColumnKind
    label: str | None = None
    description: str | None = None
    category: strawberry.ID | None = None
    value_kind: enums.MetricKind | None = None
    searchable: bool | None = None
    idfor: list[strawberry.ID] | None = None
    preferhidden: bool | None = None


@strawberry_django.type(models.BigFileStore)
class BigFileStore:
    id: auto
    path: str
    bucket: str
    key: str

    @strawberry.field()
    def presigned_url(self, info: Info) -> str:
        datalayer = get_current_datalayer()
        return cast(models.BigFileStore, self).get_presigned_url(
            info, datalayer=datalayer
        )


@strawberry_django.type(models.MediaStore)
class MediaStore:
    id: auto
    path: str
    bucket: str
    key: str

    @strawberry_django.field()
    def presigned_url(self, info: Info, host: str | None = None) -> str:
        datalayer = get_current_datalayer()
        return cast(models.MediaStore, self).get_presigned_url(
            info, datalayer=datalayer, host=host
        )


@strawberry_django.type(
    models.Experiment, filters=filters.ExperimentFilter, pagination=True
)
class Experiment:
    id: auto
    name: str
    description: str | None
    history: List["History"]
    created_at: datetime.datetime
    creator: User | None



@strawberry_django.type(
    models.GraphSequence, filters=filters.GraphSequenceFilter, pagination=True
)
class GraphSequence:
    graph: "Graph"
    id: auto
    categories: List["BaseCategory"]



def entity_to_node_subtype(
    entity: age.RetrievedEntity,
) -> Union["Structure", "Entity", "Metric", "NaturalEvent", "ProtocolEvent", "Reagent"]:
    match entity.category_type:
        case "STRUCTURE":
            return Structure(_value=entity)
        case "ENTITY":
            return Entity(_value=entity)
        case "REAGENT":
            return Reagent(_value=entity)
        case "METRIC":
            return Metric(_value=entity)
        case "NATURAL_EVENT":
            return NaturalEvent(_value=entity)
        case "PROTOCOL_EVENT":
            return ProtocolEvent(_value=entity)


def relation_to_edge_subtype(
    relation: age.RetrievedRelation,
) -> Union["Measurement", "Relation", "Participant", "Description"]:
    match relation.category_type:
        case "MEASUREMENT":
            return Measurement(_value=relation)
        case "RELATION":
            return Relation(_value=relation)
        case "PARTICIPANT":
            return Participant(_value=relation)
        case "DESCRIPTION":
            return Description(_value=relation)
        
        
    raise Exception(f"Unknown relation type {relation.category_type} for {relation}")

@strawberry_django.type(
    models.Graph,
    filters=filters.GraphFilter,
    pagination=True,
    description="A graph, that contains entities and relations.",
)
class Graph:
    id: auto
    name: str
    description: str | None
    age_name: str
    node_queries: List["NodeQuery"]  = strawberry_django.field(
        description="The list of metric expressions defined in this ontology"
    )
    graph_queries: List["GraphQuery"]  = strawberry_django.field(
        description="The list of metric expressions defined in this ontology"
    )

    # Nodes
    metric_categories: List["MetricCategory"] = strawberry_django.field(
        description="The list of metric expressions defined in this ontology"
    )
    structure_categories: List["StructureCategory"] = strawberry_django.field(
        description="The list of structure expressions defined in this ontology"
    )
    protocol_event_categories: List["ProtocolEventCategory"] = strawberry_django.field(
        description="The list of step expressions defined in this ontology"
    )
    natural_event_categories: List["NaturalEventCategory"] = strawberry_django.field(
        description="The list of step expressions defined in this ontology"
    )
    entity_categories: List["EntityCategory"] = strawberry_django.field(
        description="The list of generic expressions defined in this ontology"
    )
    reagent_categories: List["ReagentCategory"] = strawberry_django.field(
        description="The list of reagent expressions defined in this ontology"
    )

    # Edges
    measurement_categories: List["MeasurementCategory"] = strawberry_django.field(
        description="The list of measurement exprdessions defined in this ontology"
    )
    relation_categories: List["RelationCategory"] = strawberry_django.field(
        description="The list of relation expressions defined in this ontology"
    )

    @strawberry_django.field()
    def node_categories(
        self,
        info: Info,
        filters: filters.NodeCategoryFilter | None = strawberry.UNSET,
        pagination: OffsetPaginationInput | None = strawberry.UNSET,
    ) -> list["NodeCategory"]:
        if pagination is strawberry.UNSET or pagination is None:
            pagination = OffsetPaginationInput()

        sqs = models.StructureCategory.objects.filter(ontology=self)
        gqs = models.EntityCategory.objects.filter(ontology=self)

        if filters is not strawberry.UNSET:
            sqs = strawberry_django.filters.apply(filters, sqs, info)
            gqs = strawberry_django.filters.apply(filters, gqs, info)

        return paginate_querysets(
            sqs, gqs, offset=pagination.offset, limit=pagination.limit
        )

    @strawberry_django.field()
    def edge_categories(
        self,
        info: Info,
        filters: filters.EdgeCategoryFilter | None = strawberry.UNSET,
        pagination: OffsetPaginationInput | None = strawberry.UNSET,
    ) -> list["EdgeCategory"]:

        if pagination is strawberry.UNSET or pagination is None:
            pagination = OffsetPaginationInput()

        sqs = models.MeasurementCategory.objects.filter(ontology=self)
        gqs = models.RelationCategory.objects.filter(ontology=self)

        if filters is not strawberry.UNSET:
            sqs = strawberry_django.filters.apply(filters, sqs, info)
            gqs = strawberry_django.filters.apply(filters, gqs, info)

        return paginate_querysets(
            sqs, gqs, offset=pagination.offset, limit=pagination.limit
        )

    @strawberry_django.field()
    def latest_nodes(
        self,
        info: Info,
        filters: filters.EntityFilter | None = None,
        pagination: p.GraphPaginationInput | None = None,
    ) -> List["Node"]:

        filters = filters or f.EntityFilter()
        pagination = pagination or p.GraphPaginationInput()

        return [
            entity_to_node_subtype(i)
            for i in age.select_latest_nodes(self.age_name, pagination, filter=filters)
        ]

    @strawberry_django.field()
    def pinned(self, info: Info) -> bool:
        return info.context.request.user in self.pinned_by.all()


@strawberry_django.type(
    models.GraphQuery,
    filters=filters.GraphQueryFilter,
    pagination=True,
    description="A view of a graph, that contains entities and relations.",
)
class GraphQuery:
    id: auto
    name: str
    description: str | None
    kind: enums.ViewKind
    graph: Graph
    query: str
    scatter_plots: List["ScatterPlot"]  = strawberry_django.field(
        description="The list of metric expressions defined in this ontology"
    )

    @strawberry_django.field()
    def pinned(self, info: Info) -> bool:
        return info.context.request.user in self.pinned_by.all()

    @strawberry_django.field()
    def render(self, info: Info) -> Union["Path", "Pairs", "Table"]:
        from core.renderers.graph.render import render_graph_query

        return render_graph_query(self)


@strawberry_django.type(
    models.ScatterPlot,
    filters=filters.ScatterPlotFilter,
    pagination=True,
    description="A scatter plot of a table graph, that contains entities and relations.",
)
class ScatterPlot:
    graph: GraphQuery
    id: auto
    name: str
    description: str | None
    id_column: str
    x_column: str
    y_column: str
    color_column: str | None
    size_column: str | None
    shape_column: str | None
    created_at: datetime.datetime


@strawberry_django.type(
    models.NodeQuery,
    filters=filters.NodeQueryFilter,
    pagination=True,
    description="A view of a node entities and relations.",
)
class NodeQuery:
    id: auto
    name: str
    description: str | None
    kind: enums.ViewKind
    graph: Graph
    query: str

    @strawberry_django.field()
    def pinned(self, info: Info) -> bool:
        return info.context.request.user in self.pinned_by.all()

    @strawberry_django.field()
    def render(
        self, info: Info, node_id: strawberry.ID
    ) -> Union["Path", "Pairs", "Table"]:
        from core.renderers.node.render import render_node_view

        return render_node_view(self, node_id)

@strawberry.type()
class NodeQueryView:
    _query: strawberry.Private[models.NodeQuery]
    _node_id: strawberry.Private[str]
    
    
    @strawberry.field()
    def query(self, info: Info) -> "NodeQuery":
        return self._query 
    
    @strawberry_django.field()
    def render(self, info: Info) -> Union["Path", "Pairs", "Table"]:
        from core.renderers.node.render import render_node_view
        return render_node_view(self._query, self._node_id)
    
    
    @strawberry.field()
    def node_id(self, info: Info) -> str:
        return self._node_id


@strawberry.interface
class Node:
    _value: strawberry.Private[age.RetrievedEntity]

    def __hash__(self):
        return self._value.id
    
    @strawberry_django.field(
        description="The unique identifier of the entity within its graph"
    )
    def external_id(self, info: Info) -> str | None:
        return self._value.external_id
    
    @strawberry_django.field(
        description="The unique identifier of the entity within its graph"
    )
    def local_id(self, info: Info) -> str | None:
        return self._value.local_id

    @strawberry_django.field()
    def relevant_queries(self, info: Info) -> List["NodeQuery"]:
        from core.renderers.node.render import render_node_view

        return [
            q
            for q in models.NodeQuery.objects.filter(
               graph__age_name=self._value.graph_name,
               relevant_for_nodes=self._value.category_id
            ).all()
        ]
        
    @strawberry_django.field()
    def views(self, info: Info) -> List["NodeQueryView"]:
        from core.renderers.node.render import render_node_view

        return [
            q
            for q in models.NodeQuery.objects.filter(
               graph__age_name=self._value.graph_name,
               relevant_for_nodes=self._value.category_id
               
            ).annotate(pinned=Q(pinned_by=info.context.request.user)).order_by('-pinned').all()
        ]
        
    @strawberry_django.field(description="The best view of the node given the current context")
    def best_view(self, info: Info ) -> NodeQueryView | None:
        from core.renderers.node.render import render_node_view

        
        best_query = models.NodeQuery.objects.filter(
            graph__age_name=self._value.graph_name,
            relevant_for_nodes=self._value.category_id
        ).annotate(pinned=Q(pinned_by=info.context.request.user)).order_by('pinned').first()
        
        if not best_query:
            return None
        
        
        return NodeQueryView(_query=best_query, _node_id=self._value.unique_id)
        
        
        
        
        
        

    @strawberry.field(
        description="The unique identifier of the entity within its graph"
    )
    async def graph(self, info: Info) -> "Graph":
        return await loaders.graph_loader.load(self._value.graph_name)

    @strawberry_django.field()
    def label(self, info: Info, full: bool | None = None) -> str:
        
        label_string: str = ""
        
        if self._value.external_id:
            label_string += f"{self._value.external_id}"
        else:
            if self._value.local_id:
                label_string += f"{self._value.local_id}"
            else:
                label_string += f"{self._value.id}"
        if full:
            return self._value.kind_age_name +  label_string
        else:
            return label_string

    @strawberry.field(
        description="The unique identifier of the entity within its graph"
    )
    def id(self, info: Info) -> scalars.NodeID:
        return f"{self._value.graph_name}:{self._value.id}"

    @strawberry.field(
        description="The unique identifier of the entity within its graph"
    )
    def graph_id(self, info: Info) -> strawberry.ID:
        return f"{self._value.id}"

    @strawberry_django.field(
        description="The unique identifier of the entity within its graph"
    )
    def right_edges(self, info: Info) -> List["Edge"]:
        return [
            relation_to_edge_subtype(edge)
            for edge in self._value.retrieve_right_relations()
        ]

    @strawberry_django.field(
        description="The unique identifier of the entity within its graph"
    )
    def left_edges(self, info: Info) -> List["Edge"]:
        return [
            relation_to_edge_subtype(edge)
            for edge in self._value.retrieve_left_relations()
        ]

    @strawberry.field(
        description="The unique identifier of the entity within its graph"
    )
    def edges(
        self,
        info: Info,
        filter: filters.EntityRelationFilter | None = None,
        pagination: p.GraphPaginationInput | None = None,
    ) -> List["Edge"]:
        from_arg_relations = []
        if not pagination:
            pagination = p.GraphPaginationInput()

        if not filter:
            filter = filters.EntityRelationFilter()

        if not filter.left_id and not filter.right_id:
            filter.left_id = self._value.unique_id

        return [
            Edge(_value=x)
            for x in age.select_all_relations(
                self._value.graph_name, pagination, filter
            )
        ]


@strawberry.type(
    description="A Structure is a recorded data point in a graph. It can measure a property of an entity through a direct measurement edge, that connects the entity to the structure. It of course can relate to other structures through relation edges."
)
class Structure(Node):
    pass

    def __hash__(self):
        return self._value.id

    @strawberry_django.field(
        description="Protocol steps where this entity was the target"
    )
    async def category(self) -> "StructureCategory":
        return await loaders.structure_category_loader.load(self._value.category_id)

    @strawberry.field(
        description="The unique identifier of the entity within its graph"
    )
    def identifier(self, info: Info) -> str:
        return self._value.identifier

    @strawberry.field(description="The expression that defines this entity's type")
    def object(self, info: Info) -> str:
        return self._value.object
    
    
    @strawberry_django.field(description="The active measurements of this entity according to the graph")
    def active_measurements(self, info: Info) -> List["Measurement"]:
        measurement_categories = models.MeasurementCategory.objects.filter(
            graph__age_name=self._value.graph_name, pinned_by=info.context.request.user
        )
        
        if (measurement_categories.count() == 0):
            return []
        
        
        return [
            Measurement(_value=x)
            for x in age.select_measurements_for_structure(
                self._value.graph_name, self._value.id, categories=measurement_categories
            )
        ]
        
        
        
    
    
    @strawberry.field(description="The expression that defines this entity's type")
    def metrics(self) -> List["Metric"]:
        return []

    @strawberry.field(
        description="The unique identifier of the entity within its graph"
    )
    def measures(self, info: Info) -> List["Entity"]:
        return []



@strawberry.type(description="Playable Role in Protocol Event")
class PlayableEntityRoleInProtocolEvent:
    _role: strawberry.Private[str]
    _category: strawberry.Private[str]
    
    @strawberry.field(description="The unique identifier of the entity within its graph")
    def role(self, info: Info) -> str:
        return self._role
    
    
    @strawberry.field(description="The unique identifier of the entity within its graph")
    async def category(self, info: Info) -> "ProtocolEventCategory":
        return await loaders.protocol_event_category_loader.load(self._category)
    




@strawberry.type(
    description="A Entity is a recorded data point in a graph. It can measure a property of an entity through a direct measurement edge, that connects the entity to the structure. It of course can relate to other structures through relation edges."
)
class Entity(Node):

    def __hash__(self):
        return self._value.id

    @strawberry_django.field(
        description="Protocol steps where this entity was the target"
    )
    async def category(self) -> "EntityCategory":
        return await loaders.entity_category_loader.load(self._value.category_id)
    
    
    @strawberry_django.field(
        description="Subjectable to"
    )
    def subjectable_to(self) -> List["PlayableEntityRoleInProtocolEvent"]:
        # Convert category_id to string since your JSON stores them as strings
       
        category_id_str = str(self._value.category_id)
        entity_cat = models.EntityCategory.objects.get(id=self._value.category_id)

        # Using the contains lookup for JSON fields
        tags = set([str(tag.value) for tag in entity_cat.tags.all()][:1])
        q = Q()
        for tag in tags:
            q |= Q(source_entity_roles__contains=[
            {"category_definition": {"tag_filters": [tag]}}
            ])

        protocol_events =  models.ProtocolEventCategory.objects.filter(
            Q(source_entity_roles__contains=[
            {"category_definition": {"category_filters": [str(entity_cat.id)]}}
            ]) |
            q
        )
        
        playable_roles = []      
           
        for event in protocol_events:
            for source in event.source_entity_roles:
                
                category_filters = source.get("category_definition", {}).get("category_filters", None) 
                tag_filters = source.get("category_definition", {}).get("tag_filters", None)
                
                if category_filters:
                    if category_id_str in category_filters:
                        playable_roles.append(PlayableEntityRoleInProtocolEvent(
                            _role=source["role"],
                            _category=event.id
                        ))
                        continue
                if tag_filters:
                    if tags.intersection(
                        set(tag_filters)
                    ):
                        playable_roles.append(PlayableEntityRoleInProtocolEvent(
                            _role=source["role"],
                            _category=event.id
                        ))
                        continue
                
        return playable_roles
    
    @strawberry_django.field(
        description="Subjectable to"
    )
    def targetable_by(self) -> List["PlayableEntityRoleInProtocolEvent"]:
        # Convert category_id to string since your JSON stores them as strings
       
        category_id_str = str(self._value.category_id)
        entity_cat = models.EntityCategory.objects.get(id=self._value.category_id)

        # Using the contains lookup for JSON fields
        tags = set([str(tag.value) for tag in entity_cat.tags.all()][:1])
        q = Q()
        for tag in tags:
            q |= Q(target_entity_roles__contains=[
            {"category_definition": {"tag_filters": [tag]}}
            ])

        protocol_events =  models.ProtocolEventCategory.objects.filter(
            Q(target_entity_roles__contains=[
            {"category_definition": {"category_filters": [str(entity_cat.id)]}}
            ]) |
            q
        )
        
        playable_roles = []      
           
        for event in protocol_events:
            for target in event.target_entity_roles:
                
                category_filters = target.get("category_definition", {}).get("category_filters", None) 
                tag_filters = target.get("category_definition", {}).get("tag_filters", None)
                
                if category_filters:
                    if category_id_str in category_filters:
                        playable_roles.append(PlayableEntityRoleInProtocolEvent(
                            _role=target["role"],
                            _category=event.id
                        ))
                        continue
                if tag_filters:
                    if tags.intersection(
                        set(tag_filters)
                    ):
                        playable_roles.append(PlayableEntityRoleInProtocolEvent(
                            _role=target["role"],
                            _category=event.id
                        ))
                        continue
                
        return playable_roles
        
        
        

@strawberry.type(
    description="A Entity is a recorded data point in a graph. It can measure a property of an entity through a direct measurement edge, that connects the entity to the structure. It of course can relate to other structures through relation edges."
)
class Reagent(Node):

    def __hash__(self):
        return self._value.id

    @strawberry_django.field(
        description="Protocol steps where this entity was the target"
    )
    async def category(self) -> "ReagentCategory":
        return await loaders.reagent_category_loader.load(self._value.category_id)
    
    
    @strawberry.field(
        description="Subjectable to"
    )
    def usable_in(self) -> List["ProtocolEventCategory"]:
        # Convert category_id to string since your JSON stores them as strings
        category_id_str = str(self._value.category_id)

        # Using the contains lookup for JSON fields
        return models.ProtocolEventCategory.objects.filter(
            source_reagent_roles__contains=[
                {"category_definition": {"category_filters": [category_id_str]}}
            ]
        )
        
    @strawberry.field(
        description="Subjectable to"
    )
    def createable_from(self) -> List["ProtocolEventCategory"]:
        # Convert category_id to string since your JSON stores them as strings
        category_id_str = str(self._value.category_id)

        # Using the contains lookup for JSON fields
        return models.ProtocolEventCategory.objects.filter(
            target_reagent_roles__contains=[
                {"category_definition": {"category_filters": [category_id_str]}}
            ]
        )


@strawberry.type(
    description="A Metric is a recorded data point in a graph. It always describes a structure and through the structure it can bring meaning to the measured entity. It can measure a property of an entity through a direct measurement edge, that connects the entity to the structure. It of course can relate to other structures through relation edges."
)
class Metric(Node):

    def __hash__(self):
        return self._value.id

    @strawberry_django.field(
        description="Protocol steps where this entity was the target"
    )
    async def category(self) -> "MetricCategory":
        return await loaders.metric_category_loader.load(self._value.category_id)

    @strawberry_django.field(description="The value of the metric")
    async def value(self) -> float:
        return self._value.value



@strawberry.type(
    description="A Metric is a recorded data point in a graph. It always describes a structure and through the structure it can bring meaning to the measured entity. It can measure a property of an entity through a direct measurement edge, that connects the entity to the structure. It of course can relate to other structures through relation edges."
)
class NaturalEvent(Node):

    def __hash__(self):
        return self._value.id

    @strawberry_django.field(
        description="Protocol steps where this entity was the target"
    )
    async def category(self) -> "NaturalEventCategory":
        return await loaders.natural_event_category_loader.load(self._value.category_id)
        

    @strawberry_django.field(
        description="Protocol steps where this entity was the target"
    )
    async def valid_from(self) -> datetime.datetime | None:
        return datetime.datetime.fromisoformat(self._value.valid_from) if self._value.valid_from else None

    @strawberry_django.field(
        description="Protocol steps where this entity was the target"
    )
    async def valid_to(self) -> datetime.datetime | None:
        return datetime.datetime.fromisoformat(self._value.valid_to) if self._value.valid_to else None




@strawberry.type(
    description="A Metric is a recorded data point in a graph. It always describes a structure and through the structure it can bring meaning to the measured entity. It can measure a property of an entity through a direct measurement edge, that connects the entity to the structure. It of course can relate to other structures through relation edges."
)
class ProtocolEvent(Node):

    def __hash__(self):
        return self._value.id

    @strawberry_django.field(
        description="Protocol steps where this entity was the target"
    )
    async def category(self) -> "ProtocolEventCategory":
        return await loaders.protocol_event_category_loader.load(
            self._value.category_id
        )

    @strawberry_django.field(
        description="Protocol steps where this entity was the target"
    )
    async def variables(self) -> list["VariableMapping"]:
       return [VariableMapping(_mapping=x) for x in self._value.variables]

    @strawberry_django.field(
        description="Protocol steps where this entity was the target"
    )
    async def valid_from(self) -> datetime.datetime | None:
        return self._value.valid_from

    @strawberry_django.field(
        description="Protocol steps where this entity was the target"
    )
    async def valid_to(self) -> datetime.datetime | None:
        return self._value.valid_to


@strawberry.interface
class Edge:
    _value: strawberry.Private[age.RetrievedRelation]

    def __hash__(self):
        return self._value.id

    @strawberry.field(
        description="The unique identifier of the entity within its graph"
    )
    def id(self, info: Info) -> scalars.NodeID:
        return f"{self._value.graph_name}:{self._value.id}"

    @strawberry_django.field()
    def label(self, info: Info) -> str:
        return self._value.kind_age_name

    @strawberry_django.field()
    def left_id(self, info: Info) -> str:
        return self._value.unique_left_id

    @strawberry_django.field()
    def right_id(self, info: Info) -> str:
        return self._value.unique_right_id

    @strawberry_django.field()
    def left_id(self, info: Info) -> str:
        return self._value.unique_left_id

    @strawberry_django.field()
    def right_id(self, info: Info) -> str:
        return self._value.unique_right_id

    @strawberry_django.field()
    def right(self, info: Info) -> Node:
        return entity_to_node_subtype(
            age.get_age_entity(
                age.to_graph_id(self._value.unique_right_id),
                age.to_entity_id((self._value.unique_right_id)),
            )
        )

    @strawberry_django.field()
    def left(self, info: Info) -> Node:
        return entity_to_node_subtype(
            age.get_age_entity(
                age.to_graph_id(self._value.unique_left_id),
                age.to_entity_id((self._value.unique_left_id)),
            )
        )


@strawberry.type(
    description="""A measurement is an edge from a structure to an entity. Importantly Measurement are always directed from the structure to the entity, and never the other way around."""
)
class Measurement(Edge):

    def __hash__(self):
        return self._value.id

    @strawberry.field(description="Timestamp from when this entity is valid")
    def valid_from(self, info: Info) -> datetime.datetime:
        return datetime.datetime.fromisoformat(self._value.valid_from)

    @strawberry.field(description="Timestamp until when this entity is valid")
    def valid_to(self, info: Info) -> datetime.datetime:
        return datetime.datetime.fromisoformat(self._value.valid_to)


    @strawberry.field(description="When this entity was created")
    def created_at(self, info: Info) -> datetime.datetime:
        return self._value.created_at or datetime.datetime.now()

    @strawberry_django.field()
    async def category(self, info: Info) -> "MeasurementCategory":
        return await loaders.measurement_category_loader.load(self._value.category_id)


@strawberry.type(
    description="""A relation is an edge between two entities. It is a directed edge, that connects two entities and established a relationship
                 that is not a measurement between them. I.e. when they are an subjective assertion about the entities.
                 
                 
                 
                 """
)
class Relation(Edge):

    def __hash__(self):
        return self._value.id

    @strawberry.field(description="Timestamp from when this entity is valid")
    def valid_from(self, info: Info) -> datetime.datetime:
        return self._value.valid_from

    @strawberry.field(description="Timestamp until when this entity is valid")
    def valid_to(self, info: Info) -> datetime.datetime:
        return self._value.valid_to

    @strawberry.field(description="When this entity was created")
    def created_at(self, info: Info) -> datetime.datetime:
        return self._value.created_at or datetime.datetime.now()

    @strawberry_django.field()
    async def category(self, info: Info) -> "RelationCategory":
        return await loaders.relation_category_loader.load(self._value.category_id)


@strawberry.type(
    description="""A participant edge maps bioentitiy to an event (valid from is not necessary)
                 """
)
class Participant(Edge):

    def __hash__(self):
        return self._value.id

    @strawberry.field(description="Timestamp from when this entity is valid")
    def quantity(self, info: Info) -> float | None:
        return self._value.quantity

    @strawberry.field(description="Timestamp from when this entity is valid")
    def role(self, info: Info) -> str:
        return self._value.role
    
    
@strawberry.type(
    description="""A participant edge maps bioentitiy to an event (valid from is not necessary)
                 """
)
class Description(Edge):

    def __hash__(self):
        return self._value.id


@strawberry_django.type(
    models.CategoryTag,
    filters=filters.TagFilter,
    pagination=True,
    description="A tag is a label that can be assigned to entities and relations.",
)
class Tag:
    id: strawberry.ID 
    value: str

@strawberry.interface()
class BaseCategory:
    graph: "Graph" = strawberry.field(
        description="The ontology the expression belongs to."
    )

    description: str | None = strawberry.field(
        description="A description of the expression."
    )
    store: MediaStore | None = strawberry.field(
        description="An image or other media file that can be used to represent the expression."
    )
    id: strawberry.ID = strawberry.field(
        description="The unique identifier of the expression within its graph"
    )
    age_name: str = strawberry.field(
        description="The unique identifier of the expression within its graph"
    )
    color: list[float] | None = strawberry.field()
    kind: enums.ExpressionKind = strawberry.field(description="The kind of expression")
    tags: list["Tag"] = strawberry.field(
        description="The tags that are associated with the expression"
    )
    purl: str | None = strawberry.field(
        description="The unique identifier of the expression within its graph"
    )
    sequence: GraphSequence | None  = strawberry.field(
        description="The sequence of the expression within its graph"
    )
    
    @strawberry_django.field()
    def relevant_queries(self, info: Info) -> List["GraphQuery"]:
        return models.GraphQuery.objects.filter(
            graph=self.graph, relevant_for=self.id
        ).all()
        
    @strawberry_django.field()
    def relevant_node_queries(self, info: Info) -> List["NodeQuery"]:
        return models.NodeQuery.objects.filter(
            graph=self.graph, relevant_for_nodes=self.id
        ).all()
    
    
    @strawberry_django.field()
    def best_query(self, info: Info) -> Optional["GraphQuery"]:
        return models.GraphQuery.objects.filter(
            graph=self.graph, relevant_for=self.id
        ).first()
        
    @strawberry_django.field()
    def pinned(self, info: Info) -> bool:
        return info.context.request.user in self.pinned_by.all()


@strawberry.interface()
class NodeCategory:
    id: strawberry.ID = strawberry.field(
        description="The unique identifier of the expression within its graph"
    )
    position_x: float | None = strawberry.field(
        description="The x position of the node in the graph"
    )
    position_y: float | None = strawberry.field(
        description="The y position of the node in the graph"
    )
    height: float | None = strawberry.field(
        description="The height of the node in the graph"
    )
    width: float | None = strawberry.field(
        description="The width of the node in the graph"
    )
    color: list[float] | None = strawberry.field(
        description="The color of the node in the graph"
    )


    pass


@strawberry.interface()
class CategoryDefintion:
    _graph: strawberry.Private[str]
    _value = strawberry.Private[dict]

    @strawberry.field()
    def tag_filters(self, info: Info) -> list[str] | None:
        return self._value.get("tag_filters", None)

    @strawberry.field()
    def tag_exclude_filters(self, info: Info) -> list[strawberry.ID] | None:
        return self._value.get("tag_exclude_filters", None)

    @strawberry.field()
    def category_filters(self, info: Info) -> list[strawberry.ID] | None:
        return self._value.get("category_filters", None)

    @strawberry.field()
    def category_exclude_filters(self, info: Info) -> list[strawberry.ID] | None:
        return self._value.get("category_exclude_filters", None)


@strawberry.type()
class EntityCategoryDefinition(CategoryDefintion):
    _graph: strawberry.Private[str]
    _value: strawberry.Private[dict]

    @strawberry_django.field()
    def matches(self, info: Info) -> list["EntityCategory"]:
        querysets = models.EntityCategory.objects.filter(graph=self._graph)

        for i in self.tag_filters:
            querysets = querysets.filter(tags__id=i)

        for i in self.tag_exclude_filters:
            querysets = querysets.exclude(tags__id=i)

        for i in self.category_filters:
            querysets = querysets.filter(category__id=i)

        for i in self.category_exclude_filters:
            querysets = querysets.exclude(category__id=i)

        return querysets.all()
    

@strawberry.type()
class StructureCategoryDefinition(CategoryDefintion):
    _graph: strawberry.Private[str]
    _value: strawberry.Private[dict]

    @strawberry_django.field()
    def matches(self, info: Info) -> list["StructureCategory"]:
        querysets = models.StructureCategory.objects.filter(graph=self._graph)

        for i in self.tag_filters:
            querysets = querysets.filter(tags__id=i)

        for i in self.tag_exclude_filters:
            querysets = querysets.exclude(tags__id=i)

        for i in self.category_filters:
            querysets = querysets.filter(category__id=i)

        for i in self.category_exclude_filters:
            querysets = querysets.exclude(category__id=i)

        return querysets.all()


@strawberry.type()
class ReagentCategoryDefinition(CategoryDefintion):
    _graph: strawberry.Private[str]
    _value: strawberry.Private[dict]

    @strawberry_django.field()
    def matches(self, info: Info) -> list["ReagentCategory"]:
        querysets = models.ReagentCategory.objects.filter(graph=self._graph)

        for i in self.tag_filters:
            querysets = querysets.filter(tags__id=i)

        for i in self.tag_exclude_filters:
            querysets = querysets.exclude(tags__id=i)

        for i in self.category_filters:
            querysets = querysets.filter(category__id=i)

        for i in self.category_exclude_filters:
            querysets = querysets.exclude(category__id=i)

        return querysets.all()
    
    


@strawberry.type()
class ReagentRoleDefinition:
    _graph: strawberry.Private[str]
    _value: strawberry.Private[dict]

    @strawberry_django.field()
    def role(self, info: Info) -> str:
        return self._value.get("role", "")

    @strawberry_django.field()
    def category_definition(self, info: Info) -> ReagentCategoryDefinition:
        cat_def = self._value.get("category_definition", None)
        if not cat_def:
            raise ValueError("No category definition found. Integrity error")
        
        
        return ReagentCategoryDefinition(
            _value=cat_def, _graph=self._graph
        )

    @strawberry_django.field()
    def allow_multiple(self, info: Info) -> bool:
        optional = self._value.get("allow_multiple", None)
        if optional is None:
            return False
        return optional
    
    @strawberry_django.field()
    def description(self, info: Info) -> str | None:
        return self._value.get("description", None)
    
    @strawberry_django.field()
    def label(self, info: Info) -> str | None:
        return self._value.get("label", None)
    
    @strawberry_django.field()
    def optional(self, info: Info) -> bool:
        optional = self._value.get("optional", None)
        if optional is None:
            return False
        return optional
    
    @strawberry_django.field()
    def needsQuantity(self, info: Info) -> bool:
        optional = self._value.get("needs_quantity", None)
        if optional is None:
            return False
        return optional
    
    
    @strawberry_django.field()
    def current_default(self, info: Info) -> Optional["Reagent"]:
        cat_def = self._value.get("category_definition", None)
        if not cat_def:
            raise ValueError("No category definition found. Integrity error")
        
        default_use_active = cat_def.get("default_use_active")
        if not default_use_active:
            return None
        
        active = age.get_active_reagent_for_reagent_category(
            models.ReagentCategory.objects.get(id=default_use_active),
        )
        
        return Reagent(_value=active)
        
        


@strawberry.type()
class EntityRoleDefinition:
    _graph: strawberry.Private[str]
    _value: strawberry.Private[dict]

    @strawberry_django.field()
    def role(self, info: Info) -> str:
        return self._value.get("role", "")

    @strawberry_django.field()
    def category_definition(self, info: Info) -> EntityCategoryDefinition:
        return EntityCategoryDefinition(
            _value=self._value.get("category_definition", ""), _graph=self._graph
        )
    
    @strawberry_django.field()
    def allow_multiple(self, info: Info) -> bool:
        optional = self._value.get("allow_multiple", None)
        if optional is None:
            return False
        return optional
    
    @strawberry_django.field()
    def description(self, info: Info) -> str | None:
        return self._value.get("description", None)
    
    @strawberry_django.field()
    def label(self, info: Info) -> str | None:
        return self._value.get("label", None)
    
    @strawberry_django.field()
    def optional(self, info: Info) -> bool:
        optional = self._value.get("optional", None)
        if optional is None:
            return False
        return optional
    
    @strawberry_django.field()
    def current_default(self, info: Info) -> Optional["Entity"]:
        cat_def = self._value.get("category_definition", None)
        if not cat_def:
            raise ValueError("No category definition found. Integrity error")
        
        default_use_active = cat_def.get("default_use_active")
        if not default_use_active:
            return None
        
        active = age.get_active_reagent_for_reagent_category(
            models.ReagentCategory.objects.get(id=default_use_active),
        )
        
        return Reagent(_value=active)
        
        
    
    


@strawberry.interface()
class EdgeCategory:
    id: strawberry.ID = strawberry.field(
        description="The unique identifier of the expression within its graph"
    )
    """ A EdgeExpression is a class that describes the relationship between two entities."""


@strawberry_django.type(
    models.EntityCategory, filters=filters.EntityCategoryFilter, pagination=True
)
class EntityCategory(NodeCategory, BaseCategory):
    """A GenericExpression is a class that describes the relationship between two entities."""

    label: str = strawberry.field(description="The label of the expression")

    

    @strawberry_django.field(
        description="The unique identifier of the expression within its graph"
    )
    def instance_kind(self, info: Info) -> enums.InstanceKind:
        return self.instance_kind if self.instance_kind else enums.InstanceKind.ENTITY


    pass


@strawberry_django.type(
    models.ReagentCategory, filters=filters.ReagentCategoryFilter, pagination=True
)
class ReagentCategory(NodeCategory, BaseCategory):
    """A ReagentCategory is a class of Reagent that describes the relationship between two entities. It is the same as a entity, but should
    be used when designating that this entitiy in this graph is used as a reagent (mostly in protocolevents)
    """

    label: str = strawberry.field(description="The label of the expression")

    

    @strawberry_django.field(
        description="The unique identifier of the expression within its graph"
    )
    def instance_kind(self, info: Info) -> enums.InstanceKind:
        return self.instance_kind if self.instance_kind else enums.InstanceKind.ENTITY

    pass


@strawberry_django.type(
    models.StructureCategory, filters=filters.StructureCategoryFilter, pagination=True
)
class StructureCategory(NodeCategory, BaseCategory):
    identifier: str = strawberry.field(
        description="The structure that this class represents"
    )


@strawberry_django.type(
    models.MetricCategory, filters=filters.MetricCategoryFilter, pagination=True
)
class MetricCategory(NodeCategory, BaseCategory):
    """A MeasurementExpression is a class that describes the relatisonship between two entities."""

    label: str = strawberry.field(description="The label of the expression")
    metric_kind: enums.MetricKind = strawberry.field(
        description="The kind of metric this expression represents"
    )

    @strawberry_django.field(
        description="The unique identifier of the expression within its graph"
    )
    def structure_definition(self, info: Info) -> StructureCategoryDefinition:
        return StructureCategoryDefinition(_value=self.structure_definition, _graph=self.graph.id)

    pass


@strawberry_django.type(
    models.NaturalEventCategory,
    filters=filters.NaturalEventCategoryFilter,
    pagination=True,
)
class NaturalEventCategory(NodeCategory, BaseCategory):
    """A MeasurementExpression is a class that describes the relatisonship between two entities."""

    label: str = strawberry.field(description="The label of the expression")
    plate_children: list[scalars.UntypedPlateChild] | None = strawberry.field(
        description="The children of this plate"
    )

    @strawberry_django.field(
        description="The unique identifier of the expression within its graph"
    )
    def source_entity_roles(self, info: Info) -> List[EntityRoleDefinition]:
        return [EntityRoleDefinition(_value=i, _graph=self.graph.id) for i in self.source_entity_roles]

    @strawberry_django.field(
        description="The unique identifier of the expression within its graph"
    )
    def target_entity_roles(self, info: Info) -> List[EntityRoleDefinition]:
        return [EntityRoleDefinition(_value=i, _graph=self.graph.id) for i in self.target_entity_roles]

    pass


@strawberry.type 
class VariableMapping:
    _mapping: strawberry.Private[dict]
    
    @strawberry_django.field()
    def role(self) -> str:
        return self._mapping.get("param", None)
    
    @strawberry_django.field()
    def value(self) -> str:
        return self._mapping.get("value", None)
    

@strawberry.type
class VariableOption:
    _option: strawberry.Private[dict]
    
    @strawberry_django.field()
    def value(self) -> str:
        return self._option.get("value", None)
    
    @strawberry_django.field()
    def label(self) -> str:
        return self._option.get("label", None)
    
    @strawberry_django.field()
    def description(self) -> str | None:
        return self._option.get("description", None)


@strawberry.type
class VariableDefinition:
    _variable: strawberry.Private[dict]
    _graph: strawberry.Private[str]
    
    @strawberry_django.field()
    def value_kind(self) -> enums.MetricKind:
        return self._variable.get("value_kind", None)
    
    
    @strawberry_django.field()
    def param(self) -> str:
        return self._variable.get("param", None)
    
    @strawberry_django.field()
    def description(self) -> str | None:
        return self._variable.get("description", None)
    
    @strawberry_django.field()
    def label(self) -> str | None:
        return self._variable.get("param", None)
    
    @strawberry_django.field()
    def optional(self) -> bool:
        optional = self._variable.get("optional", None)
        return optional if optional is not None else False
    
    @strawberry_django.field()
    def needs_quantity(self) -> bool:
        return self._variable.get("needs_quantity", False)


    @strawberry_django.field()
    def default(self) -> scalars.Any | None:
        return self._variable.get("default", None)
    
    
    @strawberry_django.field()
    def options(self) -> list[VariableOption] | None:
        options = self._variable.get("options", None)
        if not options:
            return None
        return [VariableOption(_option=i) for i in options]

@strawberry_django.type(
    models.ProtocolEventCategory,
    filters=filters.ProtocolEventCategoryFilter,
    pagination=True,
)
class ProtocolEventCategory(NodeCategory, BaseCategory):
    """A MeasurementExpression is a class that describes the relatisonship between two entities."""

    label: str = strawberry.field(description="The label of the expression")
    plate_children: list[scalars.UntypedPlateChild] | None = strawberry.field(
        description="The children of this plate"
    )

    @strawberry_django.field(
        description="The unique identifier of the expression within its graph"
    )
    def source_entity_roles(self, info: Info) -> List[EntityRoleDefinition]:
        return [EntityRoleDefinition(_value=i, _graph=self.graph.id) for i in self.source_entity_roles]

    @strawberry_django.field(
        description="The unique identifier of the expression within its graph"
    )
    def target_entity_roles(self, info: Info) -> List[EntityRoleDefinition]:
        return [EntityRoleDefinition(_value=i, _graph=self.graph.id) for i in self.target_entity_roles]

    @strawberry_django.field(
        description="The unique identifier of the expression within its graph"
    )
    def source_reagent_roles(self, info: Info) -> List[ReagentRoleDefinition]:
        return [ReagentRoleDefinition(_value=i, _graph=self.graph.id) for i in self.source_reagent_roles]

    @strawberry_django.field(
        description="The unique identifier of the expression within its graph"
    )
    def target_reagent_roles(self, info: Info) -> List[ReagentRoleDefinition]:
        return [ReagentRoleDefinition(_value=i, _graph=self.graph.id) for i in self.target_reagent_roles]
    
    
    @strawberry_django.field()
    def variable_definitions(self, info: Info) -> List[VariableDefinition]:
        return [VariableDefinition(_variable=i, _graph=self.graph.id) for i in self.variable_definitions]



@strawberry_django.type(
    models.RelationCategory, filters=filters.RelationCategoryFilter, pagination=True
)
class RelationCategory(EdgeCategory, BaseCategory):
    """A RelationExpression is a class that describes the relationship between two entities."""

    label: str = strawberry.field(description="The label of the expression")

    @strawberry_django.field(
        description="The unique identifier of the expression within its graph"
    )
    def source_definition(self, info: Info) -> EntityCategoryDefinition:
        return EntityCategoryDefinition(_value=self.source_definition, _graph=self.graph.id)

    @strawberry_django.field()
    def target_definition(self, info: Info) -> EntityCategoryDefinition:
        return EntityCategoryDefinition(_value=self.target_definition, _graph=self.graph.id)


@strawberry_django.type(
    models.MeasurementCategory,
    filters=filters.MeasurementCategoryFilter,
    pagination=True,
)
class MeasurementCategory(EdgeCategory, BaseCategory):
    """A Measurement is a class that describes the relationship between two entities."""

    label: str = strawberry.field(description="The label of the expression")

    @strawberry_django.field(
        description="The unique identifier of the expression within its graph"
    )
    def source_definition(self, info: Info) -> StructureCategoryDefinition:
        return EntityCategoryDefinition(
            _value=self.source_definition, _graph=self.graph.id
        )

    @strawberry_django.field()
    def target_definition(self, info: Info) -> EntityCategoryDefinition:
        return EntityCategoryDefinition(
            _value=self.target_definition, _graph=self.graph.id
        )


@strawberry_django.type(
    models.Model,
    filters=filters.ModelFilter,
    pagination=True,
    description="A model represents a trained machine learning model that can be used for analysis.",
)
class Model:
    id: auto = strawberry.field(description="The unique identifier of the model")
    name: str = strawberry.field(description="The name of the model")
    store: MediaStore | None = strawberry.field(
        description="Optional file storage location containing the model weights/parameters"
    )


@strawberry.type
class Path:
    nodes: list[Node]
    edges: list[Edge]


@strawberry.type(
    description="A paired structure two entities and the relation between them."
)
class Pair:
    left: Node = strawberry.field(description="The left entity.")
    right: Node = strawberry.field(description="The right entity.")
    edge: Edge = strawberry.field(description="The relation between the two entities.")


@strawberry.type(description="A collection of paired entities.")
class Pairs:
    pairs: list[Pair] = strawberry.field(description="The paired entities.")
    graph: Graph = strawberry.field(
        description="The graph this table was queried from."
    )


@strawberry.type(description="A collection of paired entities.")
class Table:
    rows: list[scalars.Any] = strawberry.field(description="The paired entities.")
    columns: list[Column] = strawberry.field(
        description="The columns describind this table."
    )
    graph: Graph = strawberry.field(
        description="The graph this table was queried from."
    )


@strawberry.type
class KnowledgeView:
    _scat: strawberry.Private[models.StructureCategory]
    _structure: strawberry.Private[age.RetrievedEntity]
    
    @strawberry_django.field()
    def structure_category(self) -> "StructureCategory":
        return self._scat
    
    @strawberry_django.field()
    def structure(self) -> Optional["Structure"]:
        if self._structure:
            return Structure(_value=self._structure)
        return None
    