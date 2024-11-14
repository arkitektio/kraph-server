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
        null=True, blank=True, help_text="The store of the image", unique=True
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


class Protocol(models.Model):
    reagent = models.ForeignKey(
        "Reagent",
        on_delete=models.CASCADE,
        null=True,
        related_name="protocol",
        help_text="This field is set if the protocol step is used to create another reagent",
    )
    performed_at = models.DateTimeField(auto_now_add=True, auto_created=True)
    operator = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, null=True)
    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.CASCADE,
        related_name="protocols",
        null=True,
        help_text="The experiment that this protocol was designed for",
    )
    name = models.CharField(max_length=1000, help_text="The name of the protocol")
    description = models.CharField(
        max_length=1000,
        help_text="The description of the protocol",
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoryField()


class Reagent(models.Model):
    expression = models.ForeignKey(
        "Expression",
        on_delete=models.CASCADE,
        help_text="The type of reagent (based on an ontology)",
    )
    active = models.BooleanField(
        help_text="Whether the reagent is the active stock for most experiments",
        default=False,
    )
    mass = models.FloatField(
        help_text="The mass of the reagent in the protocol",
        null=True,
        blank=True,
    )
    lot_id = models.CharField(
        max_length=1000,
        help_text="The lot number of the reagent",
        null=True,
        blank=True,
    )
    order_id = models.CharField(
        max_length=1000,
        help_text="The order id of the reagent",
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["lot_id", "expression"],
                name="Only one reagent per expression and lot_id",
            )
        ]


class ProtocolStepTemplate(models.Model):
    name = models.CharField(max_length=1000, help_text="The name of the protocol")
    plate_children = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    creator = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, null=True)
    kind = TextChoicesField(
        choices_enum=enums.ProtocolStepKindChoices,
        default=enums.ProtocolStepKindChoices.UNKNOWN.value,
        help_text="The kind of the step (can be more closely defined in the expression)",
    )

    history = HistoryField()


class ProtocolStep(models.Model):
    """ " A protocol step

    Protocol steps allow to describe what happened to an entity in an experiment
    (e.g it was stained, imaged, etc.) or what happend to a reagent
    when it was created (mixed, diluted, etc.)

    Protocolsteps always have a kind, which is used to describe the kind of the step
    according (adding a reagent, waiting, acquiring, etc.). These are controlled
    by the ProtocolStepKindChoices enum and are not meant to be extended.

    To more closely define the step, you can use the expression field. This field
    is used to describe the kind of the step in more detail. E.g. if you have a
    primary antibody staining step, you would use the expression field to describe
    the purpose of the staining step. Expressions are linked to an ontology and
    allow you to search for steps in a more structured way. (e.g. searching all
    entities that were stained with a primary antibody).

    They are used to describe the steps of an experiment and are used to describe
    the steps of a protocol. Protocolsteps are supposed to be as atomic as possible
    e.g. they should describe one action that was taken in the experiment.

    E.g. when you perform a immunoflouresecence acquistion, you would have a protocol
    step for each staining step.

    - 1. CREATION_STEP: Extract: Extract the sample from the hippocampus of the mouse
    - 1. REAGENT_STEP: Blockstep: Add blocking Reagent (link to reagent) (volume: 10µl)
    - 2. WAIT_STEP: Wait for 1 hour
    - 5. ENVIRONMENT_STEP: Adjust the environment to 37°C
    - 3. REAGENT_STEP: Primary Antibody:  Add primary antibody for channel 2 (link to reagent) (volume: 10µl)
    - 4. REAGENT_STEP: Primary Antibody:  Add primary antibody for channel 2 (link to reagent) (volume: 10µl)
    - 5. WAIT_STEP: Wait for 1 hour
    - 6. REAGENT_STEP: Secondary Antibody: Add secondary antibody for channel 1 (link to reagent) (volume: 10µl)
    - 7. REAGENT_STEP: Secondary Antibody: Add secondary antibody for channel 2 (link to reagent)   (volume: 10µl)
    - 8. WAIT_STEP: Wait for 1 hour
    - 9. REAGENT_STEP: Fixation: Add fixation reagent (link to reagent (e.g. PFA 2%))
    - 10. WAIT_STEP: Wait for 1 hour
    - 11. IMAGING_STEP: Imaging: Take Z-Stack image of channel 1
    - 12. STORAGE_STEP: Store: Store the sample in the fridge

    Likewise, you can use protocol steps to describe the creation of a reagent e.g PFA 2%:

    - 1. ADD_REAGENT_STEP: Add: Add 10g of PFA to 100ml of water
    - 2. ADD_REAGENT_STEP: Dilute: Dilute reagent A with 100µl of water
    - 3. ADD_REAGENT_STEP: Mix: Mix reagent A with reagent B
    - 5. STORAGE_STEP: Store: Store reagent A in the fridge

    """

    for_reagent = models.ForeignKey(
        "Reagent",
        on_delete=models.CASCADE,
        null=True,
        related_name="creation_steps",
        help_text="This field is set if the protocol step is used to create another reagent",
    )
    for_entity_id = models.CharField(
        max_length=1000,
        help_text="The entity that this step is for",
        null=True,
        blank=True,
    )
    template = models.ForeignKey(
        ProtocolStepTemplate,
        on_delete=models.CASCADE,
        null=True,
        related_name="steps",
        help_text="The template that was used to create the step",
    )
    performed_at = models.DateTimeField(auto_now_add=True, auto_created=True)
    performed_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        null=True,
        help_text="The user that performed the step",
    )
    history = HistoryField()
    variable_mappings = models.JSONField(
        null=True,
        blank=True,
        help_text="A mapping of variables to values for this step",
    )


class ReagentMapping(models.Model):
    protocol_step = models.ForeignKey(
        ProtocolStep, on_delete=models.CASCADE, related_name="reagent_mappings"
    )
    reagent = models.ForeignKey(
        Reagent, on_delete=models.CASCADE, related_name="used_in"
    )
    volume = models.FloatField(
        help_text="The volume of the reagent in the protocol in µl. If you add some mass of a reagent, you can use the mass field instead.",
        null=True,
    )
    mass = models.FloatField(
        help_text="The mass of the reagent in the protocol in µg. If you add some volume of a reagent, you can use the volume field instead.",
    )


class Ontology(models.Model):
    name = models.CharField(max_length=1000, help_text="The name of the ontology")
    description = models.CharField(
        max_length=1000,
        help_text="The description of the ontology",
    )
    purl = models.CharField(
        max_length=1000,
        help_text="The PURL of the ontology",
        null=True,
    )
    user = models.OneToOneField(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="ontology",
        help_text="The user that this ontol",
        null=True,
        blank=True,
    )
    store = models.ForeignKey(
        MediaStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the image class",
    )

    def __str__(self) -> str:
        return self.name

    @property
    def age_name(self) -> str:
        return self.name.replace(" ", "_").lower()


def random_color():
    levels = range(32, 256, 32)
    return tuple(random.choice(levels) for _ in range(3))


class Expression(models.Model):
    ontology = models.ForeignKey(
        Ontology,
        on_delete=models.CASCADE,
        related_name="expressions",
    )
    kind = models.CharField(
        max_length=1000,
        help_text="The kind of the entity class",
        null=True,
    )
    store = models.ForeignKey(
        MediaStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the image class",
    )
    label = models.CharField(
        max_length=1000,
        help_text="The label of the entity class",
        null=True,
    )
    metric_kind = TextChoicesField(
        choices_enum=enums.MetricDataTypeChoices,
        help_text="The data type (if a metric)",
        null=True,
        blank=True,
    )
    description = models.CharField(
        max_length=1000,
        help_text="The description of the entity class",
        null=True,
    )
    purl = models.CharField(
        max_length=1000,
        help_text="The PURL of the entity class",
        null=True,
    )

    color = models.JSONField(
        max_length=1000,
        help_text="The color of the entity class as RGB",
        default=random_color,
        null=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ontology", "label"],
                name="unique_label_in_ontology",
            )
        ]

    @property
    def age_name(self) -> str:
        if self.kind == enums.ExpressionKind.ENTITY.value:
            return self.label.replace(" ", "_").replace("-", "_").lower()
        elif self.kind == enums.ExpressionKind.RELATION.value:
            return self.label.replace(" ", "_").replace("-", "_").upper()
        elif self.kind == enums.ExpressionKind.RELATION_METRIC.value:
            return self.label.replace(" ", "_").replace("-", "_").upper()
        elif self.kind == enums.ExpressionKind.METRIC.value:
            return self.label.replace(" ", "_").replace("-", "_").lower()
        elif self.kind == enums.ExpressionKind.STRUCTURE.value:
            return self.label.replace(" ", "_").replace("-", "_").lower()
        else:
            raise ValueError(f"Unknown kind {self.kind}")


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


class LinkedExpression(models.Model):
    """An EntityClass is the semantic class of an entity"""

    graph = models.ForeignKey(
        Graph,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="linked_expressions",
        help_text="The group this entity class belongs to",
    )
    expression = models.ForeignKey(
        Expression,
        on_delete=models.CASCADE,
        related_name="linked_expressions",
        help_text="The expression this entity class belongs to",
    )
    kind = models.CharField(
        max_length=1000,
        help_text="The kind of the entity class",
        null=True,
    )
    metric_kind = TextChoicesField(
        choices_enum=enums.MetricDataTypeChoices,
        help_text="The data type (if a metric)",
        null=True,
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
        help_text="The name of the entity class in the age graph",
        null=True,
    )
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_linked_expressions",
        blank=True,
        help_text="The users that pinned this Expression",
    )

    class Meta:
        default_related_name = "linked_expressions"
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "age_name"],
                name="unique_age_name_in_graph",
            )
        ]

    def __str__(self) -> str:
        return f"{self.expression} in {self.graph}"

    def create_entity(
        self, group, name: str = None, instance_kind: str = None, metrics: dict = None
    ) -> str:
        from core.age import create_age_entity

        return create_age_entity(self.graph.age_name, self.age_name)

    @property
    def rgb_color_string(self) -> str:
        return f"rgb({self.color[0]}, {self.color[1]}, {self.color[2]})"


class GraphViews(models.Model):
    """A view of a graph that is materialized"""

    graph = models.ForeignKey(
        Graph,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="graph_views",
        help_text="The graph this materialized graph belongs to",
    )
    query = models.CharField(
        max_length=7000, help_text="The query that is used to materialize the graph"
    )
    name = models.CharField(
        max_length=1000, help_text="The name of the materialized graph"
    )
    kind = models.CharField(
        max_length=1000,
        help_text="The kind of the materialized graph (i.e one-to-one, one-to-many, many-to-many)",
    )


class MaterializedGraph(models.Model):
    view = models.ForeignKey(
        GraphViews,
        on_delete=models.CASCADE,
        related_name="materialized_graphs",
        help_text="The graph this model was trained on",
    )
    materialized_at = models.DateTimeField(
        auto_now_add=True,
        help_text="The time the model was materialized. All newer entities are not part of the materialized graph",
    )


class Model(models.Model):
    """A Model is a deep learning model"""

    name = models.CharField(max_length=1000, help_text="The name of the model")
    materialized_graph = models.ForeignKey(
        MaterializedGraph,
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
