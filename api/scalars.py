"""
GraphQL Scalar types for the API.
"""
import strawberry
from typing import Any, NewType


# Scalar for arbitrary JSON-like values
AnyScalar = strawberry.scalar(
    NewType("AnyScalar", Any),
    description="A scalar that can hold any JSON-compatible value (string, number, boolean, list, object)",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

# Scalar for Unix timestamp in milliseconds
UnixMilliseconds = strawberry.scalar(
    NewType("UnixMilliseconds", int),
    description="Unix timestamp in milliseconds since epoch",
    serialize=lambda v: v,
    parse_value=lambda v: int(v) if v is not None else None,
)

# Scalar for structure identifier (e.g. "@mikro/roi")
StructureIdentifier = strawberry.scalar(
    NewType("StructureIdentifier", str),
    description="A structure identifier (e.g. '@mikro/roi', 'told_you_so')",
    serialize=lambda v: v,
    parse_value=lambda v: str(v),
)

# Global ID scalar in format "graph_name:graph_id"
GlobalID = strawberry.scalar(
    NewType("GlobalID", str),
    description="A global identifier in format 'graph_name:graph_id'",
    serialize=lambda v: v,
    parse_value=lambda v: str(v),
)
