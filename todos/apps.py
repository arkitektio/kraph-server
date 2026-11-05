from django.apps import AppConfig


class TodosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "todos"
    verbose_name = "Todo lists"

    def ready(self) -> None:
        # The hub's rekuest: todo items and their objects as structures, their saves as signals.
        # Connected in every process (web, shell, jobs), not only once the URLconf loads.
        import kraph_server.service  # noqa: F401
