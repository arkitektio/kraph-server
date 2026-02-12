from __future__ import annotations

from typing import Generic, Iterable, Optional, TYPE_CHECKING, TypeVar

from asgiref.sync import sync_to_async
from polymorphic.managers import PolymorphicManager

from datalayer import models as datalayer_models
from core import enums
from graph_engine import input_models

if TYPE_CHECKING:
    from core import models as core_models


T = TypeVar("T", bound="core_models.Category")


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
        category = await self.acreate_from_node_definition(
            graph=graph,
            definition=definition,
        )

        if definition.instance_kind is not None:
            category.instance_kind = definition.instance_kind
            await sync_to_async(category.save)(update_fields=["instance_kind"])

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


class NaturalEventCategoryManager(NodeCategoryManager["core_models.NaturalEventCategory"]):
    pass


class ProtocolEventCategoryManager(NodeCategoryManager["core_models.ProtocolEventCategory"]):
    pass


class ReagentCategoryManager(NodeCategoryManager["core_models.ReagentCategory"]):
    pass


class EdgeCategoryManager(CategoryManager[T], Generic[T]):
    async def acreate_from_edge_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.EdgeDefinitionInput,
        other_defaults: Optional[dict[str, object]] = None,
    ) -> T:
        resolved_age_name = self.key_to_age_name(definition.key)
        label = definition or definition.key

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


class MeasurementCategoryManager(EdgeCategoryManager["core_models.MeasurementCategory"]):
    pass


class MetricCategoryManager(NodeCategoryManager["core_models.MetricCategory"]):
    """Metric categories are a special type of node category that represent metrics in the graph and have additional fields to link them to specific structures and define the kind of metric they represent (e.g. float, int, etc.)."""

    async def acreate_from_metric_definition(
        self,
        graph: "core_models.Graph",
        definition: input_models.MetricDefinitionInput,
    ) -> "core_models.MetricCategory":
        from core import models as core_models

        structure = await core_models.StructureCategory.objects.aget(graph=graph, identifier=definition.structure)

        category = await super().acreate_from_node_definition(
            graph=graph,
            definition=definition,
            other_defaults={
                "structure_category": structure,
            },
        )

        return category
