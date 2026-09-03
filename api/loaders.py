"""Per-operation batching loaders.

These were fifteen module-level `DataLoader` instances, each with three separate
problems:

- **A process-lifetime cache shared across tenants.** A `DataLoader` caches
  everything it has ever loaded. Created at import time, that cache outlives
  every request, so one organization's category could be served to another's
  query — the exact leak the evidence scoping guard exists to prevent, arriving
  through the back door.
- **No batching at all.** Every load function was `for i in ids: await
  Model.objects.aget(i)`, which is N queries. A DataLoader that does not batch is
  a cache with extra steps.
- **One miss failed the whole batch.** `aget` raises `DoesNotExist`, so a single
  dangling id took down every other id loaded alongside it.

Loaders are now built per operation and bound through a ContextVar, mirroring
`ProjectionExtension`. Each does one `filter(id__in=...)` and returns `None`
for ids it could not find, so a dangling reference resolves to null instead of
erroring the query.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Callable, Iterable

from strawberry.dataloader import DataLoader
from strawberry.extensions import SchemaExtension

from core import models
from evidence import models as evidence_models

PKType = int | str

_loaders: ContextVar[dict[str, DataLoader] | None] = ContextVar("api_loaders", default=None)


def _batch_by_pk(model: type, field: str = "id") -> Callable[[list[PKType]], Any]:
    """A load function that fetches every requested row in one query.

    Returns results in the order asked for, with `None` where a row is missing —
    DataLoader requires positional correspondence, and returning the queryset's
    own order would silently mis-assign every result after the first gap.
    """

    manager = getattr(model, "all_objects", None) or model.objects

    async def load(keys: list[PKType]) -> list[Any]:
        # `all_objects` where the model has one: evidence models raise on an
        # unscoped `objects`, and a loader is keyed by primary key, which is
        # already globally unique. Authorization happens at the resolver.
        found = {}
        async for instance in manager.filter(**{f"{field}__in": list(keys)}):
            found[str(getattr(instance, field))] = instance
        return [found.get(str(key)) for key in keys]

    return load


def _batch_grouped_by(model: type, field: str, narrow: Callable[[Any], Any] | None = None) -> Callable[[list[PKType]], Any]:
    """A load function for a **one-to-many** relation: every row per key, in one query.

    The sibling `_batch_by_pk` cannot do this and fails silently if asked to:
    it builds `{key: instance}`, so a loader keyed on `Metric.structure_id` would
    quietly return the last metric per structure and drop the rest. A one-to-many
    loader has to group, so it is a different load function rather than a
    different spec.

    Returns `[]` for a key with no rows, never `None` — an empty list is the
    honest answer to "what measurements does this have", and the `Optional` a
    missing key would force on every caller would say something else.

    ``narrow`` wraps the queryset before it is grouped, which is how the standing
    filter gets applied: a retracted metric is still a row, and only the anti-join
    against `CurrentStanding` says it is gone.
    """

    manager = getattr(model, "all_objects", None) or model.objects

    async def load(keys: list[PKType]) -> list[Any]:
        queryset = manager.filter(**{f"{field}__in": list(keys)})
        if narrow is not None:
            queryset = narrow(queryset)

        grouped: dict[str, list[Any]] = {}
        async for instance in queryset:
            grouped.setdefault(str(getattr(instance, field)), []).append(instance)
        return [grouped.get(str(key), []) for key in keys]

    return load


def _standing_metrics(queryset: Any) -> Any:
    """Narrow a metric queryset to the measurements that still stand."""
    from evidence import claims as claims_module

    return claims_module.standing(queryset, "metric").order_by("measured_at")


_LOADER_SPECS: dict[str, tuple[type, str]] = {
    "entity_category": (models.EntityCategory, "id"),
    "structure_kind": (evidence_models.StructureKind, "id"),
    "natural_event_category": (models.NaturalEventCategory, "id"),
    "metric_kind": (evidence_models.MetricKind, "id"),
    "protocol_event_category": (models.ProtocolEventCategory, "id"),
    "relation_category": (models.RelationCategory, "id"),
    "structure_relation_category": (models.StructureRelationCategory, "id"),
    "measurement_category": (models.MeasurementCategory, "id"),
    "graph_by_id": (models.Graph, "id"),
    "graph_table_query_by_id": (models.GraphTableQuery, "id"),
    "term_by_id": (evidence_models.Term, "id"),
    "assertion_by_id": (evidence_models.Assertion, "id"),
    # The claims themselves, for the types that answer with one: a write's payload
    # and `Link.source`/`target`, which resolve an opaque ref into whichever of
    # these tables its `kind` says it names.
    "instance_by_id": (evidence_models.Instance, "id"),
    "link_by_id": (evidence_models.Link, "id"),
    "structure_by_id": (evidence_models.Structure, "id"),
    "comment_by_id": (evidence_models.Comment, "id"),
}


def _newest_standings(queryset: Any) -> Any:
    """Every position on a claim, newest first.

    Ordered by `(at, assertion.seq)` — the fold's own order, from
    `evidence.claims._LATEST` — so the caller can read `stands` off the first row
    instead of asking the database a second question. `select_related` because every
    standing is shown with who recorded it.
    """
    return queryset.select_related("assertion").order_by("-at", "-assertion__seq")


#: Loaders that return a **list** per key rather than a row. Kept in their own
#: table because they need `_batch_grouped_by`, not `_batch_by_pk` — see that
#: function for why asking the wrong one is a silent data-loss bug rather than an
#: error.
_GROUPED_LOADER_SPECS: dict[str, tuple[type, str, Any]] = {
    "metrics_by_structure": (evidence_models.Metric, "structure_id", _standing_metrics),
    # Keyed on `target_id` alone, without `target_type`. The ids are uuid4 primary
    # keys of five different tables, so one cannot collide with another — and the
    # callers ask about a claim they are holding, not about a type.
    "standings_by_target": (evidence_models.Standing, "target_id", _newest_standings),
    # Deliberately not narrowed by standing, unlike `metrics_by_structure`: a
    # resolved remark is shown as resolved, not hidden — hiding it would make
    # `Comment.resolved` unreachable exactly where it answers.
    "comments_by_structure": (evidence_models.Comment, "structure_id", lambda queryset: queryset.select_related("assertion").order_by("-created_at")),
    "replies_by_comment": (evidence_models.Comment, "parent_id", lambda queryset: queryset.select_related("assertion").order_by("created_at")),
}


def _batch_known_about_nodes() -> Callable[[list[PKType]], Any]:
    """The panel: everything the log says about each node, over its component.

    One load function for four fields rather than four loaders, because all four
    need the same components and computing them four times is the cost the batch
    exists to avoid. `evidence.panel.known_about` does the work; this is only the
    thread hop.

    Keys are ``(graph_handle, ref)`` pairs again (RFC 0011): a drawn node's
    component and sameness fold per view — rule-driven, within its category —
    so they are that view's answer, while labels and connections stay
    organization grain inside `known_about` itself. An empty handle — a
    claim-grain read with no view by construction — gets the organization-wide
    fold. The handle is resolved internally from our own drawn record; it is
    still never accepted as *input* (RFC 0006).
    """
    from collections import defaultdict

    from asgiref.sync import sync_to_async

    async def load(keys: list[PKType]) -> list[Any]:
        from core import models as core_models
        from evidence import panel

        normalized = [(str(key[0] or ""), str(key[1])) for key in keys]  # type: ignore[index]

        def work() -> dict[tuple[str, str], Any]:
            refs_by_handle: dict[str, list[str]] = defaultdict(list)
            for handle, ref in normalized:
                if ref not in refs_by_handle[handle]:
                    refs_by_handle[handle].append(ref)
            graphs = {graph.age_name: graph for graph in core_models.Graph.objects.filter(age_name__in=[handle for handle in refs_by_handle if handle])}
            answers: dict[tuple[str, str], Any] = {}
            for handle, refs in refs_by_handle.items():
                for ref, known in zip(refs, panel.known_about(refs, graph=graphs.get(handle))):
                    answers[(handle, ref)] = known
            return answers

        answers = await sync_to_async(work)()
        return [answers[key] for key in normalized]

    return load


def _batch_informed_nodes() -> Callable[[list[PKType]], Any]:
    """The nodes each structure is evidence for.

    Batched even though the underlying read is simple, because it is the hop the
    rest of the panel hangs off: a DataLoader dispatches once per event-loop tick,
    so resolving this per structure would put every downstream loader in a batch
    of one.
    """
    from asgiref.sync import sync_to_async

    async def load(keys: list[PKType]) -> list[Any]:
        from evidence import panel

        return await sync_to_async(panel.informed_nodes)([str(key) for key in keys])

    return load


#: Loaders whose batch is a hand-written function rather than a query over one
#: model. Third table because the two above are declarative and this cannot be.
#:
#: Neither of these authorizes: they are keyed on the primary key of a row the
#: resolver has already resolved and checked, exactly as `_batch_by_pk` is. A
#: tenant check here would be a second, weaker copy of one that already happened.
_CUSTOM_LOADER_FACTORIES: dict[str, Callable[[], Callable[[list[PKType]], Any]]] = {
    "known_about_node": _batch_known_about_nodes,
    "informed_nodes_by_structure": _batch_informed_nodes,
}


def all_loader_names() -> set[str]:
    """Every loader name, of any shape. What `build_loaders` produces."""
    return set(_LOADER_SPECS) | set(_GROUPED_LOADER_SPECS) | set(_CUSTOM_LOADER_FACTORIES)


def build_loaders() -> dict[str, DataLoader]:
    """A fresh set of loaders for one operation."""
    built = {name: DataLoader(load_fn=_batch_by_pk(model, field)) for name, (model, field) in _LOADER_SPECS.items()}
    built.update({name: DataLoader(load_fn=_batch_grouped_by(model, field, narrow)) for name, (model, field, narrow) in _GROUPED_LOADER_SPECS.items()})
    built.update({name: DataLoader(load_fn=factory()) for name, factory in _CUSTOM_LOADER_FACTORIES.items()})
    return built


class _LoaderProxy:
    """Resolves to the current operation's loader at call time.

    Call sites read `loaders.entity_category_loader.load(id)` as module state, so
    this keeps that spelling while the instance underneath is per-operation.
    Rewriting two dozen resolvers to thread a context object would be a larger
    change than the bug warrants.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def _current(self) -> DataLoader:
        active = _loaders.get()
        if active is None:
            # Outside an operation — a management command, a test calling a
            # resolver directly. A throwaway loader is correct here: there is no
            # request to scope a cache to, so caching across the call would be
            # the bug rather than the optimisation.
            if self._name in _CUSTOM_LOADER_FACTORIES:
                return DataLoader(load_fn=_CUSTOM_LOADER_FACTORIES[self._name]())
            if self._name in _GROUPED_LOADER_SPECS:
                model, field, narrow = _GROUPED_LOADER_SPECS[self._name]
                return DataLoader(load_fn=_batch_grouped_by(model, field, narrow))
            model, field = _LOADER_SPECS[self._name]
            return DataLoader(load_fn=_batch_by_pk(model, field))
        return active[self._name]

    def load(self, key: PKType) -> Any:
        """Load one key, returning None if it does not exist."""
        return self._current().load(key)

    def load_many(self, keys: Iterable[PKType]) -> Any:
        """Load several keys in one batch."""
        return self._current().load_many(list(keys))


class LoaderExtension(SchemaExtension):
    """Bind a fresh set of loaders for the duration of each operation.

    Mirrors `ProjectionExtension`. Without this the loaders never get reset,
    and a DataLoader that is never reset is a cache with no eviction and no
    tenant boundary.
    """

    def on_operation(self):
        """Install per-operation loaders, then discard them."""
        token = _loaders.set(build_loaders())
        try:
            yield
        finally:
            _loaders.reset(token)


entity_category_loader = _LoaderProxy("entity_category")
structure_kind_loader = _LoaderProxy("structure_kind")
natural_event_category_loader = _LoaderProxy("natural_event_category")
metric_kind_loader = _LoaderProxy("metric_kind")
protocol_event_category_loader = _LoaderProxy("protocol_event_category")
relation_category_loader = _LoaderProxy("relation_category")
structure_relation_category_loader = _LoaderProxy("structure_relation_category")
measurement_category_loader = _LoaderProxy("measurement_category")
graph_by_id_loader = _LoaderProxy("graph_by_id")
graph_table_query_by_id_loader = _LoaderProxy("graph_table_query_by_id")
term_by_id_loader = _LoaderProxy("term_by_id")
assertion_by_id_loader = _LoaderProxy("assertion_by_id")
instance_by_id_loader = _LoaderProxy("instance_by_id")
link_by_id_loader = _LoaderProxy("link_by_id")
structure_by_id_loader = _LoaderProxy("structure_by_id")
comment_by_id_loader = _LoaderProxy("comment_by_id")
metrics_by_structure_loader = _LoaderProxy("metrics_by_structure")
standings_by_target_loader = _LoaderProxy("standings_by_target")
comments_by_structure_loader = _LoaderProxy("comments_by_structure")
replies_by_comment_loader = _LoaderProxy("replies_by_comment")
known_about_node_loader = _LoaderProxy("known_about_node")
informed_nodes_by_structure_loader = _LoaderProxy("informed_nodes_by_structure")
