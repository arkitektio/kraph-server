"""
GraphQL Scalar types for the API.
"""

from typing import NewType


# Scalar for arbitrary JSON-like values
AnyScalar = NewType("AnyScalar", dict)

# Scalar for Unix timestamp in milliseconds
UnixMilliseconds = NewType("UnixMilliseconds", int)

# Scalar for structure identifier (e.g. "@mikro/roi")
StructureIdentifier = NewType("StructureIdentifier", str)

# Global ID scalar in format "graph_name:graph_id"
GlobalID = NewType("GlobalID", str)
