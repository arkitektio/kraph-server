"""The projection's health, for `/ht`.

`Graph.projection { lag pending }` says where one view stands, but reading it
needs an authenticated GraphQL query per graph. A probe wants one answer for the
whole service: is any consistent view further behind its organization's log than
the deployment is willing to tolerate? That is `settings.PROJECTION_LAG_THRESHOLD`
(`projection.lag_threshold` in the config).

Non-critical on purpose. A lagging projector is degraded, not down — the
evidence is durable and `reproject --incremental` (the runner) is what catches
up — so this check warns instead of failing the probe. A liveness probe that
restarted the web process for a slow drawing would help nothing.
"""

from __future__ import annotations

from django.conf import settings
from health_check.backends import BaseHealthCheckBackend
from health_check.exceptions import ServiceWarning


class ProjectionLagHealthCheck(BaseHealthCheckBackend):
    """Every consistent view is within the threshold of its organization's log."""

    critical_service = False

    def check_status(self) -> None:
        from core import models as core_models
        from graph_engine import watermark
        from graph_engine.models import Projection

        threshold = int(getattr(settings, "PROJECTION_LAG_THRESHOLD", 1000))
        graphs = list(core_models.Graph.objects.select_related("organization").order_by("pk"))
        if not graphs:
            return
        positions = watermark.positions(graphs)
        names = {graph.pk: f"{graph.organization.slug}/{graph.name}" for graph in graphs}

        behind = [(names[pk], where.lag) for pk, where in positions.items() if where.status == Projection.Status.CONSISTENT and where.lag > threshold]
        if behind:
            listed = ", ".join(f"{name} ({lag} behind)" for name, lag in behind[:5])
            more = "" if len(behind) <= 5 else f" and {len(behind) - 5} more"
            self.add_error(ServiceWarning(f"{len(behind)} view(s) more than {threshold} acts behind the log: {listed}{more}"))

        # Not lag: a view nobody has drawn yet, or a rebuild that has not finished
        # (or died). Reported separately so an operator can tell the two apart.
        unsettled = [f"{names[pk]} ({where.status})" for pk, where in positions.items() if where.status != Projection.Status.CONSISTENT]
        if unsettled:
            self.add_error(ServiceWarning(f"{len(unsettled)} view(s) not consistent: {', '.join(unsettled[:5])}"))

    def identifier(self) -> str:
        return "Projection lag"
