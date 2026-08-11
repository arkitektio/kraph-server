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
`CypherEngineExtension`. Each does one `filter(id__in=...)` and returns `None`
for ids it could not find, so a dangling reference resolves to null instead of
erroring the query.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Callable, Iterable

from authentikate.models import User
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


_LOADER_SPECS: dict[str, tuple[type, str]] = {
    "node_category": (models.NodeCategory, "id"),
    "entity_category": (models.EntityCategory, "id"),
    "structure_kind": (evidence_models.StructureKind, "id"),
    "natural_event_category": (models.NaturalEventCategory, "id"),
    "metric_kind": (evidence_models.MetricKind, "id"),
    "protocol_event_category": (models.ProtocolEventCategory, "id"),
    "relation_category": (models.RelationCategory, "id"),
    "structure_relation_category": (models.StructureRelationCategory, "id"),
    "measurement_category": (models.MeasurementCategory, "id"),
    "graph_by_id": (models.Graph, "id"),
    "graph": (models.Graph, "age_name"),
    "graph_nodes_query_by_id": (models.GraphNodesQuery, "id"),
    "graph_path_query_by_id": (models.GraphPathQuery, "id"),
    "graph_pairs_query_by_id": (models.GraphPairsQuery, "id"),
    "graph_table_query_by_id": (models.GraphTableQuery, "id"),
    "user": (User, "id"),
}


def build_loaders() -> dict[str, DataLoader]:
    """A fresh set of loaders for one operation."""
    return {name: DataLoader(load_fn=_batch_by_pk(model, field)) for name, (model, field) in _LOADER_SPECS.items()}


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

    Mirrors `CypherEngineExtension`. Without this the loaders never get reset,
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


node_category_loader = _LoaderProxy("node_category")
entity_category_loader = _LoaderProxy("entity_category")
structure_kind_loader = _LoaderProxy("structure_kind")
natural_event_category_loader = _LoaderProxy("natural_event_category")
metric_kind_loader = _LoaderProxy("metric_kind")
protocol_event_category_loader = _LoaderProxy("protocol_event_category")
relation_category_loader = _LoaderProxy("relation_category")
structure_relation_category_loader = _LoaderProxy("structure_relation_category")
measurement_category_loader = _LoaderProxy("measurement_category")
graph_loader = _LoaderProxy("graph")
graph_by_id_loader = _LoaderProxy("graph_by_id")
graph_nodes_query_by_id_loader = _LoaderProxy("graph_nodes_query_by_id")
graph_path_query_by_id_loader = _LoaderProxy("graph_path_query_by_id")
graph_pairs_query_by_id_loader = _LoaderProxy("graph_pairs_query_by_id")
graph_table_query_by_id_loader = _LoaderProxy("graph_table_query_by_id")
user_loader = _LoaderProxy("user")
