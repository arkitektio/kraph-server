"""Print the GraphQL SDL, or check that ``test.graphql`` still is the schema.

    python manage.py print_schema > test.graphql
    python manage.py print_schema --check

``test.graphql`` is the one artifact that shows a breaking change whole, so it
is asserted by ``tests/guards/test_the_schema_renders_and_splits_its_grain.py``
and regenerated through this command — never hand-edited. Building the schema
needs no database.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

SNAPSHOT = "test.graphql"


def snapshot_path() -> Path:
    return Path(settings.BASE_DIR) / SNAPSHOT


def render_sdl() -> str:
    from api.schema import get_schema_sdl

    return get_schema_sdl().strip() + "\n"


class Command(BaseCommand):
    help = "Print the GraphQL SDL (or --check that test.graphql matches it)."
    requires_system_checks: list = []

    def add_arguments(self, parser) -> None:
        parser.add_argument("--check", action="store_true", help=f"Exit 1 when {SNAPSHOT} differs from the live schema.")

    def handle(self, *args, **options) -> None:
        sdl = render_sdl()
        if options["check"]:
            path = snapshot_path()
            current = path.read_text() if path.exists() else ""
            if current.strip() != sdl.strip():
                raise CommandError(f"{SNAPSHOT} is stale; regenerate with `python manage.py print_schema > {SNAPSHOT}` and read the diff")
            self.stdout.write(f"{SNAPSHOT} matches the schema")
            return
        self.stdout.write(sdl, ending="")
