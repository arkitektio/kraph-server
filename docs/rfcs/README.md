# RFCs

Design questions written down before anything is built. **An RFC proposes no code
change while its status is open** — it states a recommendation and the evidence
behind it, so the decision can be made deliberately rather than discovered
halfway through an implementation. A finding recorded in an open RFC is
deliberately left unfixed in the code; fixing it is a separate, explicit act.

An RFC whose recommendation has since been built says **Implemented** in its
status line, and is kept as the record of why rather than as an open question.
Its findings *are* fixed, and its text describes what it replaced.

| # | Question | Recommendation |
|---|---|---|
| [0001](0001-materialized-categories.md) | Can "materialized categories" go away, given the definition and the term? | No — the definition is derived *from* the categories, not the reverse. Shrink the row instead, and rename the concept. |
| [0002](0002-term-structurekind-metrickind.md) | Are `Term`, `StructureKind` and `MetricKind` the same thing? | Same pattern, not the same thing — one vocabulary per claim target. Extract the shared half; don't merge the tables. |
| [0003](0003-undrawn-nodes.md) | Should a write return a `RetrievedNode` when no graph draws it? | **Implemented.** No — a write asserts existence and returns the assertion plus every view that draws the claim. |
