"""
Graph Engine Models

Django models for the graph engine, including schema definitions.
"""
from django.db import models
from authentikate.models import Organization
from typing import Any
import re


class GraphSchemaDefinition(models.Model):
    """
    Stores user-defined schemas for graph validation.
    
    The schema defines valid node labels, required properties,
    regex validation rules, and property types.
    """
    
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="graph_schemas",
        help_text="The organization this schema belongs to",
    )
    
    graph = models.ForeignKey(
        "core.Graph",
        on_delete=models.CASCADE,
        related_name="schema_definitions",
        help_text="The graph this schema applies to",
    )
    
    name = models.CharField(
        max_length=255,
        help_text="Human-readable name for this schema version",
    )
    
    schema_json = models.JSONField(
        default=dict,
        help_text="The schema definition containing node labels, properties, and validation rules",
    )
    
    version = models.PositiveIntegerField(
        default=1,
        help_text="Schema version for evolution tracking",
    )
    
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this schema version is currently active",
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ["-version"]
        unique_together = [("graph", "version")]
        verbose_name = "Graph Schema Definition"
        verbose_name_plural = "Graph Schema Definitions"
    
    def __str__(self) -> str:
        return f"{self.name} v{self.version} ({self.graph})"
    
    def get_node_schema(self, label: str) -> dict[str, Any] | None:
        """Get the schema definition for a specific node label."""
        nodes = self.schema_json.get("nodes", {})
        return nodes.get(label)
    
    def get_edge_schema(self, label: str) -> dict[str, Any] | None:
        """Get the schema definition for a specific edge label."""
        edges = self.schema_json.get("edges", {})
        return edges.get(label)
    
    def get_valid_node_labels(self) -> list[str]:
        """Get all valid node labels defined in the schema."""
        return list(self.schema_json.get("nodes", {}).keys())
    
    def get_valid_edge_labels(self) -> list[str]:
        """Get all valid edge labels defined in the schema."""
        return list(self.schema_json.get("edges", {}).keys())
    
    def validate_node_properties(self, label: str, properties: dict[str, Any]) -> list[str]:
        """
        Validate node properties against schema rules.
        Returns a list of validation error messages.
        """
        errors = []
        node_schema = self.get_node_schema(label)
        
        if node_schema is None:
            # If no schema defined for this label, allow all properties
            return errors
        
        required_props = node_schema.get("required_properties", [])
        property_rules = node_schema.get("properties", {})
        
        # Check required properties
        for prop in required_props:
            if prop not in properties:
                errors.append(f"Missing required property '{prop}' for node label '{label}'")
        
        # Validate property types and regex patterns
        for prop_name, prop_value in properties.items():
            if prop_name in property_rules:
                rule = property_rules[prop_name]
                
                # Type validation
                expected_type = rule.get("type")
                if expected_type:
                    if expected_type == "string" and not isinstance(prop_value, str):
                        errors.append(f"Property '{prop_name}' must be a string")
                    elif expected_type == "number" and not isinstance(prop_value, (int, float)):
                        errors.append(f"Property '{prop_name}' must be a number")
                    elif expected_type == "boolean" and not isinstance(prop_value, bool):
                        errors.append(f"Property '{prop_name}' must be a boolean")
                    elif expected_type == "array" and not isinstance(prop_value, list):
                        errors.append(f"Property '{prop_name}' must be an array")
                
                # Regex validation (only for strings)
                pattern = rule.get("pattern")
                if pattern and isinstance(prop_value, str):
                    if not re.match(pattern, prop_value):
                        errors.append(
                            f"Property '{prop_name}' value '{prop_value}' "
                            f"does not match pattern '{pattern}'"
                        )
                
                # Enum validation
                allowed_values = rule.get("enum")
                if allowed_values and prop_value not in allowed_values:
                    errors.append(
                        f"Property '{prop_name}' value '{prop_value}' "
                        f"not in allowed values: {allowed_values}"
                    )
        
        return errors


# Example schema_json structure:
# {
#     "nodes": {
#         "Person": {
#             "required_properties": ["name"],
#             "properties": {
#                 "name": {"type": "string", "pattern": "^[A-Za-z ]+$"},
#                 "age": {"type": "number"},
#                 "status": {"type": "string", "enum": ["active", "inactive"]}
#             }
#         },
#         "Organization": {
#             "required_properties": ["name", "identifier"],
#             "properties": {
#                 "name": {"type": "string"},
#                 "identifier": {"type": "string", "pattern": "^ORG-[0-9]+$"}
#             }
#         }
#     },
#     "edges": {
#         "WORKS_FOR": {
#             "required_properties": [],
#             "properties": {
#                 "since": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
#                 "role": {"type": "string"}
#             }
#         }
#     }
# }
