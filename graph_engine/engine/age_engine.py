"""
Apache AGE Cypher Engine

A real implementation of CypherEngine that executes queries against Apache AGE.
"""
import json
import re
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional

from django.db import connections

from .protocol import GraphProtocol


@contextmanager
def graph_cursor(connection_name: str = "default") -> Generator:
    """
    Create a cursor configured for Apache AGE queries.
    
    Args:
        connection_name: The Django database connection to use
        
    Yields:
        A cursor with AGE loaded and search_path configured
    """
    with connections[connection_name].cursor() as cursor:
        cursor.execute("LOAD 'age';")
        cursor.execute('SET search_path = ag_catalog, "$user", public')
        yield cursor


class AgeEngine:
    """
    Real Apache AGE engine that executes Cypher queries against PostgreSQL.
    
    This engine wraps Cypher queries in the appropriate `cypher()` function
    call that AGE requires. It takes a GraphProtocol on each execute call
    to determine which graph to query.
    """
    
    def __init__(
        self,
        connection_name: str = "default",
        statement_timeout_ms: Optional[int] = None,
    ):
        """
        Initialize the AGE engine.
        
        Args:
            connection_name: The Django database connection to use
            statement_timeout_ms: Optional timeout for queries
        """
        self.connection_name = connection_name
        self.statement_timeout_ms = statement_timeout_ms
    
    def execute(
        self, 
        graph: GraphProtocol,
        query: str, 
        params: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a Cypher query against the specified graph.
        
        The query should be written in standard Cypher syntax.
        Parameters can use $param_name notation and will be substituted safely.
        
        Args:
            graph: The graph protocol providing age_name and definition
            query: The Cypher query string
            params: Optional dictionary of parameters
            
        Returns:
            List of dictionaries representing rows of results
        """
        params = params or {}
        graph_name = graph.age_name
        
        print(f"Executing Cypher on graph '{graph_name}': {query} with params {params}")
        
        with graph_cursor(self.connection_name) as cursor:
            # Set statement timeout if configured
            if self.statement_timeout_ms:
                cursor.execute(f"SET LOCAL statement_timeout = '{self.statement_timeout_ms}ms'")
            
            # Substitute parameters into the query
            processed_query = self._substitute_params(query, params, cursor)
            
            # Determine the return columns from the query
            return_columns = self._extract_return_columns(query)
            
            # Build the column type spec for the cypher() function
            if return_columns:
                column_spec = ", ".join([f"{col} agtype" for col in return_columns])
            else:
                column_spec = "result agtype"
            
            # Wrap in AGE cypher() function
            age_query = f"""
                SELECT * FROM cypher('{graph_name}', $$
                    {processed_query}
                $$) as ({column_spec});
            """
            
            cursor.execute(age_query)
            rows = cursor.fetchall()
            
            # Parse results
            results = []
            for row in rows:
                row_dict = {}
                for i, col_name in enumerate(return_columns if return_columns else ["result"]):
                    raw_value = row[i]
                    row_dict[col_name] = self._parse_agtype(raw_value)
                results.append(row_dict)
            
            return results
    
    def execute_raw(self, query: str, params: Dict[str, Any] | None = None) -> List[tuple]:
        """
        Execute a raw SQL query (not wrapped in cypher()).
        
        Useful for administrative commands like create_graph, create_vlabel, etc.
        
        Args:
            query: The raw SQL query
            params: Optional parameters (using %s placeholders)
            
        Returns:
            Raw cursor results as list of tuples
        """
        params = params or {}
        
        with graph_cursor(self.connection_name) as cursor:
            if self.statement_timeout_ms:
                cursor.execute(f"SET LOCAL statement_timeout = '{self.statement_timeout_ms}ms'")
            
            cursor.execute(query, list(params.values()) if params else None)
            
            try:
                return cursor.fetchall()
            except Exception:
                return []
    
    def create_graph(self, graph_name: str) -> None:
        """Create an AGE graph if it doesn't exist."""
        try:
            self.execute_raw(f"SELECT * FROM ag_catalog.create_graph('{graph_name}')")
        except Exception as e:
            if "already exists" not in str(e):
                raise
    
    def drop_graph(self, graph_name: str, cascade: bool = True) -> None:
        """Drop an AGE graph."""
        cascade_str = "true" if cascade else "false"
        self.execute_raw(f"SELECT * FROM ag_catalog.drop_graph('{graph_name}', {cascade_str})")
    
    def _substitute_params(self, query: str, params: Dict[str, Any], cursor: Any) -> str:
        """
        Substitute $param placeholders with escaped values.
        
        AGE's cypher() function doesn't support parameterized queries the same way
        as standard SQL, so we need to safely substitute values into the query.
        """
        result = query
        
        # Sort by key length descending to replace longer keys first
        # This prevents $confidence from matching inside $confidence_type
        sorted_keys = sorted(params.keys(), key=len, reverse=True)
        
        for key in sorted_keys:
            value = params[key]
            placeholder = f"${key}"
            if placeholder in result:
                escaped = self._escape_for_cypher(value, cursor)
                result = result.replace(placeholder, escaped)
        
        return result
    
    def _escape_for_cypher(self, value: Any, cursor: Any) -> str:
        """Escape a value for safe use in Cypher."""
        if value is None:
            return "null"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            # Escape single quotes and wrap in quotes
            escaped = value.replace("'", "\\'")
            return f"'{escaped}'"
        elif isinstance(value, dict):
            # Convert dict to Cypher map syntax
            items = []
            for k, v in value.items():
                items.append(f"{k}: {self._escape_for_cypher(v, cursor)}")
            return "{" + ", ".join(items) + "}"
        elif isinstance(value, list):
            # Convert list to Cypher array syntax
            items = [self._escape_for_cypher(v, cursor) for v in value]
            return "[" + ", ".join(items) + "]"
        else:
            # Fallback: convert to string
            escaped = str(value).replace("'", "\\'")
            return f"'{escaped}'"
    
    def _extract_return_columns(self, query: str) -> List[str]:
        """
        Extract column names from the RETURN clause of a Cypher query.
        
        Handles:
        - Simple returns: RETURN n, m
        - Aliased returns: RETURN n.name as name, id(n) as id
        - Aggregations: RETURN count(n) as cnt
        """
        # Find the RETURN clause
        match = re.search(r'\bRETURN\s+(.+?)(?:\s+ORDER\s+BY|\s+LIMIT|\s+SKIP|\s*$)', query, re.IGNORECASE | re.DOTALL)
        
        if not match:
            return []
        
        return_clause = match.group(1).strip()
        
        # Split by comma (but not commas inside parentheses or brackets)
        columns = []
        current = ""
        depth = 0
        
        for char in return_clause:
            if char in "([{":
                depth += 1
                current += char
            elif char in ")]}":
                depth -= 1
                current += char
            elif char == "," and depth == 0:
                columns.append(current.strip())
                current = ""
            else:
                current += char
        
        if current.strip():
            columns.append(current.strip())
        
        # Extract column names (handle aliases)
        result = []
        for col in columns:
            # Check for AS alias
            alias_match = re.search(r'\s+[aA][sS]\s+(\w+)\s*$', col)
            if alias_match:
                result.append(alias_match.group(1))
            else:
                # Use the last identifier as the name
                simple_match = re.match(r'^(\w+)$', col.strip())
                if simple_match:
                    result.append(simple_match.group(1))
                else:
                    # For complex expressions without alias, create a sanitized name
                    sanitized = re.sub(r'[^\w]', '_', col.strip())
                    result.append(sanitized[:50])  # Limit length
        
        return result
    
    def _parse_agtype(self, value: Any) -> Any:
        """
        Parse an AGE agtype value into Python types.
        
        AGE returns values as strings with type suffixes like:
        - "123::integer"
        - "\"hello\"::text"
        - "{\"id\": 123, \"label\": \"Person\", \"properties\": {...}}::vertex"
        """
        if value is None:
            return None
        
        if not isinstance(value, str):
            return value
        
        # Remove type suffix
        type_suffixes = ["::vertex", "::edge", "::agtype", "::integer", "::float", "::text", "::boolean", "::null"]
        cleaned = value
        for suffix in type_suffixes:
            if cleaned.endswith(suffix):
                cleaned = cleaned[:-len(suffix)]
                break
        
        # Try to parse as JSON (vertices and edges are JSON objects)
        try:
            parsed = json.loads(cleaned)
            return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        
        # Return as-is if not JSON
        return cleaned
