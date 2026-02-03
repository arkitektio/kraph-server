from typing import Dict, List, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from graph_engine.engine.protocol import GraphProtocol


class MockCypherEngine:
    """
    A test double that records queries instead of running them.
    """
    def __init__(self):
        self.log: List[tuple] = []  # Stores (graph, query, params) tuples
        self.return_values: List[List[Dict[str, Any]]] = []  # Stack of fake results to pop

    def execute(
        self, 
        graph: "GraphProtocol",
        query: str, 
        params: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        """Execute a query and record it."""
        # Normalize whitespace for easier testing comparison
        clean_query = " ".join(query.split())
        self.log.append((graph.age_name if graph else None, clean_query, params or {}))
        
        if self.return_values:
            return self.return_values.pop(0)
        return []

    def assert_called_with(self, partial_query: str) -> bool:
        """Helper to check if a snippet of Cypher was executed."""
        for _, q, _ in self.log:
            if partial_query in q:
                return True
        raise AssertionError(f"Query snippet '{partial_query}' not found in log: {[q for _, q, _ in self.log]}")
    
    def get_queries(self) -> List[str]:
        """Get all recorded queries."""
        return [q for _, q, _ in self.log]
    
    def get_graph_names(self) -> List[str]:
        """Get all graph names that were queried."""
        return [g for g, _, _ in self.log if g]