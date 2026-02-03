from typing import Dict, List, Optional, Any
from core.scalars import Any


class MockCypherEngine:
    """
    A test double that records queries instead of running them.
    """
    def __init__(self):
        self.log = []  # Stores (query, params) tuples
        self.return_values = [] # Stack of fake results to pop

    def execute(self, query: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        # Normalize whitespace for easier testing comparison
        clean_query = " ".join(query.split())
        self.log.append((clean_query, params or {}))
        
        if self.return_values:
            return self.return_values.pop(0)
        return []

    def assert_called_with(self, partial_query: str):
        """Helper to check if a snippet of Cypher was executed."""
        for q, _ in self.log:
            if partial_query in q:
                return True
        raise AssertionError(f"Query snippet '{partial_query}' not found in log: {[q for q, _ in self.log]}")