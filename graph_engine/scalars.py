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

# Scalar for Graph ID (UUID string)
StructureObject = NewType("StructureObject", str)

# Global ID scalar in format "uuid"
GlobalID = NewType("GlobalID", str)

# Composite ID scalar "graph_id:local_id"
GraphName = NewType("GraphName", str)

# Local ID scalar (integer)
LocalID = NewType("LocalID", int)

# Graph ID scalar (integer)
GraphID = NewType("GraphID", str)

# Cypher literal scalar for raw Cypher queries or fragments
CypherLiteral = NewType("CypherLiteral", str)
