from typing import Dict, List, Any, TYPE_CHECKING
import re

if TYPE_CHECKING:
    from graph_engine.engine.protocol import GraphProtocol


class MockCypherEngine:
    """
    A test double that records queries instead of running them.

    Automatically generates sensible return values for common query patterns:
    - CREATE with RETURN id(x) -> returns a fake graph ID
    - CREATE with RETURN x.id -> returns the id from params
    - MATCH queries return empty results by default
    """

    def __init__(self) -> None:
        self.log: List[tuple] = []  # Stores (graph, query, params) tuples
        self.return_values: List[List[Dict[str, Any]]] = []  # Stack of fake results to pop
        self._next_id = 844424930131969  # Start with a realistic AGE ID
        self.created_graphs: List[str] = []
        self.dropped_graphs: List[str] = []

    def init_db(self) -> None:
        """Nothing to prepare. Satisfies CypherEngine."""

    def create_graph(self, age_name: str) -> None:
        """Record graph creation. Satisfies CypherEngine."""
        self.created_graphs.append(age_name)

    def drop_graph(self, age_name: str, cascade: bool = True) -> None:
        """Record graph deletion. Satisfies CypherEngine."""
        self.dropped_graphs.append(age_name)

    @property
    def query_log(self) -> List[tuple]:
        """Alias for log for better readability in tests."""
        return self.log

    def execute(
        self,
        graph: "GraphProtocol",
        query: str,
        params: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        """Execute a query and record it."""
        params = params or {}

        # Normalize whitespace for easier testing comparison
        clean_query = " ".join(query.split())
        self.log.append((graph.get_age_name() if graph else None, clean_query, params))

        # Return user-provided values first
        if self.return_values:
            return self.return_values.pop(0)

        # Auto-generate sensible return values based on query patterns
        return self._auto_generate_result(clean_query, params)

    def _auto_generate_result(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Generate sensible default return values based on query patterns.
        """
        query_upper = query.upper()
        result = {}

        # Pattern: id(x) as alias - AGE graph ID
        id_patterns = re.findall(r"\bid\((\w+)\)\s+as\s+(\w+)", query, re.IGNORECASE)
        for var, alias in id_patterns:
            result[alias] = self._get_next_id()

        # Pattern: x.property as alias - property access
        prop_patterns = re.findall(r"(\w+)\.(\w+)\s+as\s+(\w+)", query, re.IGNORECASE)
        for var, prop, alias in prop_patterns:
            # Look for the property in params with various prefixes
            if prop in params:
                result[alias] = params[prop]
            elif f"prop_{prop}" in params:
                result[alias] = params[f"prop_{prop}"]
            elif prop == "id" and "eid" in params:
                result[alias] = params["eid"]
            else:
                result[alias] = f"mock_{alias}"

        if result:
            return [result]

        # Pattern: MATCH with aggregation (avg, sum, count, etc.)
        agg_match = re.search(r"(avg|sum|count|min|max)\([^)]+\)\s+as\s+(\w+)", query, re.IGNORECASE)
        if agg_match:
            func, alias = agg_match.groups()
            # Return None for aggregations (no data)
            return [{alias: None}]

        # Pattern: RETURN ... ORDER BY ... LIMIT 1 (LATEST-style query)
        if "ORDER BY" in query_upper and "LIMIT 1" in query_upper:
            val_match = re.search(r"(\w+)\.value\s+as\s+(\w+)", query, re.IGNORECASE)
            if val_match:
                _, alias = val_match.groups()
                return [{alias: None}]

        # Default: return empty list
        return []

    def _get_next_id(self) -> int:
        """Get a unique graph ID."""
        current = self._next_id
        self._next_id += 1
        return current

    def set_return_value(self, result: List[Dict[str, Any]]) -> None:
        """Set the next return value."""
        self.return_values.append(result)

    def set_return_values(self, results: List[List[Dict[str, Any]]]) -> None:
        """Set multiple return values in order."""
        self.return_values.extend(results)

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

    def clear(self) -> None:
        """Clear all recorded queries and return values."""
        self.log.clear()
        self.return_values.clear()
