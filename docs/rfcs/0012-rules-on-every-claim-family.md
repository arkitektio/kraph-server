# RFC 0012 — Rules on every claim-based category family

- **Status:** Implemented.
- **Question:** After RFC 0009–0011, entity, relation and natural event
  categories carried rule lists, but structure relation and measurement
  categories could not, and protocol event categories only half could. The
  user: "implement the same for structure relation and events and measurements,
  they are all claim based."
- **What was done:** All five families now carry the same `definition`.

## Changes

- `StructureRelationDefinitionInput` and `MeasurementDefinitionInput` gained
  `definition`, stored by `materialize` and by the create mutations (the shared
  edge-category manager writes it).
- `UpdateStructureRelationCategoryInput`, `UpdateMeasurementCategoryInput` and
  `UpdateProtocolEventCategoryInput` gained `definition` / `clearDefinition`,
  with the same exclusivity rule as the other update inputs.
- `createProtocolEventCategory` stores the definition it already accepted.
  A protocol event definition change rebuilds the drawing, because
  participation edges are drawn; structure relation and measurement changes do
  not rebuild, because nothing is drawn for them — their claim lists read the
  rules live.
- `links_for_category` (the `relations`, `structureRelations` and
  `measurements` list queries) applies the category's rules: a defined category
  lists the claims its rules admit, standings folded under its EXISTENCE trust.
  A primitive category lists every claim naming its word, as before.
- Participation folding already handled protocol event categories
  (`active_participation_links` iterates both event kinds); the tests now pin
  it under a protocol event's own rules.

## Not changed

- Structure relations and measurements are still not drawn. Their rules govern
  the claim lists, nothing else.
- `GraphExtensionsInput` still has no `protocol_events` list; protocol event
  categories are created through their mutation, not the schema document.

## Tests

`tests/schema/test_definitions_across_kinds.py` is a schema zoo built from the
pydantic input models: schemas that must build (definitions on each family,
KIND splits, unless groups, NOT_IN, derived words), schemas that must be
refused, materialization checks for stored definitions and vocabulary rows, and
behavior tests for structure relation claims, measurement claims, the update
mutations, and protocol event participations.
