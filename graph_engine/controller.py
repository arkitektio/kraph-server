import json
import time
import re
from typing import Optional, Dict, Any, List

from kante.types import Info
from graph_engine import input_models
from graph_engine.input_models import (
    GraphDefinitionInput,
)
import uuid

from graph_engine.input_models import (
    MetricInput,
    ProvenanceContext,
    RelationInput,
)
from graph_engine.engine.protocol import CypherEngine
from graph_engine.retrieved import (
    RetrievedGraphNodesRender,
    RetrievedGraphPathRender,
    RetrievedMetric,
    RetrievedNaturalEvent,
    RetrievedNode,
    RetrievedEdge,
    RetrievedEntity,
    RetrievedGraphTableRender,
    RetrievedRelation,
    RetrievedStructure,
    RetrievedAssertion,
    RetrievedInforms,
)
from graph_engine import retrieved
from authentikate.models import Membership
from core import enums, models
from graph_engine import input_models as inputs
from graph_engine import vocab, scalars
from django.db import transaction
from evidence import models as evidence_models
from evidence import writer


def extract_node_id(composite_id: str | scalars.GraphID) -> scalars.LocalID:
    """
    Extract the entity UUID from a composite ID.

    Composite IDs are in the format: {graph_id}-{entity_uuid}
    This function returns everything after the first hyphen.

    Args:
        composite_id: The composite ID (e.g., "1-abc123-def456-...")

    Returns:
        The entity UUID part (e.g., "abc123-def456-...")
    """
    if "-" in composite_id:
        parts = composite_id.split("-", 1)
        if len(parts) == 2:
            return scalars.LocalID(int(parts[1]))
    if ":" in composite_id:
        parts = composite_id.split(":", 1)
        if len(parts) == 2:
            return scalars.LocalID(int(parts[1]))
    raise ValueError(f"Invalid composite ID format: {composite_id}")


def extract_graph_id(composite_id: str | scalars.GraphID) -> scalars.GraphName:
    """
    Extract the graph ID from a composite ID.

    Composite IDs are in the format: {graph_id}-{entity_uuid}
    This function returns everything before the first hyphen.

    Args:
        composite_id: The composite ID (e.g., "1-abc123-def456-...")

    Returns:
        The graph ID part (e.g., "1")
    """
    if "-" in composite_id:
        parts = composite_id.split("-", 1)
        if len(parts) == 2:
            return scalars.GraphName(parts[0])
    if ":" in composite_id:
        parts = composite_id.split(":", 1)
        if len(parts) == 2:
            return scalars.GraphName(parts[0])
    raise ValueError(f"Invalid composite ID format: {composite_id}")


def _extract_props(raw_node: Any) -> Dict[str, Any]:
    """Extract properties from an AGE node, handling both dict and nested formats."""
    if isinstance(raw_node, dict):
        if "properties" in raw_node:
            return raw_node["properties"]
        return raw_node
    return {}


def _extract_id(raw_node: Any) -> scalars.LocalID:
    """Extract the internal graph ID from an AGE node representation."""
    if isinstance(raw_node, dict) and "id" in raw_node:
        return scalars.LocalID(raw_node["id"])
    raise ValueError("Unable to extract graph ID from node representation.")


class GraphController:
    """Controller for interacting with the graph database."""

    def __init__(self, engine: CypherEngine, subject: str | None = None, app_id: str | None = None) -> None:
        """The GraphController is initialized with a CypherEngine instance for executing queries, and optional context for provenance tracking."""
        self.engine = engine
        self.subject = subject
        self.app_id = app_id

    def create_universal_id(self) -> scalars.GlobalID:
        """Generates a unique reference ID for entities."""
        return scalars.GlobalID(str(uuid.uuid4()))

    def _get_entity_category_for_local_id(self, graph: models.Graph, local_id: scalars.LocalID) -> models.EntityCategory:
        """Resolve an entity category by inspecting the node label in AGE."""
        result = self.engine.execute(
            graph,
            """
            MATCH (e) WHERE id(e) = $eid
            RETURN labels(e) as labels
            """,
            {"eid": local_id},
        )

        if not result:
            raise ValueError(f"Entity not found with local id {local_id}")

        labels = result[0].get("labels") or []
        if not labels:
            raise ValueError(f"Entity with local id {local_id} has no labels")

        age_name = labels[0]
        category = models.EntityCategory.objects.filter(graph=graph, age_name=age_name).first()

        if not category:
            raise ValueError(f"No EntityCategory found for age_name '{age_name}' in graph {graph.pk}")

        return category

    def ensure_entity(
        self,
        entity_category: models.EntityCategory,
        universal_id: scalars.GlobalID,
        payload: inputs.EntityInput,
    ) -> RetrievedEntity:
        raise NotImplementedError("Ensure entity is not implemented yet. Use create_entity for now.")

    def _create_assertion(self, organization: Any, context: ProvenanceContext) -> evidence_models.Assertion:
        """Record who is making this change, in the relational evidence base.

        Assertions used to be AGE vertices, one per graph, which meant the same
        claim had to be re-asserted in every projection that wanted to see it.
        They are organization-scoped rows now; the graph is only how we learn
        which organization the request is acting for.
        """
        return writer.create_assertion(
            organization,
            subject=context.subject,
            app_id=context.app_id,
        )

    def _provenance_from_info(self, info: Info) -> ProvenanceContext:
        request = info.context.request

        user = getattr(request, "user", None)
        client = getattr(request, "client", None)

        if not user:
            raise ValueError("No authenticated user found in context")

        return ProvenanceContext(
            subject=str(user.id),
            app_id=str(client.id) if client else "unknown",
        )

    def _get_scopes_from_info(self, info: Info) -> list[str]:
        request = info.context.request

        extension_scopes = request._extensions.get("scopes") if hasattr(request, "_extensions") else None
        if isinstance(extension_scopes, list):
            return [str(scope) for scope in extension_scopes]
        if isinstance(extension_scopes, str):
            return [scope for scope in extension_scopes.split(" ") if scope]

        token = request._extensions.get("token") if hasattr(request, "_extensions") else None
        token_scopes = getattr(token, "scopes", None)
        if isinstance(token_scopes, list):
            return [str(scope) for scope in token_scopes]
        if isinstance(token_scopes, str):
            return [scope for scope in token_scopes.split(" ") if scope]

        return []

    def _ensure_query_access(self, graph: models.Graph, info: Info | None = None) -> None:
        if info is None:
            return

        request = info.context.request
        return True

    def _infer_metric_value_kind(self, value: Any) -> input_models.PropertyType:
        if isinstance(value, bool):
            return input_models.PropertyType.BOOLEAN
        if isinstance(value, int):
            return input_models.PropertyType.INTEGER
        if isinstance(value, float):
            return input_models.PropertyType.FLOAT
        return input_models.PropertyType.STRING

    def ensure_structure_category_or_raise(self, graph: models.Graph, identifier: str, info: Info) -> models.StructureCategory:
        """Ensures that a StructureCategory with the given identifier exists in the graph, or raises an error if not found and auto-creation is disabled."""
        scategory = models.StructureCategory.objects.filter(
            graph=graph,
            identifier=identifier,
        ).first()

        if not scategory:
            if graph.can_perform_action(info, input_models.Action.AUTO_ADD_STRUCTURES):
                scategory = models.StructureCategory.objects.create_from_structure_definition(
                    graph=graph,
                    definition=input_models.StructureDefinitionInput(
                        key=identifier,
                        identifier=identifier,
                    ),
                )
            else:
                raise ValueError(f"Structure identifier {identifier} not found in graph schema. And auto-creation of structure categories is disabled for this graph.")

        return scategory

    def ensure_metric_category_or_raise(self, graph: models.Graph, structure_category: models.StructureCategory, key: str, value_kind: input_models.PropertyType, info: Info) -> models.MetricCategory:
        mcategory = models.MetricCategory.objects.filter(
            graph=graph,
            key=key,
            structure_category=structure_category,
        ).first()

        if not mcategory:
            if graph.can_perform_action(info, input_models.Action.AUTO_ADD_STRUCTURES):
                mcategory = models.MetricCategory.objects.create_from_metric_definition(
                    graph=graph,
                    definition=input_models.MetricDefinitionInput(
                        structure=structure_category.identifier,
                        value_kind=value_kind,
                        key=key,
                    ),
                )
            else:
                raise ValueError(f"Metric identifier {key} not found in graph schema for structure {structure_category.identifier}.")

        return mcategory

    def _materialize_supporting_evidence(
        self,
        graph: models.Graph,
        supporting_evidence: list[Any],
        assertion: evidence_models.Assertion,
        info: Info,
    ) -> list[tuple[Any, models.StructureCategory, evidence_models.Structure]]:
        """Write the structures and metrics backing a creation into Postgres.

        The shared path for `create_entity` and `create_natural_event`. Nothing
        here touches AGE any more: structures and metrics are the base relation,
        and the caller separately projects whatever it needs into the graph.
        """
        organization = graph.organization
        materialized_evidence: list[tuple[Any, models.StructureCategory, evidence_models.Structure]] = []

        for evidence in supporting_evidence:
            structure_category = self.ensure_structure_category_or_raise(graph, evidence.identifier, info)
            structure = writer.ensure_structure(
                organization,
                category=structure_category,
                object=evidence.object,
                assertion=assertion,
            )

            for measurement in evidence.metrics:
                metric_category = self.ensure_metric_category_or_raise(
                    graph=graph,
                    structure_category=structure_category,
                    key=measurement.key,
                    value_kind=self._infer_metric_value_kind(measurement.value),
                    info=info,
                )
                writer.record_metric(
                    organization,
                    structure,
                    metric_category,
                    key=measurement.key,
                    value=measurement.value,
                    assertion=assertion,
                    unit=measurement.unit,
                    confidence=measurement.confidence,
                    confidence_type=measurement.confidence_type,
                    measured_at=measurement.timestamp,
                )

            materialized_evidence.append((evidence, structure_category, structure))

        return materialized_evidence

    def create_entity(
        self,
        entity_category: models.EntityCategory,
        payload: inputs.EntityInput,
        info: Info,
    ) -> retrieved.RetrievedEntity:
        """
        Create a new entity with optional supporting evidence structures.

        Args:
            kind: The entity type/label (must match schema)
            ref_id: Unique reference ID for the entity
            action_id: Optional action ID (provenance)
            action_name: Optional action name (provenance)
            action_args: Optional action arguments (provenance)
            supporting_evidence: List of evidence dicts with 'identifier', 'object', 'measurements'
            schema: Optional schema override (defaults to graph's definition)

        Returns:
            EntityCreationResult with ref_id, db_id, and graph_id
        """
        supporting_evidence = payload.supporting_evidence or []
        graph: models.Graph = entity_category.graph
        organization = graph.organization

        # Evidence first, in one transaction. AGE cannot join a Django
        # transaction — the engine runs on independent cursors — so the two
        # stores commit separately by construction. That asymmetry is deliberate
        # rather than a bug to compensate for: evidence is the source of truth,
        # so a failure after this commit leaves durable evidence with no
        # projection, and `reproject` (M3) picks it up. Do not "fix" this by
        # deleting the evidence when the AGE write fails.
        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            materialized_evidence = self._materialize_supporting_evidence(
                graph=graph,
                supporting_evidence=supporting_evidence,
                assertion=assertion,
                info=info,
            )

        # The entity itself is still projected into AGE. It carries only its
        # immutable identity; every derived property is the projector's job.
        ref_id = self.create_universal_id()
        create_res = self.engine.execute(
            graph,
            f"""
            CREATE (e:{entity_category.age_name} {{id: $eid, category_id: $cid}})
            RETURN e as entity, id(e) as db_id
            """,
            {"eid": ref_id, "cid": entity_category.pk},
        )

        entity = create_res[0]["entity"]
        retrieved_entity = RetrievedEntity.from_node(self, entity, graph_name=graph.age_name)

        # The INFORMS relationship is evidence, not projection: which structures
        # justify this entity is a claim about the world and outlives any graph
        # built from it.
        for _, _, structure in materialized_evidence:
            writer.create_link(
                organization,
                kind=evidence_models.Link.Kind.INFORMS,
                source_ref=str(structure.pk),
                target_ref=str(retrieved_entity.graph_id),
                assertion=assertion,
            )

        self._stamp_projection(entity_category, retrieved_entity.local_id)
        return retrieved_entity

    def delete_entity(self, graph: models.Graph, local_id: scalars.LocalID) -> scalars.LocalID:
        """
        Deletes an entity by its composite ID.

        This performs a hard delete, removing the node and all its relationships from the graph.

        Args:
            graph: The graph to operate on
            entity_id: The composite ID of the entity to delete (e.g., "1-abc123-def456-...")
        """
        self.engine.execute(
            graph,
            """
            MATCH (e) WHERE id(e) = $eid
            DETACH DELETE e
            """,
            {"eid": local_id},
        )

        return local_id

    def get_structure_by_object(self, category: models.StructureCategory, object: scalars.StructureObject) -> retrieved.RetrievedStructure:
        """
        Retrieves a structure by its object identifier.

        Args:
            category: The StructureCategory to search within
            object: The unique object identifier of the structure

        Returns:
            A RetrievedStructure if found, or None if no matching structure exists
        """
        organization = category.graph.organization
        structure = (
            evidence_models.Structure.objects.for_organization(organization)
            .filter(identifier=category.identifier, object=object)
            .first()
        )
        if structure is None:
            raise ValueError(f"No structure found with object '{object}' in category '{category.identifier}'")

        return RetrievedStructure.from_row(self, structure, graph_name=category.graph.age_name)

    def archive_entity(self, graph: models.Graph, local_id: scalars.LocalID, info: Info) -> scalars.LocalID:
        """
        Archives an entity by its composite ID.

        This performs a soft delete, recording the retraction in the evidence
        lifecycle log and refreshing the projected node's cached state.

        Args:
            graph: The graph to operate on
            local_id: The AGE node id of the entity to archive
        """
        organization = graph.organization
        assertion = self._create_assertion(organization, self._provenance_from_info(info))

        writer.archive_ref(
            organization,
            target_type="entity",
            target_id=f"{graph.age_name}:{local_id}",
            assertion=assertion,
        )

        entity_category = self._get_entity_category_for_local_id(graph, local_id)
        self._stamp_projection(entity_category, local_id)

        return local_id

    def _stamp_projection(self, entity_category: models.EntityCategory, local_id: scalars.LocalID) -> None:
        """Write the system metadata every projected node carries.

        Split out of the old `_recalculate_entity` because these three facts —
        which schema version produced this node, when, and whether it is
        retracted — are knowable without any derivation at all. Keeping them
        working means entity creation still functions while derived *values* are
        dark between M1 and M3.
        """
        updates: Dict[str, Any] = {
            "__lifecycle_state": self._lifecycle_state_for_entity(entity_category.graph, local_id),
            "__schema_version": entity_category.schema_hash,
            "__last_derived": int(time.time() * 1000),
        }

        # Property keys are interpolated into Cypher, not bound, so they must be
        # validated as identifiers.
        set_clause = ", ".join([f"e.{self._validate_property_key(k)} = $u_{k}" for k in updates])
        update_params: Dict[str, Any] = {f"u_{k}": v for k, v in updates.items()}
        update_params["local_id"] = local_id

        self.engine.execute(
            entity_category.graph,
            f"""
            MATCH (e:{entity_category.age_name}) WHERE id(e) = $local_id
            SET {set_clause}
            """,
            update_params,
        )

    def _lifecycle_state_for_entity(self, graph: models.Graph, local_id: scalars.LocalID) -> str:
        """The current lifecycle state of a projected entity, from the evidence log."""
        entity_ref = f"{graph.age_name}:{local_id}"
        latest = (
            evidence_models.LifecycleEvent.objects.for_organization(graph.organization)
            .filter(target_type="entity", target_id=entity_ref)
            .order_by("-at")
            .first()
        )
        return latest.status if latest else evidence_models.LifecycleStatus.ACTIVE

    def _recalculate_entity(self, entity_category: models.EntityCategory, local_id: scalars.LocalID) -> None:
        """Derive an entity's cached properties from its supporting evidence.

        **Not implemented between M1 and M3, deliberately.**

        Metrics moved from AGE into Postgres, so the rollup Cypher this used to
        run (`MATCH (m:Metric)-[:DESCRIBES]->(s)`) now matches nothing. Leaving
        it in place would silently write `null` over every derived property,
        which is far worse than failing: a null derived value is
        indistinguishable from "no evidence yet", so the breakage would be
        invisible until someone noticed their numbers were gone.

        This costs nothing that previously worked. `create_metric` never
        re-derived, `link_structure_to_entity` raised a `NameError` before
        reaching this, and relations never executed at all — derivation was
        already non-functional. The replacement is the state vector (M2) plus
        the projector (M3), and this raise is what makes the gap between here
        and there impossible to ship by accident.
        """
        raise NotImplementedError(
            "Derived properties are not computed between M1 and M3. Metrics now live in "
            "the relational evidence base, and the projector that reads them lands in M3. "
            "See docs/ARCHITECTURE.md."
        )

    def list_entities_informed_by_structure(self, graph: models.Graph, structure_id: str, info: Info | None = None) -> List[RetrievedEntity]:
        """
        Lists all entities that are informed by a given structure.

        The INFORMS traversal is a SQL lookup now — the links are evidence, not
        projection — followed by fetching the named entities out of AGE. Entities
        are still projection-scoped, so this stays restricted to one graph.

        Args:
            graph: The graph to query
            structure_id: The evidence primary key of the structure
        """
        self._ensure_query_access(graph, info)

        links = evidence_models.Link.objects.for_organization(graph.organization).filter(
            kind=evidence_models.Link.Kind.INFORMS,
            source_ref=str(structure_id),
            status=evidence_models.LifecycleStatus.ACTIVE,
        )

        local_ids = []
        for link in links:
            graph_name, _, node_id = link.target_ref.partition(":")
            if graph_name == graph.age_name and node_id:
                local_ids.append(int(node_id))

        if not local_ids:
            return []

        result = self.engine.execute(
            graph,
            """
            MATCH (e) WHERE id(e) IN $eids
            RETURN e
            """,
            {"eids": local_ids},
        )
        return [RetrievedEntity.from_node(self, row["e"], graph_name=graph.age_name) for row in result]

    def set_entity_property(self, graph: models.Graph, local_id: scalars.LocalID, key: str, value: Any) -> None:
        """
        Sets a property directly on a projected entity node.

        A write straight into the projection, bypassing evidence entirely — which
        makes it exactly the kind of un-derivable state that `reproject` cannot
        reconstruct. It survives M1 because it is live and tested; M3 removes it
        once the projector owns entity properties.

        Args:
            graph: The graph to operate on
            local_id: The internal graph ID of the entity node
            key: The property key to set
            value: The value to set for the property
        """
        self.engine.execute(
            graph,
            """
            MATCH (e) WHERE id(e) = $eid
            SET e += $props
            """,
            {"eid": local_id, "props": {key: value}},
        )

    def get_node(self, graph: models.Graph, local_id: scalars.LocalID, info: Info | None = None) -> retrieved.RetrievedNode:
        """
        Retrieve a raw node by its string ID.

        This is a low-level method that returns the raw graph data without
        any schema-based processing or migration. It can be used for debugging
        or for operations that need direct access to the underlying graph.

        Args:
            graph: The graph to query
            local_id: The internal graph ID of the node to retrieve
        """
        self._ensure_query_access(graph, info)

        query = """
            MATCH (n) WHERE id(n) = $id
            RETURN n, labels(n) as lbls
        """
        result = self.engine.execute(graph, query, {"id": local_id})

        if not result:
            raise ValueError(f"Node not found with ID {local_id}")

        raw_node = result[0]["n"]

        return RetrievedNode.from_node(self, raw_node, graph_name=graph.age_name)

    def get_node_by_local_id(self, graph: models.Graph, local_id: scalars.LocalID, info: Info | None = None) -> retrieved.RetrievedNode:
        """Retrieve a raw node by its internal AGE graph ID."""
        self._ensure_query_access(graph, info)

        query = """
            MATCH (n) WHERE id(n) = $nid
            RETURN n
        """
        result = self.engine.execute(graph, query, {"nid": local_id})

        if not result:
            raise ValueError(f"Node not found with local ID {local_id}")

        raw_node = result[0]["n"]
        return RetrievedNode.from_node(self, raw_node, graph_name=graph.age_name)

    def get_node_for_composite_id(self, composite_id: scalars.GraphID, info: Info | None = None) -> retrieved.RetrievedNode:
        """
        Retrieve a node using a composite global ID (format: {graph_id}:{entity_id}).

        This method extracts the graph ID and entity ID from the composite ID,
        fetches the corresponding graph, and then retrieves the node.

        Args:
            composite_id: The composite ID in the format "graph_id:entity_id"

        Returns:
            RetrievedNode with the node's data
        """
        graph_id, entity_id = composite_id.split(":", 1)

        graph = None
        if str(graph_id).isdigit():
            graph = models.Graph.objects.filter(id=int(graph_id)).first()
        if graph is None:
            graph = models.Graph.objects.filter(age_name=graph_id).first()
        if graph is None:
            raise ValueError(f"Graph not found for identifier {graph_id}")

        return self.get_node(graph, scalars.LocalID(int(entity_id)), info=info)

    def get_entity(
        self,
        entity_category: models.EntityCategory,
        id: str,
    ) -> retrieved.RetrievedEntity:
        """
        Retrieves an Entity by ID.
        Dynamically detects the 'kind' from the Node Labels and returns
        a RetrievedEntity with the raw graph data.

        Args:
            id: The entity's unique string ID
            entity_category: The entity category (used to access the graph and schema)

        Returns:
            RetrievedEntity with the node's data
        """
        graph = entity_category.graph

        # 1. Fetch Node AND its Labels
        # We search strictly by the unique 'id' property.
        query = """
            MATCH (n) WHERE n.id = $id
            RETURN n, labels(n) as lbls
        """
        result = self.engine.execute(graph, query, {"id": id})

        if not result:
            raise ValueError(f"Entity not found with ID {id}")

        # Parse Result
        # AGE returns: {'n': {'id': <graph_id>, 'label': '...', 'properties': {...}}, 'lbls': [...]}
        raw_node = result[0]["n"]
        labels = result[0]["lbls"]

        # Extract properties - AGE wraps them in a 'properties' key
        if isinstance(raw_node, dict) and "properties" in raw_node:
            node_props = raw_node["properties"]
        else:
            node_props = raw_node

        # 2. Detect Kind from Labels
        # We look for a label that exists in our graph's entity categories
        detected_kind = None

        # Priority: Check entity categories defined in this graph
        entity_categories = {ec.age_name for ec in graph.entity_categories.all()}

        for label in labels:
            if label in entity_categories:
                detected_kind = label
                break

        if not detected_kind:
            # Fallback: Just return what we have
            detected_kind = labels[0] if labels else "Unknown"

        normalized_node = {
            "id": raw_node.get("id", 0),
            "label": detected_kind,
            "properties": node_props,
        }
        return RetrievedEntity.from_node(self, normalized_node, graph_name=graph.age_name)

    def get_structure(
        self,
        graph: models.Graph,
        identifier: str,
        object: str,
        info: Info | None = None,
    ) -> retrieved.RetrievedStructure:
        """
        Retrieves a Structure by identifier and object.

        Args:
            graph: The graph to query
            identifier: Schema identifier (e.g. '@mikro/roi')
            object: Object ID of the structure
        """
        self._ensure_query_access(graph, info)

        structure = (
            evidence_models.Structure.objects.for_organization(graph.organization)
            .filter(identifier=identifier, object=object)
            .first()
        )
        if structure is None:
            raise ValueError(f"Structure not found with identifier {identifier} and object {object}")

        return retrieved.RetrievedStructure.from_row(self, structure, graph_name=graph.age_name)

    def get_informing_structures(
        self,
        graph: models.Graph,
        entity_id: str,
        info: Info | None = None,
    ) -> List[retrieved.RetrievedStructure]:
        """
        Gets all structures that INFORM a given entity.

        Args:
            graph: The graph to query
            entity_id: The entity's composite graph ID
        """
        self._ensure_query_access(graph, info)

        organization = graph.organization
        structure_ids = (
            evidence_models.Link.objects.for_organization(organization)
            .filter(
                kind=evidence_models.Link.Kind.INFORMS,
                target_ref=str(entity_id),
                status=evidence_models.LifecycleStatus.ACTIVE,
            )
            .values_list("source_ref", flat=True)
        )

        structures = evidence_models.Structure.objects.for_organization(organization).filter(pk__in=list(structure_ids))
        return [retrieved.RetrievedStructure.from_row(self, row, graph_name=graph.age_name) for row in structures]

    def get_entities_informed_by(
        self,
        graph: models.Graph,
        identifier: str,
        structure_object: str,
        info: Info | None = None,
    ) -> List[retrieved.RetrievedEntity]:
        """
        Gets all entities that are informed by a given structure.
        """
        self._ensure_query_access(graph, info)

        structure = (
            evidence_models.Structure.objects.for_organization(graph.organization)
            .filter(identifier=identifier, object=structure_object)
            .first()
        )
        if structure is None:
            return []

        return self.list_entities_informed_by_structure(graph, str(structure.pk), info=info)

    def get_metrics_for_structure(
        self,
        graph: models.Graph,
        identifier: str,
        structure_object: str,
        info: Info | None = None,
    ) -> List[RetrievedMetric]:
        """
        Gets all measurements that describe a given structure.

        Args:
            graph: The graph to query
            identifier: Schema identifier (e.g. '@mikro/roi')
            structure_object: Object ID of the structure
        """
        self._ensure_query_access(graph, info)

        organization = graph.organization
        structure = (
            evidence_models.Structure.objects.for_organization(organization)
            .filter(identifier=identifier, object=structure_object)
            .first()
        )
        if structure is None:
            return []

        metrics = writer.active_metrics_for_structures(organization, [structure.pk])
        return [RetrievedMetric.from_row(self, row, graph_name=graph.age_name) for row in metrics]

    def get_assertion_for_entity(
        self,
        graph: models.Graph,
        entity_id: str,
        info: Info | None = None,
    ) -> Optional[RetrievedAssertion]:
        """
        Gets the assertion that introduced a given entity.

        Args:
            graph: The graph to query
            entity_id: The entity's composite graph ID
        """
        self._ensure_query_access(graph, info)

        link = (
            evidence_models.Link.objects.for_organization(graph.organization)
            .filter(kind=evidence_models.Link.Kind.INFORMS, target_ref=str(entity_id))
            .select_related("assertion")
            .order_by("created_at")
            .first()
        )
        if link is None:
            return None

        return RetrievedAssertion.from_row(self, link.assertion, graph_name=graph.age_name)

    def get_metrics_for_assertion(
        self,
        graph: models.Graph,
        assertion_id: str,
        info: Info | None = None,
    ) -> List[RetrievedMetric]:
        """
        Gets all measurements asserted by a given assertion.

        Args:
            graph: The graph to query
            assertion_id: The evidence primary key of the assertion
        """
        self._ensure_query_access(graph, info)

        metrics = evidence_models.Metric.objects.for_organization(graph.organization).filter(
            assertion_id=assertion_id
        )
        return [RetrievedMetric.from_row(self, row, graph_name=graph.age_name) for row in metrics]

    def create_structure(
        self,
        structure_category: models.StructureCategory,
        payload: inputs.StructureInput,
        info: Info,
    ) -> RetrievedStructure:
        """
        Create a structure, or return the existing one for the same datum.

        Idempotent by `(identifier, object)` within the organization, so two
        projections that reference the same external object converge on one row
        instead of each getting a private copy.

        Returns:
            RetrievedStructure with the created structure info
        """
        graph = structure_category.graph
        organization = graph.organization

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            structure = writer.ensure_structure(
                organization,
                category=structure_category,
                object=payload.object,
                assertion=assertion,
            )
            for metric in payload.metrics or []:
                self._record_metric(organization, structure, metric, graph=graph, info=info, assertion=assertion)

        return RetrievedStructure.from_row(self, structure, graph_name=graph.age_name)

    def _assert_can_access(self, organization: Any, info: Info | None) -> None:
        """Check the caller may act for this organization.

        Evidence rows are identified by a globally unique primary key, so the
        client never has to name a tenant — but that means authorization cannot
        come from the request either. It comes from the row: find what the id
        points at, then check the caller belongs to *its* organization. Skipping
        this is a cross-tenant read, which is precisely the guarantee we gave up
        by leaving per-graph AGE namespaces.
        """
        if info is None:
            return

        user = getattr(info.context.request, "user", None)
        if user is None:
            raise PermissionError("Cannot access evidence without an authenticated user")

        if not Membership.objects.filter(user=user, organization=organization, blocked=False).exists():
            raise PermissionError("You are not allowed to access this organization's evidence")

    def get_structure_for_identifier(
        self,
        graph: models.Graph,
        identifier: str,
        object: str,
        info: Info | None = None,
    ) -> evidence_models.Structure:
        """Resolve a structure row by its organization-scoped identity."""
        structure = (
            evidence_models.Structure.objects.for_organization(graph.organization)
            .filter(identifier=identifier, object=object)
            .first()
        )
        if structure is None:
            raise ValueError(f"Structure not found for {identifier}:{object}")
        return structure

    def _structure_category_for(
        self,
        graph: models.Graph,
        structure: evidence_models.Structure,
        info: Info,
    ) -> models.StructureCategory:
        """The acting graph's term for this structure's kind.

        A shared structure carries whichever graph's category first created it,
        but a metric recorded through graph B has to resolve against B's schema.
        Falls back to the structure's own category when the acting graph is the
        one that created it, which is the common case.
        """
        if structure.category.graph_id == graph.pk:
            return structure.category
        return self.ensure_structure_category_or_raise(graph, structure.identifier, info)

    def _resolve_structure(self, structure_id: str, info: Info | None = None) -> evidence_models.Structure:
        """Fetch a structure by evidence primary key, then authorize against its organization."""
        # all_objects, not objects: the organization is what we are *looking up*
        # here, so it cannot also be the filter. The `_assert_can_access` call
        # below is what makes that safe, and no use of `all_objects` is
        # acceptable without one.
        structure = evidence_models.Structure.all_objects.filter(pk=structure_id).first()
        if structure is None:
            raise ValueError(f"Structure not found with id {structure_id}")
        self._assert_can_access(structure.organization, info)
        return structure

    def _record_metric(
        self,
        organization: Any,
        structure: evidence_models.Structure,
        metric_input: MetricInput,
        *,
        graph: models.Graph,
        info: Info,
        assertion: evidence_models.Assertion,
    ) -> evidence_models.Metric:
        """Append one measurement, resolving its category from the schema.

        `graph` is the graph *recording* the measurement, and must be passed in
        rather than read off `structure.category.graph`. Structures dedupe on
        `(organization, identifier, object)` and keep whichever category first
        created the row, so a structure introduced by graph A and measured by
        graph B would otherwise resolve B's metric against A's schema — gating on
        A's permissions and filing any auto-created MetricCategory under A, where
        B cannot see it. That only bites once evidence is genuinely shared across
        graphs, which is exactly what M1 enables.
        """
        metric_category = self.ensure_metric_category_or_raise(
            graph=graph,
            structure_category=self._structure_category_for(graph, structure, info),
            key=metric_input.key,
            value_kind=self._infer_metric_value_kind(metric_input.value),
            info=info,
        )
        return writer.record_metric(
            organization,
            structure,
            metric_category,
            key=metric_input.key,
            value=metric_input.value,
            assertion=assertion,
            unit=metric_input.unit,
            confidence=metric_input.confidence,
            confidence_type=metric_input.confidence_type,
            measured_at=metric_input.timestamp,
        )

    def delete_structure(
        self,
        structure_id: str,
        info: Info | None = None,
    ) -> str:
        """Hard delete a structure and its metrics.

        Prefer `archive_structure`. Evidence is append-only by design, and a hard
        delete destroys the record of what a derived value was once computed
        from. This exists for genuine mistakes — an ingest that pointed at the
        wrong object entirely — not for retraction.
        """
        structure = self._resolve_structure(structure_id, info)
        structure.delete()
        return structure_id

    def archive_structure(
        self,
        structure_id: str,
        info: Info,
    ) -> RetrievedStructure:
        """Retract a structure by writing a lifecycle event against it."""
        structure = self._resolve_structure(structure_id, info)
        organization = structure.organization

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            writer.archive(organization, structure, assertion)

        return retrieved.RetrievedStructure.from_row(self, structure)

    def update_structure(
        self,
        structure_id: str,
        payload: inputs.StructureInput,
        info: Info,
    ) -> retrieved.RetrievedStructure:
        """Append metrics to an existing structure.

        A structure's `(identifier, object)` is its identity, so `object` is
        **immutable** and repointing it is rejected. The original plan called for
        a supersede assertion here, but a supersede is incoherent under the
        uniqueness constraint: a row with a different `object` is not a new
        version of this datum, it is a different datum. Pointing at the wrong ROI
        is fixed by creating the right structure and archiving the wrong one,
        which keeps both facts on the record.
        """
        structure = self._resolve_structure(structure_id, info)
        organization = structure.organization

        if payload.object and payload.object != structure.object:
            raise ValueError(
                f"A structure's object is immutable: {structure.identifier}:{structure.object} "
                f"cannot become {structure.identifier}:{payload.object}. Create the correct "
                f"structure and archive this one instead."
            )

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            for metric in payload.metrics or []:
                self._record_metric(
                    organization, structure, metric, graph=structure.category.graph, info=info, assertion=assertion
                )

        return RetrievedStructure.from_row(self, structure)

    def create_natural_event(
        self,
        category: models.NaturalEventCategory,
        payload: inputs.NaturalEventInput,
        info: Info,
    ) -> RetrievedNaturalEvent:
        """
        Add a natural event to the graph.

        Args:
            category: The NaturalEventCategory to use for this event
            payload: The input data for the natural event

        Returns:
            RetrievedEvent with the created event info
        """
        supporting_evidence = payload.supporting_evidence or []
        graph: models.Graph = category.graph
        organization = graph.organization

        # Evidence first, in one transaction. See the note in `create_entity`
        # about why the AGE write deliberately sits outside it.
        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            materialized_evidence = self._materialize_supporting_evidence(
                graph=graph,
                supporting_evidence=supporting_evidence,
                assertion=assertion,
                info=info,
            )

        event_vertex_name = category.get_age_vertex_name()
        create_res = self.engine.execute(
            graph,
            f"""
            CREATE (e:{event_vertex_name} {{id: $eid, category_id: $cid}})
            RETURN id(e) as event_id
            """,
            {"eid": self.create_universal_id(), "cid": category.pk},
        )

        event_id = create_res[0]["event_id"]

        for _, _, structure in materialized_evidence:
            writer.create_link(
                organization,
                kind=evidence_models.Link.Kind.INFORMS,
                source_ref=str(structure.pk),
                target_ref=f"{graph.age_name}:{event_id}",
                assertion=assertion,
            )

        # We have created the event node, now we link the roles and evidence to it, and then recalculate properties based on the evidence.

        for mapping in payload.inputs:
            role_vertex_name = category.get_age_input_role_edge_name(mapping.role)
            graph_local_entity = extract_node_id(mapping.entity_id)

            self.engine.execute(
                graph,
                f"""
                MATCH (e:{event_vertex_name}) WHERE id(e) = $eid
                MATCH (ent) WHERE id(ent) = $entity_id
                MERGE (r:{role_vertex_name})
                MERGE (e)<-[:{role_vertex_name}]-(r)
                """,
                {"eid": event_id, "entity_id": graph_local_entity},
            )

        for mapping in payload.outputs:
            role_vertex_name = category.get_age_output_role_edge_name(mapping.role)
            graph_local_entity = extract_node_id(mapping.entity_id)

            self.engine.execute(
                graph,
                f"""
                MATCH (e:{event_vertex_name}) WHERE id(e) = $eid
                MATCH (ent) WHERE id(ent) = $entity_id
                MERGE (r:{role_vertex_name})
                MERGE (e)-[:{role_vertex_name}]->(r)
                """,
                {"eid": event_id, "entity_id": graph_local_entity},
            )

        result = self.engine.execute(
            graph,
            """
            MATCH (e) WHERE id(e) = $eid
            RETURN e
            """,
            {"eid": event_id},
        )
        return RetrievedNaturalEvent.from_node(self, result[0]["e"], graph_name=graph.age_name)

    def create_metric(
        self,
        structure_id: str,
        input: MetricInput,
        info: Info,
        graph: models.Graph | None = None,
    ) -> RetrievedMetric:
        """
        Append a measurement to an existing structure.

        Args:
            structure_id: The evidence primary key of the structure
            input: The measurement data
            info: Request info used to extract provenance

        Returns:
            RetrievedMetric with the created measurement info
        """
        structure = self._resolve_structure(structure_id, info)
        organization = structure.organization
        acting_graph = graph or structure.category.graph

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            metric = self._record_metric(organization, structure, input, graph=acting_graph, info=info, assertion=assertion)

        return RetrievedMetric.from_row(self, metric)

    def _resolve_metric(self, metric_id: str, info: Info | None = None) -> evidence_models.Metric:
        """Fetch a metric by evidence primary key, then authorize against its organization."""
        metric = evidence_models.Metric.all_objects.filter(pk=metric_id).first()
        if metric is None:
            raise ValueError(f"Metric not found with id {metric_id}")
        self._assert_can_access(metric.organization, info)
        return metric

    def get_metric(self, metric_id: str, info: Info | None = None) -> RetrievedMetric:
        """Read a single metric by its evidence primary key."""
        return RetrievedMetric.from_row(self, self._resolve_metric(metric_id, info))

    def get_structure_by_id(self, structure_id: str, info: Info | None = None) -> RetrievedStructure:
        """Read a single structure by its evidence primary key."""
        return RetrievedStructure.from_row(self, self._resolve_structure(structure_id, info))

    def get_metrics_for_structure_id(self, structure_id: str, info: Info | None = None) -> List[RetrievedMetric]:
        """Every un-retracted metric describing a structure, by the structure's id."""
        structure = self._resolve_structure(structure_id, info)
        metrics = writer.active_metrics_for_structures(structure.organization, [structure.pk])
        return [RetrievedMetric.from_row(self, row) for row in metrics]

    def get_metrics_for_assertion_id(self, assertion_id: str, info: Info | None = None) -> List[RetrievedMetric]:
        """Every metric recorded under one assertion, by the assertion's id.

        Unanswerable before M1: an assertion was an AGE vertex, so its id alone
        did not say which graph to look in. Organization-scoped rows have
        globally unique keys, which is what makes this a real query.
        """
        assertion = evidence_models.Assertion.all_objects.filter(pk=assertion_id).first()
        if assertion is None:
            raise ValueError(f"Assertion not found with id {assertion_id}")
        self._assert_can_access(assertion.organization, info)

        metrics = evidence_models.Metric.objects.for_organization(assertion.organization).filter(assertion_id=assertion.pk)
        return [RetrievedMetric.from_row(self, row) for row in metrics]

    def archive_metric(
        self,
        metric_id: str,
        info: Info,
    ) -> str:
        """Retract a measurement without destroying it.

        The metric stays readable afterwards, which is the point: a derived value
        that stopped counting this measurement still has to be explainable.
        """
        metric = self._resolve_metric(metric_id, info)
        organization = metric.organization

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            writer.archive(organization, metric, assertion)

        return metric_id

    def delete_metric(
        self,
        metric_id: str,
        info: Info | None = None,
    ) -> str:
        """Hard delete a measurement. Prefer `archive_metric` — see `delete_structure`."""
        metric = self._resolve_metric(metric_id, info)
        metric.delete()
        return metric_id

    def update_metric(
        self,
        payload: inputs.UpdateMetricInput,
        info: Info,
    ) -> RetrievedMetric:
        """Correct a measurement by retracting it and asserting a new one.

        Never an in-place edit. Both the original claim and the correction stay
        on the record, under separate assertions, so `as_of` can still recover
        what was believed before the revision.
        """
        metric = self._resolve_metric(str(payload.id), info)
        organization = metric.organization
        structure = metric.structure

        metric_input = MetricInput(
            key=payload.key,
            value=payload.value,
            confidence=payload.confidence,
            confidence_type=payload.confidence_type,
            unit=payload.unit,
            timestamp=payload.timestamp,
        )

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            writer.archive(organization, metric, assertion)
            replacement = self._record_metric(
                organization, structure, metric_input, graph=metric.category.graph, info=info, assertion=assertion
            )

        return RetrievedMetric.from_row(self, replacement)

    def link_structure_to_entity(
        self,
        structure_id: str,
        entity_id: scalars.GraphID,
        info: Info,
    ) -> RetrievedStructure:
        """Assert that a structure is evidence for an entity.

        Reinstated here as a *pure evidence write* — it was removed from the
        schema in M0 because the old implementation raised a `NameError` before
        doing anything. Which structures justify an entity is a claim about the
        world, so the link is evidence and outlives any graph projected from it.

        No derivation is triggered. Recomputing the entity's properties from its
        new evidence is the projector's job and lands in M3.
        """
        structure = self._resolve_structure(structure_id, info)
        organization = structure.organization

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            writer.create_link(
                organization,
                kind=evidence_models.Link.Kind.INFORMS,
                source_ref=str(structure.pk),
                target_ref=str(entity_id),
                assertion=assertion,
            )

        return RetrievedStructure.from_row(self, structure)

    def delete_relation(
        self,
        graph: models.Graph,
        relation_id: scalars.LocalID,
        info: Info,
    ) -> scalars.LocalID:
        """Hard delete a relation edge and remove its shadow link if it becomes orphaned."""
        result = self.engine.execute(
            graph,
            """
            MATCH ()-[r]->() WHERE id(r) = $rid
            RETURN r.__shadow_link_id as sl_id
            """,
            {"rid": relation_id},
        )
        if not result:
            raise ValueError(f"Relation not found with edge ID {relation_id}")

        shadow_link_id = result[0].get("sl_id")

        self.engine.execute(
            graph,
            """
            MATCH ()-[r]->() WHERE id(r) = $rid
            DELETE r
            """,
            {"rid": relation_id},
        )

        if shadow_link_id is not None:
            self.engine.execute(
                graph,
                f"""
                MATCH (sl:{vocab.ShadowLink}) WHERE id(sl) = $sl_id
                OPTIONAL MATCH ()-[r]->() WHERE r.__shadow_link_id = $sl_id
                WITH sl, count(r) as relation_count
                WHERE relation_count = 0
                DETACH DELETE sl
                """,
                {"sl_id": shadow_link_id},
            )

        return relation_id

    def archive_relation(
        self,
        graph: models.Graph,
        relation_id: scalars.LocalID,
        info: Info,
    ) -> scalars.LocalID:
        """Soft archive a relation edge and its shadow link provenance chain."""
        result = self.engine.execute(
            graph,
            """
            MATCH ()-[r]->() WHERE id(r) = $rid
            RETURN r.__shadow_link_id as sl_id
            """,
            {"rid": relation_id},
        )
        if not result:
            raise ValueError(f"Relation not found with edge ID {relation_id}")

        shadow_link_id = result[0].get("sl_id")
        archived_at = int(time.time() * 1000)

        self.engine.execute(
            graph,
            """
            MATCH ()-[r]->() WHERE id(r) = $rid
            SET r.__lifecycle_state = $status,
                r.__archived_at = $archived_at
            """,
            {
                "rid": relation_id,
                "status": "archived",
                "archived_at": archived_at,
            },
        )

        if shadow_link_id is not None:
            # The retraction is recorded in the evidence lifecycle log; only the
            # cached state on the projected shadow link is written to AGE. The
            # old version tried to `MATCH (a:Assertion)` in the graph, which
            # after M1 matches nothing — so the whole CREATE silently did not
            # happen and the archive was lost.
            assertion = self._create_assertion(graph.organization, self._provenance_from_info(info))
            writer.archive_ref(
                graph.organization,
                target_type="shadow_link",
                target_id=f"{graph.age_name}:{shadow_link_id}",
                assertion=assertion,
            )
            self.engine.execute(
                graph,
                f"""
                MATCH (sl:{vocab.ShadowLink}) WHERE id(sl) = $sl_id
                SET sl.__lifecycle_state = $status,
                    sl.__archived_at = $archived_at
                """,
                {
                    "sl_id": shadow_link_id,
                    "status": "archived",
                    "archived_at": archived_at,
                },
            )

        return relation_id

    # ===================================================================
    # Relation Query Methods
    # ===================================================================

    def get_relation_by_id(self, edge_id: scalars.LocalID) -> Optional[RetrievedEdge]:
        """
        Get a relation edge by its graph ID.

        Args:
            edge_id: The AGE edge ID

        Returns:
            RetrievedEdge or None if not found
        """
        result = self.engine.execute(
            self.graph,
            """
            MATCH ()-[r]->() WHERE id(r) = $eid
            RETURN r, type(r) as label, id(r) as id, 
                   startNode(r) as start_node, endNode(r) as end_node
            """,
            {"eid": edge_id},
        )

        if not result:
            return None

        row = result[0]
        edge_data = row["r"] if isinstance(row["r"], dict) else {}

        return RetrievedEdge(
            graph_name=self.age_name,
            id=edge_id,
            label=row.get("label", "UNKNOWN"),
            left_id=_extract_id(row["start_node"]) if row.get("start_node") else 0,
            right_id=_extract_id(row["end_node"]) if row.get("end_node") else 0,
            properties=_extract_props(edge_data) if isinstance(edge_data, dict) else {},
        )

    def get_shadow_link(self, link_ref_id: str) -> Optional[RetrievedNode]:
        """
        Get a ShadowLink node by its ref_id.

        Args:
            link_ref_id: The reference ID of the shadow link

        Returns:
            RetrievedNode or None if not found
        """
        result = self.engine.execute(
            self.graph,
            f"""
            MATCH (sl:{vocab.ShadowLink} {{id: $link_id}})
            RETURN sl, id(sl) as graph_id
            """,
            {"link_id": link_ref_id},
        )

        if not result:
            return None

        row = result[0]
        return RetrievedNode.from_node(self, row["sl"], graph_name=self.age_name)

    def get_informing_structures_for_link(self, link_ref_id: str) -> List[retrieved.RetrievedStructure]:
        """
        Get all structures that INFORM a ShadowLink.

        Args:
            link_ref_id: The reference ID of the shadow link

        Returns:
            List of RetrievedStructure that inform the link
        """
        result = self.engine.execute(
            self.graph,
            f"""
            MATCH (sl:{vocab.ShadowLink} {{id: $link_id}})
            MATCH (s)-[:{vocab.INFORMS}]->(sl)
            RETURN s, labels(s)[0] as label, id(s) as graph_id
            """,
            {"link_id": link_ref_id},
        )

        structures = []
        for row in result:
            structures.append(retrieved.RetrievedStructure.from_node(self, row["s"], graph_name=self.age_name))
        return structures

    def get_reified_as_source_entities(self, link_ref_id: str) -> List[RetrievedEntity]:
        """
        Get all entities that a ShadowLink REIFIES (the source and target of the relation).

        Args:
            link_ref_id: The reference ID of the shadow link

        Returns:
            List of RetrievedEntity that are reified by the link
        """
        result = self.engine.execute(
            self.graph,
            f"""
            MATCH (sl:{vocab.ShadowLink} {{id: $link_id}})
            MATCH (sl)-[:{vocab.REIFIES_AS_SOURCE}]->(e)
            RETURN e, labels(e)[0] as label, id(e) as graph_id
            """,
            {"link_id": link_ref_id},
        )

        entities = []
        for row in result:
            entities.append(RetrievedEntity.from_node(self, row["e"], graph_name=self.age_name))
        return entities

    def get_reified_as_target_entities(self, link_ref_id: str) -> List[RetrievedEntity]:
        """
        Get all entities that a ShadowLink REIFIES (the source and target of the relation).

        Args:
            link_ref_id: The reference ID of the shadow link

        Returns:
            List of RetrievedEntity that are reified by the link
        """
        result = self.engine.execute(
            self.graph,
            f"""
            MATCH (sl:{vocab.ShadowLink} {{id: $link_id}})
            MATCH (sl)-[:{vocab.REIFIES_AS_TARGET}]->(e)
            RETURN e, labels(e)[0] as label, id(e) as graph_id
            """,
            {"link_id": link_ref_id},
        )

        entities = []
        for row in result:
            entities.append(RetrievedEntity.from_node(self, row["e"], graph_name=self.age_name))
        return entities

    def get_reified_entities(self, link_ref_id: str) -> List[RetrievedEntity]:
        """
        Get all entities that a ShadowLink reifies (both source and target).

        Args:
            link_ref_id: The reference ID of the shadow link

        Returns:
            List of RetrievedEntity containing both source and target
        """
        source_entities = self.get_reified_as_source_entities(link_ref_id)
        target_entities = self.get_reified_as_target_entities(link_ref_id)
        return source_entities + target_entities

    def render_graph_table_query(
        self, graph_query: models.GraphTableQuery, filters: input_models.RenderGraphTableFilter | None = None, pagination: input_models.RenderGraphTablePagination | None = None, order: input_models.RenderGraphTableOrder | None = None, info: Info | None = None
    ) -> RetrievedGraphTableRender:
        """Render a set of nodes matching the graph query, with optional filters, pagination, and ordering."""
        self._ensure_query_access(graph_query.graph, info)
        query, params = self._compose_graph_table_query(
            graph_query.query,
            filters=filters,
            pagination=pagination,
            order=order,
        )

        result_rows = self.engine.execute(graph_query.graph, query, params)

        row_dicts: list[dict[str, Any]] = []
        column_keys = [column.get("key") for column in (graph_query.columns or []) if isinstance(column, dict) and column.get("key")]

        for row in result_rows:
            if isinstance(row, dict):
                row_dicts.append(row)
                continue

            if isinstance(row, (list, tuple)):
                mapped = {(column_keys[index] if index < len(column_keys) else f"col_{index}"): value for index, value in enumerate(row)}
                row_dicts.append(mapped)
                continue

            row_dicts.append({"value": row})

        return RetrievedGraphTableRender(
            graph_name=str(graph_query.graph.age_name),
            graph_id=int(graph_query.graph_id),
            graph_query_id=int(graph_query.id),
            rows=row_dicts,
        )

    def _compose_graph_table_query(
        self,
        base_query: str,
        filters: input_models.RenderGraphTableFilter | None = None,
        pagination: input_models.RenderGraphTablePagination | None = None,
        order: input_models.RenderGraphTableOrder | None = None,
    ) -> tuple[str, dict[str, Any]]:
        query = base_query.strip().rstrip(";")
        params: dict[str, Any] = {}

        filter_clause, filter_params = self._build_graph_table_filter_clause(filters)
        params.update(filter_params)

        if filter_clause:
            query = self._inject_graph_table_filter(query, filter_clause)

        if order:
            key = self._validate_property_key(order.key)
            direction = str(order.direction).lower()
            direction = "DESC" if direction == "desc" else "ASC"
            query = f"{query}\nORDER BY {key} {direction}"

        if pagination:
            if pagination.offset is not None and pagination.offset > 0:
                query = f"{query}\nSKIP {int(pagination.offset)}"
            if pagination.limit is not None:
                query = f"{query}\nLIMIT {int(pagination.limit)}"

        return query, params

    def _build_graph_table_filter_clause(
        self,
        filters: input_models.RenderGraphTableFilter | None,
    ) -> tuple[str, dict[str, Any]]:
        if not filters:
            return "", {}

        key = self._validate_property_key(filters.key)
        operator = str(filters.operator).upper()
        value = self._coerce_filter_value(filters.value)
        value_param = "graph_table_filter_value"

        params = {value_param: value}

        if operator in {"EQUALS", "EQ", "="}:
            return f"{key} = ${value_param}", params
        if operator in {"NOT_EQUALS", "NEQ", "!="}:
            return f"{key} <> ${value_param}", params
        if operator in {"GREATER_THAN", "GT", ">"}:
            return f"{key} > ${value_param}", params
        if operator in {"LESS_THAN", "LT", "<"}:
            return f"{key} < ${value_param}", params
        if operator in {"GREATER_OR_EQUAL", "GREATER_THAN_OR_EQUAL", "GTE", ">="}:
            return f"{key} >= ${value_param}", params
        if operator in {"LESS_OR_EQUAL", "LESS_THAN_OR_EQUAL", "LTE", "<="}:
            return f"{key} <= ${value_param}", params
        if operator == "CONTAINS":
            return f"toString({key}) CONTAINS toString(${value_param})", params
        if operator == "STARTS_WITH":
            return f"toString({key}) STARTS WITH toString(${value_param})", params
        if operator == "ENDS_WITH":
            return f"toString({key}) ENDS WITH toString(${value_param})", params
        if operator == "IN":
            return f"{key} IN ${value_param}", params
        if operator == "NOT_IN":
            return f"NOT {key} IN ${value_param}", params

        raise ValueError(f"Unsupported filter operator '{operator}'.")

    def _inject_graph_table_filter(self, query: str, filter_clause: str) -> str:
        return_matches = list(re.finditer(r"\bRETURN\b", query, flags=re.IGNORECASE))
        if not return_matches:
            return f"{query}\nWHERE {filter_clause}"

        insert_at = return_matches[-1].start()
        prefix = query[:insert_at].rstrip()
        suffix = query[insert_at:].lstrip()

        if re.search(r"\bWHERE\b", prefix, flags=re.IGNORECASE):
            prefix = f"{prefix}\nAND {filter_clause}"
        else:
            prefix = f"{prefix}\nWHERE {filter_clause}"

        return f"{prefix}\n{suffix}"

    def _validate_property_key(self, key: str) -> str:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            raise ValueError(f"Invalid property key '{key}'.")
        return key

    def _coerce_filter_value(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value

        lowered = value.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"

        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value

    def _build_entity_where_clause(self, filters: input_models.EntityFilters | None, variable: str = "e") -> tuple[str, dict[str, Any]]:
        params: dict[str, Any] = {}
        clauses: list[str] = []

        if not filters:
            return "", params

        if filters.category:
            params["filter_category"] = filters.category
            clauses.append(f"labels({variable})[0] = $filter_category")

        if filters.ids:
            params["filter_ids"] = [int(extract_node_id(entity_id)) for entity_id in filters.ids]
            clauses.append(f"id({variable}) IN $filter_ids")

        if filters.search:
            params["filter_search"] = filters.search
            clauses.append(f"{variable}.label CONTAINS $filter_search")

        if filters.has_property:
            key = self._validate_property_key(filters.has_property)
            clauses.append(f"{variable}.{key} IS NOT NULL")

        if filters.matches:
            for index, match in enumerate(filters.matches):
                key = self._validate_property_key(match.key)
                operator = match.operator.value if hasattr(match.operator, "value") else str(match.operator)
                operator = operator.upper()

                value_param = f"match_value_{index}"
                coerced_value = self._coerce_filter_value(match.value)
                field_expr = f"{variable}.{key}"

                if key == "id":
                    field_expr = f"id({variable})"
                    if isinstance(coerced_value, str):
                        if ":" in coerced_value or "-" in coerced_value:
                            try:
                                coerced_value = int(extract_node_id(coerced_value))
                            except ValueError:
                                pass
                        else:
                            try:
                                coerced_value = int(coerced_value)
                            except ValueError:
                                pass

                params[value_param] = coerced_value

                if operator in {"EQUALS", "EQ", "="}:
                    clauses.append(f"{field_expr} = ${value_param}")
                elif operator in {"NOT_EQUALS", "NEQ", "!="}:
                    clauses.append(f"{field_expr} <> ${value_param}")
                elif operator in {"GREATER_THAN", "GT", ">"}:
                    clauses.append(f"{field_expr} > ${value_param}")
                elif operator in {"LESS_THAN", "LT", "<"}:
                    clauses.append(f"{field_expr} < ${value_param}")
                elif operator in {"GREATER_OR_EQUAL", "GREATER_THAN_OR_EQUAL", "GTE", ">="}:
                    clauses.append(f"{field_expr} >= ${value_param}")
                elif operator in {"LESS_OR_EQUAL", "LESS_THAN_OR_EQUAL", "LTE", "<="}:
                    clauses.append(f"{field_expr} <= ${value_param}")
                elif operator == "CONTAINS":
                    clauses.append(f"{field_expr} CONTAINS ${value_param}")
                elif operator == "STARTS_WITH":
                    clauses.append(f"{field_expr} STARTS WITH ${value_param}")
                elif operator == "ENDS_WITH":
                    clauses.append(f"{field_expr} ENDS WITH ${value_param}")
                elif operator == "IN":
                    clauses.append(f"{field_expr} IN ${value_param}")
                elif operator == "NOT_IN":
                    clauses.append(f"NOT {field_expr} IN ${value_param}")
                else:
                    raise ValueError(f"Unsupported filter operator '{operator}'.")

        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    def _build_entity_order_clause(self, order: list[input_models.EntityOrder] | None, variable: str = "e") -> str:
        if not order:
            return ""

        clauses = []
        for o in order:
            if o.property is not None:
                key = self._validate_property_key(o.property.key)
                direction = (o.property.direction.value if hasattr(o.property.direction, "value") else str(o.property.direction)).upper()
                clauses.append(f"{variable}.{key} {direction}")
            elif o.created_at is not None:
                direction = (o.created_at.value if hasattr(o.created_at, "value") else str(o.created_at)).upper()
                clauses.append(f"{variable}.created_at {direction}")
            elif o.id is not None:
                direction = (o.id.value if hasattr(o.id, "value") else str(o.id)).upper()
                clauses.append(f"id({variable}) {direction}")
        if not clauses:
            return ""
        return f"ORDER BY {', '.join(clauses)}"

    def _build_entity_pagination_clause(self, pagination: input_models.EntityPagination | None) -> str:
        if not pagination:
            return "SKIP 0 LIMIT 200"

        offset = pagination.offset if pagination.offset is not None else 0
        limit = pagination.limit if pagination.limit is not None else 200
        return f"SKIP {offset} LIMIT {limit}"

    def list_entities(self, graph: models.Graph, filters: input_models.EntityFilters | None = None, pagination: input_models.EntityPagination | None = None, ordering: list[input_models.EntityOrder] | None = None, info: Info | None = None) -> List[RetrievedEntity]:
        self._ensure_query_access(graph, info)

        entity_labels = list(models.EntityCategory.objects.filter(graph=graph).values_list("age_name", flat=True))
        if not entity_labels:
            return []

        where_clause, filter_params = self._build_entity_where_clause(filters, variable="e")
        order_clause = self._build_entity_order_clause(ordering, variable="e")
        pagination_clause = self._build_entity_pagination_clause(pagination)

        query = f"""
            MATCH (e)
            WHERE labels(e)[0] IN $entity_labels
            {("AND " + where_clause[len("WHERE ") :]) if where_clause else ""}
            RETURN e
            {order_clause}
            {pagination_clause}
        """

        params: dict[str, Any] = {"entity_labels": entity_labels, **filter_params}
        result = self.engine.execute(graph, query, params)

        return [RetrievedEntity.from_node(self, row["e"], graph_name=graph.age_name) for row in result]

    def list_entities_for_category(self, category: models.EntityCategory, filters: input_models.EntityFilters | None = None, pagination: input_models.EntityPagination | None = None, ordering: list[input_models.EntityOrder] | None = None, info: Info | None = None) -> List[RetrievedEntity]:
        self._ensure_query_access(category.graph, info)

        where_clause, filter_params = self._build_entity_where_clause(filters, variable="e")
        order_clause = self._build_entity_order_clause(ordering, variable="e")
        pagination_clause = self._build_entity_pagination_clause(pagination)

        query = f"""
            MATCH (e: {category.get_age_vertex_name()})
            {("AND " + where_clause[len("WHERE ") :]) if where_clause else ""}
            RETURN e
            {order_clause}
            {pagination_clause}
        """

        params: dict[str, Any] = {**filter_params}
        result = self.engine.execute(category.graph, query, params)

        return [RetrievedEntity.from_node(self, row["e"], graph_name=category.graph.age_name) for row in result]

    def list_structures(self, graph: models.Graph, filters: input_models.StructureFilters | None = None, pagination: input_models.StructurePagination | None = None, ordering: list[input_models.StructureOrder] | None = None, info: Info | None = None) -> List[RetrievedStructure]:
        """List structures from the evidence base.

        Scoped to the organization, not to the graph: a structure is a pointer to
        an external datum and is shared by every projection over that
        organization's evidence.
        """
        self._ensure_query_access(graph, info)

        queryset = evidence_models.Structure.objects.for_organization(graph.organization)
        queryset = self._apply_structure_filters(queryset, filters)
        queryset = queryset.order_by(*self._structure_ordering(ordering))

        offset = pagination.offset if pagination and pagination.offset is not None else 0
        limit = pagination.limit if pagination and pagination.limit is not None else 200

        return [
            RetrievedStructure.from_row(self, row, graph_name=graph.age_name)
            for row in queryset[offset : offset + limit]
        ]

    def _apply_structure_filters(self, queryset: Any, filters: input_models.StructureFilters | None) -> Any:
        """Translate structure filters into ORM predicates.

        Property filters resolve against *metrics*, because a structure carries
        no values of its own — it is only the thing measurements are about.
        """
        if not filters:
            return queryset

        if filters.ids:
            queryset = queryset.filter(pk__in=[str(gid).split(":")[-1] for gid in filters.ids])

        if filters.category:
            queryset = queryset.filter(identifier=filters.category)

        if filters.search:
            queryset = queryset.filter(object__icontains=filters.search)

        if filters.has_property:
            queryset = queryset.filter(metrics__key=filters.has_property)

        for match in filters.matches or []:
            operator = (str(match.operator).split(".")[-1] if match.operator is not None else "EQUALS").upper()
            if operator == "NOT_IN":
                queryset = queryset.exclude(
                    metrics__key=match.key, **self._metric_value_predicate("IN", match.value)
                )
            else:
                queryset = queryset.filter(metrics__key=match.key, **self._metric_value_predicate(operator, match.value))

        return queryset.distinct()

    _MATCH_LOOKUPS: Dict[str, str] = {
        "EQUALS": "", "EQ": "", "=": "",
        "GREATER_THAN": "__gt", "GT": "__gt", ">": "__gt",
        "LESS_THAN": "__lt", "LT": "__lt", "<": "__lt",
        "GREATER_OR_EQUAL": "__gte", "GREATER_THAN_OR_EQUAL": "__gte", "GTE": "__gte", ">=": "__gte",
        "LESS_OR_EQUAL": "__lte", "LESS_THAN_OR_EQUAL": "__lte", "LTE": "__lte", "<=": "__lte",
        "CONTAINS": "__contains",
        "STARTS_WITH": "__startswith",
        "ENDS_WITH": "__endswith",
        "IN": "__in",
    }

    def _metric_value_predicate(self, operator: str, value: Any) -> Dict[str, Any]:
        """Build the ORM predicate for a metric value comparison.

        Picks the typed column from the value's own type. Text operators are only
        meaningful against `value_txt`, and ordering operators only against
        `value_num`, so a mismatch is rejected rather than silently matching
        nothing.
        """
        coerced = self._coerce_filter_value(value)
        column = "value_txt" if isinstance(coerced, str) else "value_bool" if isinstance(coerced, bool) else "value_num"

        if operator not in self._MATCH_LOOKUPS:
            raise ValueError(f"Unsupported filter operator '{operator}'.")

        lookup = self._MATCH_LOOKUPS[operator]
        if lookup in {"__contains", "__startswith", "__endswith"} and column != "value_txt":
            raise ValueError(f"Operator '{operator}' needs a string value, got {type(coerced).__name__}.")

        return {f"metrics__{column}{lookup}": coerced}

    def _structure_ordering(self, ordering: list[input_models.StructureOrder] | None) -> List[str]:
        """Translate structure ordering into ORM order_by terms."""
        if not ordering:
            return ["created_at"]

        terms: List[str] = []
        for order in ordering:
            if order.created_at is not None:
                direction = order.created_at
                field = "created_at"
            elif order.id is not None:
                direction = order.id
                field = "id"
            elif order.property is not None:
                # Structures hold no properties of their own; the closest honest
                # ordering is by the datum they point at.
                direction = order.property.direction
                field = "object"
            else:
                continue
            descending = (direction.value if hasattr(direction, "value") else str(direction)).upper() == "DESC"
            terms.append(f"-{field}" if descending else field)

        return terms or ["created_at"]

    def get_assertion_for_relation(self, graph: models.Graph, edge_id: scalars.LocalID, info: Info | None = None) -> Optional[RetrievedAssertion]:
        """
        Get the Assertion that generated a relation edge.

        The assertion is connected via the ShadowLink:
        (Assertion)-[:GENERATED]->(ShadowLink) and the edge stores __shadow_link_id.

        Args:
            edge_id: The AGE edge ID

        Returns:
            RetrievedAssertion or None if not found
        """
        self._ensure_query_access(graph, info)

        # First, get the shadow_link_id stored on the edge
        edge_result = self.engine.execute(
            graph,
            """
            MATCH ()-[r]->() WHERE id(r) = $eid
            RETURN r.__shadow_link_id as sl_id
            """,
            {"eid": edge_id},
        )

        if not edge_result or not edge_result[0].get("sl_id"):
            raise ValueError(f"Edge {edge_id} does not have a shadow link ID.")

        shadow_link_id = edge_result[0]["sl_id"]

        # The assertion behind a relation lives in the evidence base now. Relations
        # themselves are rebuilt on `evidence_link` in M3, so until then there is
        # no link row to look through and this correctly returns None rather than
        # querying AGE for an Assertion vertex that no longer exists.
        link = (
            evidence_models.Link.objects.for_organization(graph.organization)
            .filter(
                kind=evidence_models.Link.Kind.RELATION,
                source_ref=f"{graph.age_name}:{shadow_link_id}",
            )
            .select_related("assertion")
            .first()
        )
        if link is None:
            return None

        return RetrievedAssertion.from_row(self, link.assertion, graph_name=graph.age_name)
