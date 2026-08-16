"""Rebuild the index of which words each category's definition derives from.

The out-of-band half of :mod:`core.asserted_terms`, and the same escape hatch
`manage.py reproject` and `manage.py rebuild_identity` are: if this cannot
reproduce what the signal handler produced, the incremental path is wrong and a
graph is deriving from a word its own definition does not name — or, worse, has
quietly stopped deriving from one it does.

Three reasons to reach for it:

- **A definition was changed with the signal bypassed.** `bulk_create`,
  `queryset.update()` and raw SQL all skip `post_save`, and any of them can edit a
  definition. `--check` says whether one did.
- **A restore or a fixture load.** Loading a fixture writes rows without the
  handler on some paths, and a graph whose defined categories are invisible looks
  like data loss rather than a stale index.
- **The code that reads `asserted_as` changed.** The rule for what a definition
  names lives in `selector.asserted_as_keys`; widening it means every existing row
  was computed under the old rule.

Nothing here is scoped by graph on purpose — `_graph_ids_by_term` reads the table
for a whole organization, so rebuilding one graph's rows would leave the map half
old and half new with nothing saying which.
"""

from authentikate.models import Organization
from django.core.management.base import BaseCommand, CommandError

from core import asserted_terms


class Command(BaseCommand):
    """Rebuild or verify the asserted-term index."""

    help = "Rebuild `CategoryAssertedTerm` from the categories' definitions."

    def add_arguments(self, parser) -> None:
        """Declare the command's arguments."""
        parser.add_argument("--organization", help="Slug of the organization to work on. Omit with --all.")
        parser.add_argument("--all", action="store_true", help="Work on every organization.")
        parser.add_argument(
            "--check",
            action="store_true",
            help="Report disagreement between the index and the definitions without writing anything.",
        )

    def handle(self, *args, **options) -> None:
        """Rebuild, or report."""
        if not options["organization"] and not options["all"]:
            raise CommandError("Name an organization with --organization, or pass --all.")

        organizations = list(Organization.objects.all()) if options["all"] else list(Organization.objects.filter(slug=str(options["organization"])))
        if not organizations:
            raise CommandError("No matching organizations.")

        for organization in organizations:
            if options["check"]:
                self._check(organization)
            else:
                written = asserted_terms.refold(organization)
                self.stdout.write(self.style.SUCCESS(f"{organization.slug}: {written} asserted-term row(s)"))

    def _check(self, organization: Organization) -> None:
        """Compare the index against the definitions, and write nothing.

        Both sides come from `core.asserted_terms` rather than being recomputed
        here, so a `--check` that passes is evidence about the same computation
        `refold` performs — not about a second one that happens to agree.
        """
        stored = asserted_terms.stored(organization)
        expected = asserted_terms.expected(organization)

        missing = sorted(expected - stored, key=lambda pair: (str(pair[0]), pair[1]))
        extra = sorted(stored - expected, key=lambda pair: (str(pair[0]), pair[1]))

        if not (missing or extra):
            self.stdout.write(self.style.SUCCESS(f"{organization.slug}: index agrees with the definitions ({len(stored)} row(s))"))
            return

        self.stdout.write(self.style.ERROR(f"{organization.slug}: index disagrees with the definitions"))
        for category_id, key in missing:
            self.stdout.write(f"  missing  category {category_id} derives from {key!r} and is not indexed")
        for category_id, key in extra:
            self.stdout.write(f"  extra    category {category_id} is indexed under {key!r} and no longer derives from it")
