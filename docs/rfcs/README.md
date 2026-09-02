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
| [0001](0001-materialized-categories.md) | Can "materialized categories" go away, given the definition and the term? | No — the definition is derived *from* the categories, not the reverse. Shrink the row instead, and rename the concept. **§6 implemented:** the separate `Materialized*Edge` tables are removed — that cache had no invalidation at all. |
| [0002](0002-term-structurekind-metrickind.md) | Are `Term`, `StructureKind` and `MetricKind` the same thing? | Same pattern, not the same thing — one vocabulary per claim target. Extract the shared half; don't merge the tables. |
| [0003](0003-undrawn-nodes.md) | Should a write return a `RetrievedNode` when no graph draws it? | **Implemented.** No — a write asserts existence and returns the assertion plus every view that draws the claim. |
| [0004](0004-the-graph-is-a-projection.md) | Where was the graph still not a projection, and what would a second projection kind need? | **Implemented.** Name the seam (`Projector`), keep the projection's standing in Postgres (outbox + derived cursor), make the saved-query contract a plan, make the view's handle random and internal. |
| [0005](0005-retire-the-cypher-projection.md) | What was Apache AGE still buying, given that every query the repo emits is a fixed-hop join? | **Implemented.** Nothing worth its costs. The table projection (`TableProjector` over `ProjectionVertex`/`ProjectionEdge`) is the projection; Cypher, the engine seam and agtype are deleted; the protocol, outbox and watermark stay exactly as 0004 built them. |
| [0006](0006-the-namespace-is-a-derived-artifact.md) | Can AGE's per-graph namespace — the schema-level answer to "what ends up in this graph?" — come back on PostgreSQL 19's native SQL/PGQ? | **Implemented.** Yes, as a derived artifact: one schema + property graph per graph, generated wholesale from the `Category` rows by `refresh_namespace`; a composite FK makes the database refuse a vertex drawn under an undeclared category; `render_table` compiles plans to `GRAPH_TABLE`. Amends two lines of 0005, knowingly. |
| [0007](0007-a-definition-is-a-union-of-clauses.md) | Can a view say "'Cell' means what Peter called Cell, and what Karl called StemCell after Dec 5"? | **Implemented.** A definition is a union of clauses (`any_of`), each binding its own words, annotators and time bounds; `since` joins `as_of` in all three claim filters; both predicates gained a structured GraphQL surface; retraction became symmetric with attestation (folded per view at write time). Link standing stays organization-wide, deliberately. |

**These files keep the old vocabulary on purpose.** `Node` (the row) is `Instance`,
`Claim` is `Standing`, and the `*Assertion` write payloads are `Asserted*` — see the
vocabulary table in `CLAUDE.md` and `evidence/migrations/0008_instance_and_standing.py`.
An RFC is a record of a decision taken at a point in time, so rewriting its nouns
would make it a worse record; read it against the table.
