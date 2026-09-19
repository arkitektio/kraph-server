# RFC 0026: A category's word always means it in its view

**Status: Implemented** (2026-09-18).

## Question

Declaring a category declares a word: `CategoryManager._term_for` mints the
category's key as the organization's `Term`, on every creation path. A view
whose `CuratedAIS` is *defined* as "anything claimed AIS or
AxonInitialSegment" has therefore introduced a new word built from two
existing ones. What happens when somebody claims that word directly, as in
"a new CuratedAIS here"?

## Finding

The claim was accepted, and it made the node a member of the view (the word is
one the view declares, so `instances_for` and `graph_ids_for_instance_ids`
both count it). But nothing admitted it. `resolve_categories` honoured a
category's own word only when the category was **primitive**. A defined
category admitted exactly what `classification_filter(definition)` matched,
and its rules named `AIS` and `AxonInitialSegment`, not `CuratedAIS`. So the
node was skipped as "admitted by no category" in the very view that minted the
word. Defined relation and event categories behaved the same way in
`_admitted_by`.

## Decision

- **A category admits its own word.** A defined category admits what its rules
  match *and* every claim naming its own term. The rules extend the word; they
  do not replace it. Standings for own-word claims fold at organization grain,
  from anyone, exactly as a primitive category's do. A primitive category is
  the special case where the rules name nothing.
- **Unless its rules name that word.** Then the rules govern it. EXAMPLE.md's
  `AIS` counts Peter's `AIS` and refuses a student's. An implicit clause that
  admitted the student would silently undo the one rule saying otherwise.
- **Every category kind**: node categories (entities, both event kinds) in
  `resolve_categories`, and the edge lanes (relations, participations) in
  `_admitted_by`.

A third case follows from the same rule: a defined category whose rules cover
no classification at all (a definition with only `KIND MEASUREMENT` rules, for
example) names no word. It used to admit nothing, because its definition was
non-empty and it matched no classification claim. It now admits its own word
from anyone, like a primitive category. That is deliberate. Its rules say
whose measurements count, not what the word means.

One predicate, `evidence.selector.admits_own_word(category)`, answers this
everywhere: `resolve_categories`, `_admitted_by`, `refs_admitted_by`'s
candidate narrowing, and the API's `links_for_category`, so the drawing and
the lists cannot disagree.

**Unchanged.** Membership (`term_ids_for`, `_graph_ids_by_term`) already
counted the declared word. `backfill_category` already rebuilds whenever a
definition names words. Existence still folds per category under the
category's own `EXISTENCE` trust (RFC 0009). An own-word node in a defined
category is retracted for that view only by someone its rules trust.
