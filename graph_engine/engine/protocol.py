"""
Graph Engine Protocols

Defines the protocols (interfaces) for graph engines and graph contexts.
"""

from typing import Any, Dict, List, Protocol, runtime_checkable, TYPE_CHECKING

if TYPE_CHECKING:
    from graph_engine.input_models import GraphDefinitionModel


@runtime_checkable
class GraphProtocol(Protocol):
    """
    Protocol for a graph that provides its AGE name and schema definition.
    This is what the engine and controller receive to know which graph to operate on.
    """

    def get_age_name(self) -> str:
        """The Apache AGE graph name (e.g., 'org_123_graph')."""
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

    def get_age_name(self) -> str:
        """The Apache AGE graph name. Satisfies GraphProtocol."""
        return self._age_name

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

    def create_graph(
        self,
        age_name: str,
    ) -> None:
        """
        Create a new graph in the database, if it does not already exist.

        Args:
            age_name: The Apache AGE graph name to create
        """
        ...

    def drop_graph(
        self,
        age_name: str,
        cascade: bool = True,
    ) -> None:
        """
        Drop a graph and everything in it.

        The projection tier is disposable by design, so dropping and replaying is a
        routine operation, not an exceptional one. Test teardown and `reproject` both
        rely on this being part of the seam.

        Args:
            age_name: The Apache AGE graph name to drop
            cascade: Whether to drop dependent objects as well
        """
        ...
