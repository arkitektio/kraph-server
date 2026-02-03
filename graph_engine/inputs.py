"""
Graph Engine Strawberry GraphQL Inputs

Defines Strawberry input types that map to Pydantic models.
All inputs are converted to Pydantic models before entering the Controller.
"""
import strawberry
from typing import Optional
from enum import Enum

from core import scalars


@strawberry.enum
class GraphOperationInput(Enum):
    """Operations that can be performed on graph nodes."""
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    MERGE = "MERGE"


@strawberry.input(description="Provenance information for tracking changes")
class ProvenanceInput:
    tool_name: str = strawberry.field(
        description="The name of the tool/application making the change"
    )
    confidence: float = strawberry.field(
        default=1.0,
        description="Confidence level of the assertion (0.0 to 1.0)"
    )
    assignation_id: Optional[str] = strawberry.field(
        default=None,
        description="The task/assignation ID if from a workflow"
    )
    metadata: Optional[scalars.Any] = strawberry.field(
        default=None,
        description="Additional metadata about the provenance"
    )


@strawberry.input(description="A single node change operation")
class NodeChangeInput:
    label: str = strawberry.field(
        description="The node label/type (e.g., 'Person', 'Entity')"
    )
    ref_id: Optional[str] = strawberry.field(
        default=None,
        description="Reference ID for linking within this batch (not a DB ID)"
    )
    id: Optional[strawberry.ID] = strawberry.field(
        default=None,
        description="Real database ID (graph_name:node_id format) for UPDATE/DELETE"
    )
    operation: GraphOperationInput = strawberry.field(
        default=GraphOperationInput.CREATE,
        description="The operation to perform on this node"
    )
    properties: Optional[scalars.Any] = strawberry.field(
        default=None,
        description="Properties to set on the node"
    )
    external_id: Optional[str] = strawberry.field(
        default=None,
        description="External ID for upsert operations (used with MERGE)"
    )


@strawberry.input(description="A single edge/relationship change")
class EdgeChangeInput:
    from_id: str = strawberry.field(
        description="Source node ID (ref:xxx for batch ref, or graph:id for DB ID)"
    )
    to_id: str = strawberry.field(
        description="Target node ID (ref:xxx for batch ref, or graph:id for DB ID)"
    )
    label: str = strawberry.field(
        description="The edge label/type (e.g., 'RELATES_TO', 'BELONGS_TO')"
    )
    properties: Optional[scalars.Any] = strawberry.field(
        default=None,
        description="Properties to set on the edge"
    )


@strawberry.input(description="Complete payload for a graph mutation operation")
class GraphMutationPayloadInput:
    graph_id: strawberry.ID = strawberry.field(
        description="The graph ID (age_name) to apply changes to"
    )
    provenance: ProvenanceInput = strawberry.field(
        description="Provenance information for this mutation"
    )
    nodes: Optional[list[NodeChangeInput]] = strawberry.field(
        default=None,
        description="List of node changes to apply"
    )
    edges: Optional[list[EdgeChangeInput]] = strawberry.field(
        default=None,
        description="List of edge changes to apply"
    )


@strawberry.input(description="Input for running a migration query")
class RunMigrationInput:
    graph_id: strawberry.ID = strawberry.field(
        description="The graph ID to run the migration on"
    )
    cypher_query: str = strawberry.field(
        description="The Cypher query to execute"
    )
    dry_run: bool = strawberry.field(
        default=False,
        description="If True, validate but don't execute"
    )


# Response types

@strawberry.type(description="Result of a single node operation")
class NodeResultType:
    ref_id: Optional[str] = None
    db_id: str = strawberry.field(description="The database ID (graph:node_id)")
    label: str
    operation: str
    success: bool
    error: Optional[str] = None


@strawberry.type(description="Result of a single edge operation")
class EdgeResultType:
    db_id: str = strawberry.field(description="The database ID of the created edge")
    from_id: str
    to_id: str
    label: str
    success: bool
    error: Optional[str] = None


@strawberry.type(description="Result of a graph mutation operation")
class GraphMutationResultType:
    success: bool = strawberry.field(
        description="Whether the entire mutation succeeded"
    )
    transaction_id: str = strawberry.field(
        description="Unique ID for this transaction"
    )
    id_map: scalars.Any = strawberry.field(
        description="Mapping of ref_id -> real db_id for created nodes"
    )
    assertion_id: Optional[str] = strawberry.field(
        default=None,
        description="The ID of the provenance assertion node"
    )
    nodes: list[NodeResultType] = strawberry.field(
        description="Results for each node operation"
    )
    edges: list[EdgeResultType] = strawberry.field(
        description="Results for each edge operation"
    )
    errors: list[str] = strawberry.field(
        description="List of errors encountered"
    )


@strawberry.type(description="Result of a migration operation")
class MigrationResultType:
    status: str = strawberry.field(description="Status of the migration")
    affected_count: Optional[int] = strawberry.field(
        default=None,
        description="Number of affected records"
    )
    query: Optional[str] = strawberry.field(
        default=None,
        description="The executed query"
    )
    original_query: Optional[str] = strawberry.field(
        default=None,
        description="The original query (for dry run)"
    )
    safe_query: Optional[str] = strawberry.field(
        default=None,
        description="The safe query with LIMIT (for dry run)"
    )
