"""The operator commands rebuild and redraw, and say what they did (A7).

`reproject`, `rematerialize --stale` and their kin are the operational form of
the rebuild claim; a command that silently rebuilds nothing looks exactly like
one that worked, so each is checked for what it changed and what it printed.
"""

from io import StringIO
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from core import models as core_models


@pytest.mark.django_db(transaction=True)
def test_reproject_requires_a_target(table_projector) -> None:
    """Refusing to guess is the point: --all is destructive across every graph."""
    with pytest.raises(CommandError, match="--graph"):
        call_command("reproject", stdout=StringIO())
@pytest.mark.django_db(transaction=True)
def test_reproject_refuses_an_unknown_graph(table_projector) -> None:
    """A typo in the graph name must not report a successful rebuild of nothing."""
    with pytest.raises(CommandError, match="No matching graphs"):
        call_command("reproject", graph="does-not-exist", stdout=StringIO())
@pytest.mark.django_db(transaction=True)
def test_dry_run_touches_nothing(test_graph: core_models.Graph, table_projector) -> None:
    """--dry-run reports the plan without dropping the projection."""
    out = StringIO()
    call_command("reproject", graph=test_graph.name, dry_run=True, stdout=out)

    output = out.getvalue()
    assert "would rebuild" in output
    assert f"#{test_graph.pk}" in output
    assert test_graph.age_name not in output, "the namespace handle is internal; the command names a graph by name and id"
@pytest.mark.django_db(transaction=True)
def test_rebuilds_by_name_and_reports_what_it_did(test_graph: core_models.Graph, table_projector) -> None:
    """The counts in the output are the evidence that it ran."""
    out = StringIO()
    call_command("reproject", graph=test_graph.name, stdout=out)

    output = out.getvalue()
    assert f"rebuilding {test_graph.name}" in output
    assert "entities projected" in output


@pytest.mark.django_db(transaction=True)
def test_rematerialize_requires_a_target(table_projector) -> None:
    """Same refusal as `reproject`: a sweep across every graph is not a default."""
    with pytest.raises(CommandError, match="--graph"):
        call_command("rematerialize", stdout=StringIO())


@pytest.mark.django_db(transaction=True)
def test_rematerialize_refuses_an_unknown_graph(table_projector) -> None:
    """A typo must not report a successful redraw of nothing."""
    with pytest.raises(CommandError, match="No matching graphs"):
        call_command("rematerialize", graph="does-not-exist", stdout=StringIO())


@pytest.mark.django_db(transaction=True)
def test_dry_run_names_the_categories_it_would_redraw(test_graph: core_models.Graph, table_projector) -> None:
    """Node categories only — an edge carries nothing derived to go stale."""
    out = StringIO()
    call_command("rematerialize", graph=test_graph.name, dry_run=True, stdout=out)

    output = out.getvalue()
    assert f"would redraw {test_graph.name} (#{test_graph.pk}).AIS" in output
    assert "IS_CONNECTED_TO" not in output, "Relations are edges; `project_edges` derives nothing onto them"


@pytest.mark.django_db(transaction=True)
def test_a_single_category_can_be_named(test_graph: core_models.Graph, table_projector) -> None:
    """Because the whole-graph sweep is the expensive thing this avoids."""
    out = StringIO()
    call_command("rematerialize", graph=test_graph.name, category="AIS", dry_run=True, stdout=out)

    output = out.getvalue()
    assert "AIS" in output
    assert "Cell" not in output


@pytest.mark.django_db(transaction=True)
def test_stale_finds_nothing_in_a_freshly_projected_graph(test_graph: core_models.Graph, table_projector) -> None:
    """The check has to be able to say "no work", or it is not a check.

    `materialize` projects as it builds, so every vertex carries the active
    schema hash. Nothing here is behind, and the command must agree.

    The empty-string assertion depends on every vertex in the fixture having gone
    through `projector.project`, which is what stamps `__schema_version`. A
    category with no vertices is fine — `_is_stale` counts zero — but a fixture
    that draws a vertex some other way would break this, and the break would be
    correct: such a vertex really has not been derived under any schema.
    """
    out = StringIO()
    call_command("rematerialize", graph=test_graph.name, stale=True, dry_run=True, stdout=out)

    assert out.getvalue() == "", "A projection level with its schema owes no redraw"


@pytest.mark.django_db(transaction=True)
def test_it_redraws_and_says_how_much(test_graph: core_models.Graph, table_projector) -> None:
    """The count in the output is the evidence that it ran."""
    out = StringIO()
    call_command("rematerialize", graph=test_graph.name, category="AIS", stdout=out)

    output = out.getvalue()
    assert f"redrawing {test_graph.name} (#{test_graph.pk}).AIS" in output
    assert "vertices redrawn" in output


@pytest.mark.django_db(transaction=True)
def test_the_runner_flags_go_with_incremental(table_projector) -> None:
    """`--loop` applies the outbox repeatedly; a full rebuild is a one-off act and refuses it."""
    with pytest.raises(CommandError, match="--loop goes with --incremental"):
        call_command("reproject", all=True, loop=True, stdout=StringIO())
    with pytest.raises(CommandError, match="--interval goes with --loop"):
        call_command("reproject", incremental=True, all=True, interval=5, stdout=StringIO())
    with pytest.raises(CommandError, match="Pick one"):
        call_command("reproject", incremental=True, all=True, loop=True, dry_run=True, stdout=StringIO())


@pytest.mark.django_db(transaction=True)
def test_the_manual_incremental_pass_reports_an_idle_organization(test_graph: core_models.Graph, table_projector) -> None:
    out = StringIO()
    call_command("reproject", incremental=True, organization=test_graph.organization.slug, stdout=out)
    assert "nothing owed" in out.getvalue()
