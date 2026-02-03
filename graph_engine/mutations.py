"""
Graph Engine Mutations

Strawberry GraphQL mutations for the graph engine.
All inputs are converted to Pydantic models before processing.
"""
import strawberry
from typing import Optional
from kante.types import Info
from pydantic import ValidationError

from .inputs import (
    GraphMutationPayloadInput,
    RunMigrationInput,
    GraphMutationResultType,
    MigrationResultType,
    NodeResultType,
    EdgeResultType,
)
from .types import (
    GraphOperation,
    NodeChangeModel,
    EdgeChangeModel,
    ProvenanceModel,
    GraphMutationPayload,
)
from .controller import GraphController


def _convert_to_pydantic(input: GraphMutationPayloadInput, info: Info) -> GraphMutationPayload:
    """
    Convert Strawberry input to Pydantic model.
    
    This triggers Pydantic validation immediately, raising errors
    if the input format is wrong.
    """
    # Convert provenance
    provenance = ProvenanceModel(
        tool_name=input.provenance.tool_name,
        confidence=input.provenance.confidence,
        user_id=str(info.context.request.user.id) if info.context.request.user else None,
        client_id=str(info.context.request.client.client_id) if hasattr(info.context.request, 'client') and info.context.request.client else None,
        assignation_id=input.provenance.assignation_id,
        metadata=input.provenance.metadata or {},
    )
    
    # Convert nodes
    nodes = []
    if input.nodes:
        for node_input in input.nodes:
            nodes.append(NodeChangeModel(
                ref_id=node_input.ref_id,
                id=str(node_input.id) if node_input.id else None,
                label=node_input.label,
                operation=GraphOperation(node_input.operation.value),
                properties=node_input.properties or {},
                external_id=node_input.external_id,
            ))
    
    # Convert edges
    edges = []
    if input.edges:
        for edge_input in input.edges:
            edges.append(EdgeChangeModel(
                from_id=edge_input.from_id,
                to_id=edge_input.to_id,
                label=edge_input.label,
                properties=edge_input.properties or {},
            ))
    
    # Create the full payload - this validates all constraints
    return GraphMutationPayload(
        graph_id=str(input.graph_id),
        provenance=provenance,
        nodes=nodes,
        edges=edges,
    )


def _result_to_type(result) -> GraphMutationResultType:
    """Convert Pydantic result to Strawberry type."""
    return GraphMutationResultType(
        success=result.success,
        transaction_id=result.transaction_id,
        id_map=result.id_map,
        assertion_id=result.assertion_id,
        nodes=[
            NodeResultType(
                ref_id=n.ref_id,
                db_id=n.db_id,
                label=n.label,
                operation=n.operation.value,
                success=n.success,
                error=n.error,
            )
            for n in result.nodes
        ],
        edges=[
            EdgeResultType(
                db_id=e.db_id,
                from_id=e.from_id,
                to_id=e.to_id,
                label=e.label,
                success=e.success,
                error=e.error,
            )
            for e in result.edges
        ],
        errors=result.errors,
    )


def perform_graph_mutation(
    info: Info,
    input: GraphMutationPayloadInput,
) -> GraphMutationResultType:
    """
    Perform a batch graph mutation atomically.
    
    This mutation:
    1. Converts Strawberry input to Pydantic models (validates format)
    2. Checks guardrails (complexity, graph size)
    3. Validates against schema (if defined)
    4. Executes all changes atomically with provenance tracking
    
    Example usage:
    ```graphql
    mutation {
        performGraphMutation(input: {
            graphId: "my_graph"
            provenance: {
                toolName: "my_tool"
                confidence: 0.95
            }
            nodes: [
                {
                    refId: "node1"
                    label: "Person"
                    operation: CREATE
                    properties: { name: "John", age: 30 }
                },
                {
                    refId: "node2"
                    label: "Organization"
                    operation: CREATE
                    properties: { name: "Acme Corp" }
                }
            ]
            edges: [
                {
                    fromId: "ref:node1"
                    toId: "ref:node2"
                    label: "WORKS_FOR"
                    properties: { since: "2020-01-01" }
                }
            ]
        }) {
            success
            transactionId
            idMap
            errors
        }
    }
    ```
    """
    # Step 1: Convert to Pydantic (triggers validation)
    try:
        payload = _convert_to_pydantic(input, info)
    except ValidationError as e:
        return GraphMutationResultType(
            success=False,
            transaction_id="",
            id_map={},
            assertion_id=None,
            nodes=[],
            edges=[],
            errors=[str(err) for err in e.errors()],
        )
    
    # Step 2: Execute via controller
    controller = GraphController()
    result = controller.execute(payload)
    
    # Step 3: Convert result to Strawberry type
    return _result_to_type(result)


def run_graph_migration(
    info: Info,
    input: RunMigrationInput,
) -> MigrationResultType:
    """
    Run a migration query on the graph.
    
    Safety features:
    - Automatically injects LIMIT clause if missing
    - Runs within a transaction with timeout
    - Supports dry run mode
    
    Example usage:
    ```graphql
    mutation {
        runGraphMigration(input: {
            graphId: "my_graph"
            cypherQuery: "MATCH (n:Person) WHERE n.status = 'old' SET n.status = 'archived'"
            dryRun: true
        }) {
            status
            affectedCount
            safeQuery
        }
    }
    ```
    """
    controller = MigrationController()
    
    try:
        result = controller.run_migration(
            graph_id=str(input.graph_id),
            cypher_query=input.cypher_query,
            dry_run=input.dry_run,
        )
        
        return MigrationResultType(
            status=result.get("status", "unknown"),
            affected_count=result.get("affected_count"),
            query=result.get("query"),
            original_query=result.get("original_query"),
            safe_query=result.get("safe_query"),
        )
    except Exception as e:
        return MigrationResultType(
            status="error",
            affected_count=None,
            query=None,
            original_query=input.cypher_query,
            safe_query=None,
        )
