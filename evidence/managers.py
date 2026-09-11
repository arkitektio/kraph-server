"""Organization scoping for evidence models.

Evidence used to be siloed by construction: every structure and metric lived in a
per-graph Apache AGE namespace, so a query against graph A *physically could not*
read graph B. Sharing evidence across projections gives that up — the isolation
stops being structural and becomes a discipline, and a single forgotten
``organization`` filter is a cross-tenant leak.

This module is the replacement for the guarantee we gave up. It makes the unsafe
call the loud one: ``Structure.objects`` has no default queryset at all, so
``Structure.objects.filter(...)`` raises instead of quietly returning every
organization's rows. The only way to get a queryset is to name an organization.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models

if TYPE_CHECKING:
    from authentikate.models import Organization


class UnscopedEvidenceAccess(RuntimeError):
    """Raised when evidence is queried without naming an organization."""


class OrganizationScopedManager[Row: models.Model](models.Manager):
    """A manager with no usable default queryset.

    Generic in its row type, and parameterized at each declaration
    (``Instance.objects = OrganizationScopedManager["Instance"]()``), so
    ``for_organization`` hands back a `QuerySet[Instance]` rather than the
    `QuerySet[Any]` it used to. That `Any` is what made every read through this
    manager — which is every read of evidence there is — untyped from its first
    line, and it carried a ``# type: ignore[type-arg]`` admitting as much.

    Every read has to go through :meth:`for_organization`, which is the whole
    point: there is no spelling of "just get me the rows" that silently spans
    tenants. Django's own internals (cascade deletion, reverse FK descriptors,
    the migration executor) do not use this manager — the models set
    ``base_manager_name``/``default_manager_name`` to ``all_objects`` so the
    framework keeps working while application code stays fenced in.
    """

    def get_queryset(self) -> models.QuerySet[Row]:
        raise UnscopedEvidenceAccess(
            f"{self.model.__name__}.objects has no default queryset because evidence is "
            f"organization-scoped. Use {self.model.__name__}.objects.for_organization(org).\n"
            f"If you genuinely need to cross organizations — a migration, a management "
            f"command, a test fixture — use {self.model.__name__}.all_objects and leave a "
            f"comment saying why."
        )

    def for_organization(self, organization: "Organization | int") -> models.QuerySet[Row]:
        """The only supported entry point for reading evidence."""
        return super().get_queryset().filter(organization=organization)

    def create_for_organization(self, organization: "Organization", **kwargs: object) -> Row:
        """Create a row with the organization bound explicitly."""
        return super().get_queryset().create(organization=organization, **kwargs)
