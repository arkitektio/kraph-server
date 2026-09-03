# A worked example

This document walks through one graph schema and what it does to the claims
people record. `RULES.md` is the reference for the rule language; this is the
same thing shown on one lab.

## Claims first, graphs second

Claims are not recorded against a graph. Nobody writes "into" a graph.

A claim names a **word**. `assertEntityExists(input: {term: "AIS"})` records
that somebody, through some app, at some time, said "this is an AIS". The
mutation has no `graph` argument. Neither does any other instance write:
retracting, attesting, measuring, linking, saying two observations are the
same. Every one of them lands in the organization's log and stays there.

A graph is a view over that log. Each of its categories says, for one word or
several, which of those claims count. Every graph reads the same log and draws
what its own categories admit. Nothing about a claim changes because a graph
exists, or because one does not.

Three graphs over the same log:

- `ais-lab`, the schema below: Peter's `AIS` claims and Karl's December
  `AxonInitialSegment` claims become AIS vertices; a student's `AIS` claim does
  not.
- `everything`, with a primitive `AIS` category: all of them become AIS
  vertices, the student's too.
- `cells-only`, with no category naming `AIS` or `AxonInitialSegment`: none
  of them appear. The claims are still there; this view has no word for them.

Create a fourth graph tomorrow with `backfill: true` and it draws whatever its
categories admit from the claims that already exist. Delete a graph and no
claim goes with it.

The one place a graph appears in a write's result is `drawings`: the list of
views that draw the claim now. That is reporting where it landed, not choosing
where it goes.

## The schema

The organization is a neuroscience lab. A segmentation pipeline finds cells.
Peter annotates axon initial segments under the word `AIS`; Karl annotated the
same structures for years under `AxonInitialSegment`. A curator decides when
two observations are one thing. A measurement pipeline produces lengths.

This is the `createGraph` input, with comments.

```jsonc
{
  "name": "ais-lab",
  "definition": {
    "systemVersion": "1.0.0",
    "extensions": {

      // ── entities ─────────────────────────────────────────────────────────
      "entities": [

        // 1. Cell is primitive. No definition, so any "Cell" claim from anyone
        //    counts: classification, retraction, sameness, measurements, all of it.
        { "key": "Cell" },

        // 2. AIS carries the rules.
        {
          "key": "AIS",
          "definition": {
            "rules": [

              // Rule A: Peter's annotations, except the ones that came through
              //    the sloppy import, and not his merges.
              { "when": [
                  { "field": "WORD",    "operator": "IS",     "value": "AIS" },
                  { "field": "SUBJECT", "operator": "IS",     "value": "peter" },
                  { "field": "KIND",    "operator": "NOT_IN", "value": ["SAMENESS"] }
                ],
                "unless": [
                  { "when": [ { "field": "APP", "operator": "IS", "value": "sloppy-import" } ] }
                ] },

              // Rule B: Karl's old word counts as AIS too, but only what he
              //    asserted after the December re-annotation, and not his merges.
              { "when": [
                  { "field": "WORD",        "operator": "IS",     "value": "AxonInitialSegment" },
                  { "field": "SUBJECT",     "operator": "IS",     "value": "karl" },
                  { "field": "ASSERTED_AT", "operator": "SINCE",  "value": "2026-12-05T00:00:00Z" },
                  { "field": "KIND",        "operator": "NOT_IN", "value": ["SAMENESS"] }
                ] },

              // Rule C: only the curator may say two AIS observations are one.
              { "when": [
                  { "field": "KIND",    "operator": "IS", "value": "SAMENESS" },
                  { "field": "SUBJECT", "operator": "IS", "value": "curator" }
                ] },

              // Rule D: by default, lengths count only from segmenter-v3,
              //    observed after the microscope was recalibrated in June.
              { "when": [
                  { "field": "KIND",        "operator": "IS",    "value": "MEASUREMENT" },
                  { "field": "APP",         "operator": "IS",    "value": "segmenter-v3" },
                  { "field": "KEY",         "operator": "IS",    "value": "vector_length" },
                  { "field": "MEASURED_AT", "operator": "SINCE", "value": "2026-06-01T00:00:00Z" }
                ] },

              // Rule E: areas come from a different tool, any time.
              { "when": [
                  { "field": "KIND", "operator": "IS", "value": "MEASUREMENT" },
                  { "field": "APP",  "operator": "IS", "value": "area-tool" },
                  { "field": "KEY",  "operator": "IS", "value": "area" }
                ] }
            ]
          },
          "propertyDefinitions": [

            // Uses the category's MEASUREMENT rules. Only rule D admits
            // `vector_length` rows, so this is segmenter-v3 since June.
            { "key": "length", "valueKind": "FLOAT", "derivation": "ROLLUP",
              "rule": { "sourceNode": "ROI", "key": "vector_length", "aggregation": "MEAN" } },

            // Same rules, other key: rule E admits `area` rows from area-tool.
            { "key": "area", "valueKind": "FLOAT", "derivation": "ROLLUP",
              "rule": { "sourceNode": "ROI", "key": "area", "aggregation": "MEAN" } },

            // Has its own rules. They replace D and E for this property; they
            // do not intersect with them. "segmenter-v3, or segmenter-v2 for
            // anything measured before June that did not come through the old
            // pipeline".
            { "key": "any_length", "valueKind": "FLOAT", "derivation": "ROLLUP",
              "rule": { "sourceNode": "ROI", "key": "vector_length", "aggregation": "MEAN",
                        "evidence": { "rules": [
                          { "when": [ { "field": "APP", "operator": "IS", "value": "segmenter-v3" } ] },
                          { "when": [ { "field": "APP",         "operator": "IS",     "value": "segmenter-v2" },
                                      { "field": "MEASURED_AT", "operator": "BEFORE", "value": "2026-06-01T00:00:00Z" } ],
                            "unless": [ { "when": [ { "field": "ACTION", "operator": "IS", "value": "old-pipeline" } ] } ] }
                        ] } } }
          ]
        }
      ],

      // ── relations between entities ───────────────────────────────────────
      "relations": [
        // 3. Only Karl's PART_OF edges are drawn. Peter's are in the log, not here.
        { "key": "PART_OF",
          "source": { "keys": ["AIS"] }, "target": { "keys": ["Cell"] },
          "definition": { "rules": [
            { "when": [ { "field": "WORD",    "operator": "IS", "value": "PART_OF" },
                        { "field": "SUBJECT", "operator": "IS", "value": "karl" } ] } ] } }
      ],

      // ── events ───────────────────────────────────────────────────────────
      "events": [
        // 4. Two words, one category, one app. The event annotator's "Mitosis"
        //    and "CellDivision" events both draw as Mitosis.
        { "key": "Mitosis", "kind": "INTRINSIC", "inputs": [], "outputs": [],
          "definition": { "rules": [
            { "when": [ { "field": "WORD", "operator": "IN", "value": ["Mitosis", "CellDivision"] },
                        { "field": "APP",  "operator": "IS", "value": "event-annotator" } ] } ] } }
      ],

      // ── structure relations (ROI to ROI) ─────────────────────────────────
      "structureRelations": [
        // 5. Adjacency between ROIs as the curator says it, under either word.
        { "key": "ADJACENT_TO",
          "source": { "identifiers": ["ROI"] }, "target": { "identifiers": ["ROI"] },
          "definition": { "rules": [
            { "when": [ { "field": "WORD",    "operator": "IN", "value": ["ADJACENT_TO", "ABUTS"] },
                        { "field": "SUBJECT", "operator": "IS", "value": "curator" } ] } ] } }
      ],

      // ── measurements (ROI to entity) ─────────────────────────────────────
      "measurements": [
        // 6. Which "this ROI shows this thing" claims count: anything but the bot.
        { "key": "SHOWS",
          "source": { "identifiers": ["ROI"] }, "target": { "keys": ["Cell", "AIS"] },
          "definition": { "rules": [
            { "when": [ { "field": "WORD", "operator": "IS",     "value": "SHOWS" },
                        { "field": "APP",  "operator": "NOT_IN", "value": ["untrusted-bot"] } ] } ] } }
      ]
    }
  }
}
```

## What the view makes of the log

People keep recording claims the same way as before the graph existed. Below,
"drawn" means "drawn in `ais-lab`". Every claim mentioned is in the log
regardless.

**Classification.** Peter asserts `AIS`: drawn (rule A). Peter's `AIS` claim
that arrived through `sloppy-import`: not drawn (the `unless`). Karl's
`AxonInitialSegment` from November: not drawn; from December 6th: drawn as AIS
(rule B). Anyone's `Cell`: drawn (primitive). A student's `AIS`: not drawn, no
rule names them.

**Existence.** Peter retracts one of his AIS nodes: it disappears here, because
rule A covers EXISTENCE (nothing in it excludes that kind). The student retracts
Peter's node: nothing happens here. The curator retracts it: also nothing,
rule C covers SAMENESS only. In `everything`, where AIS is primitive, the
curator's retraction does remove the node.

**Sameness.** Peter says two of his AIS observations are one
(`assertEntityExists(input: {term: "AIS", sameAs: [...]})`): recorded, but
this graph keeps two vertices, because rule A took SAMENESS away from him. The
curator says Peter's `AIS` and Karl's `AxonInitialSegment` are one: one
component in this view, rule C, and both observations resolve to the AIS
category even though the words differ. The curator says an AIS and a Cell are
one: never merges in any view. Sameness is within a category.
`Entity.component` and `sameAs` on a drawn AIS answer per this graph;
`instance(id:)` still gives the organization-wide component.

**Properties.** `length` averages `vector_length` over the ROIs that inform the
node, counting only measurements from `segmenter-v3` observed since June: of
the category's MEASUREMENT rules, only rule D admits `vector_length` rows.
`area` reads `area` rows, which only rule E admits, so it is area-tool's
values from any time. A `vector_length` from area-tool, or an `area` from
segmenter-v3, counts for nothing. `any_length` ignores D and E and applies its
own rules: segmenter-v3, or segmenter-v2's pre-June observations unless they
came through the old pipeline. Which ROIs inform the node at all is the
EVIDENCE kind; rules A and B cover it, so Peter's and Karl's INFORMS links
route measurements in and a bot's INFORMS link does not.

**Edges.** `PART_OF` from Karl: drawn. From Peter: not. Karl retracts his edge:
gone (his rule covers EXISTENCE). Peter retracts Karl's edge: still drawn.

**Events.** `CellDivision` from the event annotator app: drawn as a Mitosis
event with its participations. `Mitosis` typed in by hand by Peter: not drawn.

**Structure relations and measurements.** Nothing is drawn for these.
`structureRelations(structureRelationCategoryId:)` lists the curator's
`ADJACENT_TO` and `ABUTS` claims and nobody else's;
`measurements(measurementCategoryId:)` lists every `SHOWS` claim except the
bot's. The lists read the rules live, so changing one of these definitions
needs no rebuild.

**Who can change the schema.** The graph's owner, an admin of the
organization, or a superuser can create, update or delete these categories.
Everyone in the organization can read the graph and record claims.

## What this does not express

There is no whole-graph "as of" cursor. Freezing the view at a date means an
`ASSERTED_AT BEFORE` condition in every category's rules. That is by decision
(RFC 0014): a graph-wide cursor would be the graph-level scope RFC 0009
removed, under a different name.

`RULES.md`, "What is settled and what is not", is the canonical list.
