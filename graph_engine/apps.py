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


def connect_projection_lifecycle() -> None:
    """Drop a graph's projection namespace when the graph row goes — on every path.

    The `deleteGraph` mutation used to do this itself, and only it: a cascade from
    the organization or the owning user, a shell `delete()`, a test teardown all
    left an orphaned namespace behind. For the table kind the FK cascade removes
    the rows regardless, so this signal is belt-and-braces there — but it stays,
    because it is the protocol's word for cleanup and another projection kind may
    hold state no cascade reaches. Best effort: a namespace that cannot be
    dropped must not stop the row from going — it is logged.
    """
    import logging

    from django.db.models.signals import pre_delete

    from core import models as core_models

    logger = logging.getLogger(__name__)

    def on_graph_deleted(sender, instance, **kwargs) -> None:
        from graph_engine.projection.context import current_or_default

        try:
            current_or_default().drop_namespace(instance)
        except Exception:  # noqa: BLE001 - the row is going regardless; see the docstring
            logger.warning("Deleting graph #%s but could not drop its projection namespace %r; drop it by hand.", instance.pk, instance.age_name)

    pre_delete.connect(on_graph_deleted, sender=core_models.Graph, dispatch_uid="projection_namespace_drop")
