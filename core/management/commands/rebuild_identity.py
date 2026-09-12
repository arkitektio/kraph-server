"""Rebuild the instance-identity fold from the sameness claims that still stand,
less the ones a standing difference vetoes (RFC 0019).

The out-of-band half of :mod:`evidence.identity`, and the same escape hatch
`manage.py reproject` is for the AGE projection: if this cannot reproduce what
incremental maintenance produced, the incremental path is wrong and the fold is
holding an answer nobody can account for.

Three reasons to reach for it:

- **A retraction left work owed.** `identity.retract` flags a component rather
  than splitting it, because union-find has no un-union; `--stale` finishes those.
  (`identity.separate` — a `DIFFERENT_FROM` write — flags and rebuilds at once.)
- **The fold and the claims disagree.** `--check` recomputes without writing and
  reports the difference, so a suspicion can be settled without changing
  anything.
- **A migration or a redaction rewrote history.** `manage.py redact` destroys
  claims outright, which is the one sanctioned way for the log to lose rows — and
  a fold over rows that no longer exist has to be rebuilt rather than adjusted.

Nothing here is scoped by graph. Identity is organization grain, like `State`:
which claims a *view* counts is a read-time question, and folding under one
graph's selector is exactly the mistake that made `merge` and `refold_state`
disagree about metrics.
"""

from authentikate.models import Organization
from django.core.management.base import BaseCommand, CommandError

from evidence import identity as identity_module
from evidence import models as evidence_models


class Command(BaseCommand):
    """Rebuild or verify the components instance-identity claims fold into."""

    help = "Rebuild the instance-identity fold from standing SAME_AS claims, DIFFERENT_FROM vetoes applied."

    def add_arguments(self, parser) -> None:
        """Declare the command's arguments."""
        parser.add_argument("--organization", help="Slug of the organization to work on. Omit with --all.")
        parser.add_argument("--all", action="store_true", help="Work on every organization.")
        parser.add_argument(
            "--stale",
            action="store_true",
            help="Only components a retraction flagged, rather than a full refold.",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Report disagreement between the fold and the claims without writing anything.",
        )

    def handle(self, *args, **options) -> None:
        """Rebuild, or report."""
        if not options["organization"] and not options["all"]:
            raise CommandError("Name an organization with --organization, or pass --all.")

        organizations = self._select(options)
        if not organizations:
            raise CommandError("No matching organizations.")

        for organization in organizations:
            if options["check"]:
                self._check(organization)
            elif options["stale"]:
                rebuilt = identity_module.recompute_stale(organization)
                self.stdout.write(self.style.SUCCESS(f"{organization.slug}: {rebuilt} flagged component(s) rebuilt"))
            else:
                components = identity_module.refold(organization)
                self.stdout.write(self.style.SUCCESS(f"{organization.slug}: {components} component(s)"))

    def _select(self, options) -> list[Organization]:
        if options["all"]:
            return list(Organization.objects.all())
        return list(Organization.objects.filter(slug=str(options["organization"])))

    def _check(self, organization: Organization) -> None:
        """Compare what is stored against what the claims say, and write nothing.

        Reads the stored rows first, then recomputes into a dict rather than into
        the table — so a `--check` on a disagreeing database reports it and leaves
        the disagreement in place to be looked at.
        """
        stored: dict[str, str] = {str(instance_id): str(canonical_id) for instance_id, canonical_id in evidence_models.InstanceIdentity.objects.for_organization(organization).values_list("instance_id", "canonical_id")}

        expected = self._expected(organization)

        missing = sorted(set(expected) - set(stored))
        extra = sorted(set(stored) - set(expected))
        moved = sorted(node for node in set(stored) & set(expected) if stored[node] != expected[node])

        if not (missing or extra or moved):
            self.stdout.write(self.style.SUCCESS(f"{organization.slug}: fold agrees with the claims ({len(stored)} row(s))"))
            return

        self.stdout.write(self.style.ERROR(f"{organization.slug}: fold disagrees with the claims"))
        for node in missing:
            self.stdout.write(f"  missing  {node} should be under {expected[node]}")
        for node in extra:
            self.stdout.write(f"  extra    {node} is under {stored[node]} but is in no component")
        for node in moved:
            self.stdout.write(f"  moved    {node} is under {stored[node]}, should be {expected[node]}")

    def _expected(self, organization: Organization) -> dict[str, str]:
        """The fold the standing claims imply, computed without touching the
        table — the same adjacency `refold` writes, difference vetoes applied."""
        adjacency = identity_module.standing_adjacency(organization)

        expected: dict[str, str] = {}
        unassigned = set(adjacency)
        while unassigned:
            component = identity_module._reachable(min(unassigned), adjacency)
            unassigned -= component
            if len(component) < 2:
                continue
            canonical = min(component)
            for member in component:
                expected[member] = canonical
        return expected
