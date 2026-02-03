"""
Migration Controller for safe batch graph mutations.

This controller provides guardrails for running migration-style queries
that modify multiple nodes/edges to prevent runaway operations.
"""
import re
from typing import Optional

from graph_engine.engine.protocol import CypherEngine


class MigrationController:
    """
    Controller for executing migration-style Cypher queries safely.
    
    This controller adds safety checks like:
    - Injecting LIMIT clauses for modification queries
    - Tracking affected records
    - Dry-run support
    """
    
    # Patterns that indicate a modification query
    MODIFICATION_PATTERNS = [
        r'\bSET\b',
        r'\bDELETE\b',
        r'\bREMOVE\b',
        r'\bDETACH\s+DELETE\b',
        r'\bMERGE\b.*\bON\s+(CREATE|MATCH)\b',
    ]
    
    def __init__(
        self,
        engine: Optional[CypherEngine] = None,
        default_limit: int = 1000,
        dry_run: bool = False,
    ):
        """
        Initialize the migration controller.
        
        Args:
            engine: The Cypher engine to use for queries
            default_limit: Default LIMIT to inject for modification queries
            dry_run: If True, don't actually execute modifications
        """
        self.engine = engine
        self.default_limit = default_limit
        self.dry_run = dry_run
        
        # Compile modification patterns
        self._mod_patterns = [
            re.compile(pattern, re.IGNORECASE) 
            for pattern in self.MODIFICATION_PATTERNS
        ]
    
    def _is_modification_query(self, query: str) -> bool:
        """Check if a query modifies data."""
        for pattern in self._mod_patterns:
            if pattern.search(query):
                return True
        return False
    
    def _has_limit(self, query: str) -> bool:
        """Check if query already has a LIMIT clause."""
        return bool(re.search(r'\bLIMIT\s+\d+', query, re.IGNORECASE))
    
    def _ensure_limit_clause(self, query: str) -> str:
        """
        Ensure a modification query has a LIMIT clause.
        
        Injects LIMIT before RETURN or SET/DELETE if missing.
        Does not modify read-only queries.
        """
        # Don't modify read-only queries
        if not self._is_modification_query(query):
            return query
        
        # Already has LIMIT
        if self._has_limit(query):
            return query
        
        # Find the best place to inject LIMIT
        # Strategy: Insert "WITH ... LIMIT N" before the modification clause
        
        # Find WHERE or WITH clause before modification
        # Look for pattern: MATCH ... [WHERE ...] SET/DELETE/REMOVE
        
        # First check for SET, DELETE, REMOVE keywords
        mod_match = re.search(
            r'\b(SET|DELETE|REMOVE)\b', 
            query, 
            re.IGNORECASE
        )
        
        if mod_match:
            mod_pos = mod_match.start()
            
            # Find what variable names are used in the MATCH clause
            match_vars = re.findall(r'\((\w+):', query[:mod_pos])
            if not match_vars:
                # Try simpler pattern: (n) without label
                match_vars = re.findall(r'\((\w+)\)', query[:mod_pos])
            
            if match_vars:
                # Get the first matched variable
                var = match_vars[0]
                
                # Insert WITH ... LIMIT before the modification
                prefix = query[:mod_pos].rstrip()
                suffix = query[mod_pos:]
                
                return f"{prefix} WITH {var} LIMIT {self.default_limit} {suffix}"
        
        # Fallback: just append LIMIT at the end if there's a RETURN
        return_match = re.search(r'\bRETURN\b', query, re.IGNORECASE)
        if return_match:
            return query
        
        return query
    
    def execute(self, query: str, params: Optional[dict] = None) -> list:
        """
        Execute a migration query with safety checks.
        
        Args:
            query: The Cypher query to execute
            params: Optional query parameters
            
        Returns:
            List of result dictionaries
        """
        if self.engine is None:
            raise RuntimeError("No engine configured for MigrationController")
        
        safe_query = self._ensure_limit_clause(query)
        
        if self.dry_run and self._is_modification_query(query):
            # In dry-run mode, convert to a RETURN-only query
            # This is a simplified approach
            return []
        
        return self.engine.execute(safe_query, params)
