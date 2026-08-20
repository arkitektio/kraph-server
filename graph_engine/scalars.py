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

# `GraphName` is gone too: it typed the Apache AGE namespace so that
# `api/context.py` could look a graph up by it. The handle is random and internal
# now, and a graph is addressed by its primary key.

# `GraphID` is gone, and it joins the list below.
#
# It was a `NewType` over `str` registered as a pass-through scalar
# (`serialize=lambda v: v`), so it validated nothing and its only effect was on
# the name in the SDL. That name was wrong twice over, as its own comment used to
# admit: it is not a graph's id and has no graph component — it once meant the
# composite "{graph_id}:{local_id}", back when identity was a graph plus an
# Apache AGE vertex id — and it was applied to organization-scoped claim primary
# keys (`structure(id:)`, `metric(metricId:)`, `instance(id:)`, `link(id:)`).
#
# It was also only half applied. `standings(id:)`, `term(id:)`,
# `entityCategory(id:)` and every saved-query fetcher took plain `ID` for the
# same kind of value, and every id the schema *returns* is `ID` — so one value
# had two spellings, and a client could not tell from the type which it held.
# Every id argument is `ID` now.
#
# `StructureGlobalID` ("@mikro/roi:433"), `GlobalID` and `LocalID` are gone too.
# `LocalID` was registered in the schema and annotated by no field or argument at
# all; `StructureGlobalID` was used by nothing; `GlobalID` typed two fields whose
# vertex property nothing ever wrote, so they raised.

# Cypher literal scalar for raw Cypher queries or fragments
CypherLiteral = NewType("CypherLiteral", str)
