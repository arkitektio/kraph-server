import json
from typing import Dict, Any, List, Optional, Union
from graph_engine.base_models import GraphDefinitionModel, DerivationType
from graph_engine.input_models import EntityCreationPayload, EntityCreationResult
from graph_engine.engine.protocol import (
    CypherEngine, 
    GraphContext, 
    GraphWithDefinition, 
    GraphContextWithDefinition
)

IDENTIFIER_MAP = {
    "@mikro/roi": "ROI",
    "told_you_so": "ToldYouSo",
    "default": "Structure"
}


class GraphController:
    """
    Controller for graph operations.
    
    Accepts either:
    - A CypherEngine directly (for backwards compatibility)
    - A GraphContext (which provides age_name for engine creation)
    - A GraphWithDefinition (which provides both engine and schema)
    - A GraphContextWithDefinition (which provides age_name and schema)
    """
    
    def __init__(
        self, 
        engine: Optional[CypherEngine] = None,
        *,
        graph: Optional[Union[GraphContext, GraphWithDefinition, GraphContextWithDefinition]] = None,
        schema: Optional[GraphDefinitionModel] = None,
    ):
        """
        Initialize the controller.
        
        Args:
            engine: Direct CypherEngine instance (legacy mode)
            graph: A graph context or graph-with-definition protocol
            schema: Optional schema if not provided via graph
        """
        # Resolve engine
        if engine is not None:
            self.engine = engine
        elif graph is not None:
            # If graph provides an engine, use it
            if hasattr(graph, 'engine'):
                self.engine = graph.engine
            else:
                # Need to create engine from context
                from graph_engine.engine.age_engine import AgeEngineFactory
                self.engine = AgeEngineFactory.from_context(graph)
        else:
            raise ValueError("Either 'engine' or 'graph' must be provided")
        
        # Resolve schema
        if hasattr(graph, 'definition') and graph.definition is not None:
            self._default_schema = graph.definition
        else:
            self._default_schema = schema
        
        # Store graph context for additional info (like organization_id)
        self._graph = graph

    @property
    def age_name(self) -> Optional[str]:
        """Get the age_name from the graph context if available."""
        if hasattr(self._graph, 'age_name'):
            return self._graph.age_name
        return None
    
    @property
    def organization_id(self) -> Optional[str]:
        """Get the organization_id from the graph context if available."""
        if hasattr(self._graph, 'organization_id'):
            return self._graph.organization_id
        return None

    def create_entity(
        self, 
        payload: EntityCreationPayload, 
        schema: Optional[GraphDefinitionModel] = None,
    ) -> EntityCreationResult:
        """
        Create an entity in the graph.
        
        Args:
            payload: The entity creation payload
            schema: Optional schema override (uses controller's default if not provided)
            
        Returns:
            EntityCreationResult with the created entity IDs
        """
        # Use provided schema or fall back to default
        effective_schema = schema or self._default_schema
        if effective_schema is None:
            raise ValueError("No schema provided and no default schema configured")
        
        # --- Steps 1 & 2: Schema Validation & Provenance (Unchanged) ---
        entity_def = effective_schema.extensions.entities.get(payload.kind)
        if not entity_def: raise ValueError(f"Unknown Entity: {payload.kind}")

        valid_props = {}
        for k, v in payload.properties.items():
            if k in entity_def.properties: valid_props[k] = v

        prov_dict = payload.provenance.model_dump(exclude_none=True)
        if 'action_args' in prov_dict: prov_dict['action_args'] = json.dumps(prov_dict['action_args'])
        
        assertion_props = ", ".join([f"{k}: ${k}" for k in prov_dict.keys()])
        aid_res = self.engine.execute(f"CREATE (a:Assertion {{{assertion_props}}}) RETURN id(a) as aid", prov_dict)
        assertion_id = aid_res[0]['aid']

        # --- Step 3: Evidence & Measurements ---
        for evidence in payload.supporting_evidence:
            graph_label = IDENTIFIER_MAP.get(evidence.identifier, "Structure")
            
            # Auto-Create Structure
            self.engine.execute(f"""
                MERGE (s:{graph_label} {{id: $sid}})
                SET s += $extra_props
            """, {"sid": evidence.id, "extra_props": evidence.properties})

            # Create Measurements with Timestamp
            for meas in evidence.measurements:
                meas_params = meas.model_dump(exclude_none=True)
                meas_params.update({"sid": evidence.id, "aid": assertion_id})
                
                # Check if timestamp exists in params, otherwise it defaults to null in DB
                ts_clause = ", timestamp: $timestamp" if "timestamp" in meas_params else ""

                meas_query = f"""
                    MATCH (s:{graph_label} {{id: $sid}})
                    MATCH (a:Assertion) WHERE id(a) = $aid
                    
                    CREATE (m:Measurement {{
                        key: $key, 
                        value: $value, 
                        unit: $unit, 
                        confidence: $confidence
                        {ts_clause}
                    }})
                    CREATE (a)-[:GENERATED]->(m)
                    CREATE (m)-[:DESCRIBES]->(s)
                """
                self.engine.execute(meas_query, meas_params)

        # --- Step 4: Create Entity (Unchanged) ---
        props_str = ", ".join([f"{k}: $prop_{k}" for k in valid_props.keys()])
        e_params = {f"prop_{k}": v for k, v in valid_props.items()}
        e_params["aid"] = assertion_id
        
        create_res = self.engine.execute(f"""
            MATCH (a:Assertion) WHERE id(a) = $aid
            CREATE (e:{payload.kind} {{{props_str}}})
            CREATE (a)-[:GENERATED]->(e)
            RETURN e.id as db_id, id(e) as graph_id
        """, e_params)
        
        # Link Logic (Unchanged)
        graph_id = create_res[0]['graph_id']
        for evidence in payload.supporting_evidence:
            g_label = IDENTIFIER_MAP.get(evidence.identifier, "Structure")
            self.engine.execute(f"""
                MATCH (e:{payload.kind}) WHERE id(e) = $eid
                MATCH (s:{g_label} {{id: $sid}})
                MERGE (e)-[:REPRESENTED_BY]->(s)
            """, {"eid": graph_id, "sid": evidence.id})

        return EntityCreationResult(ref_id=payload.ref_id, db_id=str(create_res[0]['db_id']), graph_id=graph_id)