import json
import time
from typing import Optional, Dict, Any, List
from graph_engine.base_models import GraphDefinitionModel
from graph_engine.input_models import EntityCreationPayload, EntityCreationResult, MeasurementInput, ProvenanceContext
from graph_engine.engine.protocol import CypherEngine, GraphProtocol
from graph_engine.retrieved import (
    RetrievedNode,
    RetrievedEdge,
    RetrievedEntity,
    RetrievedStructure,
    RetrievedMeasurement,
    RetrievedAssertion,
    node_from_age_result,
    edge_from_age_result,
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


def _extract_schema_version(raw_node: Any) -> Optional[str]:
    """Helper to extract schema version from properties."""
    return raw_node.get("__schema_version")


def _extract_last_derived(raw_node: Any) -> Optional[int]:
    """Helper to extract last derived timestamp from properties."""
    return raw_node.get("__last_derived")

class GraphController:
    def __init__(self, engine: CypherEngine, graph: GraphProtocol):
        self.engine = engine
        self.graph = graph

    @property
    def age_name(self) -> str:
        return self.graph.age_name
    
    @property
    def definition(self) -> GraphDefinitionModel:
        return self.graph.definition

    def create_entity(
        self, 
        payload: EntityCreationPayload, 
        schema: Optional[GraphDefinitionModel] = None,
    ) -> EntityCreationResult:
        
        effective_schema = schema or self.graph.definition
        
        # --- Step 1: Validate Kind Only ---
        entity_def = effective_schema.extensions.entities.get(payload.kind)
        if not entity_def:
            raise ValueError(f"Unknown Entity: {payload.kind}")

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

        # --- Step 3: Handle Evidence & Measurements ---
        for evidence in payload.supporting_evidence:
            structure_graph_label = IDENTIFIER_MAP.get(evidence.identifier, "Structure")
            
            # Auto-Create Structure (MERGE) - using 'object' as the external ID
            self.engine.execute(
                self.graph,
                f"MERGE (s:{structure_graph_label} {{object: $obj}})", 
                {"obj": evidence.object}
            )

            # Create Measurements
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

        # --- Step 4: Create Entity (Shell) ---
        # We only set the immutable ID (db_id). All other props come from cache recalculation.
        # We use payload.ref_id as the immutable DB ID.
        e_params = {"eid": payload.ref_id, "aid": assertion_id}
        
        create_res = self.engine.execute(
            self.graph,
            f"""
            MATCH (a:{vocab.Assertion}) WHERE id(a) = $aid
            CREATE (e:{payload.kind} {{id: $eid}})
            CREATE (a)-[:{vocab.GENERATED}]->(e)
            RETURN e.id as db_id, id(e) as graph_id
            """, 
            e_params
        )
        
        db_id = str(create_res[0]['db_id'])
        graph_id = create_res[0]['graph_id']
        
        # --- Step 5: Link Entity -> Evidence ---
        for evidence in payload.supporting_evidence:
            g_label = IDENTIFIER_MAP.get(evidence.identifier, "Structure")
            self.engine.execute(
                self.graph,
                f"""
                MATCH (e:{payload.kind}) WHERE id(e) = $eid
                MATCH (s:{g_label} {{object: $obj}})
                MERGE (s)-[:{vocab.INFORMS}]->(e)
                """, 
                {"eid": graph_id, "obj": evidence.object}
            )

        # --- Step 6: Recalculate Cached Properties ---
        # This is where the magic happens: Properties flow from Evidence -> Entity
        self._recalculate_entity(graph_id, payload.kind, effective_schema)

        return EntityCreationResult(ref_id=payload.ref_id, db_id=db_id, graph_id=graph_id)

    def _recalculate_entity(self, graph_id: int, label: str, schema: GraphDefinitionModel):
        """
        Scans schema rules and updates the Entity's cached properties based on connected evidence.
        
        Uses the rollup module to generate appropriate Cypher queries for each property's
        derivation type and aggregation function.
        """
        entity_def = schema.extensions.entities.get(label)
        if not entity_def:
            raise ValueError(f"Unknown Entity for recalculation: {label}")

        updates: Dict[str, Any] = {}
        
        for prop_name, prop_def in entity_def.properties.items():
            # Skip the 'id' property - it's immutable
            if prop_name == "id":
                continue
                
            # Build the query using the rollup utilities
            rollup_query = build_property_query(label, prop_name, prop_def)
            
            if rollup_query:
                # Add entity id to params
                params = {**rollup_query.params, "eid": graph_id}
                
                result = self.engine.execute(self.graph, rollup_query.query, params)
                
                if result and result[0].get('val') is not None:
                    updates[prop_name] = result[0]['val']

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
            
            
    def get_entity(
        self, 
        id: str, 
        schema: Optional[GraphDefinitionModel] = None
    ) -> RetrievedEntity:
        """
        Retrieves an Entity by ID.
        Dynamically detects the 'kind' from the Node Labels and returns
        a RetrievedEntity with the raw graph data.
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
        possible_kinds = effective_schema.extensions.entities.keys()
        
        for label in labels:
            if label in possible_kinds:
                detected_kind = label
                break
        
        if not detected_kind:
            # Fallback: Just return what we have
            detected_kind = labels[0] if labels else "Unknown"

        # Extract graph_id from raw node
        graph_id = _extract_id(raw_node)
        
        return RetrievedEntity(
            graph_name=self.age_name,
            id=graph_id,
            label=detected_kind,
            properties=node_props,
        )
    
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
                (l for l in labels if l in self.definition.extensions.entities),
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