import json
import time
from typing import Optional, Dict, Any, List
from graph_engine.base_models import GraphDefinitionModel
from graph_engine.input_models import (
    EntityCreationResult,
    MeasurementInput,
    ProvenanceContext,
    RelationCreationPayload,
)
from graph_engine.engine.protocol import CypherEngine, GraphProtocol
from graph_engine.retrieved import (
    RetrievedNode,
    RetrievedEdge,
    RetrievedEntity,
    RetrievedStructure,
    RetrievedMeasurement,
    RetrievedAssertion,
)
from graph_engine import vocab
from graph_engine.rollup import build_property_query

IDENTIFIER_MAP = {
    "@mikro/roi": "ROI",
    "told_you_so": "ToldYouSo",
    "default": "Structure"
}


def _extract_props(raw_node: Any) -> Dict[str, Any]:
    """Extract properties from an AGE node, handling both dict and nested formats."""
    if isinstance(raw_node, dict):
        if 'properties' in raw_node:
            return raw_node['properties']
        return raw_node
    return {}

def _extract_id(raw_node: Any) -> int:
    """Extract the internal graph ID from an AGE node representation."""
    if isinstance(raw_node, dict) and 'id' in raw_node:
        return raw_node['id']
    raise ValueError("Unable to extract graph ID from node representation.")


class GraphController:
    """ Controller for interacting with the graph database."""
    def __init__(self, engine: CypherEngine, graph: GraphProtocol):
        self.engine = engine
        self.graph = graph

    @property
    def age_name(self) -> str:
        """ The name of the AGE graph this controller manages."""
        return self.graph.age_name
    
    @property
    def definition(self) -> GraphDefinitionModel:
        """ The graph definition model this controller uses."""
        return self.graph.definition

    def create_entity(
        self, 
        *,
        kind: str,
        ref_id: str,
        subject: str,
        app_id: str,
        action_id: Optional[str] = None,
        action_name: Optional[str] = None,
        action_args: Optional[Dict[str, Any]] = None,
        supporting_evidence: Optional[List[Dict[str, Any]]] = None,
        schema: Optional[GraphDefinitionModel] = None,
    ) -> EntityCreationResult:
        """
        Create a new entity with optional supporting evidence structures.
        
        Args:
            kind: The entity type/label (must match schema)
            ref_id: Unique reference ID for the entity
            subject: User ID (provenance)
            app_id: Client/app ID (provenance)
            action_id: Optional action ID (provenance)
            action_name: Optional action name (provenance)
            action_args: Optional action arguments (provenance)
            supporting_evidence: List of evidence dicts with 'identifier', 'object', 'measurements'
            schema: Optional schema override (defaults to graph's definition)
            
        Returns:
            EntityCreationResult with ref_id, db_id, and graph_id
        """
        effective_schema = schema or self.graph.definition
        supporting_evidence = supporting_evidence or []
        
        # --- Step 1: Validate Kind Only ---
        entity_def = effective_schema.extensions.entities_map.get(kind)
        if not entity_def:
            raise ValueError(f"Unknown Entity: {kind}")

        # --- Step 2: Create Assertion (Provenance) ---
        prov_dict: Dict[str, Any] = {"subject": subject, "app_id": app_id}
        if action_id is not None:
            prov_dict["action_id"] = action_id
        if action_name is not None:
            prov_dict["action_name"] = action_name
        if action_args is not None:
            prov_dict["action_args"] = json.dumps(action_args)
        
        assertion_props = ", ".join([f"{k}: ${k}" for k in prov_dict.keys()])
        aid_res = self.engine.execute(
            self.graph,
            f"CREATE (a:{vocab.Assertion} {{{assertion_props}}}) RETURN id(a) as aid", 
            prov_dict
        )
        assertion_id = aid_res[0]['aid']

        # --- Step 3: Handle Evidence & Measurements ---
        for evidence in supporting_evidence:
            evidence_identifier = evidence.get("identifier", "Structure")
            evidence_object = evidence.get("object")
            evidence_measurements = evidence.get("measurements", [])
            
            structure_graph_label = IDENTIFIER_MAP.get(evidence_identifier, "Structure")
            
            # Auto-Create Structure (MERGE) - using 'object' as the external ID
            self.engine.execute(
                self.graph,
                f"MERGE (s:{structure_graph_label} {{object: $obj}})", 
                {"obj": evidence_object}
            )

            # Create Measurements
            for meas in evidence_measurements:
                # meas is a dict with key, value, and optional fields
                meas_params = {k: v for k, v in meas.items() if v is not None}
                meas_params.update({"obj": evidence_object, "aid": assertion_id})
                
                prop_clauses = ["key: $key", "value: $value"]
                for optional_key in ["unit", "confidence", "confidence_type", "timestamp"]:
                    if optional_key in meas_params:
                        prop_clauses.append(f"{optional_key}: ${optional_key}")

                meas_query = f"""
                    MATCH (s:{structure_graph_label} {{object: $obj}})
                    MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
                    
                    CREATE (m:{vocab.Measurement} {{{", ".join(prop_clauses)}}})
                    CREATE (a)-[:{vocab.ASSERTED}]->(m)
                    CREATE (m)-[:{vocab.DESCRIBES}]->(s)
                """
                self.engine.execute(self.graph, meas_query, meas_params)

        # --- Step 4: Create Entity (Shell) ---
        # We only set the immutable ID (db_id). All other props come from cache recalculation.
        e_params = {"eid": ref_id, "aid": assertion_id}
        
        create_res = self.engine.execute(
            self.graph,
            f"""
            MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
            CREATE (e:{kind} {{id: $eid}})
            CREATE (a)-[:{vocab.GENERATED}]->(e)
            RETURN e.id as db_id, id(e) as graph_id
            """, 
            e_params
        )
        
        db_id = str(create_res[0]['db_id'])
        graph_id = create_res[0]['graph_id']
        
        # --- Step 5: Link Entity -> Evidence ---
        for evidence in supporting_evidence:
            evidence_identifier = evidence.get("identifier", "Structure")
            evidence_object = evidence.get("object")
            g_label = IDENTIFIER_MAP.get(evidence_identifier, "Structure")
            self.engine.execute(
                self.graph,
                f"""
                MATCH (e:{kind}) WHERE id(e) = $eid
                MATCH (s:{g_label} {{object: $obj}})
                MERGE (s)-[:{vocab.INFORMS}]->(e)
                """, 
                {"eid": graph_id, "obj": evidence_object}
            )

        # --- Step 6: Recalculate Cached Properties ---
        # This is where the magic happens: Properties flow from Evidence -> Entity
        self._recalculate_entity(graph_id, kind, effective_schema)

        return EntityCreationResult(ref_id=ref_id, db_id=db_id, graph_id=graph_id)

    def _recalculate_entity(self, graph_id: int, label: str, schema: GraphDefinitionModel):
        """
        Scans schema rules and updates the Entity's cached properties based on connected evidence.
        
        Uses the rollup module to generate appropriate Cypher queries for each property's
        derivation type and aggregation function.
        """
        entity_def = schema.extensions.entities_map.get(label)
        if not entity_def:
            raise ValueError(f"Unknown Entity for recalculation: {label}")

        updates: Dict[str, Any] = {}
        
        for prop_def in entity_def.properties:
            # Skip the 'id' property - it's immutable
            if prop_def.key == "id":
                continue
                
            # Build the query using the rollup utilities
            rollup_query = build_property_query(label, prop_def.key, prop_def)
            
            if rollup_query:
                # Add entity id to params
                params = {**rollup_query.params, "eid": graph_id}
                
                result = self.engine.execute(self.graph, rollup_query.query, params)
                
                if result and result[0].get('val') is not None:
                    updates[prop_def.key] = result[0]['val']

        # Add System Metadata
        updates["__schema_version"] = schema.system_version
        updates["__last_derived"] = int(time.time() * 1000)

        if updates:
            set_clause = ", ".join([f"e.{k} = $u_{k}" for k in updates.keys()])
            update_params = {f"u_{k}": v for k, v in updates.items()}
            update_params["eid"] = graph_id
            
            self.engine.execute(
                self.graph,
                f"""
                MATCH (e:{label}) WHERE id(e) = $eid
                SET {set_clause}
                """,
                update_params
            )
    
    # ===================================================================
    # MIGRATION METHODS
    # ===================================================================
    
    def migrate_node(
        self,
        node_id: int,
        label: str,
        from_version: Optional[str] = None,
        to_version: Optional[str] = None,
    ) -> bool:
        """
        Migrate a node from one schema version to another.
        
        This re-runs property derivation to update the node to the current
        schema version. The migration is essentially a recalculation with
        the new schema.
        
        Args:
            node_id: The AGE node ID (graph_id)
            label: The node's label (entity kind)
            from_version: The version the node was created with (optional, for logging)
            to_version: The target version (defaults to current schema version)
            
        Returns:
            True if migration was performed
        """
        target_schema = self.definition
        if to_version and target_schema.system_version != to_version:
            # In the future, we could load a specific schema version
            # For now, we only migrate to the current active schema
            pass
        
        # Perform recalculation which updates all derived properties
        self._recalculate_entity(node_id, label, target_schema)
        return True
    
    def migrate_edge(
        self,
        edge_id: int,
        label: str,
        from_version: Optional[str] = None,
        to_version: Optional[str] = None,
    ) -> bool:
        """
        Migrate an edge (relation) from one schema version to another.
        
        This re-runs property derivation on the relation to update it to
        the current schema version.
        
        Args:
            edge_id: The AGE edge ID
            label: The edge's label (relation kind)
            from_version: The version the edge was created with (optional)
            to_version: The target version (defaults to current schema version)
            
        Returns:
            True if migration was performed
        """
        target_schema = self.definition
        
        # Recalculate relation properties
        self._recalculate_relation(edge_id, label, target_schema)
        return True
    
    def _recalculate_relation(
        self,
        edge_id: int,
        label: str,
        schema: GraphDefinitionModel,
    ):
        """
        Recalculates derived properties on a relation edge.
        
        Similar to _recalculate_entity but for edges/relations.
        """
        relation_def = schema.extensions.relations_map.get(label)
        if not relation_def:
            # No schema definition for this relation type, skip
            return
        
        updates: Dict[str, Any] = {}
        
        # Process property definitions with rollup/derivation
        for prop_def in relation_def.materialization.properties if relation_def.materialization else []:
            if prop_def.key == "id":
                continue
            
            # Build rollup query for edge properties
            # This would need edge-specific rollup logic
            # For now, we just update metadata
            pass
        
        # Update system metadata
        updates["__schema_version"] = schema.system_version
        updates["__last_derived"] = int(time.time() * 1000)
        
        if updates:
            set_clause = ", ".join([f"r.{k} = $u_{k}" for k in updates.keys()])
            update_params = {f"u_{k}": v for k, v in updates.items()}
            update_params["eid"] = edge_id
            
            self.engine.execute(
                self.graph,
                f"""
                MATCH ()-[r]->() WHERE id(r) = $eid
                SET {set_clause}
                """,
                update_params
            )
    
    def _check_and_migrate_node(
        self,
        entity: 'RetrievedEntity',
        auto_migrate: bool = True,
    ) -> 'RetrievedEntity':
        """
        Check if a node needs migration and optionally migrate it.
        
        Args:
            entity: The retrieved entity to check
            auto_migrate: Whether to perform migration automatically
            
        Returns:
            The entity (possibly refreshed after migration)
        """
        current_version = self.definition.system_version
        entity_version = entity.schema_version
        
        # No migration needed if versions match or entity has no version
        if not entity_version or entity_version == current_version:
            return entity
        
        if auto_migrate:
            # Perform migration
            self.migrate_node(
                node_id=entity.graph_id,
                label=entity.kind,
                from_version=entity_version,
                to_version=current_version,
            )
            
            # Re-fetch the updated entity
            return self._get_entity_without_migration(entity.id)
        
        return entity
    
    def _get_entity_without_migration(self, id: str) -> 'RetrievedEntity':
        """
        Internal method to fetch entity without triggering migration check.
        Used after migration to avoid infinite loops.
        """
        effective_schema = self.graph.definition
        
        query = f"""
            MATCH (n) WHERE n.id = $id
            RETURN n, labels(n) as lbls
        """
        result = self.engine.execute(self.graph, query, {"id": id})
        
        if not result:
            raise ValueError(f"Entity not found with ID {id}")
            
        raw_node = result[0]['n']
        labels = result[0]['lbls']
        
        if isinstance(raw_node, dict) and 'properties' in raw_node:
            node_props = raw_node['properties']
        else:
            node_props = raw_node
        
        detected_kind = None
        possible_kinds = effective_schema.extensions.entities_map.keys()
        
        for label in labels:
            if label in possible_kinds:
                detected_kind = label
                break
        
        if not detected_kind:
            detected_kind = labels[0] if labels else "Unknown"
        
        graph_id = _extract_id(raw_node)
        
        return RetrievedEntity(
            graph_name=self.age_name,
            id=graph_id,
            label=detected_kind,
            properties=node_props,
        )
            
            
    def get_entity(
        self, 
        id: str, 
        schema: Optional[GraphDefinitionModel] = None,
        auto_migrate: bool = True,
    ) -> RetrievedEntity:
        """
        Retrieves an Entity by ID.
        Dynamically detects the 'kind' from the Node Labels and returns
        a RetrievedEntity with the raw graph data.
        
        If the entity's schema version doesn't match the current schema,
        and auto_migrate is True, the entity will be migrated automatically.
        
        Args:
            id: The entity's unique string ID
            schema: Optional override schema (defaults to graph's active schema)
            auto_migrate: Whether to auto-migrate if schema version mismatch
            
        Returns:
            RetrievedEntity with the node's data
        """
        effective_schema = schema or self.graph.definition
        
        # 1. Fetch Node AND its Labels
        # We search strictly by the unique 'id' property.
        query = f"""
            MATCH (n) WHERE n.id = $id
            RETURN n, labels(n) as lbls
        """
        result = self.engine.execute(self.graph, query, {"id": id})
        
        if not result:
            raise ValueError(f"Entity not found with ID {id}")
            
        # Parse Result
        # AGE returns: {'n': {'id': <graph_id>, 'label': '...', 'properties': {...}}, 'lbls': [...]}
        raw_node = result[0]['n']
        labels = result[0]['lbls']
        
        # Extract properties - AGE wraps them in a 'properties' key
        if isinstance(raw_node, dict) and 'properties' in raw_node:
            node_props = raw_node['properties']
        else:
            node_props = raw_node
        
        # 2. Detect Kind from Labels
        # We look for a label that exists in our Schema Entities
        detected_kind = None
        
        # Priority: Check Entities first
        possible_kinds = effective_schema.extensions.entities_map.keys()
        
        for label in labels:
            if label in possible_kinds:
                detected_kind = label
                break
        
        if not detected_kind:
            # Fallback: Just return what we have
            detected_kind = labels[0] if labels else "Unknown"

        # Extract graph_id from raw node
        graph_id = _extract_id(raw_node)
        
        entity = RetrievedEntity(
            graph_name=self.age_name,
            id=graph_id,
            label=detected_kind,
            properties=node_props,
        )
        
        # 3. Check for schema version mismatch and auto-migrate if needed
        if auto_migrate and effective_schema:
            entity = self._check_and_migrate_node(entity, auto_migrate=True)
        
        return entity
    
    def get_structure(
        self,
        identifier: str,
        object: str,
    ) -> RetrievedStructure:
        """
        Retrieves a Structure by identifier and object.
        """
        structure_label = IDENTIFIER_MAP.get(identifier, "Structure")
        
        query = f"""
            MATCH (s:{structure_label} {{object: $obj}})
            RETURN s, labels(s) as lbls
        """
        result = self.engine.execute(self.graph, query, {"obj": object})
        
        if not result:
            raise ValueError(f"Structure not found with identifier {identifier} and object {object}")
            
        raw = result[0]['s']
        props = _extract_props(raw)
        graph_id = _extract_id(raw)
        
        # Add identifier to properties for access
        props['identifier'] = identifier
        
        return RetrievedStructure(
            graph_name=self.age_name,
            id=graph_id,
            label=structure_label,
            properties=props,
        )
    
    def get_informing_structures(
        self,
        entity_id: str,
    ) -> List[RetrievedStructure]:
        """
        Gets all structures that INFORM a given entity.
        """
        query = f"""
            MATCH (s)-[:{vocab.INFORMS}]->(e)
            WHERE e.id = $eid
            RETURN s, labels(s) as lbls
        """
        result = self.engine.execute(self.graph, query, {"eid": entity_id})
        
        structures = []
        for row in result:
            raw = row['s']
            labels = row['lbls']
            graph_id = _extract_id(raw)
            props = _extract_props(raw)
            
            # Reverse lookup identifier from label
            label = labels[0] if labels else "Structure"
            identifier = next(
                (k for k, v in IDENTIFIER_MAP.items() if v == label),
                "unknown"
            )
            
            # Add identifier to properties for access
            props['identifier'] = identifier
            
            structures.append(RetrievedStructure(
                graph_name=self.age_name,
                id=graph_id,
                label=label,
                properties=props,
            ))
        
        return structures
    
    def get_entities_informed_by(
        self,
        identifier: str,
        structure_object: str,
    ) -> List[RetrievedEntity]:
        """
        Gets all entities that are informed by a given structure.
        """
        structure_label = IDENTIFIER_MAP.get(identifier, "Structure")
        
        query = f"""
            MATCH (s:{structure_label} {{object: $obj}})-[:{vocab.INFORMS}]->(e)
            RETURN e, labels(e) as lbls
        """
        result = self.engine.execute(self.graph, query, {"obj": structure_object})
        
        entities = []
        for row in result:
            raw = row['e']
            labels = row['lbls']
            props = _extract_props(raw)
            graph_id = _extract_id(raw)
            
            # Filter for entity labels
            kind = next(
                (l for l in labels if l in self.definition.extensions.entities_map),
                labels[0] if labels else "Unknown"
            )
            
            entities.append(RetrievedEntity(
                graph_name=self.age_name,
                id=graph_id,
                label=kind,
                properties=props,
            ))
        
        return entities
    
    def get_measurements_for_structure(
        self,
        identifier: str,
        structure_object: str,
    ) -> List[RetrievedMeasurement]:
        """
        Gets all measurements that describe a given structure.
        """
        structure_label = IDENTIFIER_MAP.get(identifier, "Structure")
        
        query = f"""
            MATCH (m:{vocab.Measurement})-[:{vocab.DESCRIBES}]->(s:{structure_label} {{object: $obj}})
            RETURN m
        """
        result = self.engine.execute(self.graph, query, {"obj": structure_object})
        
        measurements = []
        for row in result:
            raw = row['m']
            props = _extract_props(raw)
            graph_id = _extract_id(raw)
            
            measurements.append(RetrievedMeasurement(
                graph_name=self.age_name,
                id=graph_id,
                label=vocab.Measurement,
                properties=props,
            ))
        
        return measurements
    
    def get_assertion_for_entity(
        self,
        entity_id: str,
    ) -> Optional[RetrievedAssertion]:
        """
        Gets the assertion that generated a given entity.
        """
        query = f"""
            MATCH (a:{vocab.Assertion})-[:{vocab.GENERATED}]->(e)
            WHERE e.id = $eid
            RETURN a, id(a) as aid
        """
        result = self.engine.execute(self.graph, query, {"eid": entity_id})
        
        if not result:
            return None
            
        raw = result[0]['a']
        graph_id = result[0]['aid']
        props = _extract_props(raw)
        
        return RetrievedAssertion(
            graph_name=self.age_name,
            id=graph_id,
            label=vocab.Assertion,
            properties=props,
        )
    
    def get_measurements_for_assertion(
        self,
        assertion_id: int,
    ) -> List[RetrievedMeasurement]:
        """
        Gets all measurements asserted by a given assertion.
        """
        query = f"""
            MATCH (a:{vocab.Assertion})-[:{vocab.ASSERTED}]->(m:{vocab.Measurement})
            WHERE id(a) = $aid
            RETURN m
        """
        result = self.engine.execute(self.graph, query, {"aid": assertion_id})
        
        measurements = []
        for row in result:
            raw = row['m']
            props = _extract_props(raw)
            graph_id = _extract_id(raw)
            
            measurements.append(RetrievedMeasurement(
                graph_name=self.age_name,
                id=graph_id,
                label=vocab.Measurement,
                properties=props,
            ))
        
        return measurements

    def create_structure(
        self,
        identifier: str,
        object: str,
    ) -> RetrievedStructure:
        """
        Create a new structure node.
        
        Args:
            identifier: Schema identifier (e.g. '@mikro/roi')
            object: Unique ID of the object this structure references
            
        Returns:
            RetrievedStructure with the created structure info
        """
        structure_label = IDENTIFIER_MAP.get(identifier, "Structure")
        
        # MERGE to create or match existing, return the graph id
        result = self.engine.execute(
            self.graph,
            f"MERGE (s:{structure_label} {{object: $obj}}) RETURN id(s) as graph_id",
            {"obj": object}
        )
        
        graph_id = result[0]['graph_id']
        
        return RetrievedStructure(
            graph_name=self.age_name,
            id=graph_id,
            label=structure_label,
            properties={"object": object, "identifier": identifier},
        )

    def add_measurement(
        self,
        structure_identifier: str,
        structure_object: str,
        measurement: 'MeasurementInput',
        provenance: 'ProvenanceContext',
    ) -> RetrievedMeasurement:
        """
        Add a measurement to an existing structure.
        
        Args:
            structure_identifier: Schema identifier of the structure
            structure_object: Object ID of the structure to add measurement to
            measurement: The measurement data
            provenance: Provenance context for this measurement
            
        Returns:
            RetrievedMeasurement with the created measurement info
        """
        structure_label = IDENTIFIER_MAP.get(structure_identifier, "Structure")
        
        # First ensure structure exists
        self.engine.execute(
            self.graph,
            f"MERGE (s:{structure_label} {{object: $obj}})",
            {"obj": structure_object}
        )
        
        # Create assertion for provenance
        prov_dict = provenance.model_dump(exclude_none=True)
        if 'action_args' in prov_dict:
            prov_dict['action_args'] = json.dumps(prov_dict['action_args'])
        
        assertion_props = ", ".join([f"{k}: ${k}" for k in prov_dict.keys()])
        aid_res = self.engine.execute(
            self.graph,
            f"CREATE (a:{vocab.Assertion} {{{assertion_props}}}) RETURN id(a) as aid",
            prov_dict
        )
        assertion_id = aid_res[0]['aid']
        
        # Create measurement and link to structure and assertion
        meas_params = measurement.model_dump(exclude_none=True)
        meas_params.update({"obj": structure_object, "aid": assertion_id})
        
        prop_clauses = ["key: $key", "value: $value"]
        for optional_key in ["unit", "confidence", "confidence_type", "timestamp"]:
            if optional_key in meas_params:
                prop_clauses.append(f"{optional_key}: ${optional_key}")
        
        meas_query = f"""
            MATCH (s:{structure_label} {{object: $obj}})
            MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
            
            CREATE (m:{vocab.Measurement} {{{", ".join(prop_clauses)}}})
            CREATE (a)-[:{vocab.ASSERTED}]->(m)
            CREATE (m)-[:{vocab.DESCRIBES}]->(s)
            RETURN id(m) as mid
        """
        result = self.engine.execute(self.graph, meas_query, meas_params)
        graph_id = result[0]['mid']
        
        # Build properties dict from measurement input
        meas_props = measurement.model_dump(exclude_none=True)
        
        return RetrievedMeasurement(
            graph_name=self.age_name,
            id=graph_id,
            label=vocab.Measurement,
            properties=meas_props,
        )

    def link_structure_to_entity(
        self,
        structure_identifier: str,
        structure_object: str,
        entity_id: str,
        recalculate: bool = True,
        schema: Optional[GraphDefinitionModel] = None,
    ) -> RetrievedEntity:
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
        structure_label = IDENTIFIER_MAP.get(structure_identifier, "Structure")
        
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
            {"obj": structure_object, "eid": entity_id}
        )
        
        # Recalculate entity properties if requested
        if recalculate:
            self._recalculate_entity(entity.local_id, entity.kind, effective_schema)
        
        # Return the updated entity
        return self.get_entity(entity_id, schema=effective_schema)
    
    
    
    def create_relation(
        self,
        payload: RelationCreationPayload,
        schema: Optional[GraphDefinitionModel] = None,
    ) -> EntityCreationResult:
        """
        Creates a Relationship between two nodes, backed by Evidence.
        
        Graph Structure Created:
        1. (Source)-[RELATION]->(Target)  <-- The actual edge
        2. (ShadowLink)                   <-- The reified node holding history
        3. (ShadowLink)-[:REIFIES]->(Source)
        4. (ShadowLink)-[:REIFIES]->(Target)
        5. (Structure)-[:INFORMS]->(ShadowLink) <-- Evidence attached here
        """
        effective_schema = schema or self.graph.definition
        relation_name = payload.kind
        
        # --- Step 1: Validate Schema ---
        rel_def = effective_schema.extensions.relations_map.get(relation_name)
        if not rel_def:
            raise ValueError(f"Unknown Relation: {relation_name}")

        # --- Step 2: Create Assertion (Provenance) ---
        prov_dict = payload.provenance.model_dump(exclude_none=True)
        if 'action_args' in prov_dict:
            prov_dict['action_args'] = json.dumps(prov_dict['action_args'])
        
        assertion_props = ", ".join([f"{k}: ${k}" for k in prov_dict.keys()])
        aid_res = self.engine.execute(
            self.graph,
            f"CREATE (a:{vocab.Assertion} {{{assertion_props}}}) RETURN id(a) as aid", 
            prov_dict
        )
        assertion_id = aid_res[0]['aid']

        # --- Step 3: Create Shadow Link & Attach Evidence ---
        # We create a "ShadowLink" node to represent this specific instance of the relationship.
        # This allows us to attach measurements to "the link" rather than the edge itself.
        
        shadow_params = {"link_id": payload.ref_id, "aid": assertion_id}
        
        shadow_res = self.engine.execute(
            self.graph,
            f"""
            MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
            CREATE (sl:{vocab.ShadowLink} {{id: $link_id}})
            CREATE (a)-[:{vocab.GENERATED}]->(sl)
            RETURN id(sl) as shadow_graph_id
            """,
            shadow_params
        )
        shadow_graph_id = shadow_res[0]['shadow_graph_id']

        # Process Evidence attached to the Shadow Link
        for evidence in payload.supporting_evidence:
            structure_graph_label = IDENTIFIER_MAP.get(evidence.identifier, "Structure")
            
            # Auto-Create Structure
            self.engine.execute(
                self.graph,
                f"MERGE (s:{structure_graph_label} {{object: $obj}})", 
                {"obj": evidence.object}
            )

            # Link Structure -> Shadow Link (INFORMS)
            # This says: "This structure (e.g. ROI Overlap) informs this relationship"
            self.engine.execute(
                self.graph,
                f"""
                MATCH (s:{structure_graph_label} {{object: $obj}})
                MATCH (sl:{vocab.ShadowLink}) WHERE id(sl) = $sl_id
                MERGE (s)-[:{vocab.INFORMS}]->(sl)
                """,
                {"obj": evidence.object, "sl_id": shadow_graph_id}
            )

            # Create Measurements for that Structure
            for meas in evidence.measurements:
                meas_params = meas.model_dump(exclude_none=True)
                meas_params.update({"obj": evidence.object, "aid": assertion_id})
                
                prop_clauses = ["key: $key", "value: $value"]
                for optional_key in ["unit", "confidence", "confidence_type", "timestamp"]:
                    if optional_key in meas_params:
                        prop_clauses.append(f"{optional_key}: ${optional_key}")

                meas_query = f"""
                    MATCH (s:{structure_graph_label} {{object: $obj}})
                    MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
                    
                    CREATE (m:{vocab.Measurement} {{{", ".join(prop_clauses)}}})
                    CREATE (a)-[:{vocab.ASSERTED}]->(m)
                    CREATE (m)-[:{vocab.DESCRIBES}]->(s)
                """
                self.engine.execute(self.graph, meas_query, meas_params)

        # --- Step 4: Create the Physical Edge ---
        edge_params = {
            "src": payload.source_id, 
            "tgt": payload.target_id, 
            "aid": assertion_id,
            "sl_id": shadow_graph_id
        }
        
        # Note: AGE doesn't allow creating relationships TO relationships,
        # so we connect the assertion to the ShadowLink instead.
        # The ShadowLink already has (Assertion)-[:GENERATED]->(ShadowLink)
        create_shadow_links = self.engine.execute(
            self.graph,
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
            edge_params
        )
        
        if not create_shadow_links:
             raise ValueError(f"Could not create relation. Source {payload.source_id} or Target {payload.target_id} not found.")
             
        shadow_link_id = create_shadow_links[0]['shadow_id']

        # --- Step 5: Recalculate Relation Properties ---
        # Rolls up values from the ShadowLink evidence onto the Edge itself
        edge_id = self._recalculate_relation(shadow_link_id, relation_name, effective_schema)
        
        if edge_id is None:
            raise ValueError(f"Failed to create relation edge for {relation_name}")

        return EntityCreationResult(
            ref_id=payload.ref_id, 
            db_id=f"{payload.source_id}->{payload.target_id}", 
            graph_id=edge_id
        )

    def _recalculate_relation(self, shadow_link_id: int, relation_label: str, schema: GraphDefinitionModel) -> Optional[int]:
        """
        Updates Edge properties based on measurements connected via the ShadowLink.
        
        A relation can only exist once per direction between source and target.
        This method uses MERGE to ensure uniqueness.
        
        Returns:
            The edge ID of the created/updated relation edge
        """
        rel_def = schema.extensions.relations_map.get(relation_label)
        if not rel_def or not rel_def.materialization:
            # No materialization config - just create the edge without properties
            # Still store the shadow link id for provenance tracking
            result = self.engine.execute(
                self.graph,
                f"""
                MATCH (sl:{vocab.ShadowLink}) WHERE id(sl) = $sl_id
                MATCH (sl)-[:{vocab.REIFIES_AS_SOURCE}]->(source)
                MATCH (sl)-[:{vocab.REIFIES_AS_TARGET}]->(target)
                MERGE (source)-[r:{relation_label}]->(target)
                SET r.__shadow_link_id = $sl_id
                RETURN id(r) as edge_id
                """,
                {"sl_id": shadow_link_id}
            )
            return result[0]['edge_id'] if result else None

        updates = {"__shadow_link_id": shadow_link_id}
        
        for prop_def in rel_def.materialization.properties:
            
            # Logic: (ShadowLink) <-[INFORMS]- (Structure) <-[DESCRIBES]- (Measurement)
            if prop_def.derivation == 'ROLLUP' and prop_def.rule:
                rule = prop_def.rule
                
                agg_func = "avg"
                if rule.aggregation == "MAX": agg_func = "max"
                elif rule.aggregation == "MIN": agg_func = "min"
                elif rule.aggregation == "SUM": agg_func = "sum"
                elif rule.aggregation == "COUNT": agg_func = "count"

                target_var = "m" if rule.aggregation == "COUNT" else "m.value"
                
                query = f"""
                    MATCH (sl:{vocab.ShadowLink}) WHERE id(sl) = $sl_id
                    MATCH (sl)<-[:{vocab.INFORMS}]-(s)
                    MATCH (m:{vocab.Measurement})-[:{vocab.DESCRIBES}]->(s)
                    WHERE m.key = $key
                    RETURN {agg_func}({target_var}) as val
                """
                
                result = self.engine.execute(
                    self.graph, 
                    query, 
                    {"sl_id": shadow_link_id, "key": rule.key or prop_def.key}
                )
                
                if result and result[0]['val'] is not None:
                    updates[prop_def.key] = result[0]['val']
        
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
                update_params
            )
            return result[0]['edge_id'] if result else None
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
                {"sl_id": shadow_link_id}
            )
            return result[0]['edge_id'] if result else None
        

    # ===================================================================
    # Relation Query Methods
    # ===================================================================
    
    def get_relation_by_id(self, edge_id: int) -> Optional[RetrievedEdge]:
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
            {"eid": edge_id}
        )
        
        if not result:
            return None
        
        row = result[0]
        edge_data = row['r'] if isinstance(row['r'], dict) else {}
        
        return RetrievedEdge(
            graph_name=self.age_name,
            id=edge_id,
            label=row.get('label', 'UNKNOWN'),
            left_id=_extract_id(row['start_node']) if row.get('start_node') else 0,
            right_id=_extract_id(row['end_node']) if row.get('end_node') else 0,
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
            {"link_id": link_ref_id}
        )
        
        if not result:
            return None
        
        row = result[0]
        return RetrievedNode(
            graph_name=self.age_name,
            id=row['graph_id'],
            label=vocab.ShadowLink,
            properties=_extract_props(row['sl']),
        )
    
    def get_informing_structures_for_link(self, link_ref_id: str) -> List[RetrievedStructure]:
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
            {"link_id": link_ref_id}
        )
        
        structures = []
        for row in result:
            structures.append(RetrievedStructure(
                graph_name=self.age_name,
                id=row['graph_id'],
                label=row.get('label', 'Structure'),
                properties=_extract_props(row['s']),
            ))
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
            {"link_id": link_ref_id}
        )
        
        entities = []
        for row in result:
            entities.append(RetrievedEntity(
                graph_name=self.age_name,
                id=row['graph_id'],
                label=row.get('label', 'Entity'),
                properties=_extract_props(row['e']),
            ))
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
            {"link_id": link_ref_id}
        )
        
        entities = []
        for row in result:
            entities.append(RetrievedEntity(
                graph_name=self.age_name,
                id=row['graph_id'],
                label=row.get('label', 'Entity'),
                properties=_extract_props(row['e']),
            ))
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
    
    def get_assertion_for_relation(self, edge_id: int) -> Optional[RetrievedAssertion]:
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
            self.graph,
            """
            MATCH ()-[r]->() WHERE id(r) = $eid
            RETURN r.__shadow_link_id as sl_id
            """,
            {"eid": edge_id}
        )
        
        if not edge_result or not edge_result[0].get('sl_id'):
            raise ValueError(f"Edge {edge_id} does not have a shadow link ID.")
        
        shadow_link_id = edge_result[0]['sl_id']
        
        # Now get the assertion that GENERATED the ShadowLink
        result = self.engine.execute(
            self.graph,
            f"""
            MATCH (a:{vocab.Assertion})-[:{vocab.GENERATED}]->(sl:{vocab.ShadowLink})
            WHERE id(sl) = $sl_id
            RETURN a, id(a) as graph_id
            """,
            {"sl_id": shadow_link_id}
        )
        
        if not result:
            return None
        
        row = result[0]
        return RetrievedAssertion(
            graph_name=self.age_name,
            id=row['graph_id'],
            label=vocab.Assertion,
            properties=_extract_props(row['a']),
        )