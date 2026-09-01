import random
import uuid
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
from django.db.models import Q, QuerySet
from kante.context import Membership as KanteMembership
from graph_engine import input_models
# Create your models here.

from graph_engine.input_models import EntityDescriptorInput, StructureDescriptorInput


class KindDiscriminatedModel(models.Model):
    """Concrete-table base for what used to be a multi-table inheritance root.

    Every former subclass is now a proxy over one table and a ``kind`` column is the
    only thing separating them. `KIND` is the value a proxy's rows carry -- stamped on
    save so that `Leaf(...).save()` and `Leaf.objects.create(...)` agree without every
    call site having to pass it. `KINDS` is the set a proxy can *read*, which is how the
    intermediate proxies (`NodeCategory`, `EdgeCategory`) cover several leaves at once.
    Both are None on the concrete base itself, which therefore sees every row.
    """

    KIND: "str | None" = None
    KINDS: "tuple[str, ...] | None" = None

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.kind:
            kind = type(self).KIND
            if kind is not None:
                self.kind = kind
        return super().save(*args, **kwargs)


def _matching_structure_kinds(organization, descriptor) -> "QuerySet":
    """Structure kinds in an organization that a descriptor selects.

    Only `identifiers` survives the move to organization vocabulary. A
    `StructureKind` has no `key`, no tag many-to-many and no ontology references,
    so `keys` / `tags` / `ontology_terms` cannot be matched — and rather than
    quietly selecting nothing, `StructureDescriptorInput` now rejects them at
    validation. See `graph_engine.input_models.StructureDescriptorInput`.
    """
    from evidence.models import StructureKind

    kinds = StructureKind.objects.for_organization(organization)
    if descriptor.identifiers:
        kinds = kinds.filter(identifier__in=descriptor.identifiers)
    return kinds.distinct()


def new_projection_handle() -> str:
    """A fresh, opaque handle for a graph's Apache AGE namespace.

    Random on purpose. The handle used to be derived from the graph's name and the
    organization's slug, which made it three things it should never have been:
    an identifier clients passed back as `graph:` (so a projection detail was the
    public address of a view), a value built from user input that was interpolated
    unescaped into `cypher('…')` and `create_graph('…')` (the only defence was an
    `isalnum()` filter in a different module), and a check-then-create that could
    still collide across organizations because the dedupe was per-organization
    while the column is globally unique.

    `g` + 32 hex digits: a leading letter keeps it a legal identifier whether
    quoted or not, `[a-z0-9]` keeps it safe to interpolate, and 33 bytes sits
    well under the 63-byte ceiling of the Postgres `name` column AGE stores graph
    names in. Nothing resolves a graph by it — `graph:` is a primary key.
    """
    return f"g{uuid.uuid4().hex}"


class Graph(models.Model):
    """A view over the organization's evidence: a selector saying which claims
    count, the categories saying what its words mean, and one Apache AGE
    namespace the projection is drawn into.
    """

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
        max_length=63,
        unique=True,
        editable=False,
        default=new_projection_handle,
        help_text=(
            "Internal handle of this graph's Apache AGE namespace. Random, assigned at "
            "creation, read only through `get_age_name()` by the engine. Not an identifier: "
            "a graph is addressed by its primary key. See `new_projection_handle`."
        ),
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
            "Read in three places, all at projection or read time: which metrics a derived "
            "property counts, whose classification claims a defined category admits, and whose "
            "existence claims decide whether a node is in this view at all. "
            "**Changing it requires a reproject**: the projection is a cache of the answer this "
            "selector produced, so editing the selector without rebuilding leaves the graph "
            "showing the previous one."
        ),
    )
    is_archived = models.BooleanField(
        default=False,
        help_text=(
            "Whether this graph has been put away. Archiving is the sanctioned "
            "alternative to deleting — `delete_graph`'s own refusal points at it — "
            "because deleting a graph destroys every rule for reading the evidence "
            "while the evidence itself survives. "
            "This field did not exist until now: `archive_graph` set the attribute on "
            "the Python object and called `save()`, which persisted nothing and told "
            "the caller it had worked. Nothing read it back either, since no GraphQL "
            "type exposed it, so a client could write the value and never observe that "
            "it had not taken. "
            "It is a container flag, not evidence: it says nothing about the world, "
            "only about what this user wants to see, so it is ordinary mutable Django "
            "state and carries no assertion."
        ),
    )

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
    def protocol_event_categories(self):
        return ProtocolEventCategory.objects.filter(graph=self)

    @property
    def natural_event_categories(self):
        return NaturalEventCategory.objects.filter(graph=self)

    @property
    def reagent_categories(self):
        return ReagentCategory.objects.filter(graph=self)

    @property
    def node_categories(self):
        return NodeCategory.objects.filter(graph=self)

    @property
    def edge_categories(self):
        return EdgeCategory.objects.filter(graph=self)

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


class Category(KindDiscriminatedModel):
    """Every node and edge kind a graph allows, in one table.

    Categories were a multi-table inheritance chain (``Category`` -> ``NodeCategory`` ->
    ``EntityCategory`` and so on). They are now one concrete table whose ``kind`` column
    says which of the old classes a row is; the old class names survive as proxies, so
    ``EntityCategory.objects`` and ``isinstance`` checks against a proxy-fetched row keep
    working. Fields that only one kind uses are nullable and simply unset on the others.
    """

    objects = managers.CategoryManager()
    kind = models.CharField(
        max_length=1000,
        choices=enums.CategoryKindChoices.choices,
        help_text="Which kind of category this is, and therefore which of the kind-specific fields below are meaningful",
    )
    graph = models.ForeignKey(
        "Graph",
        on_delete=models.CASCADE,
    )
    term = models.ForeignKey(
        "evidence.Term",
        on_delete=models.PROTECT,
        related_name="categories",
        null=True,
        blank=True,
        help_text=(
            "The organization's word this category declares. **This row is what the term means "
            "*here*** — its label in Apache AGE, its `definition`, its derivation rules and its "
            "layout are all properties of this graph. The term is the part every view shares, and "
            "the part the evidence log names, so one annotator's claim can be read by a graph that "
            "did not make it. `PROTECT` because a word that has been used has to outlive the views "
            "that used it; deleting *this* row is free, and only drops the term from this graph."
        ),
    )
    image = models.ForeignKey(
        datalayer_models.MediaStore,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The store of the image if associated with the category",
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
    definition = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "What this category *means in this graph*, as a predicate over classification claims. "
            "Empty means primitive: membership is whatever was asserted, which is the default and "
            "the old behaviour. Non-empty makes it a defined category — necessary and sufficient "
            "conditions, evaluated at projection time, so 'AIS' can mean 'asserted AIS by Johannes "
            "before August' in one graph and something else in another without touching a single "
            "piece of evidence. "
            "Shape: {asserted_as: <term key or list of them>, assertion_filter: {subjects, app_ids, "
            "action_names}, as_of: timestamp}. `asserted_as` takes several words and means *any of*, "
            "so a view's 'Neuron' can be 'anything claimed Pyramidal or Interneuron' — a category "
            "derives from many words while `term` is the single one it asserts as. Naming a word "
            "this graph declares no category for is fine and is the interesting case; "
            "`evidence.selector.term_ids_for` widens membership to cover it."
        ),
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

    # --- shared by every node kind (the former NodeCategory) ---
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

    # --- shared by every edge kind (the former EdgeCategory) ---
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

    # --- kind-specific ---
    instance_kind = models.CharField(
        max_length=1000,
        help_text="What an instance of this class represents (e.g. a LOT, an object, etc.). Entity and reagent categories only",
        null=True,
        blank=True,
    )
    reverse_description = models.CharField(
        max_length=1000,
        help_text="The description of category read in reverse. Relation and structure-relation categories only",
        null=True,
    )
    source_entity_roles = models.JSONField(
        default=list,
        null=True,
        help_text="The categories or expressions that an event of this class can source from (source edges). Event categories only",
    )
    target_entity_roles = models.JSONField(
        default=list,
        null=True,
        help_text="The categories or expressions that an of this class can target to (target edges). Event categories only",
    )
    source_reagent_roles = models.JSONField(
        default=list,
        null=True,
        help_text="The reagent categories an event of this class can source from. Protocol event categories only",
    )
    target_reagent_roles = models.JSONField(
        default=list,
        null=True,
        help_text="The reagent categories an event of this class can target. Protocol event categories only",
    )
    variable_definitions = models.JSONField(
        default=list,
        null=True,
        help_text="The variables of a instance this protocol event will needs (properties on the node). Protocol event categories only",
    )
    plate_children = models.JSONField(null=True, blank=True, help_text="Event categories only")

    class Meta:
        default_related_name = "categories"
        unique_together = ("graph", "age_name"), ("graph", "key")

    def save(self, *args, **kwargs):
        """Stamp the kind, then make sure this category declares a word.

        Minting the term here rather than at each call site makes it an invariant
        of the row instead of a convention: a category always declares something,
        because a category that declared nothing could never be claimed against
        and would be a silent hole in every projection built from it.

        Idempotent — `ensure_term` is a `get_or_create` on
        `(organization, kind, key)`, so two graphs declaring the same word reach
        the same term, which is exactly what lets them read each other's claims.
        """
        super().save(*args, **kwargs)

        if self.term_id is None and self.key and self.graph_id:
            from evidence import writer as evidence_writer

            self.term = evidence_writer.ensure_term(self.graph.organization, self.kind, self.key)
            super().save(update_fields=["term"])

    def as_kind(self) -> "Category":
        """Return this row re-cast to the proxy class for its `kind`.

        A foreign key to `Category` hands back a base instance, which carries every field
        but none of the kind-specific methods -- `get_age_vertex_name`, `matches_source`
        and friends live on the proxies. This is the explicit replacement for what
        django-polymorphic used to do implicitly on every read.
        """
        proxy = CATEGORY_PROXIES.get(self.kind)
        if proxy is None or isinstance(self, proxy):
            return self

        recast = proxy()
        # Copy, don't alias: sharing one `__dict__` would make a write through either
        # object silently mutate the other. `_state` rides along in the dict.
        recast.__dict__ = self.__dict__.copy()
        return recast

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

    def relevant_queries(self):
        return GraphQuery.objects.filter(graph=self.graph, relevant_for=self.pk)


class CategoryAssertedTerm(models.Model):
    """The joinable half of :attr:`Category.definition` — which words a category derives from.

    A graph sees a word two ways: it **declares** one (:attr:`Category.term`, an
    ordinary foreign key) or it **derives** from one, by naming it in
    ``definition.asserted_as``. The first is already a join. The second is a
    string inside JSON, and nothing can join against it — so
    `selector._graph_ids_by_term`, which every instance write goes through, read
    every category in the organization, pulled every ``definition`` blob out of
    the database and looped in Python. That is a full scan of the ontology per
    write, and a second one per page of subjects on the read side.

    This is that half, normalized. Only that half: putting the declared terms in
    here as well would duplicate a foreign key that already works and create a
    second answer that can drift from it.

    **The word is stored as a key, not as a `Term` foreign key**, and both reasons
    matter. A definition may name a word the organization has never minted — terms
    appear lazily, when somebody first claims one — so an FK would have no row to
    point at and the graph would stop deriving from a word until the first claim
    arrived. And `asserted_as` names a word without naming its *kind*, while
    `Term`'s identity is ``(organization, kind, key)``; resolving to an id would
    have to pick a kind, narrowing a rule that deliberately does not.

    Lives in `core` because it names a graph. `evidence/models.py` may not: no
    evidence row names a projection, which is what lets a claim outlive every view
    built from it.

    Maintained by a signal in `graph_engine.versioning.connect`, alongside the
    schema-version handler — but **not gated on `versioning.is_suspended()`**.
    That gate exists so `materialize()` emits one schema version instead of
    dozens; sharing it here would leave a freshly materialized graph deriving from
    nothing at all. `manage.py rebuild_asserted_terms` is the out-of-band rebuild,
    with a `--check` that reports disagreement without writing.
    """

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="category_asserted_terms",
        help_text="Denormalized from the graph, so the organization-wide map is one indexed scan rather than a join.",
    )
    graph = models.ForeignKey(
        Graph,
        on_delete=models.CASCADE,
        related_name="asserted_terms",
        help_text="Denormalized from the category: the read is 'which graphs derive from this word', and without it the seek becomes a join.",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="asserted_terms",
        help_text="The category whose definition names this word. Rows are rewritten wholesale when it changes, because a definition can stop naming a word as easily as start.",
    )
    key = models.CharField(
        max_length=1000,
        help_text="The word, exactly as `definition.asserted_as` spells it.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["category", "key"], name="unique_asserted_term_per_category"),
        ]
        indexes = [
            # The panel's read: which graphs derive from these words.
            models.Index(fields=["organization", "key"]),
            # The whole-organization map `_graph_ids_by_term` builds.
            models.Index(fields=["organization", "graph"]),
        ]

    def __str__(self) -> str:
        return f"{self.graph_id} derives from {self.key}"


class NodeCategory(Category):
    objects = managers.NodeCategoryManager()
    """A Node class is a class that describes a node in the graph which represent
    a bioentity (e.g. a cell, a tissue, etc.). Node classes are the most basic building
    block of the graph and represent physical objects that can be measured
    by structures, related to other entities by relations and subjected to specific
    protocol steps.

    """

    KINDS = enums.NODE_CATEGORY_KINDS

    class Meta:
        proxy = True

    def get_age_vertex_name(self):
        raise NotImplementedError("Not implemented needs to be implemented")

    def get_age_type_name(self):
        raise NotImplementedError("Not implemented needs to be implemented")

    @classmethod
    def key_to_age_name(cls, key: str) -> str:
        """Convert an entity key to a valid AGE name by replacing invalid characters."""
        return "".join(e for e in key if e.isalnum()).lower()


class EdgeCategory(Category):
    objects = managers.EdgeCategoryManager()
    """An Edge class is a class that describes an edge in the graph which represents a relationship between two nodes."""

    KINDS = enums.EDGE_CATEGORY_KINDS

    class Meta:
        proxy = True

    def get_age_edge_name(self) -> str:
        """Should return the name of the edge in the age graph"""
        raise NotImplementedError("Not implemented needs to be implemented")

    def get_age_type_name(self) -> str:
        """Should return the type name of the edge in the age graph"""
        raise NotImplementedError("Not implemented needs to be implemented")

    @classmethod
    def key_to_age_name(cls, key: str) -> str:
        """Convert an entity key to a valid AGE name by replacing invalid characters."""
        return "".join(e for e in key if e.isalnum()).upper()


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

    KIND = enums.CategoryKindChoices.NATURAL_EVENT
    KINDS = (enums.CategoryKindChoices.NATURAL_EVENT,)

    def get_inrole_vertex_name(self, role):
        return role

    def get_outrole_vertex_name(self, role):
        return role

    def get_age_vertex_name(self) -> str:
        return self.age_name

    def get_age_type_name(self) -> str:
        return "NATURAL_EVENT"

    #: The edge labels a participation projects to. Constant per event kind, with
    #: the role carried as a property on the edge rather than folded into the
    #: label: `MATCH (e)-[:WENT_THROUGH]->(ev)` has to be able to find every input
    #: without the caller first enumerating the schema's role names.
    #:
    #: These were methods taking a `role` argument and returning a constant, so
    #: the role never reached the graph at all and every event in a graph shared
    #: two labels with nothing to tell participations apart.
    AGE_INPUT_EDGE = "WENT_THROUGH"
    AGE_OUTPUT_EDGE = "CAME_OUT_OF"

    @property
    def collected_in_role_vertex_name(self):
        return [self.AGE_INPUT_EDGE]

    @property
    def collected_out_role_vertex_name(self):
        return [self.AGE_OUTPUT_EDGE]

    class Meta:
        proxy = True


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

    KIND = enums.CategoryKindChoices.PROTOCOL_EVENT
    KINDS = (enums.CategoryKindChoices.PROTOCOL_EVENT,)

    def get_inrole_vertex_name(self, role):
        return role

    def get_outrole_vertex_name(self, role):
        return role

    def get_age_vertex_name(self):
        return self.age_name

    def get_age_type_name(self) -> str:
        return "PROTOCOL_EVENT"

    #: A protocol event acts *on* its inputs rather than being something they went
    #: through, so it takes the labels this class's own examples already use.
    #: These did not exist at all, which is why `create_protocol_event` raised
    #: `AttributeError` on any event with an input role — after the vertex, the
    #: node row, the assertion and the state merges had already committed.
    AGE_INPUT_EDGE = "SUBJECTED_IN"
    AGE_OUTPUT_EDGE = "PRODUCED"

    @property
    def collected_in_role_vertex_name(self):
        return [self.AGE_INPUT_EDGE]

    @property
    def collected_out_role_vertex_name(self):
        return [self.AGE_OUTPUT_EDGE]

    class Meta:
        proxy = True


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

    KIND = enums.CategoryKindChoices.ENTITY
    KINDS = (enums.CategoryKindChoices.ENTITY,)

    def get_age_vertex_name(self):
        return self.age_name

    def get_age_type_name(self) -> str:
        return "ENTITY"

    class Meta:
        proxy = True


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

    KIND = enums.CategoryKindChoices.REAGENT
    KINDS = (enums.CategoryKindChoices.REAGENT,)

    def get_age_vertex_name(self):
        return self.age_name

    def get_age_type_name(self) -> str:
        return "REAGENT"

    class Meta:
        proxy = True


class MeasurementCategory(EdgeCategory):
    objects = managers.MeasurementCategoryManager()
    """A Measurement class is a class that describes an edge with a value"""

    KIND = enums.CategoryKindChoices.MEASUREMENT
    KINDS = (enums.CategoryKindChoices.MEASUREMENT,)

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

    def matches_source(self, entity: "StructureKind") -> bool:
        """Check if an entity matches the source definition of this edge category."""
        return self.source_definition_model.matches(entity)

    def matches_target(self, entity: "EntityCategory") -> bool:
        """Check if an entity matches the target definition of this edge category."""
        return self.target_definition_model.matches(entity)

    def get_matching_source_structures(self) -> QuerySet["StructureKind"]:
        """Structure kinds this edge category's source definition selects."""
        return _matching_structure_kinds(self.graph.organization, self.source_definition_model)

    def get_matching_target_entities(self) -> QuerySet["EntityCategory"]:
        """Get all entities in the graph that match the target definition of this edge category."""
        kwargs = {}
        if self.target_definition_model.keys:
            kwargs["key__in"] = self.target_definition_model.keys
        if self.target_definition_model.ontology_terms:
            kwargs["ontology_references__name__in"] = self.target_definition_model.ontology_terms

        return self.graph.entity_categories.filter(**kwargs).distinct()

    class Meta:
        proxy = True


class RelationCategory(EdgeCategory):
    """A Relation class is a class that describes a relation between two entities without a value"""

    objects: managers.RelationCategoryManager = managers.RelationCategoryManager()

    KIND = enums.CategoryKindChoices.RELATION
    KINDS = (enums.CategoryKindChoices.RELATION,)

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
        if self.source_definition_model.ontology_terms:
            kwargs["ontology_references__name__in"] = self.source_definition_model.ontology_terms

        return self.graph.entity_categories.filter(**kwargs).distinct()

    def get_matching_target_entities(self) -> QuerySet["EntityCategory"]:
        """Get all entities in the graph that match the target definition of this edge category."""
        kwargs = {}
        if self.target_definition_model.keys:
            kwargs["key__in"] = self.target_definition_model.keys
        if self.target_definition_model.ontology_terms:
            kwargs["ontology_references__name__in"] = self.target_definition_model.ontology_terms

        return self.graph.entity_categories.filter(**kwargs).distinct()

    def get_age_edge_name(self):
        return self.age_name

    def get_age_type_name(self) -> str:
        return "RELATION"

    # `source_matches` lived here and was called by nothing. It read
    # `source_definition["tags"]` directly rather than through
    # `source_definition_model`, so it was also the only place that survived the
    # descriptor rewrite by ignoring it. `matches_source`, inherited from
    # `EdgeCategory`, is the one the codebase actually uses.

    class Meta:
        proxy = True


class StructureRelationCategory(EdgeCategory):
    """A Relation class is a class that describes a relation between two entities without a value"""

    KIND = enums.CategoryKindChoices.STRUCTURE_RELATION
    KINDS = (enums.CategoryKindChoices.STRUCTURE_RELATION,)

    @property
    def source_definition_model(self) -> StructureDescriptorInput:
        return StructureDescriptorInput(**self.source_definition)

    @property
    def target_definition_model(self) -> StructureDescriptorInput:
        return StructureDescriptorInput(**self.target_definition)

    def matches_source(self, entity: "StructureKind") -> bool:
        """Check if a structure matches the source definition of this edge category."""
        return self.source_definition_model.matches(entity)

    def matches_target(self, entity: "StructureKind") -> bool:
        """Check if a structure matches the target definition of this edge category."""
        return self.target_definition_model.matches(entity)

    def get_matching_source_structures(self) -> QuerySet["StructureKind"]:
        """Structure kinds this edge category's source definition selects."""
        return _matching_structure_kinds(self.graph.organization, self.source_definition_model)

    def get_matching_target_structures(self) -> QuerySet["StructureKind"]:
        """Structure kinds this edge category's target definition selects."""
        return _matching_structure_kinds(self.graph.organization, self.target_definition_model)

    def get_age_edge_name(self):
        return self.age_name

    def get_age_type_name(self) -> str:
        return "STRUCTURE_RELATION"

    class Meta:
        proxy = True


#: Which proxy class owns each `kind`, for `Category.as_kind()`.
CATEGORY_PROXIES: dict[str, type[Category]] = {
    enums.CategoryKindChoices.ENTITY: EntityCategory,
    enums.CategoryKindChoices.REAGENT: ReagentCategory,
    enums.CategoryKindChoices.NATURAL_EVENT: NaturalEventCategory,
    enums.CategoryKindChoices.PROTOCOL_EVENT: ProtocolEventCategory,
    enums.CategoryKindChoices.MEASUREMENT: MeasurementCategory,
    enums.CategoryKindChoices.RELATION: RelationCategory,
    enums.CategoryKindChoices.STRUCTURE_RELATION: StructureRelationCategory,
}


#: Shared by the three saved-query tables. All nine `archive_*_query` mutations
#: wrote `item.archived = True; item.save()` against a field that existed on no
#: model, so `save()` persisted nothing and the caller was told it had worked.
#: No GraphQL type exposed the value either, which is why a client could write it
#: and never see that it had not taken.
#:
#: Ordinary mutable Django state, deliberately. A saved query is container and UI,
#: not a claim about the world — `docs/LOG.md` lists exactly this class of thing
#: under "correctly mutable" — so archiving one carries no assertion.
ARCHIVED_HELP = "Whether this saved query has been put away. Archiving is the reversible alternative to deleting it."


class GraphQuery(KindDiscriminatedModel):
    """A saved query over a graph, in one table.

    `kind` was already the discriminator here -- it just used to sit alongside a
    multi-table inheritance chain that said the same thing a second time. The former
    subclasses are proxies, and the fields only one shape uses are nullable.
    """

    objects = managers.KindedManager()
    graph = models.ForeignKey(
        Graph,
        on_delete=models.CASCADE,
        related_name="queries",
        help_text="The graph this query belongs to",
    )
    archived = models.BooleanField(default=False, help_text=ARCHIVED_HELP)
    key = models.CharField(
        max_length=1000,
        help_text="The key of the query, used for referencing the query in the frontend and for pinning it",
    )
    # The **plan** is the contract — `graph_engine.query_ir.TableQueryPlan` as
    # JSON: matches, wheres, returns, columns. It is what a client writes, what
    # comes back, and what each projection kind compiles (`TableProjector` →
    # SQL). `query` is a fossil: raw Cypher from rows saved before plans
    # existed. A legacy row has `plan = NULL` and cannot render at all — no
    # projection kind executes Cypher — so `manage.py list_legacy_queries`
    # names them to be rebuilt through the builder.
    plan = models.JSONField(null=True, blank=True, help_text="The saved query as a `TableQueryPlan` (matches, wheres, returns, columns). Null only on a legacy row that stores raw Cypher.")
    query = models.CharField(max_length=7000, null=True, blank=True, help_text="Legacy: raw Cypher saved before plans existed. Read-only; never accepted any more.")
    label = models.CharField(max_length=1000, help_text="The name of the materialized graph")
    description = models.CharField(
        max_length=1000,
        help_text="The description of the materialized graph",
        null=True,
    )
    kind = models.CharField(
        max_length=1000,
        choices=enums.GraphQueryKindChoices.choices,
        help_text="The kind of result this query renders. Only TABLE exists.",
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
    columns = models.JSONField(
        help_text="How the returned aliases are presented. Mirrors `plan.columns` for rows that have a plan",
        default=list,
        null=True,
    )

    @property
    def is_legacy(self) -> bool:
        """A row saved as raw Cypher before the plan became the contract."""
        return not self.plan

    class Meta:
        """Some Meta options for the GraphQuery model"""

        default_related_name = "graph_queries"
        unique_together = ("graph", "key")


class GraphTableQuery(GraphQuery):
    """A query that is used to materialize a table"""

    KIND = enums.GraphQueryKindChoices.TABLE
    KINDS = (enums.GraphQueryKindChoices.TABLE,)
    objects = managers.KindedManager()

    class Meta:
        proxy = True


class ScatterPlot(models.Model):
    # The one saved query a plot is drawn from. `node_query` / `path_query` used
    # to sit beside it, pointing at `NodeTableQuery` / `NodePathQuery` — kinds
    # nothing could render — and `_scoped.graph_of` walked all three to find a
    # tenant. A plot is over a graph table query.
    graph_query = models.ForeignKey(
        GraphTableQuery,
        on_delete=models.CASCADE,
        related_name="scatter_plots",
        help_text="The graph table query this scatter plot is drawn from",
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


# Needs to be here
