from django.apps import AppConfig


class GraphEngineConfig(AppConfig):
    """Configuration for the graph engine app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "graph_engine"
    verbose_name = "Graph Engine"

    def ready(self) -> None:
        """Wire schema versioning to category changes.

        Connecting here rather than at each mutation is what makes "no code path
        mutates a category without emitting a schema version" true of every path,
        including the managers and the admin.
        """
        from graph_engine import versioning

        versioning.connect()
        connect_projection_lifecycle()


#: Graphs whose deletion is in flight. Django's collector deletes the categories
#: before the graph row, so their `post_delete` handlers would otherwise refresh
#: the namespace just dropped (`connect_projection_lifecycle`) or record a schema
#: version for a graph about to go (`versioning.on_category_changed` — an insert
#: the collector did not see, which then breaks the graph's own delete on the FK).
deleting_graphs: set[int] = set()


def connect_projection_lifecycle() -> None:
    """Keep a graph's namespace in step with its rows — on every path.

    Two halves:

    - **Graph deletion** drops the namespace. This is no longer belt-and-braces:
      the FK cascade removes the *rows*, but the namespace is DDL — a Postgres
      schema holding the per-category views and the property graph (RFC 0006) —
      and no cascade reaches DDL. This signal is the thing that removes it.
      Best effort: a namespace that cannot be dropped must not stop the row
      from going — it is logged.
    - **Category writes** refresh the namespace, because the namespace is
      derived from the category rows. Connecting here rather than at each
      mutation is what makes "no code path changes a category without
      refreshing the namespace" true of every path — mutations, managers, the
      admin. Gated on `versioning.is_suspended()`, the *opposite* choice from
      `CategoryAssertedTerm`'s signal: this refresh is O(schema) DDL per save,
      and `materialize` (which runs suspended) refreshes once itself after all
      its categories exist. DDL is transactional, so the refresh commits or
      rolls back with the category row — no second staleness ledger.

    Django's deletion collector sends **every** pre_delete before it deletes
    anything, then deletes children (categories) before the graph — so a graph
    deletion runs: drop the namespace, cascade the categories (whose post_delete
    must NOT rebuild what was just dropped), delete the graph. The
    `_deleting_graphs` registry is how the category handler knows to stand
    aside; the graph's post_delete drops once more, so a rebuild that slipped
    in anyway cannot orphan a schema.
    """
    import logging

    from django.db.models.signals import post_delete, post_save, pre_delete

    from core import models as core_models

    logger = logging.getLogger(__name__)
    _deleting_graphs = deleting_graphs

    def _drop(instance) -> None:
        from graph_engine.projection.context import current_or_default

        try:
            current_or_default().drop_namespace(instance)
        except Exception:  # noqa: BLE001 - the row is going regardless; see the docstring
            logger.warning("Deleting graph #%s but could not drop its projection namespace %r; drop it by hand.", instance.pk, instance.age_name)

    def on_graph_deleting(sender, instance, **kwargs) -> None:
        _deleting_graphs.add(int(instance.pk))
        _drop(instance)

    def on_graph_deleted(sender, instance, **kwargs) -> None:
        _deleting_graphs.discard(int(instance.pk))
        _drop(instance)

    pre_delete.connect(on_graph_deleting, sender=core_models.Graph, dispatch_uid="projection_namespace_drop")
    post_delete.connect(on_graph_deleted, sender=core_models.Graph, dispatch_uid="projection_namespace_drop_final")

    def on_category_changed(sender, instance, **kwargs) -> None:
        from graph_engine import versioning
        from graph_engine.projection.context import current_or_default

        if versioning.is_suspended():
            return
        if int(instance.graph_id) in _deleting_graphs:
            return
        graph = core_models.Graph.objects.filter(pk=instance.graph_id).first()
        if graph is None:
            # A cascade got here after the graph row itself went; the graph's
            # own signal dropped the namespace and there is nothing to derive.
            return
        current_or_default().refresh_namespace(graph)

    category_classes = {
        core_models.Category,
        core_models.NodeCategory,
        core_models.EdgeCategory,
        *core_models.CATEGORY_PROXIES.values(),
    }
    for model in category_classes:
        post_save.connect(on_category_changed, sender=model, dispatch_uid=f"projection_namespace_{model.__name__}_save")
        post_delete.connect(on_category_changed, sender=model, dispatch_uid=f"projection_namespace_{model.__name__}_delete")
