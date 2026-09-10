"""The projection's signal receivers outlive the function that connected them (A7).

`graph_engine.apps.connect_projection_lifecycle` connects closures — the graph
delete that drops the namespace, the category write that refreshes it. Django
holds receivers weakly by default, so a closure nothing else references is
collected the moment its connecting function returns, and the signal fires into
nothing. No database: the receivers are inspected after a forced collection.

History: the closures were connected weakly and survived only while
`DEBUG = True`, because Django's debug-mode receiver validation goes through an
`lru_cache` that kept a strong reference by accident. Reading `DEBUG` from the
config for the first time made category writes stop refreshing the namespace and
graph deletion trip the schema-version foreign key.
"""

import gc

from django.db.models.signals import post_delete, post_save, pre_delete

from core import models as core_models


def _receiver_modules(signal, sender) -> set[str]:
    sync_receivers, async_receivers = signal._live_receivers(sender)
    return {receiver.__module__ for receiver in [*sync_receivers, *async_receivers]}


def test_the_projection_receivers_are_still_connected_after_collection() -> None:
    gc.collect()

    assert "graph_engine.apps" in _receiver_modules(pre_delete, core_models.Graph), "deleting a graph must still drop its namespace"
    assert "graph_engine.apps" in _receiver_modules(post_delete, core_models.Graph)
    for model in (core_models.Category, *core_models.CATEGORY_PROXIES.values()):
        assert "graph_engine.apps" in _receiver_modules(post_save, model), f"a {model.__name__} write must still refresh the namespace"
        assert "graph_engine.apps" in _receiver_modules(post_delete, model), f"a {model.__name__} delete must still refresh the namespace"
