"""The label strings the read side recognises.

**Nothing here is ever written to Apache AGE.** `projector.create_vertex` labels
a vertex with `category.age_name` — the category's key, chosen by whoever defined
the schema — and `project_edges` / `project_participation` label edges the same
way. So these are names the *reader* looks for, not names the writer produces,
and `VocabNodeTypeMap` in `graph_engine/retrieved.py` is the one place they are
consulted.

Seven more constants used to live here and were read by nothing at all:
`DESCRIBES`, `INFORMS`, `ASSERTED`, `GENERATED`, `REIFIES_AS_SOURCE`,
`REIFIES_AS_TARGET` and `ShadowLink`. They named relationship types from an
earlier design in which provenance and structure-to-entity links were AGE edges;
`evidence.Link` replaced all of them, and `evidence/models.py` says so. Keeping
the constants made that design look current to anyone grepping for it — an
`INFORMS` here and an `evidence.Link.Kind.INFORMS` there, spelled identically,
meaning different things, only one of them live.
"""

#: Labels the adapters in `graph_engine/retrieved.py` construct for rows that
#: have no vertex at all — a structure and a metric are Postgres rows, and these
#: are what their in-memory node-shaped form is labelled with.
#:
#: `Assertion` used to be a third. It labelled `RetrievedAssertion`, the adapter
#: behind the `Activity` GraphQL type, whose two queries matched a vertex nothing
#: has ever drawn and so always came back empty. An assertion is served as the
#: Django row now and needs no label.
Structure = "Structure"
Metric = "Metric"

#: Labels `VocabNodeTypeMap` recognises when discriminating a node read out of a
#: projection. A vertex only carries one of these if somebody happened to name a
#: category key exactly so; the reliable discriminator is the `type` property,
#: which `RetrievedNode.node_type` checks first.
Entity = "Entity"
ProtocolEvent = "ProtocolEvent"
NaturalEvent = "NaturalEvent"
