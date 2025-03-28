import random
import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.forms import FileField
from taggit.managers import TaggableManager
from core import enums
from koherent.fields import HistoryField, HistoricForeignKey
import koherent.signals
from django_choices_field import TextChoicesField
from core.fields import S3Field
from core.datalayer import Datalayer

# Create your models here.
import boto3
import json
from django.conf import settings


class S3Store(models.Model):
    path = S3Field(
        null=True, blank=True, help_text="The stodre of the image", unique=True
    )
    key = models.CharField(max_length=1000)
    bucket = models.CharField(max_length=1000)
    populated = models.BooleanField(default=False)


class BigFileStore(S3Store):
    pass

    def fill_info(self) -> None:
        pass

    def get_presigned_url(
        self,
        info,
        datalayer: Datalayer,
        host: str | None = None,
    ) -> str:
        s3 = datalayer.s3
        url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": self.bucket,
                "Key": self.key,
            },
            ExpiresIn=3600,
        )
        return url.replace(settings.AWS_S3_ENDPOINT_URL, host or "")


class MediaStore(S3Store):

    def get_presigned_url(
        self, info, datalayer: Datalayer, host: str | None = None
    ) -> str:
        s3 = datalayer.s3
        url: str = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": self.bucket,
                "Key": self.key,
            },
            ExpiresIn=3600,
        )
        return url.replace(settings.AWS_S3_ENDPOINT_URL, host or "")

    def fill_info(self) -> None:
        pass

    def put_file(self, datalayer: Datalayer, file: FileField):
        s3 = datalayer.s3
        s3.upload_fileobj(file, self.bucket, self.key)
        self.save()


class Experiment(models.Model):
    name = models.CharField(max_length=1000, help_text="The name of the experiment")
    description = models.CharField(
        max_length=1000,
        help_text="The description of the experiment",
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoryField()


class Graph(models.Model):
    """An EntityGroup is a collection of Entities.

    It is used to group Entities together, for example all groups that
    are part of a specific sample, or all entities that are part of a specific
    experiment. Within an entity group, entities are unique according
    to their name.

    """
    user = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="entity_groups",
        help_text="The user that this entity group belongs to",
    )
    name = models.CharField(max_length=1000, help_text="The name of the entity group")
    description = models.CharField(
        max_length=2000,
        help_text="The description of the entity group",
        null=True,
    )
    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="graphs",
        help_text="The experiment this entity group belongs to (if its part of an experiment)",
    )
    history = HistoryField()
    age_name = models.CharField(
        max_length=1000,
        help_text="The name of the graph class in the age graph",
        unique=True,
    )
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_graphs",
        help_text="The users that have this query active",
        
    )
    
    @classmethod
    def get_active(cls, user):
        return cls.objects.filter(user=user).first()
    
    
    @property
    def structure_categories(self):
        return StructureCategory.objects.filter(graph=self)
    
    @property
    def entity_categories(self):
        return EntityCategory.objects.filter(graph=self)
    
    @property
    def relation_categories(self):
        return RelationCategory.objects.filter(graph=self)

    @property
    def measurement_categories(self):
        return MeasurementCategory.objects.filter(graph=self)
    
    
    
    
    
    
    
   

def random_color():
    levels = range(32, 256, 32)
    return tuple(random.choice(levels) for _ in range(3))


class CategoryTag(models.Model):
    """A tag for a category"""
    value = models.CharField(
        max_length=1000,
        unique=True,
        help_text="The value of the tag",
    )
    description = models.CharField(
        max_length=1000,
        help_text="The description of the tag",
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    


class Category(models.Model):
    graph = models.ForeignKey(
        "Graph",
        on_delete=models.CASCADE,
    )
    store = models.ForeignKey(
        MediaStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the image if associated with the category",
    )
    label = models.CharField(
        max_length=1000,
        help_text="The label of the entity class",
        null=True,
    )
    position_x = models.FloatField(
        help_text="The x position of the node class in the graph (if a node)",
        null=True,
    )
    position_y = models.FloatField(
        help_text="The y position of the  node class in the graph (if a node)",
        null=True,
    )
    height = models.FloatField(
        help_text="The height of the  node class in the graph (if a node)",
        null=True,
    )
    width = models.FloatField(
        help_text="The width of the  node class in the graph (if a node)",
        null=True,
    )
    color = models.JSONField(
        max_length=1000,
        help_text="The color of  node class in the graph (if a node)",
        default=random_color,
        null=True,
    )
    description = models.CharField(
        max_length=1000,
        help_text="The description of category",
        null=True,
    )
    purl = models.CharField(
        max_length=1000,
        help_text="The PURL (Persistent Uniform Resource Locator)",
        null=True,
    )
    tags = models.ManyToManyField(
        CategoryTag,
        related_name="categories",
        help_text="The tags of the category",
        blank=True,
    )
    color = models.JSONField(
        max_length=1000,
        help_text="The color of the entity class as RGB",
        default=random_color,
        null=True,
    )
    
    age_name = models.CharField(
        max_length=1000,
        help_text="The name of the graph class in the age graph",
    )
    
    left = models.ForeignKey(
        "Category",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="left_edges",
    )
    right = models.ForeignKey(
        "Category",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="right_edges",
    )
    
    
    def get_real_instance(self):
        """Returns the real instance if it is a child class."""
        print("Getting real instance", dir(self))
        for child in ["structure_categories", "generic_categories", "measurement_categories", "relation_categories"]:
            if hasattr(self, child.lower()):
                return getattr(self, child.lower())
    
        raise ValueError("No real instance found")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "age_name", "left", "right"],
                name="unique_age_name_per_graph_and_mapping_left_and_right",
            )
        ]
        

class StructureCategory(Category):
    """ A Structure class is a class represents a datapoint in your graph and
    will relate metrics (like Intensity, Area, etc.) to it and then in turn
    relate temporally to a bioentity. It therefore is one element in the
    
    (b: Metric) -[d: describes] -> (a: Structure) -> [m: measures] -> (c: Bioentity) path.
    
    Structure are just datapoints in the graph and should be considered inspectable links
    to the data that was analysed, e.g. the image that was taken, metrics hold the actual
    information about that image (e.g. the cell count in the image, the maximum intensity and
    so forth).
    
    """
    
    identifier = models.CharField(
        max_length=1000,
        help_text="The structure identifier that the node relates to",
        null=True,
        blank=True,
    )
    
         
    class Meta:
        default_related_name = "structure_categories"
        
        
class NaturalEventCategory(Category):
    """ A natural event class is a class that describes a natural event that happened
    to some bioenties (e.g. a cell division, a cell death, etc.). Natural events are
    used to describe the natural events that happen to a bioentity and are not
    to be confused with protocol events, which happen as an external variable to
    the bioentity.
    
    Natural events will always be associated with a supporting measurement node
    the justifys the event (e.g. a cell division event will be associated with a
    tracking image that shows the cell division event).
    
    This is unnegotiable, and a "itoldyousou" object will be created for natural events
    that are not associated with a supporting measurement node.
    
    """
    source_definitions = models.JSONField(
       default=list,
       help_text="The categories or expressions that an event of this class can source from (source edges)", 
    )
    target_definitions = models.JSONField(
        default=list,
        help_text="The categories or expressions that an of this class can target to (target edges)",
    )
         
    class Meta:
        default_related_name = "natural_event_categories"
        
        
class ProtocolEventCategory(Category):
    """ A protocol event class is a node that describes a protocol event that some
    entities were subjected to using, creating or altering them. 
    
    E.g.
    
    CreationEvent:
        (a: Animal) -> [r: SUBJECTED_IN] -> (p: ExtractionEvent) -> [d: PRODUCED] -> (b: Hippocampus)
        
    Transformation:
        (a: Animal) -> [r: SUBJECTED_IN] -> (f: FixationEvent) -> [d: PRODUCED] -> (b: Animal)
        (b: FourPercentFormaldayhyde) -> [r: SUBJECTED_IN {quantity: 50µm }] -> (f: FixationEvent)
    """
    source_definitions = models.JSONField(
       default=list,
       help_text="The categories or expressions that an event of this class can sourc from (source edges)", 
    )
    target_definitions = models.JSONField(
        default=list,
        help_text="The categories or expressions that an of this class can target to (target edges)",
    )
    variable_definitions = models.JSONField(
        default=list,
        help_text="The variables of a instance this protocol event will needs (properties on the node)",
    )
    plate_children = models.JSONField(null=True, blank=True)
    
    class Meta:
        default_related_name = "protocol_event_categories"

class EntityCategory(Category):
    """ An Entity class is a class that describes a node in the graph which represent
    a bioentity (e.g. a cell, a tissue, etc.). Entitys are the most basic building
    block of the graph and represent physical objects that can be measured
    by structures, related to other entities by relations and subjected to specific
    protocol steps.
    
    On temporality:
    
    Bioentity by design are meant to "immortal" and for the purpose of the graph should
    not be considered to be deleted. Instead when there is no measurement or relation
    pointing towards them in the active validation window, they are not considered for the
    ongoing analysis. Imaging a cell that was image in one of your experiments and then
    was not imaged in the next experiment. The cell still existed ONCE in time, but will not
    be monitored in the next experiment, so will have no structure point to it.
    
    If you of course create a timelapse of the cell, you will have multiple measurements 
    pointing to the same cell, so the cell will still exist in the graph in the next experiment.
    
    They belong to these subgraphs:
    
    The measurement path:
    (b: $Metric) -[d: describes] -> (a: $Structure) -> [m: measures] -> (c: $Bioentity)
    
    E.g. the intensity (metric) of the image (structure) that measures the cell (bioentity)
    
    The relation path:
    (a: $Bioentity) -[r: $RELATION] -> (b: $Bioentity)
    
    E.g. A cell was related for the timestramp of the experiment to another cell
    
    The natural event path:
    (a: Structure) -> [d: determines] ->  (b: NaturalEvent) 
    (a: $Bioentity) -[r: underwent]-> (b: NaturalEvent) -> [d: created] -> (c: $Bioentity)
    
    E.g. the cell (a bioentity) "budded" (the relation) another cell (another bioentity)) at the time of the valid relation (informed structure in metadata)
   
    The protocol event path:
    (a: $Bioentity) -[r: underwent]-> (b: ProtocolEvent) -> [d: created] -> (c: $Bioentity)
    
    E.g. A cell was isolated from a cell culture and is now considered a new bioentity, that backlinks to
    the parent through the protocols
   
    
    """
    instance_kind = models.CharField(
        max_length=1000,
        help_text="What an instance of this class represents (e.g. a LOT, an object, etc.)",
        null=True,
        blank=True,
    )
    
    class Meta:
        default_related_name = "entity_categories"

class ReagentCategory(Category):
    """ An Regation class is a class that describes a node in the graph which represent
    a reagent in the graph that does not have a biological meaning in this graph (e.g. a
    4% formaldehyde, a 10% DMSO, etc.). 
    
    On temporality:
    
    Bioentity by design are meant to "immortal" and for the purpose of the graph should
    not be considered to be deleted. Instead when there is no measurement or relation
    pointing towards them in the active validation window, they are not considered for the
    ongoing analysis. Imaging a cell that was image in one of your experiments and then
    was not imaged in the next experiment. The cell still existed ONCE in time, but will not
    be monitored in the next experiment, so will have no structure point to it.
    
    If you of course create a timelapse of the cell, you will have multiple measurements 
    pointing to the same cell, so the cell will still exist in the graph in the next experiment.
    
    They belong to these subgraphs:
    
    The measurement path:
    (b: $Metric) -[d: describes] -> (a: $Structure) -> [m: measures] -> (c: $Bioentity)
    
    E.g. the intensity (metric) of the image (structure) that measures the cell (bioentity)
    
    The relation path:
    (a: $Bioentity) -[r: $RELATION] -> (b: $Bioentity)
    
    E.g. A cell was related for the timestramp of the experiment to another cell
    
    The natural event path:
    (a: Structure) -> [d: determines] ->  (b: NaturalEvent) 
    (a: $Bioentity) -[r: underwent]-> (b: NaturalEvent) -> [d: created] -> (c: $Bioentity)
    
    E.g. the cell (a bioentity) "budded" (the relation) another cell (another bioentity)) at the time of the valid relation (informed structure in metadata)
   
    The protocol event path:
    (a: $Bioentity) -[r: underwent]-> (b: ProtocolEvent) -> [d: created] -> (c: $Bioentity)
    
    E.g. A cell was isolated from a cell culture and is now considered a new bioentity, that backlinks to
    the parent through the protocols
   
    
    """
    instance_kind = models.CharField(
        max_length=1000,
        help_text="What an instance of this class represents (e.g. a LOT, an object, etc.)",
        null=True,
        blank=True,
    )
    
    class Meta:
        default_related_name = "reagent_categories"


class MetricCategory(Category):
    """ A Metric class is an analticay statement that describes a structure. 
    
    Metric classes are used to describe a kind of  metric that described a certain measurment
    (e.g. intensity, area, etc.) and will always be attached to a structure that in turn
    measures a bioentity. It therefore is one element in the
    
    (b: Metric) -[d: describes] -> (a: Structure) -> [m: measures] -> (c: Bioentity) path.
    
    Kraph will always enfore that metrics are linked to a structure category first
    and disallow liking them directly to a bioentity. This is to ensure that the graph
    is temporally consistent (e.g. multiple same structures can measure the same bioentity at the different times)
    
    While this may no seem obvious at first clance, it is important to understand that
    the graph is not a static representation of your world but a dynamic representation
    of the world that is constantly changing. 
    
    """
    
    metric_kind = TextChoicesField(
        choices_enum=enums.MeasurementKindChoices,
        help_text="The data type (if a metric)",
        null=True,
        blank=True,
    )
    
    class Meta:
        default_related_name = "metric_categories"




class MeasurementCategory(Category):
    """ A Measurement class is a class that describes an edge with a value"""
    
    metric_kind = TextChoicesField(
        choices_enum=enums.MeasurementKindChoices,
        help_text="The data type (if a metric)",
        null=True,
        blank=True,
    )
    
    class Meta:
        default_related_name = "measurement_categories"
 
class ParticipantCategory(Category):
    """ A Step class describes a protocol step that was taken"""
    
    acting_as = models.CharField(
        max_length=1000,
        help_text="How this step acts in the protocol (e.g. as which reagent)",
        null=True,
    )
    
    class Meta:
        default_related_name = "participant_categories"   
    
    
class RelationCategory(Category):
    """ A Relation class is a class that describes a relation between two entities without a value"""
    
    class Meta:
        default_related_name = "relation_categories"


class GraphQuery(models.Model):
    graph = models.ForeignKey(
        Graph,
        on_delete=models.CASCADE,
        related_name="graph_queries",
        help_text="The graph this query belongs to",
    )
    query = models.CharField(
        max_length=7000, help_text="The query that is used to materialize the graph"
    )
    name = models.CharField(
        max_length=1000, help_text="The name of the materialized graph"
    )
    description = models.CharField(
        max_length=1000,
        help_text="The description of the materialized graph",
        null=True,
    )
    kind = models.CharField(
        max_length=1000,
        help_text="The kind of the materialized graph (i.e path, property, etc.)",
    )
    columns = models.JSONField(
        help_text="The columns (if ViewKind is Table)",
        default=None,
        null=True,
    )
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_graph_queries",
        help_text="The users that have this query active",
    )
    relevant_for = models.ManyToManyField(
        Category,
        related_name="relevant_graph_queries",
        help_text="The expression that this query should be mostly used for",
    )
    
    @property
    def input_columns(self):
        from core import inputs
        return [inputs.ColumnInput(**i) for i in self.columns]
    
class NodeQuery(models.Model):
    graph = models.ForeignKey(
        Graph,
        on_delete=models.CASCADE,
        related_name="node_queries",
        help_text="The graph this query belongs to",
    )
    query = models.CharField(
        max_length=7000, help_text="The query that is used to materialize the graph"
    )
    name = models.CharField(
        max_length=1000, help_text="The name of the materialized graph"
    )
    description = models.CharField(
        max_length=1000,
        help_text="The description of the materialized graph",
        null=True,
    )
    kind = models.CharField(
        max_length=1000,
        help_text="The kind of the materialized graph (i.e path, property, etc.)",
    )
    columns = models.JSONField(
        help_text="The columns (if ViewKind is Table)",
        default=None,
        null=True,
    )
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_node_queries",
        help_text="The users that have this query active",
    )
    relevant_for = models.ManyToManyField(
        Category,
        related_name="relevant_node_queries",
        help_text="The entities that this query should be mostly used for",
    )
    
    
    @property
    def input_columns(self):
        from core import inputs
        return [inputs.ColumnInput(**i) for i in self.columns]
    
    
    @classmethod
    def active_for_user_and_graph(self, user, graph):
        
        return self.objects.filter(graph=graph, pinned_by=user).first()
        
    








class MaterializedView(models.Model):
    """A view of a graph that is materialized"""
    query = models.ForeignKey(
        GraphQuery,
        on_delete=models.CASCADE,
        related_name="views",
        help_text="The query that is used to materialize the graph",
    )
    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="graph_views",
        help_text="The user that created the view",
    )
    materialized_at = models.DateTimeField(
        auto_now_add=True,
        help_text="The time the view was materialized. Newer created or deleted_instances are not part of the view",
    )
    valid_from = models.DateTimeField(
        help_text="The time the view was created. Newer created or deleted_instances are not part of the view",
        null=True,
        blank=True,
    )
    valid_to = models.DateTimeField(
        help_text="The time the view was created. Newer created or deleted_instances are not part of the view",
        null=True,
        blank=True,
    )
    



    


class ScatterPlot(models.Model):
    query = models.ForeignKey(
        GraphQuery,
        on_delete=models.CASCADE,
        related_name="scatter_plots",
        help_text="The query this scatter plot was trained on",
    )
    view = models.ForeignKey(
        MaterializedView,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="scatter_plots",
        help_text="If this scatter plot is based on a materialized view, this is the view",
    )
    name = models.CharField(max_length=1000, help_text="The name of the scatter plot")
    description = models.CharField(
        max_length=1000,
        help_text="The description of the scatter plot",
        null=True,
    )
    id_column = models.CharField(
        max_length=1000,
        help_text="The column that assigns the row_id (could be an edge, a node, etc.)",
    )
    x_column = models.CharField(
        max_length=1000, help_text="The column that assigns the x value", null=True
    )
    x_id_column = models.CharField(
        max_length=1000, help_text="The column that assigns the x_id value", null=True
    )
    y_column = models.CharField(
        max_length=1000, help_text="The column that assigns the y value", null=True
    )
    y_id_column = models.CharField(
        max_length=1000, help_text="The column that assigns an ID to the y value", null=True
    )
    color_column = models.CharField(
        max_length=1000, help_text="The column that assigns the color value", null=True
    )
    size_column = models.CharField(
        max_length=1000, help_text="The column that assigns the size value", null=True
    )
    shape_column = models.CharField(
        max_length=1000, help_text="The column that assigns the shape value", null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="scatter_plots",
        help_text="The user that created the scatter plot",
    )





class Model(models.Model):
    """A Model is a deep learning model"""

    name = models.CharField(max_length=1000, help_text="The name of the model")
    materialized_graph = models.ForeignKey(
        MaterializedView,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="models",
        help_text="The materialized grpah this model was trained on",
    )
    store = models.ForeignKey(
        MediaStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="models",
        help_text="The store of the model",
    )
