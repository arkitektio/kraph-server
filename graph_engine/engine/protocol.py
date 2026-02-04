"""
Graph Engine Protocols

Defines the protocols (interfaces) for graph engines and graph contexts.
"""
from typing import Any, Dict, List, Protocol, runtime_checkable, TYPE_CHECKING

if TYPE_CHECKING:
    from graph_engine.base_models import GraphDefinitionModel


@runtime_checkable
class GraphProtocol(Protocol):
    """
    Protocol for a graph that provides its AGE name and schema definition.
    This is what the engine and controller receive to know which graph to operate on.
    """
    
    @property
    def age_name(self) -> str:
        """The Apache AGE graph name (e.g., 'org_123_graph')."""
        ...
    
    @property
    def definition(self) -> "GraphDefinitionModel":
        """The graph schema definition."""
        ...


class SimpleGraph:
    """
    A simple implementation of GraphProtocol for testing and basic usage.
    """
    
    def __init__(self, age_name: str, definition: "GraphDefinitionModel") -> None:
        if not age_name:
            raise ValueError("age_name cannot be empty")
        if definition is None:
            raise ValueError("definition cannot be None")
        self._age_name = age_name
        self._definition = definition
    
    @property
    def age_name(self) -> str:
        return self._age_name
    
    @property
    def definition(self) -> "GraphDefinitionModel":
        return self._definition


@runtime_checkable
class CypherEngine(Protocol):
    """
    Protocol defining how we interact with the graph database.
    Implementations could be a RealAgeEngine or a MockCypherEngine.
    
    The execute method takes a GraphProtocol to know which graph to query.
    """
    
    def execute(
        self, 
        graph: GraphProtocol,
        query: str, 
        params: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a Cypher query against a graph.
        
        Args:
            graph: The graph protocol providing age_name and definition
            query: The Cypher query string (may contain $param placeholders)
            params: Optional dictionary of parameters to substitute
            
        Returns:
            List of dictionaries representing rows of results
        """
        ...
