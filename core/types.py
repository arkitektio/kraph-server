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
from core import age, pagination as p


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


@strawberry.type
class NodeMetric:
    _value: strawberry.Private[age.RetrievedNodeMetric]
    """A metric."""

    @strawberry.django.field()
    def id(self, info: Info) -> strawberry.ID:
        return f"{self._value.graph_name}:{self._value.id}"

    @strawberry.django.field()
    async def linked_expression(self, info: Info) -> "LinkedExpression":
        return await loaders.linked_expression_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )

    @strawberry.django.field()
    async def valid_from(self, info: Info) -> datetime.datetime | None:
        return self._value.valid_from

    @strawberry.django.field()
    async def valid_to(self, info: Info) -> datetime.datetime | None:
        return self._value.valid_to

    @strawberry.django.field()
    async def value(self, info: Info) -> scalars.Metric | None:
        return self._value.value

    @strawberry.django.field()
    async def key(self, info: Info) -> str:
        return self._value.kind_age_name


@strawberry.type
class RelationMetric:
    _value: strawberry.Private[age.RetrievedRelationMetric]
    """A metric."""

    @strawberry.django.field()
    async def linked_expression(self, info: Info) -> "LinkedExpression":
        return await loaders.linked_expression_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )

    @strawberry.django.field()
    async def value(self, info: Info) -> str:
        return self._value.value


@strawberry.type
class EntityRelation:
    """A relation."""

    _value: strawberry.Private[age.RetrievedRelation]

    @strawberry.django.field()
    def id(self, info: Info) -> strawberry.ID:
        return self._value.unique_id

    @strawberry.django.field()
    async def linked_expression(self, info: Info) -> "LinkedExpression":
        return await loaders.linked_expression_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )

    @strawberry.django.field()
    def left(self, info: Info) -> "Entity":
        return Entity(_value=self._value.retrieve_left())

    @strawberry.django.field()
    def right(self, info: Info) -> "Entity":
        return Entity(_value=self._value.retrieve_right())

    @strawberry.django.field()
    def left_id(self, info: Info) -> str:
        return self._value.unique_left_id

    @strawberry.django.field()
    def right_id(self, info: Info) -> str:
        return self._value.unique_right_id

    @strawberry.django.field()
    def label(self, info: Info) -> str:
        return self._value.kind_age_name

    @strawberry.django.field()
    def metrics(self, info: Info) -> List[RelationMetric]:
        return [
            RelationMetric(_value=metric) for metric in self._value.retrieve_metrics()
        ]

    @strawberry.django.field()
    def metric_map(self, info: Info) -> scalars.MetricMap:
        return self._value.retrieve_properties()


@strawberry_django.type(
    models.Expression,
    filters=filters.ExpressionFilter,
    pagination=True,
    description="""An expression in an ontology. Expression are used to label entities and their relations in a graph like structure. Depending on the kind of the expression
    it can be used to describe different aspects of the entities and relations.""",
)
class Expression:
    id: auto = strawberry.field(description="The unique identifier of the expression.")
    ontology: "Ontology" = strawberry.field(
        description="The ontology the expression belongs to."
    )
    kind: enums.ExpressionKind = strawberry.field(
        description="The kind of the expression."
    )
    label: str = strawberry.field(description="The label of the expression. The class")
    description: str | None = strawberry.field(
        description="A description of the expression."
    )
    store: MediaStore | None = strawberry.field(
        description="An image or other media file that can be used to represent the expression."
    )
    metric_kind: enums.MetricDataType | None = strawberry.field(
        description="The kind of metric that can be attached to the expression."
    )
    linked_expressions: List["LinkedExpression"] = strawberry.field(
        description="The linked expressions of the expression. i.e in which graphs the expression is used."
    )


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
    linked_expressions: List["LinkedExpression"]
    age_name: str


@strawberry.type(
    description="""An entity is a node in a graph. Entities are the building blocks of the data model in kraph.
                 
                 They are used to represent the different objects in your data model, and how they are connected to each other, through
                 relations. 

                 Kraph distinguishes between two core types of entities: Biological entities and Data entities. Biological entities
                 are describing real-world objects, such as cells, tissues, organs, etc. Data entities are describing data objects, such as
                 images, tables, etc.

                 While you can relate any entity to any other entity, it is important to keep in mind that the relations between entities
                    should be meaningful, and should reflect the real-world relationships between the objects they represent.
                 
                 If you want to attach measurments or metrics to an entity, you should never attach them directly to the entity, but rather
                 point from the measurement (the data object) to the entity. This way, you can keep track of the provenance of the data, and
                 ensure that you never know anything about the entity that is not backed by data.
           
                 """
)
class Entity:
    """An entity is a node in a graph representing either a biological object or data object."""

    _value: strawberry.Private[age.RetrievedEntity]

    @strawberry.field(
        description="The unique identifier of the entity within its graph"
    )
    def id(self, info: Info) -> strawberry.ID:
        return f"{self._value.graph_name}:{self._value.id}"

    @strawberry_django.field(
        description="The expression that defines this entity's type"
    )
    async def linked_expression(self, info: Info) -> "LinkedExpression":
        return await loaders.linked_expression_loader.load(
            f"{self._value.graph_name}:{self._value.kind_age_name}"
        )

    @strawberry.field(description="The name of the entity's type/kind")
    def kind_name(self, info: Info) -> str:
        return self._value.kind_age_name

    @strawberry.field(description="A human readable label for this entity")
    def label(self, info: Info) -> str:
        return self._value.label

    @strawberry.field(
        description="A unique identifier for this entity if available"
    )
    def identifier(self, info: Info) -> str | None:
        return self._value.identifier

    @strawberry.field(
        description="Reference to an external object if this entity represents one"
    )
    def object(self, info: Info) -> str | None:
        return self._value.object

    @strawberry.field(description="Timestamp from when this entity is valid")
    def valid_from(self, info: Info) -> datetime.datetime:
        return self._value.valid_from

    @strawberry.field(description="Timestamp until when this entity is valid")
    def valid_to(self, info: Info) -> datetime.datetime:
        return self._value.valid_to

    @strawberry.field(description="When this entity was created")
    def created_at(self, info: Info) -> datetime.datetime:
        return self._value.created_at or datetime.datetime.now()

    @strawberry_django.field(
        description="Relations this entity has with other entities"
    )
    def relations(
        self,
        filter: filters.EntityRelationFilter | None = None,
        pagination: p.GraphPaginationInput | None = None,
    ) -> List[EntityRelation]:
        from_arg_relations = []
        if not pagination:
            pagination = p.GraphPaginationInput()

        if not filter:
            filter = filters.EntityRelationFilter()

        if not filter.left_id and not filter.right_id:
            filter.left_id = self._value.unique_id

        return [
            EntityRelation(_value=x)
            for x in age.select_all_relations(
                self._value.graph_name, pagination, filter
            )
        ]

    @strawberry.django.field(
        description="Protocol steps where this entity was the target"
    )
    def subjected_to(self) -> list[ProtocolStep]:
        return models.ProtocolStep.objects.filter(for_entity_id=self._value.unique_id)

    @strawberry.django.field(description="Protocol steps where this entity was used")
    def used_in(self) -> list[ProtocolStep]:
        return models.ProtocolStep.objects.filter(used_entity_id=self._value.unique_id)

    @strawberry.django.field(
        description="Map of metric values associated with this entity"
    )
    def metric_map(self, info: Info) -> scalars.MetricMap:
        return self._value.retrieve_properties()

    @strawberry.django.field(description="List of metrics associated with this entity")
    def metrics(self, info: Info) -> List[NodeMetric]:
        metrics = self._value.retrieve_metrics()
        print(metrics)
        return [NodeMetric(_value=metric) for metric in metrics]


@strawberry_django.type(
    models.LinkedExpression, filters=filters.LinkedExpressionFilter, pagination=True
)
class LinkedExpression:
    id: auto
    graph: "Graph"
    expression: "Expression"
    kind: enums.ExpressionKind
    description: str | None
    purl: str | None
    data_kind: enums.MetricDataType | None = None

    @strawberry.django.field()
    def color(self, info: Info) -> str:
        return self.rgb_color_string

    @strawberry.django.field()
    def label(self, info: Info) -> str:
        return f"{self.expression.label} @ {self.graph.name}"

    @strawberry_django.field()
    def entities(
        self,
        filter: filters.EntityFilter | None = None,
        pagination: p.GraphPaginationInput | None = None,
    ) -> List[Entity]:
        if filter is None:
            filter = filters.EntityFilter()

        filter.linked_expression = self.id

        if pagination is None:
            pagination = p.GraphPaginationInput()

        return [
            Entity(_value=x)
            for x in age.select_all_entities(self.graph.age_name, pagination, filter)
        ]

    @strawberry.django.field()
    def pinned(self, info: Info) -> bool:
        return self.pinned_by.filter(id=info.context.request.user.id).exists()


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
