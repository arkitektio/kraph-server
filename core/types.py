from pydantic import BaseModel
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
    value_kind: enums.MetricDataType | None = None
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
    protocols: List["Protocol"]


@strawberry_django.type(
    models.Protocol, filters=filters.ProtocolFilter, pagination=True
)
class Protocol:
    id: auto
    name: str
    description: str | None
    history: List["History"]
    created_at: datetime.datetime
    creator: User | None
    experiment: Experiment


@strawberry_django.type(models.Reagent, filters=filters.ReagentFilter, pagination=True)
class Reagent:
    id: auto
    expression: Optional["Expression"]
    lot_id: str
    order_id: str | None
    protocol: Optional["Protocol"]
    creation_steps: List["ProtocolStep"]
    used_in: List["ReagentMapping"]

    @strawberry.django.field()
    def label(self, info: Info) -> str:
        return f"{self.expression.label} ({self.lot_id})"


@strawberry_django.type(
    models.ProtocolStepTemplate,
    filters=filters.ProtocolStepTemplateFilter,
    pagination=True,
)
class ProtocolStepTemplate:
    id: auto
    name: str
    plate_children: list[scalars.UntypedPlateChild]
    created_at: datetime.datetime





def entity_to_node_subtype(entity: age.RetrievedEntity) -> Union["Structure","Entity"]:
    if entity.identifier:
        return Structure(_value=entity)
    else:
        return Entity(_value=entity)
    

def relation_to_edge_subtype(relation: age.RetrievedRelation) -> Union["Measurement","Relation"]:
    if relation.value:
        return Measurement(_value=relation)
    else:
        return Relation(_value=relation)


@strawberry_django.type(
    models.ProtocolStep, filters=filters.ProtocolStepFilter, pagination=True
)
class ProtocolStep:
    id: auto
    template: ProtocolStepTemplate
    history: List["History"]
    for_reagent: Optional["Reagent"]
    performed_at: datetime.datetime | None
    performed_by: User | None
    reagent_mappings: List["ReagentMapping"]

    @strawberry.django.field()
    def for_entity(self, info: Info) -> Optional["Entity"]:
        if self.for_entity_id:
            return Entity(
                _value=age.get_age_entity(
                    age.to_graph_id(self.for_entity_id),
                    age.to_entity_id(self.for_entity_id),
                )
            )
        return None

    @strawberry.django.field()
    def used_entity(self, info: Info) -> Optional["Entity"]:
        if self.used_entity_id:
            return Entity(
                _value=age.get_age_entity(
                    age.to_graph_id(self.used_entity_id),
                    age.to_entity_id(self.used_entity_id),
                )
            )
        return None

    @strawberry.django.field()
    def name(self, info) -> str:
        return self.template.name if self.template else "No template"


@strawberry_django.type(
    models.ReagentMapping, filters=filters.ProtocolStepFilter, pagination=True
)
class ReagentMapping:
    id: auto
    reagent: Reagent
    protocol_step: ProtocolStep


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
    ontology: "Ontology"
    name: str
    description: str | None
    age_name: str
    
    @strawberry_django.field()
    def latest_nodes(self, info: Info, filters: filters.EntityFilter | None = None , pagination: p.GraphPaginationInput | None = None) -> List["Node"]:
        
        filters = filters or f.EntityFilter()
        pagination = pagination or p.GraphPaginationInput()
        
        return [entity_to_node_subtype(i) for i in age.select_latest_nodes(self.age_name, pagination, filter=filters)]
    
    
  
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
    ontology: "Ontology"
    query: str
    


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
    ontology: "Ontology"
    query: str
    
    

    


@strawberry.django.type(
    models.GraphView,
    filters=filters.GraphViewFilter,
    pagination=True,
    description="A view of a graph, that contains entities and relations.",
)
class GraphView:
    id: auto
    graph: Graph
    query: "GraphQuery"



@strawberry.django.type(
    models.NodeView,
    filters=filters.NodeViewFilter,
    pagination=True,
    description="A view of a graph, that contains entities and relations.",
)
class NodeView:
    id: auto
    node: "Node"
    node: "NodeQuery"

@strawberry.interface
class Node: 
    _value: strawberry.Private[age.RetrievedEntity]

    def __hash__(self):
        return self._value.id
    
    
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
    def right_edges(self, info: Info) -> List["Edge"]:
        return [Edge(_value=edge) for edge in self._value.right_edges]
    
    @strawberry.field(
        description="The unique identifier of the entity within its graph"
    )
    def left_edges(self, info: Info) -> List["Edge"]:
        return [Edge(_value=edge) for edge in self._value.left_edges]
    
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
    def subjected_to(self) -> list[ProtocolStep]:
        return models.ProtocolStep.objects.filter(for_entity_id=self._value.unique_id)

    @strawberry.django.field(description="Protocol steps where this entity was used")
    def used_in(self) -> list[ProtocolStep]:
        return models.ProtocolStep.objects.filter(used_entity_id=self._value.unique_id)



    @strawberry.django.field()
    async def expression(self, info: Info) -> "Expression":
        return await loaders.expression_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )




@strawberry.interface
class Edge:
    _value: strawberry.Private[age.RetrievedRelation]


    def __hash__(self):
        return self._value.id
    
    
    @strawberry.field(description="The unique identifier of the entity within its graph")
    def id(self, info: Info) -> scalars.NodeID:
        return f"{self._value.graph_name}:{self._value.id}"


    @strawberry.django.field()
    async def expression(self, info: Info) -> "Expression":
        return await loaders.expression_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )
        
        
    @strawberry.django.field()
    async def infered_by(self, info: Info) -> "Edge":
        return Edge(_value=self._value.infered_by)


    @strawberry.django.field()
    def label(self, info: Info) -> str:
        return self._value.kind_age_name



    @strawberry.django.field()
    def left_id(self, info: Info) -> str:
        return self._value.unique_left_id

    @strawberry.django.field()
    def right_id(self, info: Info) -> str:
        return self._value.unique_right_id


@strawberry_django.type(models.Expression)
class Expression:
    ontology: "Ontology" = strawberry.field(
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


    @strawberry.field(description=" The value  type of the metric")
    def metric_kind(self, info: Info) -> Optional["MetricKind"]:
        
        return self.metric_kind
    
    @strawberry.field(description=" The unit  type of the metric")
    def unit(self, info: Info) -> str | None:
        return "µm"
    
    
@strawberry.enum
class MetricKind(str, Enum):
    STRING = "STRING"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    VECTOR = "VECTOR"


@strawberry.type(description="""A measurement is an edge from a structure to an entity. Importantly Measurement are always directed from the structure to the entity, and never the other way around. 

Why an edge? 
Because a measurement is a relation between two entities, and it is important to keep track of the provenance of the data. 
                 By making the measurement an edge, we can keep track of the timestamp when the data point (entity) was taken,
                  and the timestamp when the measurment was created. We can also keep track of the validity of the measurment
                 over time (valid_from, valid_to). Through these edges we can establish when a entity really existed (i.e. when it was measured)
                 """)
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
    async def expression(self, info: Info) -> "Expression":
        return await loaders.expression_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )
    
    
    @strawberry.field(description="The value of the measurement")
    def value(self, info: Info) -> scalars.Metric:
        return self._value.value
    

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
    async def expression(self, info: Info) -> "Expression":
        return await loaders.expression_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )




@strawberry.type(description=" A ComputedMeasurement is a measurement that is computed from other measurements. It is a special kind of measurement that is derived from other measurements.")
class ComputedMeasurement(Measurement):
    pass

    @strawberry.field(description="Timestamp from when this entity is valid")
    def valid_from(self, info: Info) -> datetime.datetime:
        return self._value.valid_from

    @strawberry.field(description="Timestamp until when this entity is valid")
    def valid_to(self, info: Info) -> datetime.datetime:
        return self._value.valid_to
    
    @strawberry.django.field()
    async def expression(self, info: Info) -> "Expression":
        return await loaders.expression_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )
    

    @strawberry.field(description="When this entity was created")
    def computed_from(self, info: Info) -> List[Measurement]:
        # get the computed from measurements
        return [Measurement(_value=x) for x in self._value.computed_from]


def type_caster(self, value: models.Expression) -> Expression:
    
    if value.kind == enums.ExpressionKind.ENTITY:
        return EntityExpression()


@strawberry_django.type(
    models.Ontology,
    filters=filters.OntologyFilter,
    pagination=True,
    description="""An ontology represents a formal naming and definition of types, properties, and 
    interrelationships between entities in a specific domain. In kraph, ontologies provide the vocabulary
    and semantic structure for organizing data across graphs.""",
)
class Ontology:
    id: auto = strawberry.field(description="The unique identifier of the ontology")
    name: str = strawberry.field(description="The name of the ontology")
    description: str | None = strawberry.field(
        description="A detailed description of what this ontology represents and how it should be used"
    )
    purl: str | None = strawberry.field(
        description="The Persistent URL (PURL) that uniquely identifies this ontology globally"
    )
    expressions: List["Expression"] = strawberry.field(
        description="The list of expressions (terms/concepts) defined in this ontology"
    )
    store: MediaStore | None = strawberry.field(
        description="Optional associated media files like documentation or diagrams"
    )
    node_queries: List["NodeQuery"] = strawberry_django.field(
        description="The list of node queries defined in this ontology"
    )
    graph_queries: List["GraphQuery"] = strawberry_django.field(
        description="The list of graph queries defined in this ontology"
    )
    
    graphs: List["Graph"] = strawberry_django.field(
        description="The list of graphs defined in this ontology"
    )
    
    
    @strawberry.django.field()
    def expressions(self, 
        info: Info,
        filters: filters.ExpressionFilter | None = strawberry.UNSET,
        pagination: OffsetPaginationInput | None = strawberry.UNSET,
    ) -> list[Expression]:
        qs = models.Expression.objects.filter(ontology=self)


        # apply filters if defined
        if filters is not strawberry.UNSET:
            qs = strawberry_django.filters.apply(filters, qs, info)

        return qs.all()


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


@strawberry.type(
    description="A collection of paired entities."
)
class Table:
    rows: list[scalars.Any] = strawberry.field(description="The paired entities.")
    columns: list[Column] = strawberry.field(description="The columns describind this table.")
    