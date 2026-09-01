"""Destroy evidence, on purpose, outside the API.

Every ``delete*`` mutation for instance data is gone: evidence is append-only, so
retraction is a ``Standing`` and the record of what a derived value once
rested on survives. That is the right default and it is not negotiable through
the API.

It is not sufficient for everything. A datum ingested that should never have been
— personal data, a mis-scoped import, a leaked object key — has to actually
leave, and no amount of archiving achieves that. This command is that escape
hatch: deliberate, operator-only, logged, and impossible to reach from a GraphQL
request.

Redaction records *that* it happened, and now what it reached. The `Assertion` it
writes survives the rows it destroys and carries the target's id and the row
counts in `action_args`, so the log says something was erased, by whom, when, and
how much. What it cannot say is what the thing *was*. That is the honest limit of
erasure, and the reason to prefer `archive*` for anything that is merely wrong
rather than prohibited.

**The claim log itself is never destroyed.** This used to delete the `Standing` rows
about the target along with the target, which erased the record of who had
asserted or retracted it — the one part of the account that is *about people
rather than about the datum*, and the part an erasure has least business
removing. The claims survive, pointing at a target that is gone; refs are opaque,
so nothing breaks, and "somebody claimed this and later withdrew it" remains
answerable after the thing itself has left.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from api.extensions.projection import current_or_default
from authentikate.models import Organization
from core import models
from evidence import models as evidence_models
from evidence import writer
from graph_engine.controller import GraphController


class Command(BaseCommand):
    """Erase a structure or an entity and everything derived from it."""

    help = "Permanently destroy evidence. Prefer the archive mutations; this is for data that must not exist."

    def add_arguments(self, parser) -> None:
        """Declare the command's arguments."""
        parser.add_argument("--organization", required=True, help="Slug of the organization owning the evidence.")
        parser.add_argument("--structure", help="Primary key of a structure to erase, with every metric describing it.")
        parser.add_argument("--entity", help="Uuid of an entity or event to erase.")
        parser.add_argument("--subject", default="redaction", help="Who is accountable for this erasure. Recorded on the assertion.")
        parser.add_argument("--dry-run", action="store_true", help="Report what would be destroyed without destroying it.")
        parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt. Required for non-interactive use.")

    def handle(self, *args, **options) -> None:
        """Erase the named target."""
        if bool(options["structure"]) == bool(options["entity"]):
            raise CommandError("Name exactly one of --structure or --entity.")

        organization = Organization.objects.filter(slug=options["organization"]).first()
        if organization is None:
            raise CommandError(f"No organization with slug '{options['organization']}'.")

        if options["structure"]:
            plan = self._plan_structure(organization, options["structure"])
        else:
            plan = self._plan_entity(organization, options["entity"])

        for line in plan["describe"]:
            self.stdout.write(line)

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("dry run — nothing destroyed"))
            return

        if not options["yes"]:
            confirm = input("This cannot be undone. Type the target id to confirm: ")
            if confirm.strip() != plan["confirm"]:
                raise CommandError("Confirmation did not match. Nothing destroyed.")

        with transaction.atomic():
            # Written before the rows go, and deliberately not deleted with them:
            # the log keeps a record that an erasure happened. `action_name` and
            # `action_args` say which target and how much — the first production
            # writer of those columns, which have existed unpopulated since the
            # model was written and which every selector's `action_names` branch
            # filters on.
            writer.create_assertion(
                organization,
                subject=options["subject"],
                app_id="manage.py redact",
                action_name="redact",
                action_args=plan["record"],
            )
            # The log refuses DELETE by trigger (`0005_log_is_append_only`). This
            # is the one sanctioned reason to destroy evidence, so it says so
            # explicitly, and `LOCAL` scopes the permission to this transaction —
            # nothing outside it inherits the exemption.
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL kraph.allow_log_rewrite = 'on'")
            plan["destroy"]()

        self.stdout.write(self.style.SUCCESS("destroyed"))
        self._reproject(plan["graphs"])

    def _plan_structure(self, organization, structure_id: str) -> dict:
        structure = evidence_models.Structure.objects.for_organization(organization).filter(pk=structure_id).first()
        if structure is None:
            raise CommandError(f"No structure {structure_id} in this organization.")

        metrics = evidence_models.Metric.objects.for_organization(organization).filter(structure=structure)
        links = evidence_models.Link.objects.for_organization(organization).filter(source_ref=str(structure.pk))
        refs = sorted({str(ref) for ref in links.values_list("target_ref", flat=True)})

        def destroy() -> None:
            # State rows are folded statistics over these metrics, so they have to
            # be dropped and refolded rather than left holding a contribution
            # whose source no longer exists.
            evidence_models.State.objects.for_organization(organization).filter(claim_ref__in=refs).delete()
            links.delete()
            structure.delete()  # cascades to its metrics

        return {
            "describe": [
                f"structure {structure.identifier}:{structure.object} ({structure.pk})",
                f"  {metrics.count()} metrics, {links.count()} links, {len(refs)} dependent refs",
            ],
            "record": {
                "target_type": "structure",
                "target_id": str(structure.pk),
                "identifier": structure.identifier,
                "metrics": metrics.count(),
                "links": links.count(),
                "dependent_refs": len(refs),
            },
            "confirm": str(structure.pk),
            "destroy": destroy,
            "graphs": self._graphs_for(organization, refs),
        }

    def _plan_entity(self, organization, ref: str) -> dict:
        node = evidence_models.Instance.objects.for_organization(organization).filter(id=ref).first()
        if node is None:
            raise CommandError(f"No node with ref '{ref}' in this organization.")

        links = evidence_models.Link.objects.for_organization(organization).filter(source_ref=ref) | evidence_models.Link.objects.for_organization(organization).filter(target_ref=ref)
        states = evidence_models.State.objects.for_organization(organization).filter(claim_ref=ref)
        lifecycle = evidence_models.Standing.objects.for_organization(organization).filter(target_id=ref)

        def destroy() -> None:
            states.delete()
            links.delete()
            # `lifecycle` is deliberately *not* deleted — see the module
            # docstring. The claims outlive the node they are about.
            node.delete()

        return {
            "describe": [
                f"node {ref} ({node.kind})",
                f"  {links.count()} links, {states.count()} state rows, {lifecycle.count()} claims (kept)",
            ],
            "record": {
                "target_type": "node",
                "target_id": str(ref),
                "node_kind": str(node.kind),
                "links": links.count(),
                "states": states.count(),
                "claims_kept": lifecycle.count(),
            },
            "confirm": ref,
            "destroy": destroy,
            "graphs": self._graphs_for(organization, [ref]),
        }

    def _graphs_for(self, organization, refs) -> list[models.Graph]:
        """The projections that will be wrong until they are rebuilt.

        Asked of the evidence base rather than read off the front of a ref: refs
        are bare uuids, and a node can be shown by more than one view.
        """
        from evidence import selector as selector_module

        # Pairs, not a mapping. `graph_ids_for_instance_ids` returns
        # `list[tuple[ref, graph_id]]` because a node can be in more than one
        # graph — a `dict[ref, graph]` could only record the last one. This called
        # `.values()` on that list, so `redact` raised `AttributeError` the moment
        # it reached the reprojection step and the command was broken outright.
        graph_ids = {graph_id for _, graph_id in selector_module.graph_ids_for_instance_ids(organization, refs)}
        return list(models.Graph.objects.filter(organization=organization, pk__in=graph_ids))

    def _reproject(self, graphs: list[models.Graph]) -> None:
        """Rebuild every projection that referenced the destroyed evidence.

        Not optional. The projection is a cache of the evidence, so leaving it
        alone would leave the redacted datum visible in the drawing — which is the
        one outcome this command exists to prevent.
        """
        if not graphs:
            return

        controller = GraphController(projector=current_or_default())
        for graph in graphs:
            self.stdout.write(f"rebuilding {graph.name} ({graph.age_name})…")
            controller.rebuild_projection(graph)

