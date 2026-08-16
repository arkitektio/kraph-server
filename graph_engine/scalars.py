"""
GraphQL Scalar types for the API.
"""

from typing import NewType


# Scalar for arbitrary JSON-like values
AnyScalar = NewType("AnyScalar", str)

# Scalar for Unix timestamp in milliseconds
UnixMilliseconds = NewType("UnixMilliseconds", int)

# Scalar for structure identifier (e.g. "@mikro/roi")
StructureIdentifier = NewType("StructureIdentifier", str)

# Scalar for Graph ID (UUID string)
StructureObject = NewType("StructureObject", str)

# The AGE namespace a graph is drawn in. Internal — it never crosses the API
# boundary; `api/context.py` uses it to look a graph up by name.
GraphName = NewType("GraphName", str)

# What every instance id in this API is: **a bare uuid**. The name is historical
# — it once meant the composite "{graph_id}:{local_id}", back when identity was a
# graph plus an Apache AGE vertex id. It is not a graph's id and has no graph
# component; the one field that genuinely names a graph is the subscription's
# `graphId`.
GraphID = NewType("GraphID", str)

# `StructureGlobalID` ("@mikro/roi:433"), `GlobalID` and `LocalID` are gone.
# `LocalID` was registered in the schema and annotated by no field or argument at
# all; `StructureGlobalID` was used by nothing; `GlobalID` typed two fields whose
# vertex property nothing ever wrote, so they raised.

# Cypher literal scalar for raw Cypher queries or fragments
CypherLiteral = NewType("CypherLiteral", str)
