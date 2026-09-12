# RFC 0008 — Trust is view-scoped for every contestable claim

- **Status:** **Implemented**, substantially amended by RFC 0009: the *mechanism*
  (both halves of trust folding through `claims.standing(predicate=…)`) survives
  whole, but the predicate is built per **category** (its definition's clauses),
  not per graph — `Graph.selector` is gone. Deliberately rolled back: the panel
  and sameness returned to organization grain (a view cannot veto a merge). The
  `_contributing_metrics` leak this RFC missed is closed and pinned by 0009's
  regression tests.
- (original status) A record, like 0004–0007: which claim kinds fold
  under a view's selector, which stay organization grain and why, and the one
  SQL footnote that will bite anyone who touches the fold.
- **Question:** RFC 0007 made two things per-view — whose *existence* claims
  count (`claim_filter` → `retracted_ids`) and which classification claims a
  *category's definition* believes. Everything else still folded organization-
  wide: a view drew every standing relation whose word it declared, whoever
  claimed it; a link retracted by anybody vanished from every view
  (`CurrentStanding` has no selector); sameness components unioned everybody's
  `SAME_AS` claims; and three metric-adjacent reads skipped the selector that
  `_scoped_state` honored. Should "whose claims count" mean the same thing for
  every contestable claim kind?
- **Recommendation (taken):** Yes. One selector, one meaning, every table. The
  graph's `claim_filter` — phrased over `assertion__*` paths, so it applies to
  any row with an assertion — now scopes both **the claim itself** and **its
  standing**, for every kind where a view's disagreement is meaningful.

## The mechanism

`claims.standing(queryset, target_type, predicate=None)` grew the predicate the
rest of the family (`stands_for`, `retracted_ids`) always had. Without one it is
the `CurrentStanding` anti-join — the organization-wide cache, still the fast
path for the selectorless view, which is every view by default. With one it
folds the log directly: the newest predicate-matching `Standing` about each row
decides, and a row nobody-the-view-counts has spoken about stands.

The footnote: the fold is spelled `filter(Q(stands=True) | Q(isnull=True))`,
never `exclude(_view_stands=False)` — under SQL's three-valued logic
`NOT (NULL = FALSE)` is `NULL`, and the exclude silently drops every undisputed
row. It did, for one test run.

Everywhere a view is in scope, two halves apply together:

- **the claim scope**: `.filter(claim_filter(graph.selector))` on the claim
  rows themselves — an untrusted annotator's relation draws no edge, their
  `INFORMS` link routes no evidence, their `SAME_AS` merges nothing *here*;
- **the standing predicate**: `standing(..., predicate=view_predicate(...))` —
  an untrusted retraction takes nothing away either.

## What became view-scoped

| Read | Where |
|---|---|
| Relation edges (claims and their standing, `__assertion_count` follows) | `projector.active_relation_links`, `controller._reproject_proposition` |
| Participation edges — moves with relations, shared grouping keys | `projector.active_participation_links`, `controller._reproject_participation` |
| Classification standing (which retractions a view counts; *which claims mean a category* stays the definition's question — RFC 0007) | `selector.classification_claims_for` |
| Metric standing | `selector.metrics_for`, `projector._scoped_state` |
| Evidence links (`INFORMS`) — claim and standing; the metrics were scoped while the link routing them was not | `selector.informs_links_for` |
| **Three closed leaks**: PRIORITY_LATEST / LATEST_ASSERTION_TOOL read metrics directly and skipped `metric_filter`; so did the `valid_from`/`valid_to` observation window | `projector._priority_scoped_value`, `projector._observation_window` |
| **Sameness** — the user-facing point: "this view does not accept the bot's merge". A scoped view's component is a walk of the sameness claims it counts (`identity.component_refs_for_view`, the same frontier loop `recompute` uses); the org-grain `InstanceIdentity` cache is untouched and serves every unscoped view | `evidence/identity.py`, threaded through `evidence/panel.py` (`components_for`/`labels_for`/`sameness_for`/`connections_for`/`known_about` take a `graph`) |
| The panel over the API: a drawn node's `component`/`labels`/`sameAs`/`connections` are the answer of **the view it was read from** — loader keys are `(graph_handle, ref)`, resolved internally from our own drawn record (the handle is still never accepted as input, RFC 0006). A claim-grain `Instance` read has no view by construction and stays organization grain | `api/loaders.py::_batch_known_about_nodes`, `api/types.py` |

The write paths agree with the rebuild: `_reproject_proposition` /
`_reproject_participation` compute survivors under the same two predicates the
replay reads through `active_*` — the divergence class `retract_node` had
(fixed in RFC 0007) does not reopen for links.

## Deliberately organization grain, still

- **The identity cache.** `InstanceIdentity` folds everybody, on purpose: a
  per-view cache means `(graph, instance)` rows — a graph FK inside
  `evidence/`, which that app may not grow. Scoped views pay a read-time walk
  instead; it is seeded by the page's refs over the indexed
  `(organization, kind, source_ref)` and costs the component, not the log.
- **`CurrentStanding`.** Still selector-less, and now honestly named: it is the
  fast path, consulted only when no predicate is in play.
- **Structures and comments.** A structure is a pointer, idempotent by
  `(identifier, object)`; a comment's standing has no view. Unchanged, as
  RFC 0007 recorded.
- **`State`.** Organization grain as ever; `_scoped_state` narrows on read.

## Amends RFC 0007

Its "Deliberately left" recorded link standing as organization-wide with the
asymmetry pinned by `test_link_retraction_is_organization_wide`. That test is
now `test_link_claims_and_their_retractions_fold_per_view`, asserting the
opposite, on purpose: somebody asked (the thing 0007 said had not happened).

## What would count as regressing this RFC

- A standing fold that reaches `CurrentStanding` while a predicate is in play,
  or a new claim-kind read that applies only one of the two halves.
- A per-view identity **cache** (the read-time walk is the design).
- `exclude(...=False)` over the standing annotation — the three-valued-logic
  trap above.
- A panel or component read for a *drawn* node that ignores the view it was
  drawn in.
