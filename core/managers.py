from __future__ import annotations

from typing import Generic, Iterable, Optional, TYPE_CHECKING, TypeVar

from asgiref.sync import sync_to_async, async_to_sync
from django.db import models

from datalayer import models as datalayer_models
from graph_engine import input_models

if TYPE_CHECKING:
    from core import models as core_models


T = TypeVar("T", bound="core_models.Category")


class KindedManager[Row: models.Model](models.Manager):
    """Manager for a proxy model that owns a subset of its table's ``kind`` values.

    Multi-table inheritance used to do this work: each subclass had its own table, so
    querying the subclass could only ever return its own rows. Now every former subclass
    is a proxy over one table, and the ``kind`` column is the only thing separating them --
    so the manager has to narrow reads and stamp writes. A model with neither ``KIND`` nor
    ``KINDS`` (the concrete base) is left alone and sees every row.
    """

    def get_queryset(self) -> models.QuerySet[Row]:
        queryset = super().get_queryset()
        kinds = getattr(self.model, "KINDS", None)
        return queryset.filter(kind__in=kinds) if kinds else queryset

    def _stamped(self, values: dict[str, object]) -> dict[str, object]:
        """Add this proxy's ``kind`` unless the caller set one explicitly.

        Belt and braces, not the primary mechanism: `acreate` goes through the
        *queryset*, so it never reaches these manager overrides. What actually
        guarantees the column on every path is `KindDiscriminatedModel.save()`. The
        load-bearing part of this manager is `get_queryset` -- it is what scopes reads
        and, with them, the lookup half of `update_or_create`.
        """
        kind = getattr(self.model, "KIND", None)
        if kind is not None:
            values.setdefault("kind", kind)
        return values

    def create(self, **kwargs: object) -> Row:
        return super().create(**self._stamped(kwargs))

    def get_or_create(self, defaults: Optional[dict[str, object]] = None, **kwargs: object) -> tuple[Row, bool]:
        return super().get_or_create(defaults=self._stamped(dict(defaults or {})), **kwargs)

    def update_or_create(self, defaults: Optional[dict[str, object]] = None, **kwargs: object) -> tuple[Row, bool]:
        return super().update_or_create(defaults=self._stamped(dict(defaults or {})), **kwargs)


class CategoryManager(KindedManager["core_models.Category"], Generic[T]):
    """Base manager for all category types, providing common functionality for creating/updating categories from definitions."""

    def key_to_age_name(self, key: str) -> str:
        """Convert a category key to an AGE-compatible name by converting to lowercase and replacing spaces with underscores."""
        return key.lower().replace(" ", "_")

    def _term_for(self, graph: "core_models.Graph", key: str):
        """The organization's word this category declares, minted if it is new.

        The join the evidence log names. Every path that creates a category comes
        through here, so two graphs declaring "AIS" reach the *same* term — which
        is what lets a claim made in one view be read by the other.

        `KIND` is the proxy's own discriminator, so an entity "AIS" and a relation
        "AIS" resolve to different terms. They are different words that happen to
        be spelled alike.
        """
        from evidence import writer as evidence_writer

        return evidence_writer.ensure_term(graph.organization, self.model.KIND, key)

    def _resolve_store_id(self, image: datalayer_models.MediaStore | str | None) -> str | None:
        if image is None:
            return None
        if hasattr(image, "id"):
            return image.id
        return image

    def _apply_pin(self, category: "core_models.Category", user, pin: Optional[bool]) -> None:
        """Add or remove this user's pin. `None` means the caller said nothing about it.

        Pinning is per-user and lives on a many-to-many, so it cannot ride in
        `defaults` with the rest of a category's fields — which is why it was a
        five-line block hand-copied into nine resolvers. Three states, and the
        third is the one the copies kept getting right by accident: absent is not
        the same as `False`.
        """
        if pin is None:
            return
        if pin:
            category.pinned_by.add(user)
        else:
            category.pinned_by.remove(user)

    async def _apply_ontology_references(
        self,
        category: "core_models.Category",
        references: Optional[Iterable[input_models.OntologyReferenceInput]],
    ) -> None:
        """Record the ontology terms this category was declared against.

        The reference set is replaced **whole**: a category declaration is a
        statement of what the category is, so a declaration that omits a reference
        is saying it no longer carries one. The ontology itself is upserted by
        prefix rather than refused when unknown, because nothing else in the API
        can create a `GraphOntology` — refusing an unknown prefix would make the
        field unusable.

        Both of those are *choices*, not preserved behaviour. Four of the six
        category mutations carried their own copy of this loop written against
        `GraphOntology.prefix` and `OntologyReference.graph_id` / `category_key`,
        none of which are fields — so that copy raised `FieldError` on every
        non-empty reference list and had never run. See
        `tests/view/test_a_category_names_the_ontologies_it_references.py`.
        """
        if references is None:
            return
        from core import models as core_models

        await sync_to_async(core_models.OntologyReference.objects.filter(category=category).delete)()
        for reference in references:
            ontology, _ = await sync_to_async(core_models.GraphOntology.objects.get_or_create)(
                graph=category.graph,
                name=reference.prefix,
                defaults={"url": reference.uri, "description": None},
            )
            await sync_to_async(core_models.OntologyReference.objects.create)(
                category=category,
                name=reference.uri,
                ontology=ontology,
            )


class NodeCategoryManager(CategoryManager[T], Generic[T]):
    """Manager for node categories, providing additional functionality specific to node categories (e.g. handling property definitions)."""

    pass

    def key_to_age_name(self, key: str) -> str:
        return key

    async def acreate_from_node_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.NodeDefinitionInput,
        other_defaults: Optional[dict[str, object]] = None,
    ) -> T:
        resolved_age_name = self.key_to_age_name(definition.key)
        label = definition.label or definition.key

        defaults: dict[str, object] = {
            "label": label,
            "description": definition.description,
            "age_name": resolved_age_name,
            # The organization's word this category declares. Minted here rather
            # than at each call site so that every path which creates a category —
            # `materialize`, and the schema mutations — reaches the same term for
            # the same key, which is what lets two graphs read one claim.
            "term": await sync_to_async(self._term_for)(graph, definition.key),
            **(other_defaults or {}),
        }

        store_id = self._resolve_store_id(definition.image)
        if store_id is not None:
            # `image_id`, not `store_id`. `Category` has an `image` FK and no
            # `store` field at all, so `defaults["store_id"]` named a column that
            # does not exist — and `update_or_create` splits on that: the create
            # branch passes defaults to `Model(**kwargs)` and raised `TypeError`,
            # while the update branch `setattr`s it and Django dropped it on
            # `save()`. So declaring a category with an image failed the first
            # time and silently discarded the image every time after. The
            # `re_materialize` path 70 lines down already had this right.
            defaults["image_id"] = store_id
        if definition.color is not None:
            defaults["color"] = definition.color

        category, _ = await sync_to_async(self.update_or_create)(
            graph=graph,
            key=definition.key,
            defaults=defaults,
        )

        await self._apply_ontology_references(category, definition.ontology_references)

        return category


class EntityCategoryManager(NodeCategoryManager["core_models.EntityCategory"]):
    async def acreate_from_entity_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.EntityDefinitionInput,
    ) -> "core_models.EntityCategory":
        property_defs = [p.model_dump(mode="json") for p in definition.property_definitions] if definition.property_definitions else []

        category = await self.acreate_from_node_definition(
            graph=graph,
            definition=definition,
            other_defaults={
                "instance_kind": definition.instance_kind,
                "property_definitions": property_defs,
                # The category's *meaning* (RFC 0007). Empty means primitive.
                "definition": definition.definition.to_stored() if definition.definition else {},
            },
        )

        return category

    def create_from_entity_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.EntityDefinitionInput,
    ) -> "core_models.EntityCategory":
        return async_to_sync(self.acreate_from_entity_definition)(graph, definition)

    def update_from_entity_definition(
        self,
        category: "core_models.EntityCategory",
        definition: input_models.EntityDefinitionInput,
    ) -> "core_models.EntityCategory":
        return async_to_sync(self.aupdate_from_entity_definition)(category, definition)

    async def aupdate_from_entity_definition(
        self,
        category: "core_models.EntityCategory",
        definition: input_models.EntityDefinitionInput,
    ) -> "core_models.EntityCategory":
        property_defs = [p.model_dump(mode="json") for p in definition.property_definitions] if definition.property_definitions else []

        category.label = definition.label or category.label
        category.description = definition.description or category.description
        category.instance_kind = definition.instance_kind or category.instance_kind
        category.property_definitions = property_defs or category.property_definitions

        # The category's meaning (RFC 0007): a new predicate replaces the old one
        # whole; `clear_definition` resets to primitive; absent means unchanged.
        # The input model refuses both at once.
        if getattr(definition, "clear_definition", False):
            category.definition = {}
        elif getattr(definition, "definition", None) is not None:
            category.definition = definition.definition.to_stored()

        store_id = self._resolve_store_id(definition.image)
        if store_id is not None:
            category.image_id = store_id
        if definition.color is not None:
            category.color = definition.color

        await category.asave()

        await self._apply_ontology_references(category, definition.ontology_references)

        return category


class EventCategoryManager(NodeCategoryManager[T], Generic[T]):
    """Shared creator for both event kinds.

    Natural and protocol events differ in what they *are* — one arises in the
    system, the other is applied from outside — and in nothing about how a
    category for one is written. They had a manager each, both `pass`, so
    `create_natural_event_category` and `create_protocol_event_category` each
    hand-rolled an `update_or_create` instead; the two modules then drifted, and
    the natural one lost `definition` entirely. `materialize` had a third copy.
    This is the one place an event category is written.
    """

    async def acreate_from_event_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.EventDefinitionInput,
    ) -> T:
        return await self.acreate_from_node_definition(
            graph=graph,
            definition=definition,
            other_defaults={
                "property_definitions": [prop.model_dump(mode="json") for prop in definition.properties],
                # The category's complete rule (RFC 0009). Empty means primitive.
                # Absent from `create_natural_event_category`'s hand-written
                # defaults, so a natural event category declared with a rule
                # stored none and folded as primitive ever after.
                "definition": definition.definition.to_stored() if definition.definition else {},
                # Who may take part, and under which role name. An **empty list
                # admits everything** (`namespace._role_endpoints`), so dropping
                # these did not lose a label — it silently widened every event
                # category created through the API to every entity-like category
                # in the view, while the same category created by `materialize`
                # carried the declared roles.
                "source_entity_roles": [role.model_dump(mode="json") for role in definition.inputs],
                "target_entity_roles": [role.model_dump(mode="json") for role in definition.outputs],
            },
        )

    def create_from_event_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.EventDefinitionInput,
    ) -> T:
        return async_to_sync(self.acreate_from_event_definition)(graph, definition)


class NaturalEventCategoryManager(EventCategoryManager["core_models.NaturalEventCategory"]):
    pass


class ProtocolEventCategoryManager(EventCategoryManager["core_models.ProtocolEventCategory"]):
    pass


class EdgeCategoryManager(CategoryManager[T], Generic[T]):
    def key_to_age_name(self, key: str) -> str:
        return key.upper()

    # `_term_for` is inherited from `CategoryManager`.

    async def acreate_from_edge_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.EdgeDefinitionInput,
        other_defaults: Optional[dict[str, object]] = None,
    ) -> T:
        resolved_age_name = self.key_to_age_name(definition.key)
        label = definition.label or definition.key
        property_definitions = getattr(definition, "properties", None)

        defaults: dict[str, object] = {
            "label": label or definition.key,
            "description": definition.description,
            "age_name": resolved_age_name,
            # The category's complete rule (RFC 0012). Empty means primitive.
            "definition": definition.definition.to_stored() if getattr(definition, "definition", None) else {},
            # See `NodeCategoryManager._term_for` — the same reasoning for edges.
            "term": await sync_to_async(self._term_for)(graph, definition.key),
            **(other_defaults or {}),
        }

        # Endpoints are written only when the definition carries them, and that
        # conditionality is load-bearing rather than defensive.
        #
        # `CreateRelationCategoryInput` extends the *entity* shape, so it has no
        # `source`/`target` at all — reading them unconditionally is why this
        # method could not be called from `create_relation_category`. And this is
        # an `update_or_create` on `(graph, key)`: writing the keys unconditionally
        # would overwrite a `materialize`-created relation category's endpoints
        # with `{}` on the next `createRelationCategory` naming the same word —
        # and those two columns are what `namespace.py` expands into the graph's
        # edge element tables. Held by
        # `tests/view/test_editing_a_relation_category_keeps_its_endpoints.py`.
        source = getattr(definition, "source", None)
        if source is not None:
            defaults["source_definition"] = source.model_dump(mode="json")
        target = getattr(definition, "target", None)
        if target is not None:
            defaults["target_definition"] = target.model_dump(mode="json")

        if property_definitions is not None:
            defaults["property_definitions"] = [prop.model_dump(mode="json") for prop in property_definitions]

        store_id = self._resolve_store_id(definition.image)
        if store_id is not None:
            # `image_id`, not `store_id`. `Category` has an `image` FK and no
            # `store` field at all, so `defaults["store_id"]` named a column that
            # does not exist — and `update_or_create` splits on that: the create
            # branch passes defaults to `Model(**kwargs)` and raised `TypeError`,
            # while the update branch `setattr`s it and Django dropped it on
            # `save()`. So declaring a category with an image failed the first
            # time and silently discarded the image every time after. The
            # `re_materialize` path 70 lines down already had this right.
            defaults["image_id"] = store_id
        if definition.color is not None:
            defaults["color"] = definition.color

        category, _ = await sync_to_async(self.update_or_create)(
            graph=graph,
            key=definition.key,
            defaults=defaults,
        )

        await self._apply_ontology_references(category, definition.ontology_references)

        return category

    def create_from_edge_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.EdgeDefinitionInput,
        other_defaults: Optional[dict[str, object]] = None,
    ) -> T:
        return async_to_sync(self.acreate_from_edge_definition)(graph, definition, other_defaults)


class StructureRelationCategoryManager(EdgeCategoryManager["core_models.StructureRelationCategory"]):
    async def acreate_from_structure_relation_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.StructureRelationDefinitionInput,
    ) -> "core_models.StructureRelationCategory":
        return await super().acreate_from_edge_definition(graph=graph, definition=definition)

    def create_from_structure_relation_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.StructureRelationDefinitionInput,
    ) -> "core_models.StructureRelationCategory":
        return async_to_sync(self.acreate_from_structure_relation_definition)(graph, definition)


class RelationCategoryManager(EdgeCategoryManager["core_models.RelationCategory"]):
    async def acreate_from_relation_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.RelationDefinitionInput,
    ) -> "core_models.RelationCategory":
        category = await super().acreate_from_edge_definition(
            graph=graph,
            definition=definition,
        )

        return category

    def create_from_relation_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.RelationDefinitionInput,
    ) -> "core_models.RelationCategory":
        return async_to_sync(self.acreate_from_relation_definition)(graph, definition)


class MeasurementCategoryManager(EdgeCategoryManager["core_models.MeasurementCategory"]):
    async def acreate_from_measurement_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.MeasurementDefinitionInput,
    ) -> "core_models.MeasurementCategory":
        return await super().acreate_from_edge_definition(
            graph=graph,
            definition=definition,
        )

    def create_from_measurement_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.MeasurementDefinitionInput,
    ) -> "core_models.MeasurementCategory":
        return async_to_sync(self.acreate_from_measurement_definition)(graph, definition)
