"""The label strings the read side recognises.

**Nothing here is ever written to the drawing.** `Projector.draw_node` labels
a vertex with `category.age_name` — the category's key, chosen by whoever defined
the schema — and `project_edges` / `project_participation` label edges the same
way. So these are names the *reader* invents for rows that have no vertex, not
names the writer produces.

Seven more constants used to live here and were read by nothing at all:
`DESCRIBES`, `INFORMS`, `ASSERTED`, `GENERATED`, `REIFIES_AS_SOURCE`,
`REIFIES_AS_TARGET` and `ShadowLink`. They named relationship types from an
earlier design in which provenance and structure-to-entity links were drawn edges;
`evidence.Link` replaced all of them, and `evidence/models.py` says so. Keeping
the constants made that design look current to anyone grepping for it — an
`INFORMS` here and an `evidence.Link.Kind.INFORMS` there, spelled identically,
meaning different things, only one of them live.

`Entity`, `ProtocolEvent` and `NaturalEvent` were three more, and they were read
by `VocabNodeTypeMap` alone — a map from a vertex's label to what kind of thing it
is. A drawn vertex is labelled with the category's `age_name`, so it carried one
of those three words only if a schema author happened to pick it, and the map's
default sent everything else to `"ENTITY"`: every drawn event answered
`__typename: Entity`. The kind is read from the claim now — `create_vertex` writes
`type` from `Instance.kind` — so there is nothing left to recognise a label for.
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
