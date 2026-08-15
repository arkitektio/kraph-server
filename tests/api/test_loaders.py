"""Loaders batch, tolerate misses, and do not outlive a request.

The previous fifteen loaders were module-level `DataLoader` instances, which gave
them three separate defects at once:

- a process-lifetime cache with no tenant boundary, so one organization's
  category could be served to another's query
- `for i in ids: await Model.objects.aget(i)` — N queries, which makes a
  DataLoader a cache with extra steps
- `aget` raising `DoesNotExist`, so one dangling id failed every id batched
  alongside it

None of this was covered, because nothing tested the loaders at all.

These run async: a `DataLoader` dispatches its batch on the running event loop,
so driving one from synchronous code fights the loop rather than exercising it.
"""

import pytest
from asgiref.sync import sync_to_async

from api import loaders
from core import models as core_models


@sync_to_async
def _make_categories(graph: core_models.Graph, keys: list[str]) -> list[int]:
    return [core_models.EntityCategory.objects.create(graph=graph, key=key, age_name=key.lower()).pk for key in keys]


@sync_to_async
def _first_category_pk(graph: core_models.Graph) -> int:
    return core_models.EntityCategory.objects.filter(graph=graph).values_list("id", flat=True).first()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_missing_id_resolves_to_none_rather_than_raising(test_graph: core_models.Graph) -> None:
    """One dangling reference must not take down the whole batch."""
    existing = await _first_category_pk(test_graph)
    assert existing is not None

    loader = loaders.build_loaders()["entity_category"]
    results = await loader.load_many([existing, 999_999])

    assert results[0].pk == existing
    assert results[1] is None, "A missing row is null, not an exception"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_results_line_up_with_the_keys_asked_for(test_graph: core_models.Graph) -> None:
    """DataLoader requires positional correspondence.

    Returning the queryset's own order would silently mis-assign every result
    after the first gap — each caller getting somebody else's category.
    """
    alpha, beta = await _make_categories(test_graph, ["Alpha", "Beta"])

    loader = loaders.build_loaders()["entity_category"]
    results = await loader.load_many([beta, 999_999, alpha])

    assert results[0].key == "Beta"
    assert results[1] is None
    assert results[2].key == "Alpha"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_batch_is_one_query(test_graph: core_models.Graph) -> None:
    """Batching is the entire purpose; N queries would defeat it.

    Counted through the load function itself rather than through Django's query
    capture, which does not see across the thread `sync_to_async` runs the ORM
    on.
    """
    ids = await _make_categories(test_graph, ["B1", "B2", "B3"])

    calls: list[list] = []
    original = loaders._batch_by_pk

    def counting(model, field="id"):
        inner = original(model, field)

        async def load(keys):
            calls.append(list(keys))
            return await inner(keys)

        return load

    loaders._batch_by_pk = counting
    try:
        loader = loaders.build_loaders()["entity_category"]
        results = await loader.load_many(ids)
    finally:
        loaders._batch_by_pk = original

    assert all(result is not None for result in results)
    assert len(calls) == 1, f"Expected one batched call, got {len(calls)}"
    assert sorted(calls[0]) == sorted(ids)


def test_each_operation_gets_its_own_loaders() -> None:
    """The cache must not span requests, let alone tenants.

    A `DataLoader` caches every key it has ever seen. Built once at import time,
    that cache outlives every request — a cross-tenant leak arriving through the
    back door, past the evidence scoping guard.
    """
    first = loaders.build_loaders()
    second = loaders.build_loaders()

    assert first["entity_category"] is not second["entity_category"]


def test_every_declared_loader_is_constructible() -> None:
    """Every spec resolves to a real model and field, and every proxy has a spec.

    The count used to be asserted as a literal — `len(built) == 16` — which said
    nothing the set comparison above it did not, and broke the moment three
    loaders nothing loaded through were removed. What is worth pinning is the
    pairing: `build_loaders` constructs one DataLoader per spec on **every**
    operation, so a `_LoaderProxy` naming a spec that does not exist fails at
    request time, and a spec with no proxy is a loader built per request and
    never used.
    """
    built = loaders.build_loaders()

    assert set(built) == set(loaders._LOADER_SPECS)

    proxied = {proxy._name for proxy in vars(loaders).values() if isinstance(proxy, loaders._LoaderProxy)}
    assert proxied <= set(loaders._LOADER_SPECS), f"proxy with no spec: {sorted(proxied - set(loaders._LOADER_SPECS))}"
    assert set(loaders._LOADER_SPECS) <= proxied, f"spec with no proxy: {sorted(set(loaders._LOADER_SPECS) - proxied)}"
