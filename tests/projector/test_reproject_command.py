"""`manage.py reproject` is the operational form of the rebuild claim.

Second management command in the repo, after `validate_settings`. Worth testing
because it is the thing someone reaches for at 3am after a bad deploy, and
because a command that silently rebuilds nothing looks exactly like a command
that worked.
"""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core import models as core_models


@pytest.mark.django_db(transaction=True)
def test_requires_a_target(age_engine) -> None:
    """Refusing to guess is the point: --all is destructive across every graph."""
    with pytest.raises(CommandError, match="--graph"):
        call_command("reproject", stdout=StringIO())


@pytest.mark.django_db(transaction=True)
def test_unknown_graph_is_an_error_not_a_silent_success(age_engine) -> None:
    """A typo in the graph name must not report a successful rebuild of nothing."""
    with pytest.raises(CommandError, match="No matching graphs"):
        call_command("reproject", graph="does-not-exist", stdout=StringIO())


@pytest.mark.django_db(transaction=True)
def test_dry_run_touches_nothing(test_graph: core_models.Graph, age_engine) -> None:
    """--dry-run reports the plan without dropping the projection."""
    out = StringIO()
    call_command("reproject", graph=test_graph.name, dry_run=True, stdout=out)

    output = out.getvalue()
    assert "would rebuild" in output
    assert f"#{test_graph.pk}" in output
    assert test_graph.age_name not in output, "the AGE handle is internal; the command names a graph by name and id"


@pytest.mark.django_db(transaction=True)
def test_rebuilds_by_name_and_reports_what_it_did(test_graph: core_models.Graph, age_engine) -> None:
    """The counts in the output are the evidence that it ran."""
    out = StringIO()
    call_command("reproject", graph=test_graph.name, stdout=out)

    output = out.getvalue()
    assert f"rebuilding {test_graph.name}" in output
    assert "entities projected" in output
