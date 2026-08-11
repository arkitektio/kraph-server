from __future__ import annotations

from typing import Any, Generic, Iterable, Optional, TYPE_CHECKING, TypeVar

from asgiref.sync import sync_to_async, async_to_sync
from duckdb import identifier
from polymorphic.managers import PolymorphicManager
from django.db import models

from datalayer import models as datalayer_models
from core import enums
from graph_engine import input_models, scalars

if TYPE_CHECKING:
    from core import models as core_models


T = TypeVar("T", bound="core_models.Category")


class GraphManager(models.Manager):
    """A small manager class for Graph objects, providing common functionality for retrieving graphs based on different identifiers (e.g. graph ID, graph name, etc.) and ensuring that the correct graph is returned based on the provided identifier format."""

    def get_graph_from_graph_name(self, name: scalars.GraphName) -> "core_models.Graph":
        from core import models as core_models

        graph = core_models.Graph.objects.filter(age_name=name).first()
        if graph is None:
            raise ValueError(f"Graph not found for identifier {name}")
        return graph

    async def aget_graph_from_graph_name(self, name: scalars.GraphName) -> "core_models.Graph":
        from core import models as core_models

        graph = await core_models.Graph.objects.filter(age_name=name).afirst()
        if graph is None:
            raise ValueError(f"Graph not found for identifier {name}")
        return graph


class CategoryManager(PolymorphicManager, Generic[T]):
    """Base manager for all category types, providing common functionality for creating/updating categories from definitions."""

    def key_to_age_name(self, key: str) -> str:
        """Convert a category key to an AGE-compatible name by converting to lowercase and replacing spaces with underscores."""
        return key.lower().replace(" ", "_")

    def _resolve_store_id(self, image: datalayer_models.MediaStore | str | None) -> str | None:
        if image is None:
            return None
        if hasattr(image, "id"):
            return image.id
        return image

    async def _apply_tags(self, category: "core_models.Category", tags: Optional[Iterable[str]]) -> None:
        if tags is None:
            return
        from core import models as core_models

        await sync_to_async(category.tags.clear)()
        for tag in tags:
            tag_obj, _ = await sync_to_async(core_models.CategoryTag.objects.get_or_create)(value=tag, graph=category.graph)
            await sync_to_async(category.tags.add)(tag_obj)

    async def _apply_ontology_references(
        self,
        category: "core_models.Category",
        references: Optional[Iterable[input_models.OntologyReferenceInput]],
    ) -> None:
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
            **(other_defaults or {}),
        }

        store_id = self._resolve_store_id(definition.image)
        if store_id is not None:
            defaults["store_id"] = store_id
        if definition.color is not None:
            defaults["color"] = definition.color

        category, _ = await sync_to_async(self.update_or_create)(
            graph=graph,
            key=definition.key,
            defaults=defaults,
        )

        await self._apply_tags(category, definition.tags)
        await self._apply_ontology_references(category, definition.ontology_references)

        return category


class EntityCategoryManager(NodeCategoryManager["core_models.EntityCategory"]):
    async def acreate_from_entity_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.EntityDefinitionInput,
    ) -> "core_models.EntityCategory":
        from graph_engine.materialize import compute_properties_hash

        property_defs = [p.model_dump(mode="json") for p in definition.property_definitions] if definition.property_definitions else []
        props_hash = compute_properties_hash(property_defs)

        category = await self.acreate_from_node_definition(
            graph=graph,
            definition=definition,
            other_defaults={
                "instance_kind": definition.instance_kind,
                "property_definitions": property_defs,
                "schema_hash": props_hash,
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
        from graph_engine.materialize import compute_properties_hash

        property_defs = [p.model_dump(mode="json") for p in definition.property_definitions] if definition.property_definitions else []
        props_hash = compute_properties_hash(property_defs)

        category.label = definition.label or category.label
        category.description = definition.description or category.description
        category.instance_kind = definition.instance_kind or category.instance_kind
        category.property_definitions = property_defs or category.property_definitions
        category.schema_hash = props_hash or category.schema_hash

        store_id = self._resolve_store_id(definition.image)
        if store_id is not None:
            category.image_id = store_id
        if definition.color is not None:
            category.color = definition.color

        await category.asave()

        await self._apply_tags(category, definition.tags)
        await self._apply_ontology_references(category, definition.ontology_references)

        return category


class StructureCategoryManager(NodeCategoryManager["core_models.StructureCategory"]):
    """Structure categories are a special type of node category that represent structures in the graph (e.g. regions of interest, etc.) and can be referenced by metric categories to link metrics to specific structures. They have an additional identifier field that is used to link them to the corresponding structure in the AGE data model."""

    async def acreate_from_structure_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.StructureDefinitionInput,
    ) -> "core_models.StructureCategory":
        category = await super().acreate_from_node_definition(
            graph=graph,
            definition=definition,
        )

        if definition.identifier is not None:
            category.identifier = definition.identifier
            await sync_to_async(category.save)(update_fields=["identifier"])

        return category

    def create_from_structure_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.StructureDefinitionInput,
    ) -> "core_models.StructureCategory":
        return async_to_sync(self.acreate_from_structure_definition)(graph, definition)


class NaturalEventCategoryManager(NodeCategoryManager["core_models.NaturalEventCategory"]):
    pass


class ProtocolEventCategoryManager(NodeCategoryManager["core_models.ProtocolEventCategory"]):
    pass


class ReagentCategoryManager(NodeCategoryManager["core_models.ReagentCategory"]):
    pass


class EdgeCategoryManager(CategoryManager[T], Generic[T]):
    def key_to_age_name(self, key: str) -> str:
        return key.upper()

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
            "source_definition": definition.source.model_dump(mode="json"),
            "target_definition": definition.target.model_dump(mode="json"),
            **(other_defaults or {}),
        }

        if property_definitions is not None:
            defaults["property_definitions"] = [prop.model_dump(mode="json") for prop in property_definitions]

        store_id = self._resolve_store_id(definition.image)
        if store_id is not None:
            defaults["store_id"] = store_id
        if definition.color is not None:
            defaults["color"] = definition.color

        category, _ = await sync_to_async(self.update_or_create)(
            graph=graph,
            key=definition.key,
            defaults=defaults,
        )

        await self._apply_tags(category, definition.tags)
        await self._apply_ontology_references(category, definition.ontology_references)

        return category

    def create_from_edge_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.EdgeDefinitionInput,
        other_defaults: Optional[dict[str, object]] = None,
    ) -> T:
        return async_to_sync(self.acreate_from_edge_definition)(graph, definition, other_defaults)


class RelationCategoryManager(EdgeCategoryManager["core_models.RelationCategory"]):
    pass

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
    pass

    async def acreate_from_measurement_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.MeasurementDefinitionInput,
    ) -> "core_models.MeasurementCategory":
        from graph_engine.materialize import re_materialize_measurement_relation_category

        category = await super().acreate_from_edge_definition(
            graph=graph,
            definition=definition,
        )

        await sync_to_async(re_materialize_measurement_relation_category)(graph, category)

        return category

    def create_from_measurement_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.MeasurementDefinitionInput,
    ) -> "core_models.MeasurementCategory":
        return async_to_sync(self.acreate_from_measurement_definition)(graph, definition)


def _metric_kind_for(value_kind: Any) -> "enums.MetricKindChoices | None":
    """The stored metric kind for a declared value kind, matched by name."""
    if value_kind is None:
        return None
    name = getattr(value_kind, "name", str(value_kind)).upper()
    # PropertyType still spells these INTEGER and POINT_3D on the input surface.
    name = {"INTEGER": "INT", "POINT_3D": "THREE_D_VECTOR"}.get(name, name)
    return getattr(enums.MetricKindChoices, name, None)


class MetricCategoryManager(NodeCategoryManager["core_models.MetricCategory"]):
    """Metric categories are a special type of node category that represent metrics in the graph and have additional fields to link them to specific structures and define the kind of metric they represent (e.g. float, int, etc.)."""

    async def acreate_from_metric_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.MetricDefinitionInput,
    ) -> "core_models.MetricCategory":
        from core import models as core_models

        # No conversion table. `MetricKindChoices` declares exactly the same
        # members as `ValueKind`, so the canonical kind maps across by name. The
        # table this replaces went through PropertyType and silently lost
        # CATEGORY and every vector kind except 3D.
        structure = await core_models.StructureCategory.objects.aget(graph=graph, identifier=definition.structure)

        category = await super().acreate_from_node_definition(
            graph=graph,
            definition=definition,
            other_defaults={
                "structure_category": structure,
                "value_kind": _metric_kind_for(definition.value_kind),
            },
        )

        return category

    def create_from_metric_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.MetricDefinitionInput,
    ) -> "core_models.MetricCategory":
        return async_to_sync(self.acreate_from_metric_definition)(graph, definition)
