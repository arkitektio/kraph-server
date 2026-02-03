import json
import time
from typing import Optional, Dict, Any
from graph_engine.base_models import GraphDefinitionModel, DerivationType, AggregationFunction
from graph_engine.input_models import EntityCreationPayload, EntityCreationResult
from graph_engine.engine.protocol import CypherEngine, GraphProtocol
from graph_engine import output_models as outputs
from graph_engine import vocab

IDENTIFIER_MAP = {
    "@mikro/roi": "ROI",
    "told_you_so": "ToldYouSo",
    "default": "Structure"
}

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
            
            # Auto-Create Structure (MERGE)
            # Only strictly immutable ID properties allowed here
            self.engine.execute(
                self.graph,
                f"""
                MERGE (s:{structure_graph_label} {{id: $sid}})
                SET s += $extra_props
                """, 
                {"sid": evidence.id, "extra_props": evidence.properties}
            )

            # Create Measurements
            for meas in evidence.measurements:
                meas_params = meas.model_dump(exclude_none=True)
                meas_params.update({"sid": evidence.id, "aid": assertion_id})
                
                prop_clauses = ["key: $key", "value: $value"]
                for optional_key in ["unit", "confidence", "confidence_type", "timestamp"]:
                    if optional_key in meas_params:
                        prop_clauses.append(f"{optional_key}: ${optional_key}")

                meas_query = f"""
                    MATCH (s:{structure_graph_label} {{id: $sid}})
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
                MATCH (s:{g_label} {{id: $sid}})
                MERGE (s)-[:{vocab.INFORMS}]->(e)
                """, 
                {"eid": graph_id, "sid": evidence.id}
            )

        # --- Step 6: Recalculate Cached Properties ---
        # This is where the magic happens: Properties flow from Evidence -> Entity
        self._recalculate_entity(graph_id, payload.kind, effective_schema)

        return EntityCreationResult(ref_id=payload.ref_id, db_id=db_id, graph_id=graph_id)

    def _recalculate_entity(self, graph_id: int, label: str, schema: GraphDefinitionModel):
        """
        Scans schema rules and updates the Entity's cached properties based on connected evidence.
        """
        entity_def = schema.extensions.entities.get(label)
        if not entity_def:
            raise ValueError(f"Unknown Entity for recalculation: {label}")

        updates = {}
        
        for prop_name, prop_def in entity_def.properties.items():
            
            
            
            
            # CASE A: ROLLUP (Aggregates)
            if prop_def.derivation == DerivationType.ROLLUP and prop_def.rule:
                rule = prop_def.rule
                
                # Map Schema Aggregation to Cypher Function
                agg_func = "avg" # Default
                if rule.aggregation == AggregationFunction.MAX: agg_func = "max"
                elif rule.aggregation == AggregationFunction.MIN: agg_func = "min"
                elif rule.aggregation == AggregationFunction.SUM: agg_func = "sum"
                elif rule.aggregation == AggregationFunction.COUNT: agg_func = "count"
                elif rule.aggregation == AggregationFunction.MEAN: agg_func = "avg"
                else:
                    raise ValueError(f"Unsupported aggregation function: {rule.aggregation}")
                
                target_var = "m" if rule.aggregation == AggregationFunction.COUNT else f"m.value"

                query = f"""
                    MATCH (e:{label}) WHERE id(e) = $eid
                    MATCH (s:{rule.source_node})-[:{vocab.INFORMS}]->(e)
                    MATCH (m:{vocab.Measurement})-[:{vocab.DESCRIBES}]->(s)
                    WHERE m.key = $key
                    RETURN {agg_func}({target_var}) as val
                """
                result = self.engine.execute(self.graph, query, {"eid": graph_id, "key": rule.key})
                print("ROLLUP Result:", result)
                if result and result[0]['val'] is not None:
                    updates[prop_name] = result[0]['val']

            # CASE B: LATEST (Scalar Properties from Measurements)
            # Used for manual properties asserted via ToldYouSo
            elif prop_def.derivation == DerivationType.LATEST:
                # Rule: Find the most recent Measurement describing any connected structure
                # that matches the property key.
                
                # Default logic: Look for measurements on connected structures
                # If a specific rule exists (e.g. source_node="ToldYouSo"), use it.
                source_node_type = prop_def.rule.source_node if (prop_def.rule and prop_def.rule.source_node) else "Structure"
                measure_key = prop_def.rule.key if (prop_def.rule and prop_def.rule.key) else prop_name
                
                query = f"""
                    MATCH (e:{label}) WHERE id(e) = $eid
                    MATCH (e)-[:REPRESENTED_BY]->(s:{source_node_type})
                    MATCH (m:Measurement)-[:DESCRIBES]->(s)
                    WHERE m.key = $key
                    RETURN m.value as val
                    ORDER BY m.timestamp DESC LIMIT 1
                """
                
                result = self.engine.execute(self.graph, query, {"eid": graph_id, "key": measure_key})
                if result and result[0]['val'] is not None:
                    updates[prop_name] = result[0]['val']
                    
            else:
                raise ValueError(f"Unsupported derivation type for property '{prop_name}': {prop_def.derivation}")

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
    ) -> outputs.EntityResponse:
        """
        Retrieves an Entity by ID.
        Dynamically detects the 'kind' from the Node Labels and hydrates 
        the response using the matching Schema Definition.
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
        # Mock engine returns [{'n': {...}, 'lbls': ['AIS', 'Entity']}]
        raw_props = result[0]['n']
        labels = result[0]['lbls']
        
        # 2. Detect Kind from Labels
        # We look for a label that exists in our Schema Entities
        detected_kind = None
        entity_def = None
        
        # Priority: Check Entities first, then Structures (if you want to fetch structures too)
        possible_kinds = effective_schema.extensions.entities.keys()
        
        for label in labels:
            if label in possible_kinds:
                detected_kind = label
                entity_def = effective_schema.extensions.entities[label]
                break
        
        if not detected_kind:
            # Fallback: Just return what we have without rich metadata
            detected_kind = labels[0] if labels else "Unknown"

        # 3. Filter System Properties
        system_keys = {"__schema_version", "__last_derived", "id"}
        clean_props = {k: v for k, v in raw_props["properties"].items() if k not in system_keys}
        
        # 4. Hydrate Rich Properties
        rich_props = []
        
        if entity_def:
            for key, val in clean_props.items():
                # Look up definition in the detected schema
                schema_prop = entity_def.properties.get(key)
                
                rich_p = outputs.RichProperty(
                    key=key,
                    value=val,
                    unit=schema_prop.unit if schema_prop else None,
                    description=schema_prop.description if schema_prop else None,
                    derivation_mode=schema_prop.derivation if schema_prop else "MANUAL"
                )
                rich_props.append(rich_p)
        else:
            # No schema found for this label, return basic props
            for key, val in clean_props.items():
                rich_props.append(outputs.RichProperty(key=key, value=val, derivation_mode="UNKNOWN"))

        return outputs.EntityResponse(
            id=raw_props.get("id"),
            kind=detected_kind, # <--- Populated dynamically
            properties=clean_props,
            rich_properties=rich_props,
            __schema_version=raw_props.get("__schema_version"),
            __last_derived=raw_props.get("__last_derived")
        )
    
    # ... [_recalculate_entity logic remains the same] ...