"""
Schema Migration Module

Generates staging mutations to migrate from one GraphDefinitionModel to another.
This enables schema evolution by detecting additions, removals, and changes.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Set

from graph_engine.base_models import (
    GraphDefinitionModel, 
    GraphExtensions,
    NodeDefinition,
    RelationDefinition,
    PropertyDefinition,
    PropertyType,
)


class MigrationAction(str, Enum):
    """Type of schema migration action."""
    ADD_NODE_TYPE = "add_node_type"
    REMOVE_NODE_TYPE = "remove_node_type"
    ADD_PROPERTY = "add_property"
    REMOVE_PROPERTY = "remove_property"
    MODIFY_PROPERTY = "modify_property"
    ADD_RELATION_TYPE = "add_relation_type"
    REMOVE_RELATION_TYPE = "remove_relation_type"
    ADD_EVENT_TYPE = "add_event_type"
    REMOVE_EVENT_TYPE = "remove_event_type"


@dataclass
class SchemaMutation:
    """
    Represents a single schema change mutation.
    """
    action: MigrationAction
    target: str  # Node/Relation/Event type name
    property_name: Optional[str] = None
    old_definition: Optional[Dict] = None
    new_definition: Optional[Dict] = None
    cypher_query: Optional[str] = None
    description: str = ""


@dataclass
class SchemaMigrationPlan:
    """
    A complete migration plan from one schema to another.
    """
    from_version: str
    to_version: str
    mutations: List[SchemaMutation] = field(default_factory=list)
    
    @property
    def has_breaking_changes(self) -> bool:
        """Check if migration has breaking changes (removals)."""
        breaking_actions = {
            MigrationAction.REMOVE_NODE_TYPE,
            MigrationAction.REMOVE_PROPERTY,
            MigrationAction.REMOVE_RELATION_TYPE,
            MigrationAction.REMOVE_EVENT_TYPE,
        }
        return any(m.action in breaking_actions for m in self.mutations)
    
    @property
    def is_empty(self) -> bool:
        """Check if there are no changes."""
        return len(self.mutations) == 0
    
    def get_cypher_mutations(self) -> List[str]:
        """Get all Cypher queries for data migration."""
        return [m.cypher_query for m in self.mutations if m.cypher_query]


def generate_schema_migration(
    current: Optional[GraphDefinitionModel],
    target: GraphDefinitionModel,
) -> SchemaMigrationPlan:
    """
    Generate a migration plan from current schema to target schema.
    
    Args:
        current: The current schema (None if creating from scratch)
        target: The target schema to migrate to
        
    Returns:
        SchemaMigrationPlan with all required mutations
    """
    mutations: List[SchemaMutation] = []
    
    # Handle creating from scratch
    if current is None:
        current = GraphDefinitionModel(
            system_version="0.0.0",
            extensions=GraphExtensions()
        )
    
    current_ext = current.extensions
    target_ext = target.extensions
    
    # --- Migrate Structures ---
    mutations.extend(_diff_node_types(
        current_ext.structures, 
        target_ext.structures,
        "structure"
    ))
    
    # --- Migrate Entities ---
    mutations.extend(_diff_node_types(
        current_ext.entities,
        target_ext.entities,
        "entity"
    ))
    
    # --- Migrate Relations ---
    mutations.extend(_diff_relations(
        current_ext.relations,
        target_ext.relations
    ))
    
    # --- Migrate Events ---
    mutations.extend(_diff_events(
        current_ext.events,
        target_ext.events
    ))
    
    return SchemaMigrationPlan(
        from_version=current.system_version,
        to_version=target.system_version,
        mutations=mutations,
    )


def _diff_node_types(
    current: Dict[str, NodeDefinition],
    target: Dict[str, NodeDefinition],
    node_category: str,
) -> List[SchemaMutation]:
    """Diff node type definitions (structures or entities)."""
    mutations = []
    
    current_names = set(current.keys())
    target_names = set(target.keys())
    
    # Added node types
    for name in target_names - current_names:
        mutations.append(SchemaMutation(
            action=MigrationAction.ADD_NODE_TYPE,
            target=name,
            new_definition=target[name].model_dump(),
            description=f"Add {node_category} type '{name}'"
        ))
    
    # Removed node types
    for name in current_names - target_names:
        mutations.append(SchemaMutation(
            action=MigrationAction.REMOVE_NODE_TYPE,
            target=name,
            old_definition=current[name].model_dump(),
            description=f"Remove {node_category} type '{name}'",
            # Warning: this would delete existing nodes!
            cypher_query=f"MATCH (n:{name}) DETACH DELETE n"
        ))
    
    # Modified node types (check properties)
    for name in current_names & target_names:
        mutations.extend(_diff_properties(
            name,
            current[name].properties,
            target[name].properties
        ))
    
    return mutations


def _diff_properties(
    node_type: str,
    current: Dict[str, PropertyDefinition],
    target: Dict[str, PropertyDefinition],
) -> List[SchemaMutation]:
    """Diff property definitions for a node type."""
    mutations = []
    
    current_props = set(current.keys())
    target_props = set(target.keys())
    
    # Added properties
    for prop in target_props - current_props:
        prop_def = target[prop]
        default_value = _get_default_for_type(prop_def.type)
        
        mutations.append(SchemaMutation(
            action=MigrationAction.ADD_PROPERTY,
            target=node_type,
            property_name=prop,
            new_definition=prop_def.model_dump(),
            description=f"Add property '{prop}' to '{node_type}'",
            # Set default value on existing nodes
            cypher_query=f"MATCH (n:{node_type}) WHERE n.{prop} IS NULL SET n.{prop} = {default_value}"
        ))
    
    # Removed properties
    for prop in current_props - target_props:
        mutations.append(SchemaMutation(
            action=MigrationAction.REMOVE_PROPERTY,
            target=node_type,
            property_name=prop,
            old_definition=current[prop].model_dump(),
            description=f"Remove property '{prop}' from '{node_type}'",
            cypher_query=f"MATCH (n:{node_type}) REMOVE n.{prop}"
        ))
    
    # Modified properties (type change, etc.)
    for prop in current_props & target_props:
        current_def = current[prop]
        target_def = target[prop]
        
        if current_def.type != target_def.type:
            mutations.append(SchemaMutation(
                action=MigrationAction.MODIFY_PROPERTY,
                target=node_type,
                property_name=prop,
                old_definition=current_def.model_dump(),
                new_definition=target_def.model_dump(),
                description=f"Change type of '{prop}' on '{node_type}' from {current_def.type.value} to {target_def.type.value}",
                # Type conversion query (may need manual handling)
                cypher_query=_generate_type_conversion_query(node_type, prop, current_def.type, target_def.type)
            ))
    
    return mutations


def _diff_relations(
    current: Dict[str, RelationDefinition],
    target: Dict[str, RelationDefinition],
) -> List[SchemaMutation]:
    """Diff relation definitions."""
    mutations = []
    
    current_names = set(current.keys())
    target_names = set(target.keys())
    
    # Added relations
    for name in target_names - current_names:
        mutations.append(SchemaMutation(
            action=MigrationAction.ADD_RELATION_TYPE,
            target=name,
            new_definition=target[name].model_dump(),
            description=f"Add relation type '{name}'"
        ))
    
    # Removed relations
    for name in current_names - target_names:
        mutations.append(SchemaMutation(
            action=MigrationAction.REMOVE_RELATION_TYPE,
            target=name,
            old_definition=current[name].model_dump(),
            description=f"Remove relation type '{name}'",
            cypher_query=f"MATCH ()-[r:{name}]->() DELETE r"
        ))
    
    return mutations


def _diff_events(
    current: Dict[str, any],
    target: Dict[str, any],
) -> List[SchemaMutation]:
    """Diff event definitions."""
    mutations = []
    
    current_names = set(current.keys())
    target_names = set(target.keys())
    
    # Added events
    for name in target_names - current_names:
        mutations.append(SchemaMutation(
            action=MigrationAction.ADD_EVENT_TYPE,
            target=name,
            new_definition=target[name].model_dump() if hasattr(target[name], 'model_dump') else dict(target[name]),
            description=f"Add event type '{name}'"
        ))
    
    # Removed events
    for name in current_names - target_names:
        mutations.append(SchemaMutation(
            action=MigrationAction.REMOVE_EVENT_TYPE,
            target=name,
            old_definition=current[name].model_dump() if hasattr(current[name], 'model_dump') else dict(current[name]),
            description=f"Remove event type '{name}'",
            cypher_query=f"MATCH (n:{name}) DETACH DELETE n"
        ))
    
    return mutations


def _get_default_for_type(prop_type: PropertyType) -> str:
    """Get a Cypher literal for default value based on property type."""
    defaults = {
        PropertyType.STRING: "''",
        PropertyType.FLOAT: "0.0",
        PropertyType.INTEGER: "0",
        PropertyType.BOOLEAN: "false",
        PropertyType.DATETIME: "null",
        PropertyType.POINT_3D: "null",
    }
    return defaults.get(prop_type, "null")


def _generate_type_conversion_query(
    node_type: str,
    prop: str,
    from_type: PropertyType,
    to_type: PropertyType,
) -> Optional[str]:
    """Generate a Cypher query to convert property types."""
    # Simple conversions
    if from_type == PropertyType.INTEGER and to_type == PropertyType.FLOAT:
        return f"MATCH (n:{node_type}) SET n.{prop} = toFloat(n.{prop})"
    elif from_type == PropertyType.FLOAT and to_type == PropertyType.INTEGER:
        return f"MATCH (n:{node_type}) SET n.{prop} = toInteger(n.{prop})"
    elif to_type == PropertyType.STRING:
        return f"MATCH (n:{node_type}) SET n.{prop} = toString(n.{prop})"
    
    # Complex conversions may need manual intervention
    return f"-- Manual migration required: convert {prop} from {from_type.value} to {to_type.value}"


def apply_migration(
    engine: "CypherEngine",
    graph: "GraphProtocol",
    plan: SchemaMigrationPlan,
    dry_run: bool = False,
) -> Dict[str, any]:
    """
    Apply a migration plan to a graph.
    
    Args:
        engine: The Cypher engine to use
        graph: The graph to migrate
        plan: The migration plan to apply
        dry_run: If True, don't actually execute changes
        
    Returns:
        Dict with migration results
    """
    from graph_engine.engine.protocol import CypherEngine, GraphProtocol
    
    results = {
        "applied": [],
        "skipped": [],
        "errors": [],
        "dry_run": dry_run,
    }
    
    for mutation in plan.mutations:
        if mutation.cypher_query:
            if dry_run:
                results["skipped"].append({
                    "action": mutation.action.value,
                    "target": mutation.target,
                    "query": mutation.cypher_query,
                })
            else:
                try:
                    engine.execute(graph, mutation.cypher_query)
                    results["applied"].append({
                        "action": mutation.action.value,
                        "target": mutation.target,
                        "description": mutation.description,
                    })
                except Exception as e:
                    results["errors"].append({
                        "action": mutation.action.value,
                        "target": mutation.target,
                        "error": str(e),
                    })
        else:
            # Schema-only changes (no data migration needed)
            results["applied"].append({
                "action": mutation.action.value,
                "target": mutation.target,
                "description": mutation.description,
            })
    
    return results
