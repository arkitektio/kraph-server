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
