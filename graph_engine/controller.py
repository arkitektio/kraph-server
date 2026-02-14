import json
import time
import re
from typing import Optional, Dict, Any, List
from graph_engine import input_models
from graph_engine.input_models import (
    GraphDefinitionInput,
)
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
from core import models
from graph_engine import input_models as inputs
from graph_engine import vocab, scalars
from graph_engine.rollup import build_property_query


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
        self.engine = engine
        self.subject = subject
        self.app_id = app_id

    def create_universal_id(self) -> scalars.GlobalID:
        """Generates a unique reference ID for entities."""
        import uuid

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
            raise ValueError(f"No EntityCategory found for age_name '{age_name}' in graph {graph.id}")

        return category

    def ensure_entity(
        self,
        entity_category: models.EntityCategory,
        universal_id: scalars.GlobalID,
        payload: inputs.EntityInput,
    ) -> RetrievedEntity:
        raise NotImplementedError("Ensure entity is not implemented yet. Use create_entity for now.")

    def _create_provenance_node(self, graph: models.Graph, context: ProvenanceContext) -> scalars.LocalID:
        """
        Creates an Assertion node for provenance tracking and returns its internal graph ID.

        Args:
            graph: The graph to create the assertion in
            context: The provenance context with subject and app_id
        Returns:
            The internal graph ID of the created assertion node
        """
        query = f"""
            CREATE (a:{vocab.Assertion} {{subject: $subject, app_id: $app_id, timestamp: $timestamp}})
            RETURN id(a) as assertion_id
        """
        params = {
            "subject": context.subject,
            "app_id": context.app_id,
            "timestamp": int(time.time() * 1000),
        }
        result = self.engine.execute(graph, query, params)
        return scalars.LocalID(result[0]["assertion_id"])

    def create_entity(
        self,
        entity_category: models.EntityCategory,
        payload: inputs.EntityInput,
        context: ProvenanceContext,
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

        # --- Step 2: Create Assertion (Provenance) ---
        assertion_id = self._create_provenance_node(graph, context)

        # --- Step 3: Handle Evidence & Measurements ---
        for evidence in supporting_evidence:
            if graph.allow_auto_add_structure_definitions:
                scategory, _ = models.StructureCategory.objects.get_or_create(
                    graph=graph,
                    identifier=evidence.identifier,
                )
            else:
                scategory = models.StructureCategory.objects.filter(
                    graph=graph,
                    identifier=evidence.identifier,
                ).first()
                if not scategory:
                    raise ValueError(f"Structure identifier {evidence.identifier} not found in graph schema.")

            structure_vertex_name = scategory.get_age_vertex_name()

            # Auto-Create Structure (MERGE) - using 'object' as the external ID
            result = self.engine.execute(entity_category.graph, f"MERGE (s:{structure_vertex_name} {{object: $obj, identifier: $identifier, category: $sid}}) RETURN id(s) as sid", {"obj": evidence.object, "identifier": evidence.identifier, "sid": scategory.pk})
            structure_id = result[0]["sid"]

            # Create Metrics
            for meas in evidence.metrics:
                # meas is a MetricInput with key, value, and optional fields

                if graph.allow_auto_adding_metrics:
                    mcategory, _ = models.MetricCategory.objects.get_or_create(
                        graph=graph,
                        identifier=meas.key,
                        structure_category=scategory,
                    )
                else:
                    mcategory = models.MetricCategory.objects.filter(
                        graph=graph,
                        identifier=meas.key,
                        structure_category=scategory,
                    ).first()
                    if not mcategory:
                        raise ValueError(f"Metric identifier {meas.key} not found in graph schema for structure {evidence.identifier}.")

                params = {"sid": structure_id, "aid": assertion_id, "category": mcategory.pk, "key": meas.key, "value": meas.value, "unit": meas.unit, "confidence": meas.confidence, "confidence_type": meas.confidence_type, "timestamp": meas.timestamp}

                property_clauses = ", ".join([f"{k}: ${k}" for k in params.keys()])

                meas_query = f"""
                    MATCH (s:{structure_vertex_name}) WHERE id(s) = $sid
                    MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
                    
                    CREATE (m:{vocab.Metric} {{{property_clauses}}})
                    CREATE (a)-[:{vocab.ASSERTED}]->(m)
                    CREATE (m)-[:{vocab.DESCRIBES}]->(s)
                    RETURN id(m) as mid
                """
                self.engine.execute(entity_category.graph, meas_query, params)

        # --- Step 4: Create Entity (Shell) ---
        # We only set the immutable ID (db_id). All other props come from cache recalculation.
        ref_id = self.create_universal_id()
        e_params = {"eid": ref_id, "aid": assertion_id}

        create_res = self.engine.execute(
            entity_category.graph,
            f"""
            MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
            CREATE (e:{entity_category.age_name} {{id: $eid}})
            CREATE (a)-[:{vocab.GENERATED}]->(e)
            RETURN e as entity, id(e) as db_id
            """,
            e_params,
        )

        str(create_res[0]["db_id"])
        entity = create_res[0]["entity"]

        retrieved = RetrievedEntity.from_node(self, entity, graph_name=graph.age_name)

        # --- Step 5: Link Entity -> Evidence ---
        for evidence in supporting_evidence:
            evidence_identifier = evidence.identifier

            evidence_object = evidence.object
            self.engine.execute(
                entity_category.graph,
                f"""
                MATCH (e:{entity_category.age_name}) WHERE id(e) = $eid
                MATCH (s:{g_label} {{object: $obj}})
                MERGE (s)-[:{vocab.INFORMS}]->(e)
                """,
                {"eid": retrieved.local_id, "obj": evidence_object},
            )

        # --- Step 6: Recalculate Cached Properties ---
        # This is where the magic happens: Properties flow from Evidence -> Entity
        self._recalculate_entity(
            entity_category,
            retrieved.local_id,
        )

        return retrieved

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
        result = self.engine.execute(
            category.graph,
            f"""
            MATCH (s:{category.get_age_vertex_name()} {{object: $obj, category: $sid,  identifier: $identifier}})
            RETURN s, id(s) as sid
            """,
            {"obj": object, "sid": category.pk, "identifier": category.identifier},
        )

        if not result:
            raise ValueError(f"No structure found with object '{object}' in category '{category.identifier}'")
        raw = result[0]["s"]
        return RetrievedStructure.from_node(self, raw, graph_name=category.graph.age_name)

    def archive_entity(self, graph: models.Graph, local_id: scalars.LocalID, provenance: ProvenanceContext) -> scalars.LocalID:
        """
        Archives an entity by its composite ID.

        This performs a soft delete, setting the 'archived' flag and recording provenance.

        Args:
            graph: The graph to operate on
            entity_id: The composite ID of the entity to delete (e.g., "1-abc123-def456-...")
        """
        assertion_id = self._create_provenance_node(graph, provenance)
        archived_at = int(time.time() * 1000)

        self.engine.execute(
            graph,
            f"""
            MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
            MATCH (e) WHERE id(e) = $eid
            CREATE (lc:LifeCycleAssertion {{status: $status, archived_at: $archived_at, timestamp: $timestamp}})
            CREATE (a)-[:{vocab.ASSERTED}]->(lc)
            CREATE (lc)-[:{vocab.INFORMS}]->(e)
            RETURN id(lc) as lifecycle_id
            """,
            {
                "aid": assertion_id,
                "eid": local_id,
                "status": "archived",
                "archived_at": archived_at,
                "timestamp": archived_at,
            },
        )

        entity_category = self._get_entity_category_for_local_id(graph, local_id)
        self._recalculate_entity(entity_category, local_id)

        return local_id

    def _recalculate_entity(self, entity_category: models.EntityCategory, local_id: scalars.LocalID) -> None:
        """
        Scans schema rules and updates the Entity's cached properties based on connected evidence.

        Uses the rollup module to generate appropriate Cypher queries for each property's
        derivation type and aggregation function.
        """
        entity_def = entity_category

        updates: Dict[str, Any] = {}

        for prop_def in entity_def.defined_properties:
            # Skip the 'id' property - it's immutable
            if prop_def.key == "id":
                continue

            # Build the query using the rollup utilities
            rollup_query = build_property_query(entity_category.age_name, prop_def.key, prop_def)

            if rollup_query:
                # Add entity id to params
                params = {**rollup_query.params, "eid": local_id}

                result = self.engine.execute(entity_category.graph, rollup_query.query, params)

                if result and result[0].get("val") is not None:
                    updates[prop_def.key] = result[0]["val"]

        lifecycle_result = self.engine.execute(
            entity_category.graph,
            f"""
            MATCH (lc:LifeCycleAssertion)-[:{vocab.INFORMS}]->(e:{entity_category.age_name})
            WHERE id(e) = $eid
            RETURN lc.status as status
            ORDER BY coalesce(lc.archived_at, lc.timestamp, 0) DESC
            LIMIT 1
            """,
            {"eid": local_id},
        )

        updates["__lifecycle_state"] = lifecycle_result[0]["status"] if lifecycle_result else "active"
        updates["__measured__from"] = None  # Placeholder - real logic would determine the earliest timestamp from connected evidence and set this property
        updates["__measured__to"] = None  # Placeholder - real logic would determine the latest timestamp from connected evidence and set this property
        updates["__measured__at"] = None  # Placeholder - real logic would determine the timestamp of the measurement, if ONLY one piece of evidence is connected, and set this property

        # Add System Metadata
        updates["__schema_version"] = entity_category.schema_hash
        updates["__last_derived"] = int(time.time() * 1000)

        if updates:
            set_clause = ", ".join([f"e.{k} = $u_{k}" for k in updates.keys()])
            update_params = {f"u_{k}": v for k, v in updates.items()}
            update_params["local_id"] = local_id

            self.engine.execute(
                entity_category.graph,
                f"""
                MATCH (e:{entity_category.age_name}) WHERE id(e) = $local_id
                SET {set_clause}
                """,
                update_params,
            )

    # ===================================================================
    # MIGRATION METHODS
    # ===================================================================

    def _recalculate_relation(self, relation_category: models.RelationCategory, local_id: scalars.LocalID) -> Optional[scalars.LocalID]:
        """
        Updates Edge properties based on measurements connected via the ShadowLink.

        A relation can only exist once per direction between source and target.
        This method uses MERGE to ensure uniqueness.

        Returns:
            The edge ID of the created/updated relation edge
        """

        rel_def = relation_category.defined_properties
        # No materialization config - just create the edge without properties
        # Still store the shadow link id for provenance tracking

        result = self.engine.execute(
            relation_category.graph,
            f"""
            MATCH (sl:{vocab.ShadowLink}) WHERE id(sl) = $sl_id
            MATCH (sl)-[:{vocab.REIFIES_AS_SOURCE}]->(source)
            MATCH (sl)-[:{vocab.REIFIES_AS_TARGET}]->(target)
            MERGE (source)-[r:{relation_label}]->(target)
            SET r.__shadow_link_id = $sl_id
            RETURN id(r) as edge_id
            """,
            {"sl_id": shadow_link_id},
        )

        updates = {"__shadow_link_id": shadow_link_id}

        for prop_def in rel_def.materialization.properties:
            # Logic: (ShadowLink) <-[INFORMS]- (Structure) <-[DESCRIBES]- (Measurement)
            if prop_def.derivation == "ROLLUP" and prop_def.rule:
                rule = prop_def.rule

                agg_func = "avg"
                if rule.aggregation == "MAX":
                    agg_func = "max"
                elif rule.aggregation == "MIN":
                    agg_func = "min"
                elif rule.aggregation == "SUM":
                    agg_func = "sum"
                elif rule.aggregation == "COUNT":
                    agg_func = "count"

                target_var = "m" if rule.aggregation == "COUNT" else "m.value"

                query = f"""
                    MATCH (sl:{vocab.ShadowLink}) WHERE id(sl) = $sl_id
                    MATCH (sl)<-[:{vocab.INFORMS}]-(s)
                    MATCH (m:{vocab.Measurement})-[:{vocab.DESCRIBES}]->(s)
                    WHERE m.key = $key
                    RETURN {agg_func}({target_var}) as val
                """

                result = self.engine.execute(self.graph, query, {"sl_id": shadow_link_id, "key": rule.key or prop_def.key})

                if result and result[0]["val"] is not None:
                    updates[prop_def.key] = result[0]["val"]

        # Use MERGE to ensure the relation exists only once per direction
        # Then SET the aggregated properties
        if updates:
            set_clause = ", ".join([f"r.{k} = $u_{k}" for k in updates.keys()])
            update_params = {f"u_{k}": v for k, v in updates.items()}
            update_params["sl_id"] = shadow_link_id

            result = self.engine.execute(
                self.graph,
                f"""
                MATCH (sl:{vocab.ShadowLink}) WHERE id(sl) = $sl_id
                MATCH (sl)-[:{vocab.REIFIES_AS_SOURCE}]->(source)
                MATCH (sl)-[:{vocab.REIFIES_AS_TARGET}]->(target)
                MERGE (source)-[r:{relation_label}]->(target)
                SET {set_clause}
                RETURN id(r) as edge_id
                """,
                update_params,
            )
            return result[0]["edge_id"] if result else None
        else:
            # No properties to set, just ensure the edge exists
            result = self.engine.execute(
                self.graph,
                f"""
                MATCH (sl:{vocab.ShadowLink}) WHERE id(sl) = $sl_id
                MATCH (sl)-[:{vocab.REIFIES_AS_SOURCE}]->(source)
                MATCH (sl)-[:{vocab.REIFIES_AS_TARGET}]->(target)
                MERGE (source)-[r:{relation_label}]->(target)
                RETURN id(r) as edge_id
                """,
                {"sl_id": shadow_link_id},
            )
            return result[0]["edge_id"] if result else None

    def list_entities_informed_by_structure(self, graph: models.Graph, structure_id: scalars.LocalID) -> List[RetrievedEntity]:
        """
        Lists all entities that are informed by a given structure.

        Args:
            graph: The graph to query
            structure_id: The internal graph ID of the structure node

        Returns:
            List of RetrievedEntity objects that are informed by the structure
        """
        query = f"""
            MATCH (s)-[:{vocab.INFORMS}]->(e)
            WHERE id(s) = $sid
            RETURN e, labels(e) as lbls
        """
        result = self.engine.execute(graph, query, {"sid": structure_id})

        entities = []
        for row in result:
            raw = row["e"]
            entities.append(RetrievedEntity.from_node(self, raw, graph_name=graph.age_name))

        return entities

    def get_node(self, graph: models.Graph, local_id: scalars.LocalID) -> retrieved.RetrievedNode:
        """
        Retrieve a raw node by its string ID.

        This is a low-level method that returns the raw graph data without
        any schema-based processing or migration. It can be used for debugging
        or for operations that need direct access to the underlying graph.

        Args:
            graph: The graph to query
            local_id: The internal graph ID of the node to retrieve
        """

        query = """
            MATCH (n) WHERE id(n) = $id
            RETURN n, labels(n) as lbls
        """
        result = self.engine.execute(graph, query, {"id": local_id})

        if not result:
            raise ValueError(f"Node not found with ID {local_id}")

        raw_node = result[0]["n"]

        return RetrievedNode.from_node(self, raw_node, graph_name=graph.age_name)

    def get_node_by_local_id(self, graph: models.Graph, local_id: scalars.LocalID) -> retrieved.RetrievedNode:
        """Retrieve a raw node by its internal AGE graph ID."""
        query = """
            MATCH (n) WHERE id(n) = $nid
            RETURN n
        """
        result = self.engine.execute(graph, query, {"nid": local_id})

        if not result:
            raise ValueError(f"Node not found with local ID {local_id}")

        raw_node = result[0]["n"]
        return RetrievedNode.from_node(self, raw_node, graph_name=graph.age_name)

    def get_node_for_composite_id(self, composite_id: scalars.GraphID) -> retrieved.RetrievedNode:
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

        return self.get_node(graph, entity_id)

    def get_entity(
        self,
        entity_category: models.EntityCategory,
        id: str,
        auto_migrate: bool = True,
    ) -> retrieved.RetrievedEntity:
        """
        Retrieves an Entity by ID.
        Dynamically detects the 'kind' from the Node Labels and returns
        a RetrievedEntity with the raw graph data.

        If the entity's schema version doesn't match the current schema,
        and auto_migrate is True, the entity will be migrated automatically.

        Args:
            id: The entity's unique string ID
            entity_category: The entity category (used to access the graph and schema)
            auto_migrate: Whether to auto-migrate if schema version mismatch

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
        entity = RetrievedEntity.from_node(self, normalized_node, graph_name=graph.age_name)

        if entity.schema_hash != entity_category.schema_hash and auto_migrate:
            # Perform migration
            self._migrate_entity(entity, entity_category)

            # Refetch the node after migration to get updated properties
            return self.get_entity(entity_category, id, auto_migrate=False)

        return entity

    def get_structure(
        self,
        graph: models.Graph,
        identifier: str,
        object: str,
    ) -> retrieved.RetrievedStructure:
        """
        Retrieves a Structure by identifier and object.

        Args:
            graph: The graph to query
            identifier: Schema identifier (e.g. '@mikro/roi')
            object: Object ID of the structure
        """
        try:
            scat = models.StructureCategory.objects.get(graph=graph, identifier=identifier)
        except models.StructureCategory.DoesNotExist:
            raise ValueError(f"Structure not found with identifier {identifier} and object {object}")

        query = f"""
            MATCH (s:{scat.get_age_vertex_name()} {{object: $obj}})
            RETURN s, labels(s) as lbls
        """
        result = self.engine.execute(graph, query, {"obj": object})

        if not result:
            raise ValueError(f"Structure not found with identifier {identifier} and object {object}")

        raw = result[0]["s"]
        return retrieved.RetrievedStructure.from_node(self, raw, graph_name=graph.age_name)

    def get_informing_structures(
        self,
        graph: models.Graph,
        entity_id: str,
    ) -> List[retrieved.RetrievedStructure]:
        """
        Gets all structures that INFORM a given entity.

        Args:
            graph: The graph to query
            entity_id: The entity's string ID
        """
        query = f"""
            MATCH (s)-[:{vocab.INFORMS}]->(e)
            WHERE e.id = $eid
            RETURN s
        """
        result = self.engine.execute(graph, query, {"eid": entity_id})

        structures = []
        for row in result:
            raw = row["s"]

            structures.append(retrieved.RetrievedStructure.from_node(self, raw, graph_name=graph.age_name))

        return structures

    def get_entities_informed_by(
        self,
        graph: models.Graph,
        identifier: str,
        structure_object: str,
    ) -> List[retrieved.RetrievedEntity]:
        """
        Gets all entities that are informed by a given structure.
        """
        structure_label = get_label_for_identifier(identifier)

        query = f"""
            MATCH (s:{structure_label} {{object: $obj}})-[:{vocab.INFORMS}]->(e)
            RETURN e, labels(e) as lbls
        """
        result = self.engine.execute(graph, query, {"obj": structure_object})

        entities = []
        for row in result:
            raw = row["e"]
            entities.append(RetrievedEntity.from_node(self, raw, graph_name=graph.age_name))

        return entities

    def get_metrics_for_structure(
        self,
        graph: models.Graph,
        identifier: str,
        structure_object: str,
    ) -> List[RetrievedMetric]:
        """
        Gets all measurements that describe a given structure.

        Args:
            graph: The graph to query
            identifier: Schema identifier (e.g. '@mikro/roi')
            structure_object: Object ID of the structure
        """
        structure_label = get_label_for_identifier(identifier)

        query = f"""
            MATCH (m:{vocab.Metric})-[:{vocab.DESCRIBES}]->(s:{structure_label} {{object: $obj}})
            RETURN m
        """
        result = self.engine.execute(graph, query, {"obj": structure_object})

        measurements = []
        for row in result:
            raw = row["m"]
            measurements.append(RetrievedMetric.from_node(self, raw, graph_name=graph.age_name))

        return measurements

    def get_assertion_for_entity(
        self,
        graph: models.Graph,
        entity_id: str,
    ) -> Optional[RetrievedAssertion]:
        """
        Gets the assertion that generated a given entity.

        Args:
            graph: The graph to query
            entity_id: The entity's string ID
        """
        query = f"""
            MATCH (a:{vocab.Assertion})-[:{vocab.GENERATED}]->(e)
            WHERE e.id = $eid
            RETURN a, id(a) as aid
        """
        result = self.engine.execute(graph, query, {"eid": entity_id})

        if not result:
            return None

        raw = result[0]["a"]
        return RetrievedAssertion.from_node(self, raw, graph_name=graph.age_name)

    def get_metrics_for_assertion(
        self,
        graph: models.Graph,
        assertion_id: scalars.LocalID,
    ) -> List[RetrievedMetric]:
        """
        Gets all measurements asserted by a given assertion.

        Args:
            graph: The graph to query
            assertion_id: The internal graph ID of the assertion
        """
        query = f"""
            MATCH (a:{vocab.Assertion})-[:{vocab.ASSERTED}]->(m:{vocab.Metric})
            WHERE id(a) = $aid
            RETURN m
        """
        result = self.engine.execute(graph, query, {"aid": assertion_id})

        measurements = []
        for row in result:
            raw = row["m"]
            measurements.append(RetrievedMetric.from_node(self, raw, graph_name=graph.age_name))

        return measurements

    def create_structure(
        self,
        structure_category: models.StructureCategory,
        payload: inputs.StructureInput,
    ) -> RetrievedStructure:
        """
        Create a new structure node.

        Args:
            graph: The graph to create the structure in
            identifier: Schema identifier (e.g. '@mikro/roi')
            object: Unique ID of the object this structure references

        Returns:
            RetrievedStructure with the created structure info
        """
        structure_label = structure_category.get_age_vertex_name()
        graph = structure_category.graph

        # MERGE to create or match existing, return the graph id
        result = self.engine.execute(
            graph,
            f"""
            MERGE (s:{structure_label} {{object: $obj}})
            SET s.identifier = coalesce(s.identifier, $identifier)
            RETURN s
            """,
            {"obj": payload.object, "identifier": structure_category.identifier},
        )
        created_node = result[0]["s"]
        return RetrievedStructure.from_node(
            self,
            created_node,
            graph_name=graph.age_name,
        )

    def delete_structure(
        self,
        graph: models.Graph,
        structure_id: scalars.LocalID,
        provenance: ProvenanceContext,
    ) -> scalars.LocalID:
        """Hard delete a structure node and all attached relationships."""
        self.engine.execute(
            graph,
            """
            MATCH (s) WHERE id(s) = $sid
            DETACH DELETE s
            """,
            {"sid": structure_id},
        )
        return structure_id

    def archive_structure(
        self,
        graph: models.Graph,
        structure_id: scalars.LocalID,
        provenance: ProvenanceContext,
    ) -> RetrievedStructure:
        """Archive a structure by attaching a lifecycle assertion and setting lifecycle state."""
        assertion_id = self._create_provenance_node(graph, provenance)
        archived_at = int(time.time() * 1000)

        self.engine.execute(
            graph,
            f"""
            MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
            MATCH (s) WHERE id(s) = $sid
            CREATE (lc:LifeCycleAssertion {{status: $status, archived_at: $archived_at, timestamp: $timestamp}})
            CREATE (a)-[:{vocab.ASSERTED}]->(lc)
            CREATE (lc)-[:{vocab.INFORMS}]->(s)
            RETURN id(lc) as lifecycle_id
            """,
            {
                "aid": assertion_id,
                "sid": structure_id,
                "status": "archived",
                "archived_at": archived_at,
                "timestamp": archived_at,
            },
        )

        x = self.engine.execute(
            graph,
            """
            MATCH (lc:LifeCycleAssertion)-[:INFORMS]->(s)
            WHERE id(s) = $sid
            WITH s, lc
            ORDER BY coalesce(lc.archived_at, lc.timestamp, 0) DESC
            WITH s, collect(lc)[0] as latest
            SET s.__lifecycle_state = latest.status
            RETURN s
            """,
            {"sid": structure_id},
        )
        archived_node = x[0]["s"]

        return retrieved.RetrievedStructure.from_node(
            self,
            archived_node,
            graph_name=graph.age_name,
        )

    def update_structure(
        self,
        graph: models.Graph,
        structure_id: scalars.LocalID,
        payload: inputs.StructureInput,
        provenance: ProvenanceContext,
    ) -> retrieved.RetrievedStructure:
        """Update a structure in-place and optionally append new metrics."""
        node = self.get_node_by_local_id(graph, local_id=structure_id)
        label = node.label

        x = self.engine.execute(
            graph,
            f"""
            MATCH (s:{label}) WHERE id(s) = $sid
            SET s.object = $obj
            RETURN s
            """,
            {"sid": structure_id, "obj": payload.object},
        )

        for metric in payload.metrics or []:
            self.create_metric(
                graph,
                structure_id=structure_id,
                input=metric,
                provenance=provenance,
            )

        node = x[0]["s"]
        return RetrievedStructure.from_node(
            self,
            node=node,
            graph_name=graph.age_name,
        )

    def create_natural_event(
        self,
        category: models.NaturalEventCategory,
        payload: inputs.NaturalEventInput,
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

        # --- Step 1: Create Assertion (Provenance) ---
        prov_dict: Dict[str, Any] = {"subject": self.subject, "app_id": self.app_id}
        assertion_props = ", ".join([f"{k}: ${k}" for k in prov_dict.keys()])
        aid_res = self.engine.execute(graph, f"CREATE (a:{vocab.Assertion} {{{assertion_props}}}) RETURN id(a) as aid", prov_dict)
        assertion_id = aid_res[0]["aid"]

        # Assertion Created but not linked to anything yet - we will link evidence and event after we create them

        # --- Step 2: Handle Evidence & Measurements ---
        for evidence in supporting_evidence:
            if graph.allow_auto_add_structure_definitions:
                scategory, _ = models.StructureCategory.objects.get_or_create(
                    graph=graph,
                    identifier=evidence.identifier,
                )
            else:
                scategory = models.StructureCategory.objects.filter(
                    graph=graph,
                    identifier=evidence.identifier,
                ).first()
                if not scategory:
                    raise ValueError(f"Structure identifier {evidence.identifier} not found in graph schema.")

            structure_vertex_name = scategory.get_age_vertex_name()

            # Auto-Create Structure (MERGE) - using 'object' as the external ID
            result = self.engine.execute(graph, f"MERGE (s:{structure_vertex_name} {{object: $obj, identifier: $identifier, category: $sid}}) RETURN id(s) as sid", {"obj": evidence.object, "identifier": evidence.identifier, "sid": scategory.pk})
            structure_id = result[0]["sid"]

            # Create Metrics
            for meas in evidence.metrics:
                # meas is a MetricInput with key, value, and optional fields

                if graph.allow_auto_adding_metrics:
                    mcategory, _ = models.MetricCategory.objects.get_or_create(
                        graph=graph,
                        identifier=meas.key,
                        structure_category=scategory,
                    )
                else:
                    mcategory = models.MetricCategory.objects.filter(
                        graph=graph,
                        identifier=meas.key,
                        structure_category=scategory,
                    ).first()
                    if not mcategory:
                        raise ValueError(f"Metric identifier {meas.key} not found in graph schema for structure {evidence.identifier}.")

                params = {"sid": structure_id, "aid": assertion_id, "category": mcategory.pk, "key": meas.key, "value": meas.value, "unit": meas.unit, "confidence": meas.confidence, "confidence_type": meas.confidence_type, "timestamp": meas.timestamp}

                property_clauses = ", ".join([f"{k}: ${k}" for k in params.keys()])

                meas_query = f"""
                    MATCH (s:{structure_vertex_name}) WHERE id(s) = $sid
                    MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
                    
                    CREATE (m:{vocab.Metric} {{{property_clauses}}})
                    CREATE (a)-[:{vocab.ASSERTED}]->(m)
                    CREATE (m)-[:{vocab.DESCRIBES}]->(s)
                    RETURN id(m) as mid
                """
                self.engine.execute(graph, meas_query, params)

                # We have created the metric and linked it to the structure and assertion, so when we later link the structure to the event, the metric will inform the event's properties through the rollup mechanism.

        # --- Step 4: Create Entity (Shell) ---
        # We only set the immutable ID (db_id). All other props come from cache recalculation.
        e_params = {"eid": self.create_universal_id(), "aid": assertion_id}

        event_vertex_name = category.get_age_vertex_name()

        create_res = self.engine.execute(
            graph,
            f"""
            MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
            CREATE (e:{event_vertex_name} {{id: $eid}})
            CREATE (a)-[:{vocab.GENERATED}]->(e)
            RETURN id(e) as event_id
            """,
            e_params,
        )

        event_id = create_res[0]["event_id"]

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

        # --- Step 6: Recalculate Cached Properties ---

        # This is where the magic happens: Properties flow from Evidence -> Entity
        return self.get_event_by_graph_id(graph, event_id)

    def create_metric(
        self,
        graph: models.Graph,
        structure_id: scalars.LocalID,
        input: MetricInput,
        provenance: "ProvenanceContext",
    ) -> RetrievedMetric:
        """
        Add a measurement to an existing structure.

        Args:
            graph: The graph to add the measurement to
            structure_id: Internal graph ID of the structure node
            input: The measurement data
            provenance: Provenance context for this measurement

        Returns:
            RetrievedMetric with the created measurement info
        """
        structure_result = self.engine.execute(
            graph,
            """
            MATCH (s) WHERE id(s) = $sid
            RETURN s
            """,
            {"sid": structure_id},
        )
        if not structure_result:
            raise ValueError(f"Structure not found with node ID {structure_id}")

        effective_provenance = self._effective_provenance(provenance)
        assertion_id = self._create_provenance_node(graph, effective_provenance)

        metric_props: Dict[str, Any] = {
            "key": input.key,
            "value": input.value,
        }
        for optional_key in ["unit", "confidence", "confidence_type", "timestamp"]:
            val = getattr(input, optional_key, None)
            if val is not None:
                metric_props[optional_key] = val

        metric_params = {**metric_props, "sid": structure_id, "aid": assertion_id}

        prop_clauses = ["key: $key", "value: $value"]
        for optional_key in ["unit", "confidence", "confidence_type", "timestamp"]:
            if optional_key in metric_props:
                prop_clauses.append(f"{optional_key}: ${optional_key}")

        metric_query = f"""
            MATCH (s) WHERE id(s) = $sid
            MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
            CREATE (m:{vocab.Metric} {{{", ".join(prop_clauses)}}})
            CREATE (a)-[:{vocab.ASSERTED}]->(m)
            CREATE (m)-[:{vocab.DESCRIBES}]->(s)
            RETURN id(m) as mid
        """
        result = self.engine.execute(graph, metric_query, metric_params)
        graph_id = result[0]["mid"]
        raw_metric = self.engine.execute(
            graph,
            """
            MATCH (m) WHERE id(m) = $mid
            RETURN m
            """,
            {"mid": graph_id},
        )
        if raw_metric:
            return RetrievedMetric.from_node(self, raw_metric[0]["m"], graph_name=graph.age_name)

        return RetrievedMetric.from_node(
            self,
            {
                "id": graph_id,
                "label": vocab.Metric,
                "properties": metric_props,
            },
            graph_name=graph.age_name,
        )

    def _effective_provenance(self, provenance: ProvenanceContext | None = None) -> ProvenanceContext:
        if provenance is not None:
            return provenance
        return ProvenanceContext(
            subject=self.subject or "unknown",
            app_id=self.app_id or "unknown",
        )

    def _recalculate_metric_lifecycle_state(
        self,
        graph: models.Graph,
        metric_id: scalars.LocalID,
    ) -> None:
        self.engine.execute(
            graph,
            """
            MATCH (m) WHERE id(m) = $mid
            OPTIONAL MATCH (lc:LifeCycleAssertion)-[:INFORMS]->(m)
            WITH m, lc
            ORDER BY coalesce(lc.archived_at, lc.timestamp, 0) DESC
            WITH m, collect(lc)[0] as latest
            SET m.__lifecycle_state = coalesce(latest.status, m.__lifecycle_state)
            RETURN m
            """,
            {"mid": metric_id},
        )

    def archive_metric(
        self,
        graph: models.Graph,
        metric_id: scalars.LocalID,
        provenance: ProvenanceContext | None = None,
    ) -> scalars.LocalID:
        metric_result = self.engine.execute(
            graph,
            """
            MATCH (m) WHERE id(m) = $mid
            RETURN m
            """,
            {"mid": metric_id},
        )
        if not metric_result:
            raise ValueError(f"Metric not found with node ID {metric_id}")

        assertion_id = self._create_provenance_node(graph, self._effective_provenance(provenance))
        archived_at = int(time.time() * 1000)

        self.engine.execute(
            graph,
            f"""
            MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
            MATCH (m:{vocab.Metric}) WHERE id(m) = $mid
            CREATE (lc:LifeCycleAssertion {{status: $status, archived_at: $archived_at, timestamp: $timestamp}})
            CREATE (a)-[:{vocab.ASSERTED}]->(lc)
            CREATE (lc)-[:{vocab.INFORMS}]->(m)
            RETURN id(lc) as lifecycle_id
            """,
            {
                "aid": assertion_id,
                "mid": metric_id,
                "status": "archived",
                "archived_at": archived_at,
                "timestamp": archived_at,
            },
        )

        self._recalculate_metric_lifecycle_state(graph, metric_id)
        return metric_id

    def delete_metric(
        self,
        graph: models.Graph,
        metric_id: scalars.LocalID,
        provenance: ProvenanceContext | None = None,
    ) -> scalars.LocalID:
        metric_result = self.engine.execute(
            graph,
            """
            MATCH (m) WHERE id(m) = $mid
            RETURN m
            """,
            {"mid": metric_id},
        )
        if not metric_result:
            raise ValueError(f"Metric not found with node ID {metric_id}")

        self.engine.execute(
            graph,
            """
            MATCH (m) WHERE id(m) = $mid
            DETACH DELETE m
            """,
            {"mid": metric_id},
        )

        return metric_id

    def update_metric(
        self,
        graph: models.Graph,
        payload: inputs.UpdateMetricInput,
        provenance: ProvenanceContext,
    ) -> RetrievedMetric:
        metric_local_id = extract_node_id(payload.id)

        result = self.engine.execute(
            graph,
            f"""
            MATCH (m:{vocab.Metric})-[:{vocab.DESCRIBES}]->(s)
            WHERE id(m) = $mid
            RETURN id(s) as sid
            """,
            {"mid": metric_local_id},
        )
        if not result:
            raise ValueError(f"Metric not found with node ID {payload.id}")

        structure_id = scalars.LocalID(result[0]["sid"])
        self.archive_metric(graph, metric_id=metric_local_id, provenance=provenance)

        metric_input = MetricInput(
            key=payload.key,
            value=payload.value,
            confidence=payload.confidence,
            confidence_type=payload.confidence_type,
            unit=payload.unit,
            timestamp=payload.timestamp,
        )

        return self.create_metric(
            graph,
            structure_id=structure_id,
            input=metric_input,
            provenance=provenance,
        )

    def link_structure_to_entity(
        self,
        structure_identifier: str,
        structure_object: str,
        entity_id: str,
        recalculate: bool = True,
    ) -> RetrievedInforms:
        """
        Link an existing structure to an existing entity.

        This creates an INFORMS relationship from the structure to the entity,
        allowing the structure's measurements to contribute to the entity's
        derived properties.

        Args:
            structure_identifier: Schema identifier of the structure (e.g. '@mikro/roi')
            structure_object: Object ID of the structure
            entity_id: The string ID of the entity to link to
            recalculate: Whether to recalculate entity properties after linking (default True)
            schema: Optional schema to use for recalculation

        Returns:
            RetrievedEntity with the updated entity info
        """
        effective_schema = schema or self.graph.definition
        structure_label = get_label_for_identifier(structure_identifier)

        # First, get the entity to find its graph_id and kind
        entity = self.get_entity(entity_id, schema=effective_schema)

        # Create the INFORMS relationship
        self.engine.execute(
            self.graph,
            f"""
            MATCH (s:{structure_label} {{object: $obj}})
            MATCH (e) WHERE e.id = $eid
            MERGE (s)-[:{vocab.INFORMS}]->(e)
            """,
            {"obj": structure_object, "eid": entity_id},
        )

        # Recalculate entity properties if requested
        if recalculate:
            self._recalculate_entity(entity.local_id, entity.kind, effective_schema)

        # Return the updated entity
        return self.get_entity(entity_id, schema=effective_schema)

    def create_relation(
        self,
        category: models.RelationCategory,
        payload: RelationInput,
        provenance: ProvenanceContext,
    ) -> RetrievedRelation:
        """
        Creates a Relationship between two nodes, backed by Evidence.

        Graph Structure Created:
        1. (Source)-[RELATION]->(Target)  <-- The actual edge
        2. (ShadowLink)                   <-- The reified node holding history
        3. (ShadowLink)-[:REIFIES]->(Source)
        4. (ShadowLink)-[:REIFIES]->(Target)
        5. (Structure)-[:INFORMS]->(ShadowLink) <-- Evidence attached here
        """

        assertion_id = self._create_provenance_node(category.graph, provenance)
        # --- Step 3: Create Shadow Link & Attach Evidence ---
        # We create a "ShadowLink" node to represent this specific instance of the relationship.
        # This allows us to attach measurements to "the link" rather than the edge itself.

        ref_id = self.create_universal_id()

        shadow_params = {"link_id": ref_id, "aid": assertion_id}

        # TODO: Check if a relation already exists between these nodes in this direction, and if so,
        # either prevent creation or create a new ShadowLink and overwrite the existing edge to point to the new ShadowLink.
        # This allows us to maintain history of changes to the relationship over time, while still enforcing that only one "active"
        # relationship exists between any two nodes in a given direction.
        shadow_res = self.engine.execute(
            category.graph,
            f"""
            MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
            MERGE (sl:{vocab.ShadowLink} {{id: $link_id, ref_id: $link_id}})
            CREATE (a)-[:{vocab.GENERATED}]->(sl)
            RETURN id(sl) as shadow_graph_id
            """,
            shadow_params,
        )
        shadow_graph_id = shadow_res[0]["shadow_graph_id"]

        # Process Evidence attached to the Shadow Link
        for evidence in payload.supporting_evidence:
            structure_graph_label = get_label_for_identifier(evidence.identifier)

            # Auto-Create Structure
            self.engine.execute(category.graph, f"MERGE (s:{structure_graph_label} {{object: $obj}})", {"obj": evidence.object})

            # Link Structure -> Shadow Link (INFORMS)
            # This says: "This structure (e.g. ROI Overlap) informs this relationship"
            self.engine.execute(
                category.graph,
                f"""
                MATCH (s:{structure_graph_label} {{object: $obj}})
                MATCH (sl:{vocab.ShadowLink}) WHERE id(sl) = $sl_id
                MERGE (s)-[:{vocab.INFORMS}]->(sl)
                """,
                {"obj": evidence.object, "sl_id": shadow_graph_id},
            )

            # Create Measurements for that Structure
            for meas in evidence.metrics:
                meas_params = meas.model_dump(exclude_none=True)
                meas_params.update({"obj": evidence.object, "aid": assertion_id})

                prop_clauses = ["key: $key", "value: $value"]
                for optional_key in ["unit", "confidence", "confidence_type", "timestamp"]:
                    if optional_key in meas_params:
                        prop_clauses.append(f"{optional_key}: ${optional_key}")

                meas_query = f"""
                    MATCH (s:{structure_graph_label} {{object: $obj}})
                    MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
                    
                    CREATE (m:{vocab.Metric} {{{", ".join(prop_clauses)}}})
                    CREATE (a)-[:{vocab.ASSERTED}]->(m)
                    CREATE (m)-[:{vocab.DESCRIBES}]->(s)
                """
                self.engine.execute(category.graph, meas_query, meas_params)

        # --- Step 4: Create the Physical Edge ---
        edge_params = {"src": payload.source_id, "tgt": payload.target_id, "aid": assertion_id, "sl_id": shadow_graph_id}

        # Note: AGE doesn't allow creating relationships TO relationships,
        # so we connect the assertion to the ShadowLink instead.
        # The ShadowLink already has (Assertion)-[:GENERATED]->(ShadowLink)
        create_shadow_links = self.engine.execute(
            category.graph,
            f"""
            MATCH (source) WHERE source.id = $src
            MATCH (target) WHERE target.id = $tgt
            MATCH (sl:{vocab.ShadowLink}) WHERE id(sl) = $sl_id
            MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid

            
            // Connect Shadow Link to nodes for traversability
            CREATE (sl)-[:{vocab.REIFIES_AS_SOURCE}]->(source)
            CREATE (sl)-[:{vocab.REIFIES_AS_TARGET}]->(target)
            
            RETURN id(sl) as shadow_id
            """,
            edge_params,
        )

        if not create_shadow_links:
            raise ValueError(f"Could not create relation. Source {payload.source_id} or Target {payload.target_id} not found.")

        shadow_link_id = create_shadow_links[0]["shadow_id"]

        # --- Step 5: Recalculate Relation Properties ---
        # Rolls up values from the ShadowLink evidence onto the Edge itself
        edge_id = self._recalculate_relation(relation_category=category, local_id=shadow_link_id)

        if edge_id is None:
            raise ValueError(f"Failed to create relation edge for {relation_name}")

        return EntityCreationResult(ref_id=payload.ref_id, db_id=f"{payload.source_id}->{payload.target_id}", graph_id=edge_id)

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

    def render_graph_nodes_query(self, graph_query: models.GraphNodesQuery, filters: input_models.RenderGraphNodesFilter | None = None, pagination: input_models.RenderGraphNodesPagination | None = None, order: input_models.RenderGraphNodesOrder | None = None) -> RetrievedGraphNodesRender:
        """Render a set of nodes matching the graph query, with optional filters, pagination, and ordering."""
        raise Exception("Not implemented yet")

    def render_graph_path_query(self, graph_query: models.GraphPathQuery, filters: input_models.RenderGraphPathFilter | None = None, pagination: input_models.RenderGraphPathPagination | None = None, order: input_models.RenderGraphPathOrder | None = None) -> RetrievedGraphPathRender:
        """Render a set of nodes matching the graph query, with optional filters, pagination, and ordering."""
        raise Exception("Not implemented yet")

    def render_graph_table_query(self, graph_query: models.GraphTableQuery, filters: input_models.RenderGraphTableFilter | None = None, pagination: input_models.RenderGraphTablePagination | None = None, order: input_models.RenderGraphTableOrder | None = None) -> RetrievedGraphTableRender:
        """Render a set of nodes matching the graph query, with optional filters, pagination, and ordering."""
        raise Exception("Not implemented yet")

    def _validate_property_key(self, key: str) -> str:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            raise ValueError(f"Invalid property key '{key}'.")
        return key

    def _build_entity_where_clause(self, filters: input_models.EntityFilters | None, variable: str = "e") -> tuple[str, dict[str, Any]]:
        params: dict[str, Any] = {}
        clauses: list[str] = []

        if not filters:
            return "", params

        operator = (filters.operator or "EQUALS").upper()
        key = filters.key
        value = filters.value

        if key == "id":
            field_expr = f"id({variable})"
        else:
            validated_key = self._validate_property_key(key)
            field_expr = f"{variable}.{validated_key}"

        params["filter_value"] = value

        if operator in {"EQUALS", "EQ", "="}:
            clauses.append(f"{field_expr} = $filter_value")
        elif operator in {"NOT_EQUALS", "NEQ", "!="}:
            clauses.append(f"{field_expr} <> $filter_value")
        elif operator in {"GREATER_THAN", "GT", ">"}:
            clauses.append(f"{field_expr} > $filter_value")
        elif operator in {"LESS_THAN", "LT", "<"}:
            clauses.append(f"{field_expr} < $filter_value")
        elif operator in {"GREATER_OR_EQUAL", "GREATER_THAN_OR_EQUAL", "GTE", ">="}:
            clauses.append(f"{field_expr} >= $filter_value")
        elif operator in {"LESS_OR_EQUAL", "LESS_THAN_OR_EQUAL", "LTE", "<="}:
            clauses.append(f"{field_expr} <= $filter_value")
        elif operator == "CONTAINS":
            clauses.append(f"{field_expr} CONTAINS $filter_value")
        elif operator == "STARTS_WITH":
            clauses.append(f"{field_expr} STARTS WITH $filter_value")
        elif operator == "ENDS_WITH":
            clauses.append(f"{field_expr} ENDS WITH $filter_value")
        elif operator == "IN":
            clauses.append(f"{field_expr} IN $filter_value")
        elif operator == "NOT_IN":
            clauses.append(f"NOT {field_expr} IN $filter_value")
        else:
            raise ValueError(f"Unsupported filter operator '{filters.operator}'.")

        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    def _build_entity_order_clause(self, order: input_models.EntityOrder | None, variable: str = "e") -> str:
        if not order:
            return ""

        key = self._validate_property_key(order.key)
        direction = (order.direction or "asc").upper()
        if direction not in {"ASC", "DESC"}:
            raise ValueError("Order direction must be 'asc' or 'desc'.")

        return f"ORDER BY {variable}.{key} {direction}"

    def _build_entity_pagination_clause(self, pagination: input_models.EntityPagination | None) -> str:
        if not pagination:
            return "SKIP 0 LIMIT 200"

        offset = pagination.offset if pagination.offset is not None else 0
        limit = pagination.limit if pagination.limit is not None else 200
        return f"SKIP {offset} LIMIT {limit}"

    def list_entities(self, graph: models.Graph, filters: input_models.EntityFilters | None = None, pagination: input_models.EntityPagination | None = None, order: input_models.EntityOrder | None = None) -> List[RetrievedEntity]:
        entity_labels = list(models.EntityCategory.objects.filter(graph=graph).values_list("age_name", flat=True))
        if not entity_labels:
            return []

        where_clause, filter_params = self._build_entity_where_clause(filters, variable="e")
        order_clause = self._build_entity_order_clause(order, variable="e")
        pagination_clause = self._build_entity_pagination_clause(pagination)

        query = f"""
            MATCH (e)
            WHERE any(lbl IN labels(e) WHERE lbl IN $entity_labels)
            {("AND " + where_clause[len("WHERE ") :]) if where_clause else ""}
            RETURN e
            {order_clause}
            {pagination_clause}
        """

        params: dict[str, Any] = {"entity_labels": entity_labels, **filter_params}
        result = self.engine.execute(graph, query, params)

        return [RetrievedEntity.from_node(self, row["e"], graph_name=graph.age_name) for row in result]

    def get_assertion_for_relation(self, graph: models.Graph, edge_id: scalars.LocalID) -> Optional[RetrievedAssertion]:
        """
        Get the Assertion that generated a relation edge.

        The assertion is connected via the ShadowLink:
        (Assertion)-[:GENERATED]->(ShadowLink) and the edge stores __shadow_link_id.

        Args:
            edge_id: The AGE edge ID

        Returns:
            RetrievedAssertion or None if not found
        """
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

        # Now get the assertion that GENERATED the ShadowLink
        result = self.engine.execute(
            graph,
            f"""
            MATCH (a:{vocab.Assertion})-[:{vocab.GENERATED}]->(sl:{vocab.ShadowLink})
            WHERE id(sl) = $sl_id
            RETURN a, id(a) as graph_id
            """,
            {"sl_id": shadow_link_id},
        )

        if not result:
            return None

        row = result[0]
        return RetrievedAssertion.from_node(self, row["a"], graph_name=graph.age_name)
