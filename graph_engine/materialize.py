"""
Graph Materialization Module

This module handles the creation of Django database models from a GraphDefinitionModel.
It creates EntityCategory, RelationCategory, NaturalEventCategory, and GraphSchema
instances from the schema definition.
"""

import hashlib
import json
from typing import Optional
from pydantic import BaseModel, Field

from .base_models import GraphDefinitionModel
from .engine.protocol import CypherEngine
from core import models
from itertools import product
from django.db.models import Q
from authentikate.models import Organization, Membership, User


class MaterializeInput(BaseModel):
    """Input for materializing a graph."""

    name: str = Field(..., description="Name of the graph")
    description: Optional[str] = Field(None, description="Description of the graph")
    definition: GraphDefinitionModel = Field(..., description="The graph schema definition")


def compute_definition_hash(definition: GraphDefinitionModel) -> str:
    """
    Compute a stable hash of the graph definition for versioning.

    Args:
        definition: The GraphDefinitionModel to hash

    Returns:
        SHA256 hash string
    """
    json_str = definition.model_dump_json(exclude_none=True)
    return hashlib.sha256(json_str.encode()).hexdigest()[:16]


def compute_properties_hash(properties: list) -> str:
    """
    Compute a stable hash of property definitions for versioning.

    Args:
        properties: List of property definition dicts

    Returns:
        SHA256 hash string
    """
    sorted_props = sorted(properties, key=lambda p: p.get("key", ""))
    json_str = json.dumps(sorted_props, sort_keys=True, default=str)
    return hashlib.sha256(json_str.encode()).hexdigest()[:16]


class LinkPairs:
    """Helper dataclass to store pairs of source and target nodes for relation materialization."""

    source_id: str
    target_id: str


def re_materialize_relation_category(graph: models.Graph, relation_category: models.EdgeCategory) -> models.EdgeCategory:
    """
    Docstring for re_materialize_relation_category

    :param graph: Description
    :type graph: models.Graph
    :param relation_category: Description
    :type relation_category: models.EdgeCategory
    :return: Description
    :rtype: EdgeCategory
    """

    sources = relation_category.get_matching_source_entities()
    target = relation_category.get_matching_target_entities()

    models.MaterializedEdge.objects.filter(graph=graph, relation=relation_category).delete()

    for source_cat, target_cat in product(sources, target):
        models.MaterializedEdge.objects.create(
            graph=graph,
            relation=relation_category,
            source=source_cat,
            target=target_cat,
        )

    return relation_category


def re_materialize_from_entity_category(graph: models.Graph, entity_category: models.EntityCategory) -> models.EntityCategory:
    # Get all relation categories where this entity category might be a source or target
    as_potential_input_relations = models.RelationCategory.objects.filter(
        graph=graph,
    ).filter(Q(source_definition__category___contains=[entity_category.pk]) | Q(target_definition__tags___contains=[entity_category.tags]))

    for relation_category in as_potential_input_relations:
        re_materialize_relation_category(graph, relation_category)


def materialize(
    definition: GraphDefinitionModel,
    engine: CypherEngine,
    user: User,
    organization: Organization,
    membership: Membership,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> models.Graph:
    """
    Materialize a graph based on the provided graph definition.

    This creates all database models from the schema definition:
    - Graph: The root graph container
    - EntityCategory: For each entity definition
    - RelationCategory: For each relation definition
    - NaturalEventCategory: For each event definition
    - GraphSchema: The schema definition

    Args:
        definition: GraphDefinitionModel containing the graph schema definition
        engine: The CypherEngine to execute queries against
        name: Optional name for the graph (defaults to "graph_{hash}")
        description: Optional description for the graph
        user: Optional user for the graph (required for production)
        organization: Optional organization for the graph (required for production)
        membership: Optional membership for the graph (required for production)

    Returns:
        The materialized Graph instance with all related models created
    """

    # Compute schema hash for versioning
    schema_hash = compute_definition_hash(definition)

    # Generate name if not provided
    if name is None:
        name = f"graph_{schema_hash}"

    # Create unique age_name
    age_name = models.Graph.create_age_name(name, organization)

    # Create the Graph
    graph = models.Graph.objects.create(
        name=name,
        description=description or f"Graph materialized from schema v{definition.system_version}",
        age_name=age_name,
        user=user,
        organization=organization,
        membership=membership,
    )

    # Create the AGE graph in the database
    try:
        engine.create_graph(age_name=age_name)
    except Exception as e:
        if "already exists" not in str(e):
            raise

    # Create EntityCategories
    for entity_def in definition.extensions.entities:
        property_defs = [p.model_dump(mode="json") for p in entity_def.properties]
        props_hash = compute_properties_hash(property_defs)

        models.EntityCategory.objects.create(
            graph=graph,
            age_name=entity_def.key,
            label=entity_def.key,
            description=entity_def.description or "",
            property_definitions=property_defs,
            schema_hash=props_hash,
        )

    # Create RelationCategories
    for relation_def in definition.extensions.relations:
        # Handle source/target that can be string or list
        source = relation_def.source if isinstance(relation_def.source, list) else [relation_def.source]
        target = relation_def.target if isinstance(relation_def.target, list) else [relation_def.target]

        source_def = {"types": source, "cardinality": relation_def.cardinality}
        target_def = {"types": target, "cardinality": relation_def.cardinality}

        # Get properties from materialization config if present
        property_defs = []
        if relation_def.materialization:
            property_defs = [p.model_dump(mode="json") for p in relation_def.materialization.properties]

        models.RelationCategory.objects.create(
            graph=graph,
            age_name=relation_def.key,
            label=relation_def.key,
            description=getattr(relation_def, "description", None) or "",
            source_definition=source_def,
            target_definition=target_def,
        )

    # Create NaturalEventCategories
    for event_def in definition.extensions.events:
        property_defs = [p.model_dump(mode="json") for p in event_def.properties]
        props_hash = compute_properties_hash(property_defs)

        # Map inputs/outputs to source/target roles
        source_roles = [p.model_dump(mode="json") for p in event_def.inputs]
        target_roles = [p.model_dump(mode="json") for p in event_def.outputs]

        models.NaturalEventCategory.objects.create(
            graph=graph,
            age_name=event_def.key,
            label=event_def.key,
            description=getattr(event_def, "description", None) or "",
            property_definitions=property_defs,
            schema_hash=props_hash,
            source_entity_roles=source_roles,
            target_entity_roles=target_roles,
        )

    # Create the GraphSchema
    models.GraphSchema.objects.create(
        graph=graph,
        version=definition.system_version,
        index=1,
        definition=definition.model_dump(mode="json"),
        is_active=True,
        created_by=user,
    )

    for category in graph.relation_categories.all():
        re_materialize_relation_category(graph, category)

    return graph
