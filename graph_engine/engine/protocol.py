"""
Graph Engine Protocols

Defines the protocols (interfaces) for graph engines and graph contexts.
"""
from typing import Any, Dict, List, Protocol, Optional, runtime_checkable
from dataclasses import dataclass


@runtime_checkable
class CypherEngine(Protocol):
    """
    Protocol defining how we interact with the graph database.
    Implementations could be a RealAgeEngine or a MockCypherEngine.
    """
    
    def execute(self, query: str, params: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        """
        Execute a Cypher query and return results.
        
        Args:
            query: The Cypher query string (may contain $param placeholders)
            params: Optional dictionary of parameters to substitute
            
        Returns:
            List of dictionaries representing rows of results
        """
        ...


@runtime_checkable
class GraphContext(Protocol):
    """
    Protocol for a graph context that provides the age_name and schema.
    This is what the controller receives to know which graph to operate on.
    """
    
    @property
    def age_name(self) -> str:
        """The Apache AGE graph name (e.g., 'my_org_graph')."""
        ...
    
    @property
    def organization_id(self) -> str:
        """The organization ID this graph belongs to."""
        ...


@dataclass
class SimpleGraphContext:
    """
    A simple implementation of GraphContext for testing and basic usage.
    """
    age_name: str
    organization_id: str
    
    def __post_init__(self):
        if not self.age_name:
            raise ValueError("age_name cannot be empty")


@runtime_checkable
class GraphWithDefinition(Protocol):
    """
    Extended graph context that includes a schema definition.
    Used when schema validation is required.
    """
    
    @property
    def age_name(self) -> str:
        """The Apache AGE graph name."""
        ...
    
    @property
    def organization_id(self) -> str:
        """The organization ID."""
        ...
    
    @property
    def definition(self) -> Optional[Dict[str, Any]]:
        """
        The graph schema definition (JSON structure).
        Can be None if no schema is defined.
        """
        ...


@dataclass
class GraphContextWithDefinition:
    """
    A graph context that includes schema definition for validation.
    """
    age_name: str
    organization_id: str
    definition: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if not self.age_name:
            raise ValueError("age_name cannot be empty")

