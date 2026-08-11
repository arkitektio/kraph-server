import random
from typing import Any
from django.db import models
from django.contrib.auth import get_user_model
from kante import Info
from core import enums
from core import managers
from koherent.fields import ProvenanceField
from django_choices_field import TextChoicesField
from datalayer import models as datalayer_models
from authentikate.models import Organization, Membership
from polymorphic.models import PolymorphicModel
from django.db.models import Q, QuerySet
from kante.context import Membership as KanteMembership
from graph_engine import input_models
# Create your models here.

from graph_engine.input_models import EntityDescriptorInput, StructureDescriptorInput


class Graph(models.Model):
    """An Graph is a collection of Entities.

    It is used to group Entities together, for example all groups that
    are part of a specific sample, or all entities that are part of a specific
    experiment. Within an entity group, entities are unique according
    to their name.s

    """

    objects: managers.GraphManager = managers.GraphManager()

    node_deletion_allowed = models.BooleanField(
        default=True,
        help_text="If node deletion is allowed in this graph",
    )
    edge_deletion_allowed = models.BooleanField(
        default=True,
        help_text="If edge deletion is allowed in this graph",
    )
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="graphs")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="graphs")
    user = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="graphs",
        help_text="The user that this graph belongs to",
    )
    image = models.ForeignKey(
        datalayer_models.MediaStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the image if associated with the category",
    )
    name = models.CharField(max_length=1000, help_text="The name of the entity group")
    purl = models.CharField(max_length=1000, help_text="The name of the entity group", null=True, blank=True)
    description = models.CharField(
        max_length=2000,
        help_text="The description of the entity group",
        null=True,
    )
    provenance = ProvenanceField()
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
    rules = models.JSONField(
        default=list,
        blank=True,
        help_text="Action-level allow/deny rules evaluated against request context",
    )
    selector = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Declarative definition of which of the organization's evidence this graph "
            "projects. A graph is a view now, not a silo: membership is evaluated from "
            "this selector into a droppable cache, never maintained on write — otherwise "
            "every ingest would have to know about every projection. "
            "Shape: {category_keys: [...], assertion_filter: {subjects, app_ids, "
            "action_names}, as_of: timestamp, observed_window: [from, to]}. "
            "Consumed by the projector in M3; inert until then."
        ),
    )

    @classmethod
    def get_for_node_global_id(cls, node_id: str):
        graph_id, node_id = node_id.split(":")
        return cls.objects.get(id=graph_id)

    @classmethod
    def create_age_name(cls, name: str, organization: Organization) -> str:
        base_name = "".join(e for e in name if e.isalnum()).lower()
        org_slug = "".join(e for e in organization.slug if e.isalnum()).lower()
        age_name = f"{base_name}_{org_slug}"
        counter = 1
        while cls.objects.filter(age_name=age_name, organization=organization).exists():
            age_name = f"{base_name}_{org_slug}_{counter}"
            counter += 1
        return age_name

    @property
    def rules_model(self) -> list[input_models.ActionRuleInput]:
        from graph_engine.input_models import ActionRuleInput

        return [ActionRuleInput(**rule) for rule in self.rules] if self.rules else []

    def get_age_name(self) -> str:
        """Get the Apache AGE graph name for this graph, which is used to identify the graph in the AGE database."""
        return self.age_name

    def get_entity_def(self, key: str) -> "EntityCategory":
        """Get the entity definition for a specific label from the active schema."""
        return self.entity_categories.get(key=key)

    async def aget_entity_def(self, key: str) -> "EntityCategory":
        """Async version of get_entity_def."""
        return await self.entity_categories.aget(key=key)

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
    def structure_relation_categories(self):
        return StructureRelationCategory.objects.filter(graph=self)

    @property
    def measurement_categories(self):
        return MeasurementCategory.objects.filter(graph=self)

    @property
    def metric_categories(self):
        return MetricCategory.objects.filter(graph=self)

    @property
    def protocol_event_categories(self):
        return ProtocolEventCategory.objects.filter(graph=self)

    @property
    def natural_event_categories(self):
        return NaturalEventCategory.objects.filter(graph=self)

    @property
    def reagent_categories(self):
        return ReagentCategory.objects.filter(graph=self)

    @property
    def active_schema(self) -> "GraphSchema | None":
        """Get the currently active schema for this graph, if any."""
        return self.schemas.filter(is_active=True).first()

    @property
    def definition(self):
        """Get the GraphDefinitionModel from the active schema."""
        from graph_engine.input_models import GraphDefinitionModel

        schema = self.active_schema
        if schema:
            return GraphDefinitionModel.model_validate(schema.definition)
        return None

    def can_auto_add_structures(self, info: Info) -> bool:
        """Whether this graph allows automatically adding structures when recording metrics with new structure identifiers."""
        return self.can_perform_action(info=info, action="AUTO_ADD_STRUCTURES")

    def _extract_request_roles(self, info: Info | Any) -> set[str]:
        return set()

    def _extract_request_scopes(self, request: Any) -> set[str]:
        return set()

    def _rule_filter_matches(self, rule_filter: input_models.ActionFilterInput, request: Any) -> bool:
        required_roles = rule_filter.required_roles if rule_filter else None
        if required_roles:
            request_roles = self._extract_request_roles(info=request)
            if not set(map(str, required_roles)).issubset(request_roles):
                return False

        required_scopes = rule_filter.required_scopes if rule_filter else None
        if required_scopes:
            request_scopes = self._extract_request_scopes(request)
            if not set(map(str, required_scopes)).issubset(request_scopes):
                return False

        return True

    def can_perform_action(self, info: Info | Any, action: input_models.Action) -> bool:
        # DO NOT CHANGE THIS THIS PART WE WILL ONLY EXTRAX ROLES AND SCOPES HERE AND THEN CHECK THEM IN THE RULES, THIS WAY WE CAN SUPPORT BOTH A FLAT RULE STRUCTURE AND A NESTED ONE WITH ACTIONS AS KEYS
        scopes = self._extract_request_scopes(info)
        roles = self._extract_request_roles(info)
        for rule in self.rules_model:
            rule_action = rule.action
            if rule_action and rule_action != action:
                continue

            rule_filter = rule.filter
            if not self._rule_filter_matches(rule_filter, info.context.request):
                continue

            if rule.allow:
                return True
            else:
                return False

        return True

    def validate_action_allowed(self, info: Info | Any, action: str) -> None:
        if not self.can_perform_action(info=info, action=action):
            raise PermissionError(f"Action {action} is not allowed in this graph for the current user context")

    @property
    def allow_adding_structure_definitions(self) -> bool:
        return True

    @property
    def allow_auto_add_structures(self) -> bool:
        return True

    @property
    def allow_auto_add_structure_definitions(self) -> bool:
        return True

    @property
    def allow_adding_entity_definitions(self) -> bool:
        return True

    @property
    def allow_adding_relation_definitions(self) -> bool:
        return True

    @property
    def allow_auto_adding_metrics(self) -> bool:
        return True

    def validate_accessible(self, membership: Membership, scopes: list[str]):
        """Validate if the graph is accessible for a given membership and scopes."""
        if self.membership.organization != membership.organization:
            raise PermissionError("You do are not allowed to access this graph")
        # Here you can add additional scope checks if needed
        return True


class GraphSchema(models.Model):
    """
    A versioned schema definition for a graph.

    Schemas are immutable once created. Each graph has one active schema
    at a time, and schemas have increasing indices for version tracking.
    """

    graph = models.ForeignKey(
        Graph,
        on_delete=models.CASCADE,
        related_name="schemas",
        help_text="The graph this schema belongs to",
    )

    version = models.CharField(
        max_length=100,
        help_text="Semantic version of this schema (e.g., '1.0.0')",
    )

    index = models.PositiveIntegerField(
        help_text="Sequential index of this schema version (auto-incremented)",
    )

    definition = models.JSONField(
        help_text="The full GraphDefinitionModel as JSON",
    )

    is_active = models.BooleanField(
        default=False,
        help_text="Whether this is the currently active schema for the graph",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    created_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_schemas",
        help_text="User who created this schema",
    )

    description = models.TextField(
        null=True,
        blank=True,
        help_text="Description of changes in this schema version",
    )

    hash = models.CharField(
        max_length=64,
        default="",
        db_index=True,
        help_text=(
            "Content hash of `definition`. This is the identity a projected node stamps as its "
            "`__schema_version`, so a derived value can be told apart from one computed under an "
            "older schema. Distinct from `NodeCategory.schema_hash`, which hashes one category's "
            "properties rather than the whole graph definition."
        ),
    )

    class Meta:
        # `index` is the sequence; `version` is the *semantic* version of the
        # schema format. Many revisions legitimately share one semantic version —
        # every edit to a 1.0.1 schema is still 1.0.1 — so uniqueness belongs on
        # the index alone. `(graph, version)` was harmless only while there was
        # exactly one schema per graph, and blocks per-change versioning outright.
        unique_together = [("graph", "index")]
        ordering = ["-index"]
        constraints = [
            # One active schema per graph, enforced by the database rather than by
            # convention. `activate()` deactivating siblings is not enough on its
            # own: two concurrent activations would each see the other as
            # inactive, and a graph with two active schemas has no answer to
            # "which version derived this value".
            models.UniqueConstraint(
                fields=["graph"],
                condition=Q(is_active=True),
                name="one_active_schema_per_graph",
            )
        ]

    def __str__(self) -> str:
        active_marker = " (active)" if self.is_active else ""
        return f"{self.graph.name} v{self.version}{active_marker}"

    def save(self, *args, **kwargs) -> None:
        """Assign the next index and content hash before saving."""
        if self.index is None:
            last_schema = GraphSchema.objects.filter(graph=self.graph).order_by("-index").first()
            self.index = (last_schema.index + 1) if last_schema else 1
        if not self.hash and self.definition:
            from graph_engine.materialize import compute_definition_hash

            self.hash = compute_definition_hash(self.definition)
        super().save(*args, **kwargs)

    def activate(self) -> None:
        """Make this the graph's active schema.

        The only supported way to set `is_active`. Deactivating siblings first is
        required by the partial unique constraint above — writing `is_active=True`
        directly on a second schema is a database error, which is the point.
        """
        GraphSchema.objects.filter(graph=self.graph).exclude(pk=self.pk).update(is_active=False)
        self.is_active = True
        self.save(update_fields=["is_active"])

    @classmethod
    def active_for(cls, graph: "Graph") -> "GraphSchema | None":
        """The graph's current schema, or None if it has never been materialized."""
        return cls.objects.filter(graph=graph, is_active=True).first()

def random_color():
    levels = range(32, 256, 32)
    return tuple(random.choice(levels) for _ in range(3))


class GraphOntology(models.Model):
    """An ontology reference for the graph schema."""

    graph = models.ForeignKey(
        "Graph",
        on_delete=models.CASCADE,
        related_name="ontologies",
        help_text="The graph this ontology belongs to",
    )
    name = models.CharField(
        max_length=1000,
        help_text="The name of the ontology",
    )
    url = models.CharField(
        max_length=2000,
        help_text="The URL of the ontology",
    )
    description = models.CharField(
        max_length=2000,
        help_text="The description of the ontology",
        null=True,
    )

    class Meta:
        unique_together = ("graph", "name")
        default_related_name = "graph_ontologies"


class OntologyReference(models.Model):
    category = models.ForeignKey(
        "Category",
        on_delete=models.CASCADE,
        related_name="ontology_references",
    )
    name = models.CharField(
        max_length=1000,
        help_text="The name of the ontology reference",
    )
    ontology = models.ForeignKey(
        GraphOntology,
        on_delete=models.CASCADE,
        related_name="references",
    )


class GraphSequence(models.Model):
    """A node index for a category"""

    graph = models.ForeignKey(
        Graph,
        on_delete=models.CASCADE,
        related_name="graph_sequences",
        help_text="The graph this sequence belongs to",
    )

    index = models.CharField(
        max_length=1000,
        help_text="The index name that was created",
    )
    label = models.CharField(
        max_length=1000,
        help_text="The label of the sequence",
        null=True,
    )
    description = models.CharField(
        max_length=1000,
        help_text="The description of the sequence",
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    min_value = models.IntegerField(default=0)
    start_value = models.IntegerField(default=0)
    max_value = models.IntegerField(
        null=True,
        blank=True,
        help_text="The maximum value of the sequence (can be null if not set)",
    )
    cycle = models.BooleanField(
        default=False,
        help_text="If the sequence is circular (e.g. 1,2,3,4,5,1,2,3,4,5)",
    )
    step_size = models.IntegerField(
        default=1,
        help_text="The step size of the sequence (e.g. 1,2,3,4,5,6)",
    )

    class Meta:
        unique_together = ("graph", "index")
        default_related_name = "graph_sequences"

    @property
    def ps_name(self) -> str:
        return f"{self.graph.age_name}{self.index}"


class CategoryTag(models.Model):
    """A tag for a category"""

    graph = models.ForeignKey(
        "Graph",
        on_delete=models.CASCADE,
        related_name="category_tags",
        help_text="The graph this tag belongs to",
    )

    value = models.CharField(
        max_length=1000,
        help_text="The value of the tag",
    )
    name = models.CharField(
        max_length=1000,
        help_text="The name of the tag",
        null=True,
    )
    description = models.CharField(
        max_length=1000,
        help_text="The description of the tag",
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("graph", "value")
        default_related_name = "category_tags"


class Category(PolymorphicModel):
    objects = managers.CategoryManager()
    graph = models.ForeignKey(
        "Graph",
        on_delete=models.CASCADE,
    )
    sequence = models.ForeignKey(
        GraphSequence,
        on_delete=models.CASCADE,
        related_name="categories",
        null=True,
        blank=True,
        help_text="The index of this category (new entities will be created with this index)",
    )
    image = models.ForeignKey(
        datalayer_models.MediaStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the image if associated with the category",
    )
    color = models.JSONField(
        max_length=1000,
        help_text="The color of  node class in the graph (if a node)",
        default=random_color,
        null=True,
    )
    age_name = models.CharField(
        max_length=1000,
        help_text="The name of the graph class in the age graph",
    )
    key = models.CharField(
        max_length=1000,
        help_text="The entity key that the node relates to (e.g. a cell line, a cell type, etc.)",
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
        help_text="The tags of the category",
        blank=True,
    )
    color = models.JSONField(
        max_length=1000,
        help_text="The color of the entity class as RGB",
        default=random_color,
        null=True,
    )
    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_categories",
        help_text="The users that have this query active",
    )
    label = models.CharField(
        max_length=1000,
        help_text="The label of the node class",
        null=True,
    )
    ports = models.JSONField(
        help_text="The ports of the node class ssin the graph (if a node)",
        default=list,
        null=True,
    )

    class Meta:
        default_related_name = "categories"
        unique_together = ("graph", "age_name"), ("graph", "key")

    @classmethod
    def key_to_age_name(cls, key: str) -> str:
        """Convert an entity key to a valid AGE name by replacing invalid characters."""
        return "".join(e for e in key if e.isalnum()).lower()

    def relevant_queries(self):
        return GraphQuery.objects.filter(graph=self.graph, relevant_for=self.pk)


class Descriptor(models.Model):
    """A descriptor for a category"""

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="descriptors",
        help_text="The category this descriptor belongs to",
    )

    key = models.CharField(
        max_length=1000,
        help_text="The name of the descriptor",
    )
    description = models.CharField(
        max_length=1000,
        help_text="The description of the descriptor",
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    value = models.CharField(
        max_length=1000,
        help_text="The value of the descriptor",
    )

    class Meta:
        unique_together = ("category", "key")
        default_related_name = "descriptors"


class NodeCategory(Category):
    objects = managers.NodeCategoryManager()
    """A Node class is a class that describes a node in the graph which represent
    a bioentity (e.g. a cell, a tissue, etc.). Node classes are the most basic building
    block of the graph and represent physical objects that can be measured
    by structures, related to other entities by relations and subjected to specific
    protocol steps.

    """

    schema_hash = models.CharField(
        max_length=1000,
        help_text="The schema hash representing the version of the schema this category was defined with",
        default="",
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
    property_definitions = models.JSONField(default=list, help_text="The property definitions of this")

    def get_age_vertex_name(self):
        raise NotImplementedError("Not implemented needs to be implemented")

    def get_age_type_name(self):
        raise NotImplementedError("Not implemented needs to be implemented")

    @property
    def defined_properties(self):
        from graph_engine.input_models import PropertyDefinitionInput

        return [PropertyDefinitionInput(**p) for p in self.property_definitions] if self.property_definitions else []

    @property
    def property_map(self):
        return {prodf.key: prodf for prodf in self.defined_properties}

    @classmethod
    def key_to_age_name(cls, key: str) -> str:
        """Convert an entity key to a valid AGE name by replacing invalid characters."""
        return "".join(e for e in key if e.isalnum()).lower()


class EdgeCategory(Category):
    objects = managers.EdgeCategoryManager()
    """An Edge class is a class that describes an edge in the graph which represents a relationship between two nodes."""

    source_definition = models.JSONField(
        default=dict,
        help_text="Filters for the right side of the edge (e.g. which tags the right side should have)",
        null=True,
    )
    target_definition = models.JSONField(
        default=dict,
        help_text="Filters for the left side of the edge (e.g. which tags the left side should have)",
        null=True,
    )
    reverse_label = models.CharField(
        max_length=1000,
        help_text="The reverse label of the edge class",
        null=True,
    )
    property_definitions = models.JSONField(default=list, help_text="The property definitions of this")

    def get_age_edge_name(self) -> str:
        """Should return the name of the edge in the age graph"""
        raise NotImplementedError("Not implemented needs to be implemented")

    def get_age_type_name(self) -> str:
        """Should return the type name of the edge in the age graph"""
        raise NotImplementedError("Not implemented needs to be implemented")

    @property
    def defined_properties(self):
        from graph_engine.input_models import PropertyDefinitionInput

        return [PropertyDefinitionInput(**p) for p in self.property_definitions] if self.property_definitions else []

    @property
    def property_map(self):
        return {prodf.key: prodf for prodf in self.defined_properties}

    @classmethod
    def key_to_age_name(cls, key: str) -> str:
        """Convert an entity key to a valid AGE name by replacing invalid characters."""
        return "".join(e for e in key if e.isalnum()).upper()


class StructureCategory(NodeCategory):
    objects: managers.StructureCategoryManager = managers.StructureCategoryManager()
    """A Structure class is a class represents a datapoint in your graph and
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

    def get_age_vertex_name(self):
        return "Structure"

    def get_age_type_name(self) -> str:
        return "STRUCTURE"

    def get_age_identifier(self):
        return self.identifier

    class Meta:
        default_related_name = "structure_categories"


class NaturalEventCategory(NodeCategory):
    objects: managers.NaturalEventCategoryManager = managers.NaturalEventCategoryManager()
    """A natural event class is a class that describes a natural event that happened
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

    source_entity_roles = models.JSONField(
        default=list,
        help_text="The categories or expressions that an event of this class can source from (source edges)",
    )
    target_entity_roles = models.JSONField(
        default=list,
        help_text="The categories or expressions that an of this class can target to (target edges)",
    )
    plate_children = models.JSONField(null=True, blank=True)

    def get_inrole_vertex_name(self, role):
        return role

    def get_outrole_vertex_name(self, role):
        return role

    def get_age_vertex_name(self) -> str:
        return self.age_name

    def get_age_type_name(self) -> str:
        return "NATURAL_EVENT"

    def get_age_input_role_edge_name(self, role) -> str:
        return "WENT_THROUGH"

    def get_age_output_role_edge_name(self, role) -> str:
        return "CAME_OUT_OF"

    @property
    def collected_in_role_vertex_name(self):
        return ["WENT_THROUGH"]  # TODO This needs to be implemented but currently not used

    @property
    def collected_out_role_vertex_name(self):
        return ["CREATED"]  # TODO This needs to be implemented but currently not used

    class Meta:
        default_related_name = "natural_event_categories"


class ProtocolEventCategory(NodeCategory):
    objects: managers.ProtocolEventCategoryManager = managers.ProtocolEventCategoryManager()
    """A protocol event class is a node that describes a protocol event that some
    entities were subjected to using, creating or altering them.

    E.g.

    CreationEvent:
        (a: Animal) -> [r: SUBJECTED_IN] -> (p: ExtractionEvent) -> [d: PRODUCED] -> (b: Hippocampus)

    Transformation:
        (a: Animal) -> [r: SUBJECTED_IN] -> (f: FixationEvent) -> [d: PRODUCED] -> (b: Animal)
        (b: FourPercentFormaldayhyde) -> [r: SUBJECTED_IN {quantity: 50µm }] -> (f: FixationEvent)
    """

    source_entity_roles = models.JSONField(
        default=list,
        help_text="The categories or expressions that an event of this class can source from (source edges)",
    )
    target_entity_roles = models.JSONField(
        default=list,
        help_text="The categories or expressions that an of this class can target to (target edges)",
    )
    source_reagent_roles = models.JSONField(
        default=list,
        help_text="The categories or expressions that an event of this class can source from (source edges)",
    )
    target_reagent_roles = models.JSONField(
        default=list,
        help_text="The categories or expressions that an of this class can target to (target edges)",
    )
    variable_definitions = models.JSONField(
        default=list,
        help_text="The variables of a instance this protocol event will needs (properties on the node)",
    )
    plate_children = models.JSONField(null=True, blank=True)

    def get_inrole_vertex_name(self, role):
        return role

    def get_outrole_vertex_name(self, role):
        return role

    def get_age_vertex_name(self):
        return self.age_name

    def get_age_type_name(self) -> str:
        return "PROTOCOL_EVENT"

    @property
    def collected_in_role_vertex_name(self):
        return ["UNDERWENT"]  # TODO This needs to be implemented but currently not used

    @property
    def collected_out_role_vertex_name(self):
        return ["CREATED"]  # TODO This needs to be implemented but currently not used

    class Meta:
        default_related_name = "protocol_event_categories"


class Protocol(models.Model):
    graph = models.ForeignKey(
        Graph,
        on_delete=models.CASCADE,
        related_name="protocols",
        help_text="The graph this protocol belongs to",
    )
    name = models.CharField(max_length=1000, help_text="The name of the protocol")
    description = models.CharField(
        max_length=2000,
        help_text="The description of the protocol",
        null=True,
    )
    plate_children = models.JSONField(
        default=list,
        help_text="The steps of the protocol, each step is a dict with the following keys: name, description, event_category, source_entities, target_entities, source_reagents, target_reagents, variables",
    )


class EntityCategory(NodeCategory):
    objects: managers.EntityCategoryManager = managers.EntityCategoryManager()
    """An Entity class is a class that describes a node in the graph which represent
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

    def get_age_vertex_name(self):
        return self.age_name

    def get_age_type_name(self) -> str:
        return "ENTITY"

    @property
    def descriptors(self) -> QuerySet["Descriptor"]:
        return self.descriptors

    class Meta:
        default_related_name = "entity_categories"


class ReagentCategory(NodeCategory):
    objects = managers.ReagentCategoryManager()
    """An Regation class is a class that describes a node in the graph which represent
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

    def get_age_vertex_name(self):
        return self.age_name

    def get_age_type_name(self) -> str:
        return "REAGENT"

    class Meta:
        default_related_name = "reagent_categories"


class MetricCategory(NodeCategory):
    objects: managers.MetricCategoryManager = managers.MetricCategoryManager()
    """A Metric class is an analticay statement that describes a structure.

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

    value_kind = TextChoicesField(
        choices_enum=enums.MetricKindChoices,
        help_text="The data type (if a metric)",
        null=True,
        blank=True,
    )
    structure_category = models.ForeignKey(
        StructureCategory,
        on_delete=models.CASCADE,
        related_name="metric_categories",
        help_text="The structure category that this metric describes",
    )

    def validate_input(self, value):
        if self.metric_kind == enums.MetricKind.INT:
            try:
                return int(value)
            except ValueError:
                raise ValueError(f"Value {value} is not an integer")
        elif self.metric_kind == enums.MetricKind.FLOAT:
            try:
                return float(value)
            except ValueError:
                raise ValueError(f"Value {value} is not a float")
        elif self.metric_kind == enums.MetricKind.BOOLEAN:
            if value not in [True, False, "true", "false", "True", "False", 1, 0, "1", "0"]:
                raise ValueError(f"Value {value} is not a boolean")
            return value in [True, "true", "True", 1, "1"]
        # STRING and CATEGORICAL do not need validation
        return value

    def get_age_vertex_name(self):
        return self.age_name

    def get_age_type_name(self) -> str:
        return "METRIC"

    class Meta:
        default_related_name = "metric_categories"


class MeasurementCategory(EdgeCategory):
    objects = managers.MeasurementCategoryManager()
    """A Measurement class is a class that describes an edge with a value"""

    def get_age_edge_name(self):
        return self.age_name

    def get_age_type_name(self) -> str:
        return "MEASUREMENT"

    @property
    def source_definition_model(self) -> StructureDescriptorInput:
        return StructureDescriptorInput(**self.source_definition)

    @property
    def target_definition_model(self) -> EntityDescriptorInput:
        return EntityDescriptorInput(**self.target_definition)

    def matches_source(self, entity: "StructureCategory") -> bool:
        """Check if an entity matches the source definition of this edge category."""
        return self.source_definition_model.matches(entity)

    def matches_target(self, entity: "EntityCategory") -> bool:
        """Check if an entity matches the target definition of this edge category."""
        return self.target_definition_model.matches(entity)

    def get_matching_source_structures(self) -> QuerySet["StructureCategory"]:
        """Get all structures in the graph that match the source definition of this edge category."""
        """Get all entities in the graph that match the target definition of this edge category."""
        kwargs = {}
        if self.source_definition_model.keys:
            kwargs["key__in"] = self.source_definition_model.keys
        if self.source_definition_model.tags:
            kwargs["tags__value__in"] = self.source_definition_model.tags
        if self.source_definition_model.ontotology_terms:
            kwargs["ontology_references__name__in"] = self.source_definition_model.ontotology_terms

        return self.graph.structure_categories.filter(**kwargs).distinct()

    def get_matching_target_entities(self) -> QuerySet["EntityCategory"]:
        """Get all entities in the graph that match the target definition of this edge category."""
        kwargs = {}
        if self.target_definition_model.keys:
            kwargs["key__in"] = self.target_definition_model.keys
        if self.target_definition_model.tags:
            kwargs["tags__value__in"] = self.target_definition_model.tags
        if self.target_definition_model.ontotology_terms:
            kwargs["ontology_references__name__in"] = self.target_definition_model.ontotology_terms

        return self.graph.entity_categories.filter(**kwargs).distinct()

    class Meta:
        default_related_name = "measurement_categories"


class RelationCategory(EdgeCategory):
    """A Relation class is a class that describes a relation between two entities without a value"""

    objects: managers.RelationCategoryManager = managers.RelationCategoryManager()
    reverse_description = models.CharField(
        max_length=1000,
        help_text="The description of category",
        null=True,
    )

    @property
    def source_definition_model(self) -> EntityDescriptorInput:
        return EntityDescriptorInput(**self.source_definition)

    @property
    def target_definition_model(self) -> EntityDescriptorInput:
        return EntityDescriptorInput(**self.target_definition)

    def matches_source(self, entity: "EntityCategory") -> bool:
        """Check if an entity matches the source definition of this edge category."""
        return self.source_definition_model.matches(entity)

    def matches_target(self, entity: "EntityCategory") -> bool:
        """Check if an entity matches the target definition of this edge category."""
        return self.target_definition_model.matches(entity)

    def get_matching_source_entities(self) -> QuerySet["EntityCategory"]:
        """Get all entities in the graph that match the source definition of this edge category."""
        """Get all entities in the graph that match the target definition of this edge category."""
        kwargs = {}
        if self.source_definition_model.keys:
            kwargs["key__in"] = self.source_definition_model.keys
        if self.source_definition_model.tags:
            kwargs["tags__value__in"] = self.source_definition_model.tags
        if self.source_definition_model.ontotology_terms:
            kwargs["ontology_references__name__in"] = self.source_definition_model.ontotology_terms

        return self.graph.entity_categories.filter(**kwargs).distinct()

    def get_matching_target_entities(self) -> QuerySet["EntityCategory"]:
        """Get all entities in the graph that match the target definition of this edge category."""
        kwargs = {}
        if self.target_definition_model.keys:
            kwargs["key__in"] = self.target_definition_model.keys
        if self.target_definition_model.tags:
            kwargs["tags__value__in"] = self.target_definition_model.tags
        if self.target_definition_model.ontotology_terms:
            kwargs["ontology_references__name__in"] = self.target_definition_model.ontotology_terms

        return self.graph.entity_categories.filter(**kwargs).distinct()

    def get_age_edge_name(self):
        return self.age_name

    def get_age_type_name(self) -> str:
        return "RELATION"

    def source_matches(self, entity: EntityCategory) -> bool:
        """Check if the given entity matches the source definition of this relation category."""
        if not self.source_definition:
            return True  # If no source definition, match all
        # For simplicity, we assume source_definition is a list of required tags
        required_tags = set(self.source_definition.get("tags", []))
        entity_tags = set(entity.tags.values_list("value", flat=True))
        return required_tags.issubset(entity_tags)

    class Meta:
        default_related_name = "relation_categories"


class StructureRelationCategory(EdgeCategory):
    """A Relation class is a class that describes a relation between two entities without a value"""

    reverse_description = models.CharField(
        max_length=1000,
        help_text="The description of category",
        null=True,
    )

    @property
    def source_definition_model(self) -> StructureDescriptorInput:
        return StructureDescriptorInput(**self.source_definition)

    @property
    def target_definition_model(self) -> StructureDescriptorInput:
        return StructureDescriptorInput(**self.target_definition)

    def matches_source(self, entity: "StructureCategory") -> bool:
        """Check if a structure matches the source definition of this edge category."""
        return self.source_definition_model.matches(entity)

    def matches_target(self, entity: "StructureCategory") -> bool:
        """Check if a structure matches the target definition of this edge category."""
        return self.target_definition_model.matches(entity)

    def get_matching_source_structures(self) -> QuerySet["StructureCategory"]:
        """Get all structures in the graph that match the source definition of this edge category."""
        """Get all structures in the graph that match the target definition of this edge category."""
        kwargs = {}
        if self.source_definition_model.keys:
            kwargs["key__in"] = self.source_definition_model.keys
        if self.source_definition_model.tags:
            kwargs["tags__value__in"] = self.source_definition_model.tags
        if self.source_definition_model.ontotology_terms:
            kwargs["ontology_references__name__in"] = self.source_definition_model.ontotology_terms
        if self.source_definition_model.identifiers:
            kwargs["identifier__in"] = self.source_definition_model.identifiers

        return self.graph.structure_categories.filter(**kwargs).distinct()

    def get_matching_target_structures(self) -> QuerySet["StructureCategory"]:
        """Get all structures in the graph that match the target definition of this edge category."""
        kwargs = {}
        if self.target_definition_model.keys:
            kwargs["key__in"] = self.target_definition_model.keys
        if self.target_definition_model.tags:
            kwargs["tags__value__in"] = self.target_definition_model.tags
        if self.target_definition_model.ontotology_terms:
            kwargs["ontology_references__name__in"] = self.target_definition_model.ontotology_terms
        if self.target_definition_model.identifiers:
            kwargs["identifier__in"] = self.target_definition_model.identifiers

        return self.graph.structure_categories.filter(**kwargs).distinct()

    def get_age_edge_name(self):
        return self.age_name

    def get_age_type_name(self) -> str:
        return "STRUCTURE_RELATION"

    class Meta:
        default_related_name = "structure_relation_categories"


class GraphQuery(PolymorphicModel):
    graph = models.ForeignKey(
        Graph,
        on_delete=models.CASCADE,
        related_name="queries",
        help_text="The graph this query belongs to",
    )
    key = models.CharField(
        max_length=1000,
        help_text="The key of the query, used for referencing the query in the frontend and for pinning it",
    )
    query = models.CharField(max_length=7000, help_text="The query that is used to materialize the graph")
    name = models.CharField(max_length=1000, help_text="The name of the materialized graph")
    description = models.CharField(
        max_length=1000,
        help_text="The description of the materialized graph",
        null=True,
    )
    kind = models.CharField(
        max_length=1000,
        help_text="The kind of the materialized graph (i.e path, property, etc.)",
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
    returns = models.JSONField(
        help_text="The returns of the query",
        default=list,
        null=True,
    )
    matches = models.JSONField(
        help_text="The matches of the query",
        default=list,
        null=True,
    )
    wheres = models.JSONField(
        help_text="The wheres of the query",
        default=list,
        null=True,
    )

    class Meta(PolymorphicModel.Meta):
        """Some Meta options for the GraphQuery model"""

        default_related_name = "graph_queries"
        unique_together = ("graph", "key")


class GraphNodesQuery(GraphQuery):
    """A query that is used to materialize a list of nodes"""

    # The node category this query is associated with (e.g. if this is a query that materializes the nodes of a certain category, this is the category)
    node_category = models.ForeignKey(
        NodeCategory,
        default=None,
        null=True,
        on_delete=models.CASCADE,
        related_name="node_list_queries",
        help_text="The category this query is associated if its a node_list",
    )


class GraphPathQuery(GraphQuery):
    """A query that is used to materialize a list of paths"""

    # The node category this query is associated with (e.g. if this is a query that materializes the nodes of a certain category, this is the category)
    left_category = models.ForeignKey(
        NodeCategory,
        default=None,
        null=True,
        on_delete=models.CASCADE,
        related_name="path_list_queries",
        help_text="The category this query is associated if its a path_list",
    )
    right_category = models.ForeignKey(
        NodeCategory,
        default=None,
        null=True,
        on_delete=models.CASCADE,
        related_name="path_list_queries_right",
        help_text="The category this query is associated if its a path_list",
    )


class GraphPairsQuery(GraphQuery):
    """A query that is used to materialize a list of paths"""

    # The node category this query is associated with (e.g. if this is a query that materializes the nodes of a certain category, this is the category)
    left_category = models.ForeignKey(
        NodeCategory,
        default=None,
        null=True,
        on_delete=models.CASCADE,
        related_name="pairs_left_queries",
        help_text="The category this query is associated if its a path_list",
    )
    right_category = models.ForeignKey(
        NodeCategory,
        default=None,
        null=True,
        on_delete=models.CASCADE,
        related_name="pairs_right_queries",
        help_text="The category this query is associated if its a path_list",
    )


class GraphTableQuery(GraphQuery):
    """A query that is used to materialize a table"""

    columns = models.JSONField(
        help_text="The columns (if ViewKind is Table)",
        default=list,
        null=True,
    )

    @property
    def input_columns(self):
        from core import inputs

        return [inputs.ColumnInput(**i) for i in self.columns]


class NodeQuery(PolymorphicModel):
    graph = models.ForeignKey(
        Graph,
        on_delete=models.CASCADE,
        related_name="node_queries",
        help_text="The graph this query belongs to",
    )
    key = models.CharField(
        max_length=1000,
        help_text="The key of the query, used for referencing the query in the frontend and for pinning it",
    )
    query = models.CharField(max_length=7000, help_text="The query that is used to materialize the graph")
    name = models.CharField(max_length=1000, help_text="The name of the materialized graph")
    description = models.CharField(
        max_length=1000,
        help_text="The description of the materialized graph",
        null=True,
    )
    kind = models.CharField(
        max_length=1000,
        help_text="The kind of the materialized graph (i.e path, property, etc.)",
    )

    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_node_queries",
        help_text="The users that have this query active",
    )
    relevant_for_nodes = models.ManyToManyField(
        NodeCategory,
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

    class Meta(PolymorphicModel.Meta):
        """Some Meta options for the GraphQuery model"""

        default_related_name = "node_queries"
        unique_together = ("graph", "key")


class NodePathQuery(NodeQuery):
    pass


class NodePairsQuery(NodeQuery):
    pass


class NodeTableQuery(NodeQuery):
    columns = models.JSONField(
        help_text="The columns (if ViewKind is Table)",
        default=list,
        null=True,
    )

    @property
    def input_columns(self):
        from core import inputs

        return [inputs.ColumnInput(**i) for i in self.columns]


class EdgeQuery(PolymorphicModel):
    graph = models.ForeignKey(
        Graph,
        on_delete=models.CASCADE,
        related_name="edge_queries",
        help_text="The graph this query belongs to",
    )
    key = models.CharField(
        max_length=1000,
        help_text="The key of the query, used for referencing the query in the frontend and for pinning it",
    )
    query = models.CharField(max_length=7000, help_text="The query that is used to materialize the graph")
    name = models.CharField(max_length=1000, help_text="The name of the materialized graph")
    description = models.CharField(
        max_length=1000,
        help_text="The description of the materialized graph",
        null=True,
    )
    kind = models.CharField(
        max_length=1000,
        help_text="The kind of the materialized graph (i.e path, property, etc.)",
    )

    pinned_by = models.ManyToManyField(
        get_user_model(),
        related_name="pinned_edge_queries",
        help_text="The users that have this query active",
    )
    relevant_for_edges = models.ManyToManyField(
        EdgeCategory,
        related_name="relevant_edge_queries",
        help_text="The entities that this query should be mostly used for",
    )

    @property
    def input_columns(self):
        from core import inputs

        return [inputs.ColumnInput(**i) for i in self.columns]

    @classmethod
    def active_for_user_and_graph(self, user, graph):
        return self.objects.filter(graph=graph, pinned_by=user).first()

    class Meta(PolymorphicModel.Meta):
        """Some Meta options for the GraphQuery model"""

        default_related_name = "edge_queries"
        unique_together = ("graph", "key")


class EdgePathQuery(EdgeQuery):
    pass


class EdgePairsQuery(EdgeQuery):
    pass


class EdgeTableQuery(EdgeQuery):
    columns = models.JSONField(
        help_text="The columns (if ViewKind is Table)",
        default=list,
        null=True,
    )

    @property
    def input_columns(self):
        from core import inputs

        return [inputs.ColumnInput(**i) for i in self.columns]


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
    graph_query = models.ForeignKey(
        GraphTableQuery,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="scatter_plots",
        help_text="The query this scatter plot was trained on",
    )
    node_query = models.ForeignKey(
        NodeTableQuery,
        on_delete=models.CASCADE,
        related_name="scatter_plots",
        null=True,
        blank=True,
        help_text="The node query this scatter plot was trained on",
    )
    path_query = models.ForeignKey(
        NodePathQuery,
        on_delete=models.CASCADE,
        related_name="scatter_plots",
        null=True,
        blank=True,
        help_text="The path query this scatter plot was trained on",
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
    x_column = models.CharField(max_length=1000, help_text="The column that assigns the x value", null=True)
    x_id_column = models.CharField(max_length=1000, help_text="The column that assigns the x_id value", null=True)
    y_column = models.CharField(max_length=1000, help_text="The column that assigns the y value", null=True)
    y_id_column = models.CharField(
        max_length=1000,
        help_text="The column that assigns an ID to the y value",
        null=True,
    )
    color_column = models.CharField(max_length=1000, help_text="The column that assigns the color value", null=True)
    size_column = models.CharField(max_length=1000, help_text="The column that assigns the size value", null=True)
    shape_column = models.CharField(max_length=1000, help_text="The column that assigns the shape value", null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    creator = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="scatter_plots",
        help_text="The user that created the scatter plot",
    )


class MaterializedEdge(PolymorphicModel):
    graph = models.ForeignKey(
        Graph,
        on_delete=models.CASCADE,
        related_name="materialized_edges",
        help_text="The graph this edge belongs to",
    )


class MaterializedRelationEdge(MaterializedEdge):
    source = models.ForeignKey(
        EntityCategory,
        on_delete=models.CASCADE,
        related_name="materialized_relation_edges_as_source",
        help_text="The source category of the edge",
    )
    target = models.ForeignKey(
        EntityCategory,
        on_delete=models.CASCADE,
        related_name="materialized_relation_edges_as_target",
        help_text="The target category of the edge",
    )
    edge = models.ForeignKey(
        RelationCategory,
        db_column="relation_id",
        on_delete=models.CASCADE,
        related_name="materialized_relation_edges_as_relation",
        help_text="The relation category of the edge",
    )
    role = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
        help_text="The role of the edge, if its part of a protocol or natural event (e.g. source, target, etc.)",
    )


class MaterializedMeasurementEdge(MaterializedEdge):
    source = models.ForeignKey(
        StructureCategory,
        on_delete=models.CASCADE,
        related_name="materialized_measurement_edges_as_source",
        help_text="The source category of the edge",
    )
    target = models.ForeignKey(
        EntityCategory,
        on_delete=models.CASCADE,
        related_name="materialized_measurement_edges_as_target",
        help_text="The target category of the edge",
    )
    edge = models.ForeignKey(
        MeasurementCategory,
        db_column="measurement_id",
        on_delete=models.CASCADE,
        related_name="materialized_measurement_edges_as_measurement",
        help_text="The measurement category of the edge",
    )


class MaterializedStructureRelationEdge(MaterializedEdge):
    source = models.ForeignKey(
        StructureCategory,
        on_delete=models.CASCADE,
        related_name="materialized_structure_relation_edges_as_source",
        help_text="The source category of the edge",
    )
    target = models.ForeignKey(
        StructureCategory,
        on_delete=models.CASCADE,
        related_name="materialized_structure_relation_edges_as_target",
        help_text="The target category of the edge",
    )
    edge = models.ForeignKey(
        StructureRelationCategory,
        db_column="relation_id",
        on_delete=models.CASCADE,
        related_name="materialized_structure_relation_edges_as_relation",
        help_text="The relation category of the edge",
    )
    role = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
        help_text="The role of the edge, if its part of a protocol or natural event (e.g. source, target, etc.)",
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
        datalayer_models.MediaStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="models",
        help_text="The store of the model",
    )


# Needs to be here
