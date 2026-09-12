"""The request-bound half of writing a category, shared by all six kinds.

A category write has two halves. What the row *is* — the term it declares, the
label, the rule, the endpoints, the roles — belongs to `core/managers.py`, which
knows nothing about a request and is therefore reachable from `materialize` and
from a management command as well as from here. What is left is the part that
genuinely needs the caller: who is asking (RBAC), whose pin it is, and what the
projection owes afterwards. That is this module.

The split is borrowed from the app this one replaced. `core-backup-do-not-delete`
gave every category mutation a `<noun>_creator(...)` carrying the logic and a thin
`create_<noun>(info, input)` that only unpacked the input — and `create_graph`
bootstrapped a whole ontology by calling the creators directly. The rewrite kept
the mutations and lost the seam, so `graph_engine/materialize.py` grew a second,
divergent way to create the same rows and the six modules became copies of each
other. `diff natural_event_category.py protocol_event_category.py` was 115 lines
over a 136-line file, and every substantive difference in it was a slip:
one had `definition=` in its `defaults` and the other did not.

Three things below look like they could be parameters and are deliberately not:

- **`node=`** gates the rematerialize. `_rematerialize`'s "node categories only"
  is a fact about edges, not an unfinished rollout: an edge carries `category_id`
  and `__assertion_count` and nothing derived, so there is nothing on one to go
  stale.
- **`rebuild_on_rule_change=`** is false for measurement and structure relation,
  which draw nothing at all — their claim lists read the rules live and the
  vocabulary index follows the category-save signal.
- **`patch=`** exists because an entity category's update input carries
  `property_definitions` and `instance_kind` while the other five are the
  all-optional patch shape. Entity passes its manager method; the rest take the
  default.
"""

from typing import Callable, Optional

import strawberry

from api import context
from ._guards import delete_or_explain, refuse_bad_color
from ._rematerialize import fingerprint, rematerialize_if_moved
from .._scoped import schema_graph, schema_scoped


def _patch_fields(item, model, manager) -> bool:
    """The all-optional patch every category update but entity's applies.

    `or item.x` throughout: these inputs cannot distinguish "not provided" from
    "explicitly empty", which is a property of the input shape rather than a
    decision made here.

    Returns whether it persisted the row itself. This one does not; a patch that
    delegates to a manager method does, and saying so is what keeps
    `update_category` from saving a second time. A second save is not a harmless
    no-op here — every `Category.save()` fires the signal that drops and recreates
    the graph's namespace schema (RFC 0006), so saving twice does that DDL twice.
    """
    item.label = model.label if model.label else item.label
    item.description = model.description if model.description else item.description
    item.color = model.color if model.color else item.color

    store_id = manager._resolve_store_id(getattr(model, "image", None))
    if store_id is not None:
        # `image_id`, not `image` — see the comment in
        # `NodeCategoryManager.acreate_from_node_definition`, which records what
        # naming the wrong attribute here used to cost.
        item.image_id = store_id

    # The category's rule (RFC 0009 / RFC 0012): replaced whole, cleared to
    # primitive, or left alone. The input model refuses the first two together.
    if getattr(model, "clear_definition", False):
        item.definition = {}
    elif getattr(model, "definition", None) is not None:
        item.definition = model.definition.to_stored()

    return False


def create_category(info, model, proxy, creator: Callable, *, node: bool):
    """Declare a category, then settle what the declaration owes the projection.

    `creator` is the manager method that writes the row — the half that does not
    need a request. Everything here does.
    """
    refuse_bad_color(getattr(model, "color", None))

    graph = schema_graph(info, model.graph)

    # An upsert on `(graph, key)`, so this may well be an edit to a category that
    # already draws vertices, and the manager does not report which. Snapshotted
    # before the write because nothing versions `property_definitions`: one line
    # later, which keys the old definition owned is unrecoverable. See
    # `_rematerialize`.
    before = None
    if node:
        existing = proxy.objects.filter(graph=graph, key=model.key).first()
        before = fingerprint(existing) if existing else None

    category = creator(graph, model)

    proxy.objects._apply_pin(category, info.context.request.user, getattr(model, "pin", None))

    if getattr(model, "backfill", False):
        context.get_controller().backfill_category(category)

    if before is not None:
        # After the backfill, not instead of it: a backfill widens membership and
        # re-derives through `SET`, and only this path `REMOVE`s the keys a
        # dropped property left behind.
        rematerialize_if_moved(category, before)

    return category


def update_category(
    info,
    model,
    proxy,
    *,
    what: str,
    node: bool,
    rebuild_on_rule_change: bool,
    patch: Optional[Callable] = None,
):
    """Patch a category, then settle what the change owes the projection."""
    item = schema_scoped(info, proxy, model.id, what=what)

    refuse_bad_color(getattr(model, "color", None))

    # Both snapshots come before the write: nothing versions either, so one line
    # later the old values are gone and with them the ability to tell what moved.
    before = fingerprint(item) if node else None
    meaning_before = dict(item.definition or {})

    persisted = (patch or _patch_fields)(item, model, proxy.objects)

    proxy.objects._apply_pin(item, info.context.request.user, getattr(model, "pin", None))

    if not persisted:
        item.save()

    if rebuild_on_rule_change and dict(item.definition or {}) != meaning_before:
        # A rule change moves *membership* — which claims the category admits,
        # whose existence standings count, which claims draw its edges — and only
        # a rebuild moves that honestly. It also redraws every derived property,
        # so the rematerialize below would be redundant work on top.
        context.get_controller().rebuild_projection(item.graph)
    elif before is not None:
        # Synchronous and unbounded in the size of the graph: the accepted limit,
        # per `_rematerialize`'s module docstring. Cheap when nothing moved, which
        # is the common case — most updates are relabelling.
        rematerialize_if_moved(item, before)

    return item


def delete_category(info, model, proxy, *, what: str, instead: str) -> strawberry.ID:
    """Delete a category, or explain which evidence is holding it up."""
    item = schema_scoped(info, proxy, model.id, what=what)
    delete_or_explain(item, what=f"{what} '{item.key}'", instead=instead)
    return model.id
