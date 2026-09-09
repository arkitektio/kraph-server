"""Emitting a schema version whenever the ontology changes.

`GraphSchema` used to be written exactly once per graph, by `materialize()`, with
`index=1` and `is_active=True` hardcoded — and every category mutation then
edited rows in place. There was nothing to diff, so nothing could be scoped, so
every schema change looked like "recalculate everything". That is the whole
reason the derivation layer appeared to be expensive.

Here, each category mutation snapshots the graph's ontology afterwards and emits
a new version if it actually changed. Two consequences worth stating:

- A mutation that changes nothing (re-saving identical input) emits nothing. The
  hash is the test, not the fact that a mutation ran.
- With versions to compare, `graph_engine.schema_diff` can answer what work a
  change implies — and for an aggregation swap the answer is "none".
"""

from __future__ import annotations

import contextlib
import contextvars
from typing import Any, Iterator

from django.db import transaction

from core import models as core_models
from graph_engine.materialize import compute_definition_hash

# Versioning is driven by a signal rather than by call sites, so that "no code
# path mutates a category without emitting a schema" is true of *every* path —
# the eight mutation modules, the managers, the admin, and anything written
# later — rather than of the paths somebody remembered to annotate.
_suspended: contextvars.ContextVar[bool] = contextvars.ContextVar("schema_versioning_suspended", default=False)


@contextlib.contextmanager
def suspended() -> Iterator[None]:
    """Stop emitting versions for the duration of a bulk change.

    `materialize()` creates dozens of categories to express one schema; without
    this, each would emit its own version and the history would describe the
    order rows happened to be written rather than anything a user did. The caller
    emits a single version afterwards.
    """
    token = _suspended.set(True)
    try:
        yield
    finally:
        _suspended.reset(token)


def is_suspended() -> bool:
    """Whether versioning is currently paused."""
    return _suspended.get()


def _property_definitions(category: Any) -> list[dict[str, Any]]:
    """A category's property definitions in their stored JSON form."""
    return list(category.property_definitions or [])


def snapshot_definition(graph: core_models.Graph) -> dict[str, Any]:
    """Rebuild the graph definition from its current categories.

    The inverse of `materialize()`: where that turns a definition into rows, this
    reads the rows back into a definition. Going through the categories rather
    than through the previous schema is deliberate — the categories are what the
    mutations edit, so they are what a new version has to reflect.
    """
    active = core_models.GraphSchema.active_for(graph)
    version = active.version if active else "1.0.0"

    # `definition` — the category's complete rule since RFC 0009 — is part of
    # the snapshot: a trust edit is a schema change, versioned like one. (This
    # closes the RFC 0007 open item for the predicate; rule evidence filters
    # ride `property_definitions` and were always included.)
    entities = [{"key": category.key, "description": category.description, "property_definitions": _property_definitions(category), **({"definition": dict(category.definition)} if category.definition else {})} for category in graph.entity_categories.order_by("key")]

    relations = [
        {
            "key": category.key,
            "description": category.description,
            "source": category.source_definition,
            "target": category.target_definition,
            "properties": _property_definitions(category),
            **({"definition": dict(category.definition)} if category.definition else {}),
        }
        for category in graph.relation_categories.order_by("key")
    ]

    events = [
        {
            "key": category.key,
            "description": category.description,
            "inputs": list(category.source_entity_roles or []),
            "outputs": list(category.target_entity_roles or []),
            "properties": _property_definitions(category),
            **({"definition": dict(category.definition)} if category.definition else {}),
        }
        for category in graph.natural_event_categories.order_by("key")
    ]

    structure_relations = [
        {
            "key": category.key,
            "description": category.description,
            "source": category.source_definition,
            "target": category.target_definition,
            "properties": _property_definitions(category),
            **({"definition": dict(category.definition)} if category.definition else {}),
        }
        for category in graph.structure_relation_categories.order_by("key")
    ]

    measurements = [
        {
            "key": category.key,
            "description": category.description,
            "source": category.source_definition,
            "target": category.target_definition,
            "properties": _property_definitions(category),
            **({"definition": dict(category.definition)} if category.definition else {}),
        }
        for category in graph.measurement_categories.order_by("key")
    ]

    return {
        "system_version": version,
        "extensions": {
            "entities": entities,
            "relations": relations,
            "events": events,
            "structure_relations": structure_relations,
            "measurements": measurements,
        },
    }


@transaction.atomic
def emit_schema_version(
    graph: core_models.Graph,
    description: str | None = None,
    user: Any = None,
) -> core_models.GraphSchema | None:
    """Record a new schema version if the ontology actually changed.

    Returns the new schema, or None when the snapshot hashes the same as the
    active one. Emitting unconditionally would fill the history with
    indistinguishable versions and make `schema_diff` report empty changes as
    real ones.
    """
    definition = snapshot_definition(graph)
    new_hash = compute_definition_hash(definition)

    active = core_models.GraphSchema.active_for(graph)
    if active is not None and active.hash == new_hash:
        return None

    schema = core_models.GraphSchema(
        graph=graph,
        version=definition["system_version"],
        index=None,
        definition=definition,
        hash=new_hash,
        description=description,
        created_by=user,
        is_active=False,
    )
    schema.save()
    schema.activate()
    return schema


def graph_of(category: Any) -> core_models.Graph:
    """The graph a category belongs to, for mutations that only hold the category."""
    return category.graph


def record_change(category_or_graph: Any, description: str, info: Any = None) -> core_models.GraphSchema | None:
    """Convenience wrapper used by the category mutations.

    Accepts a category or a graph so call sites stay one line, which matters when
    there are two dozen of them and every missed one is a version that silently
    never got recorded.
    """
    graph = category_or_graph if isinstance(category_or_graph, core_models.Graph) else graph_of(category_or_graph)
    user = getattr(getattr(info, "context", None), "request", None)
    user = getattr(user, "user", None) if user is not None else None
    return emit_schema_version(graph, description=description, user=user)


def on_category_changed(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Signal handler: a category was saved or deleted.

    Deliberately tolerant. A failure to record a version must not roll back the
    mutation that triggered it — the ontology change is the user's intent, the
    version is bookkeeping — but it must also not pass unnoticed, hence the
    warning rather than a bare except.
    """
    if is_suspended():
        return

    graph = getattr(instance, "graph", None)
    if graph is None:
        return

    try:
        emit_schema_version(graph, description=f"{sender.__name__} changed")
    except Exception as error:  # noqa: BLE001 - see docstring
        import logging

        logging.getLogger(__name__).warning("Could not record a schema version for graph %s: %s", graph.pk, error)


def connect() -> None:
    """Wire the signal handlers. Called from the app config's `ready()`.

    Two handlers per model, and they deliberately do **not** share the suspension
    gate:

    - :func:`on_category_changed` emits a schema version, and is suspended during
      `materialize()` so that expressing one schema does not produce a version per
      category.
    - `core.asserted_terms` indexes the words each definition derives from, and is
      **never** suspended. A freshly materialized graph is exactly the case where
      that index matters most, and gating it would leave the graph deriving from
      nothing until somebody ran the rebuild command.

    The asserted-term handler is wired on **every** category class, taken from
    `CATEGORY_PROXIES` plus the concrete `Category` and the two intermediate
    proxies, rather than on a hand-written list. Django sends `post_save` with the
    proxy the instance was created through as sender (`save_base` keeps `origin`
    as the proxy), so a class missing from the list is a class whose saves are
    silently unindexed. The handler is idempotent — it rewrites a category's rows
    rather than adding to them — so overlapping registrations cost a redundant
    delete and nothing else.
    """
    from django.db.models.signals import post_delete, post_save

    from core import asserted_terms
    from core import models as models_module

    # Structure and metric kinds are deliberately absent: they are organization
    # vocabulary, not schema, so there is no graph whose version changed when one
    # appears. They are also created lazily on every write, which would have
    # emitted a schema version per ingest.
    for model in (
        models_module.EntityCategory,
        models_module.RelationCategory,
        models_module.MeasurementCategory,
        models_module.StructureRelationCategory,
        models_module.NaturalEventCategory,
        models_module.ProtocolEventCategory,
    ):
        post_save.connect(on_category_changed, sender=model, dispatch_uid=f"schema_version_{model.__name__}_save")
        post_delete.connect(on_category_changed, sender=model, dispatch_uid=f"schema_version_{model.__name__}_delete")

    category_classes = {
        models_module.Category,
        models_module.NodeCategory,
        models_module.EdgeCategory,
        *models_module.CATEGORY_PROXIES.values(),
    }
    for model in category_classes:
        post_save.connect(asserted_terms.on_category_saved, sender=model, dispatch_uid=f"asserted_terms_{model.__name__}_save")
        post_delete.connect(asserted_terms.on_category_deleted, sender=model, dispatch_uid=f"asserted_terms_{model.__name__}_delete")
