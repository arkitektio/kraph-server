from core.utils import paginate_querysets
import strawberry
import strawberry.django
from strawberry import auto
from typing import List, Optional, Annotated, Union, cast
import strawberry_django
from core import models, scalars, filters, enums, loaders
from django.contrib.auth import get_user_model
from koherent.models import AppHistoryModel
from authentikate.models import App as AppModel
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

@strawberry_django.type(AppModel, description="An app.")
class App:
    id: auto
    name: str
    client_id: str


@strawberry_django.type(get_user_model(), description="A user.")
class User:
    id: auto
    sub: str
    username: str
    email: str
    password: str


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




@strawberry.type(
    description="A column definition for a table view."
)
class Column:
    name: str
    kind: enums.ColumnKind
    label: str | None = None
    description: str | None = None
    expression: strawberry.ID | None = None
    value_kind: enums.MetricKind | None = None
    searchable: bool | None = None
    
    


@strawberry.django.type(models.BigFileStore)
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


def entity_to_node_subtype(entity: age.RetrievedEntity) -> Union["Structure","Entity", "Metric", "NaturalEvent", "ProtocolEvent"]:
    if entity.identifier:
        return Structure(_value=entity)
    else:
        return Entity(_value=entity)
    

def relation_to_edge_subtype(relation: age.RetrievedRelation) -> Union["Measurement", "Relation", "Participant"]:
    if relation.value:
        return Measurement(_value=relation)
    else:
        return Relation(_value=relation)



@strawberry.enum
class HistoryKind(str, Enum):
    CREATE = "+"
    UPDATE = "~"
    DELETE = "-"


@strawberry.type()
class ModelChange:
    field: str
    old_value: str | None
    new_value: str | None


@strawberry_django.type(AppHistoryModel, pagination=True)
class History:
    app: App | None

    @strawberry.django.field()
    def user(self, info: Info) -> User | None:
        return self.history_user

    @strawberry.django.field()
    def kind(self, info: Info) -> HistoryKind:
        return self.history_type

    @strawberry.django.field()
    def date(self, info: Info) -> datetime.datetime:
        return self.history_date

    @strawberry.django.field()
    def during(self, info: Info) -> str | None:
        return self.assignation_id

    @strawberry.django.field()
    def id(self, info: Info) -> strawberry.ID:
        return self.history_id

    @strawberry.django.field()
    def effective_changes(self, info: Info) -> list[ModelChange]:
        new_record, old_record = self, self.prev_record

        changes = []
        if old_record is None:
            return changes

        delta = new_record.diff_against(old_record)
        for change in delta.changes:
            changes.append(
                ModelChange(
                    field=change.field, old_value=change.old, new_value=change.new
                )
            )

        return changes


@strawberry.django.type(
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
    node_queries: List["NodeQuery"]
    graph_queries: List["GraphQuery"]
    
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
    
    # Edges
    measurement_categories: List["MeasurementCategory"] = strawberry_django.field(
        description="The list of measurement exprdessions defined in this ontology"
    )
    relation_categories: List["RelationCategory"] = strawberry_django.field(
        description="The list of relation expressions defined in this ontology"
    )
    participant_categories: List["ParticipantCategory"] = strawberry_django.field(
        description="The list of participant expressions defined in this ontology"
    )
    
  
    
    
    @strawberry.django.field()
    def node_categories(self, 
        info: Info,
        filters: filters.CategoryFilter | None = strawberry.UNSET,
        pagination: OffsetPaginationInput | None = strawberry.UNSET,
    ) -> list["NodeCategory"]:
        if pagination is strawberry.UNSET or pagination is None:
            pagination = OffsetPaginationInput()
            
        
        sqs = models.StructureCategory.objects.filter(ontology=self)
        gqs = models.EntityCategory.objects.filter(ontology=self)
        
        if filters is not strawberry.UNSET:
            sqs = strawberry_django.filters.apply(filters, sqs, info)
            gqs = strawberry_django.filters.apply(filters, gqs, info)

        return paginate_querysets(sqs, gqs, offset=pagination.offset, limit=pagination.limit)
    
    
    @strawberry.django.field()
    def edge_categories(self, 
        info: Info,
        filters: filters.CategoryFilter | None = strawberry.UNSET,
        pagination: OffsetPaginationInput | None = strawberry.UNSET,
    ) -> list["EdgeCategory"]:
        
        if pagination is strawberry.UNSET or pagination is None:
            pagination = OffsetPaginationInput()
            
        
        sqs = models.MeasurementCategory.objects.filter(ontology=self)
        gqs = models.RelationCategory.objects.filter(ontology=self)
        
        if filters is not strawberry.UNSET:
            sqs = strawberry_django.filters.apply(filters, sqs, info)
            gqs = strawberry_django.filters.apply(filters, gqs, info)


        return paginate_querysets(sqs, gqs, offset=pagination.offset, limit=pagination.limit)
    
    @strawberry_django.field()
    def latest_nodes(self, info: Info, filters: filters.EntityFilter | None = None , pagination: p.GraphPaginationInput | None = None) -> List["Node"]:
        
        filters = filters or f.EntityFilter()
        pagination = pagination or p.GraphPaginationInput()
        
        return [entity_to_node_subtype(i) for i in age.select_latest_nodes(self.age_name, pagination, filter=filters)]
    
  
    
    @strawberry.django.field()
    def pinned(self, info: Info) -> bool:
        return info.context.request.user in self.pinned_by.all()
    


@strawberry.django.type(
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
    scatter_plots: List["ScatterPlot"]
    
    @strawberry.django.field()
    def pinned(self, info: Info) -> bool:
        return info.context.request.user in self.pinned_by.all()
    
    @strawberry.django.field()
    def render(self, info: Info) -> Union["Path", "Pairs", "Table"]:
        from core.renderers.graph.render import render_graph_query
        return render_graph_query(self)
    

@strawberry.django.type(
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


@strawberry.django.type(
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
    
    @strawberry.django.field()
    def pinned(self, info: Info) -> bool:
        return info.context.request.user in self.pinned_by.all()
    
    
    @strawberry.django.field()
    def render(self, info: Info, node_id: strawberry.ID) -> Union["Path", "Pairs", "Table"]:
        from core.renderers.node.render import render_node_view
        return render_node_view(self, node_id)
    
    
@strawberry.interface
class Node: 
    _value: strawberry.Private[age.RetrievedEntity]

    def __hash__(self):
        return self._value.id
    
    @strawberry_django.field()
    def renders(self, info: Info) -> List[Union["Path", "Pairs", "Table"]]:
        from core.renderers.node.render import render_node_view
        return [render_node_view(self, self._value.id) for self in models.NodeQuery.objects.filter(node_id=self._value.unique_id).all()]
    
    
    @strawberry.field(description="The unique identifier of the entity within its graph")
    async def graph(self, info: Info) -> "Graph":
        return await loaders.graph_loader.load(self._value.graph_name)
    
    
    @strawberry.django.field()
    def label(self, info: Info) -> str:
        return self._value.kind_age_name

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
        return [relation_to_edge_subtype(edge) for edge in self._value.retrieve_right_relations()]
    
    @strawberry_django.field(
        description="The unique identifier of the entity within its graph"
    )
    def left_edges(self, info: Info) -> List["Edge"]:
        return [relation_to_edge_subtype(edge) for edge in self._value.retrieve_left_relations()]
    
    @strawberry.field(
        description="The unique identifier of the entity within its graph"
    )
    def edges(self, info: Info,
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
        
    



@strawberry.type(description="A Structure is a recorded data point in a graph. It can measure a property of an entity through a direct measurement edge, that connects the entity to the structure. It of course can relate to other structures through relation edges.")
class Structure(Node):
    pass

    def __hash__(self):
        return self._value.id
    
    @strawberry.django.field(
        description="Protocol steps where this entity was the target"
    )
    async def category(self) -> "StructureCategory":
        
        return await loaders.structure_category_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )

    @strawberry.field(description="The unique identifier of the entity within its graph")
    def identifier(self, info: Info) -> str:
        return self._value.identifier
    
    @strawberry.field(description="The expression that defines this entity's type")
    def object(self, info: Info) -> str:
        return self._value.object
    
    
    
        



@strawberry.type(description="A Entity is a recorded data point in a graph. It can measure a property of an entity through a direct measurement edge, that connects the entity to the structure. It of course can relate to other structures through relation edges.")
class Entity(Node):
    
    def __hash__(self):
        return self._value.id

    
    @strawberry.django.field(
        description="Protocol steps where this entity was the target"
    )
    async def category(self) -> "EntityCategory":
        return await loaders.generic_category_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )

    

@strawberry.type(description="A Metric is a recorded data point in a graph. It always describes a structure and through the structure it can bring meaning to the measured entity. It can measure a property of an entity through a direct measurement edge, that connects the entity to the structure. It of course can relate to other structures through relation edges.")
class Metric(Node):
    
    def __hash__(self):
        return self._value.id

    
    @strawberry.django.field(
        description="Protocol steps where this entity was the target"
    )
    async def category(self) -> "MetricCategory":
        return await loaders.generic_category_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )

@strawberry.type(description="A Metric is a recorded data point in a graph. It always describes a structure and through the structure it can bring meaning to the measured entity. It can measure a property of an entity through a direct measurement edge, that connects the entity to the structure. It of course can relate to other structures through relation edges.")
class NaturalEvent(Node):
    
    def __hash__(self):
        return self._value.id

    
    @strawberry.django.field(
        description="Protocol steps where this entity was the target"
    )
    async def category(self) -> "NaturalEventCategory":
        return await loaders.generic_category_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )

@strawberry.type(description="A Metric is a recorded data point in a graph. It always describes a structure and through the structure it can bring meaning to the measured entity. It can measure a property of an entity through a direct measurement edge, that connects the entity to the structure. It of course can relate to other structures through relation edges.")
class ProtocolEvent(Node):
    
    def __hash__(self):
        return self._value.id

    
    @strawberry.django.field(
        description="Protocol steps where this entity was the target"
    )
    async def category(self) -> "ProtocolEventCategory":
        return await loaders.generic_category_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )
        
    @strawberry.django.field(
        description="Protocol steps where this entity was the target"
    )
    async def variables(self) -> scalars.Any:
       raise NotImplementedError("Not implemented yet")

    

@strawberry.interface
class Edge:
    _value: strawberry.Private[age.RetrievedRelation]


    def __hash__(self):
        return self._value.id
    
    
    @strawberry.field(description="The unique identifier of the entity within its graph")
    def id(self, info: Info) -> scalars.NodeID:
        return f"{self._value.graph_name}:{self._value.id}"


    @strawberry.django.field()
    def label(self, info: Info) -> str:
        return self._value.kind_age_name

    @strawberry.django.field()
    def left_id(self, info: Info) -> str:
        return self._value.unique_left_id

    @strawberry.django.field()
    def right_id(self, info: Info) -> str:
        return self._value.unique_right_id
    
    @strawberry.django.field()
    def left_id(self, info: Info) -> str:
        return self._value.unique_left_id

    @strawberry.django.field()
    def right_id(self, info: Info) -> str:
        return self._value.unique_right_id
    
    @strawberry.django.field()
    def right(self, info: Info) -> Node:
        return entity_to_node_subtype(age.get_age_entity(age.to_graph_id(self._value.unique_right_id), age.to_entity_id((self._value.unique_right_id))))

    @strawberry.django.field()
    def left(self, info: Info) -> Node:
        return entity_to_node_subtype(age.get_age_entity(age.to_graph_id(self._value.unique_left_id), age.to_entity_id((self._value.unique_left_id))))


    

@strawberry.type(description="""A measurement is an edge from a structure to an entity. Importantly Measurement are always directed from the structure to the entity, and never the other way around.""")
class Measurement(Edge):

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
    
    @strawberry.django.field()
    async def category(self, info: Info) -> "MeasurementCategory":
        return await loaders.measurement_category_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )
        
    

@strawberry.type(description="""A relation is an edge between two entities. It is a directed edge, that connects two entities and established a relationship
                 that is not a measurement between them. I.e. when they are an subjective assertion about the entities.
                 
                 
                 
                 """)
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
    
    @strawberry.django.field()
    async def category(self, info: Info) -> "RelationCategory":
        return await loaders.relation_category_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )

@strawberry.type(description="""A participant edge maps bioentitiy to an event (valid from is not necessary)
                 """)
class Participant(Edge):

    def __hash__(self):
        return self._value.id
    
    @strawberry.django.field()
    async def category(self, info: Info) -> "ParticipantCategory":
        return await loaders.relation_category_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )


@strawberry_django.type(models.Category, filters=filters.CategoryFilter, pagination=True)
class Category:
    graph: "Graph" = strawberry_django.field(
        description="The ontology the expression belongs to."
    )
    description: str | None = strawberry.field(
        description="A description of the expression."
    )
    store: MediaStore | None = strawberry.field(
        description="An image or other media file that can be used to represent the expression."
    )
    id: strawberry.ID = strawberry.field(description="The unique identifier of the expression within its graph")
    age_name: str = strawberry.field(description="The unique identifier of the expression within its graph")    
    color: list[float] | None = strawberry.field()
    kind: enums.ExpressionKind = strawberry.field(description="The kind of expression")



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
    id: strawberry.ID = strawberry.field(description="The unique identifier of the expression within its graph")
    age_name: str = strawberry.field(description="The unique identifier of the expression within its graph")    
    color: list[float] | None = strawberry.field()
    kind: enums.ExpressionKind = strawberry.field(description="The kind of expression")
    
    
    @strawberry_django.field(description="The unique identifier of the expression within its graph")
    def label(self, info: Info) -> str:
        return self.label or self.age_name
    

@strawberry.interface()
class NodeCategory:
    id: strawberry.ID = strawberry.field(description="The unique identifier of the expression within its graph")
    
    position_x: float | None = strawberry.field(description="The x position of the node in the graph")
    position_y: float | None = strawberry.field(description="The y position of the node in the graph")
    height: float | None = strawberry.field(description="The height of the node in the graph")
    width: float | None = strawberry.field(description="The width of the node in the graph")
    color: list[float] | None = strawberry.field(description="The color of the node in the graph")
    
    @strawberry.field(description="The unique identifier of the expression within its graph")
    def instance_kind(self, info: Info) -> enums.InstanceKind:
        return self.instance_kind if self.instance_kind else enums.InstanceKind.ENTITY
    
    pass

@strawberry.interface()
class EdgeCategory:
    id: strawberry.ID = strawberry.field(description="The unique identifier of the expression within its graph")
    """ A EdgeExpression is a class that describes the relationship between two entities."""
    
    @strawberry_django.field()
    def left(self, info: Info) -> NodeCategory:
        return self.left.get_real_instance()
    
    
    @strawberry_django.field()
    def right(self, info: Info) -> NodeCategory:
        return self.right.get_real_instance()
    


@strawberry_django.type(models.EntityCategory, filters=filters.EntityCategoryFilter, pagination=True)
class EntityCategory(NodeCategory, BaseCategory):
    """ A GenericExpression is a class that describes the relationship between two entities."""
    label: str = strawberry.field(description="The label of the expression")
    
    pass

@strawberry_django.type(models.StructureCategory, filters=filters.StructureCategoryFilter, pagination=True)
class StructureCategory(NodeCategory, BaseCategory):
    identifier: str = strawberry.field(description="The structure that this class represents")
    

@strawberry_django.type(models.MetricCategory, filters=filters.MeasurementCategoryFilter, pagination=True)
class MetricCategory(NodeCategory, BaseCategory):
    """ A MeasurementExpression is a class that describes the relatisonship between two entities."""
    metric_kind: enums.MetricKind = strawberry.field(description="The kind of metric this expression represents")
    
    pass  

@strawberry_django.type(models.NaturalEventCategory, filters=filters.MeasurementCategoryFilter, pagination=True)
class NaturalEventCategory(NodeCategory, BaseCategory):
    """ A MeasurementExpression is a class that describes the relatisonship between two entities."""
    metric_kind: enums.MetricKind = strawberry.field(description="The kind of metric this expression represents")
    
    pass

@strawberry_django.type(models.ProtocolEventCategory, filters=filters.MeasurementCategoryFilter, pagination=True)
class ProtocolEventCategory(NodeCategory, BaseCategory):
    """ A MeasurementExpression is a class that describes the relatisonship between two entities."""
    metric_kind: enums.MetricKind = strawberry.field(description="The kind of metric this expression represents")
    
    pass 
    
    
    
@strawberry_django.type(models.RelationCategory, filters=filters.RelationCategoryFilter, pagination=True)
class RelationCategory(EdgeCategory, BaseCategory):
    """ A RelationExpression is a class that describes the relationship between two entities."""
    pass


@strawberry_django.type(models.ParticipantCategory, filters=filters.ParticipantCategoryFilter, pagination=True)
class ParticipantCategory(EdgeCategory, BaseCategory):
    """ A Particiant is a class that describes that an entitiy is a participan in an event"""
    force_quantity: bool = strawberry.field(
        description="Whether this port needs a quantity or not",
    )
    pass

@strawberry_django.type(models.MeasurementCategory, filters=filters.MeasurementCategoryFilter, pagination=True)
class MeasurementCategory(EdgeCategory, BaseCategory):
    """ A RelationExpression is a class that describes the relationship between two entities."""
    label: str = strawberry.field(description="The label of the expression")



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
    edge: Edge = strawberry.field(
        description="The relation between the two entities."
    )


@strawberry.type(
    description="A collection of paired entities."
)
class Pairs:
    pairs: list[Pair] = strawberry.field(description="The paired entities.")
    graph: Graph = strawberry.field(description="The graph this table was queried from.")

@strawberry.type(
    description="A collection of paired entities."
)
class Table:
    rows: list[scalars.Any] = strawberry.field(description="The paired entities.")
    columns: list[Column] = strawberry.field(description="The columns describind this table.")
    graph: Graph = strawberry.field(description="The graph this table was queried from.")
    
    
    