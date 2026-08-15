"""Redrawing a category's vertices when its properties change — the in-request half.

The bill for the rule that a read is a graph query: the vertex is the answer, so
changing the question has to rewrite it.

**Full write-up, including why this runs synchronously and what to do when that
bites: [`docs/REMATERIALIZATION.md`](../../../docs/REMATERIALIZATION.md).** The
short version, because it decides how the code below reads:

- The snapshot is taken **before** the write. Nothing versions
  `Category.property_definitions`, so once the row is saved, what the old
  definition owned is gone — and with it the knowledge of which vertex keys are
  now orphaned. That is the only thing this half can do that
  `manage.py rematerialize` cannot.
- The **hash is the trigger**, not the fact that a mutation ran.
  `create_*_category` is an `update_or_create` whose manager swallows `created`,
  so comparing fingerprints answers the question `created` cannot: did the
  properties *move*.
- It runs inside the request and is unbounded in the size of the graph. Accepted,
  stated, and detectable — `manage.py rematerialize --stale` finds what an
  unfinished redraw left behind.
- Node categories only: an edge carries `category_id` and `__assertion_count` and
  nothing derived, so there is nothing on one to go stale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api import context


@dataclass(frozen=True)
class Fingerprint:
    """What a category's properties looked like at one moment.

    Both halves are needed and neither substitutes for the other: the hash
    decides *whether* to redraw, the key set says what to sweep. The hash alone
    cannot name an orphaned key, and the key set alone cannot tell a reordering
    from a change — `compute_properties_hash` is what the rest of the schema
    layer already trusts for that question.

    A frozen dataclass rather than the tuple this used to be, because the two
    halves are not interchangeable and `before[1] - after[1]` said nothing about
    which side of the subtraction retires a key. Immutable because it is a
    *before* snapshot: a fingerprint that could be edited after the write is a
    fingerprint that cannot be compared against.
    """

    #: `compute_properties_hash` over the category's stored property definitions.
    properties_hash: str
    #: The vertex property keys this category's definition currently owns.
    derived_keys: frozenset[str]


def fingerprint(category: Any) -> Fingerprint:
    """What a category's properties look like right now."""
    from graph_engine import projector
    from graph_engine.materialize import compute_properties_hash

    return Fingerprint(
        properties_hash=compute_properties_hash(category.property_definitions or []),
        derived_keys=frozenset(projector.derived_property_keys(category)),
    )


def rematerialize_if_moved(category: Any, before: Fingerprint) -> int:
    """Redraw the category's vertices if its properties changed. Returns how many.

    Cheap when nothing moved — an equal hash returns without touching AGE, which
    is the common case, since most `update_*_category` calls are relabelling.

    Still needed after a `backfill`, which is why the resolvers run both. A
    backfill goes through `project_all` or `rebuild` and re-derives every
    property, but it derives with `SET` — it widens *membership* and has no
    reason to know that a key on an existing vertex is now an orphan. Sweeping
    those is this function's job alone.

    Note which removal this cannot see: `EntityCategoryManager` keeps the old
    definitions when the incoming list is empty (`property_defs or
    category.property_definitions`), so clearing the *last* property is
    unreachable through the API and the hash does not move. Partial removal —
    dropping one of several — works, and is what the tests exercise.
    """
    after = fingerprint(category)
    if after.properties_hash == before.properties_hash:
        return 0

    return context.get_controller().rematerialize_category(category, retired_keys=before.derived_keys - after.derived_keys)
