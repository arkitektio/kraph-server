from django.apps import AppConfig


class DatasetsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "datasets"
    verbose_name = "Paired datasets"

    def ready(self) -> None:
        # The hub's rekuest: a paired dataset as a structure with descriptors, so a port can
        # require what it pairs. Connected in every process, as the todos are.
        import kraph_server.service  # noqa: F401
