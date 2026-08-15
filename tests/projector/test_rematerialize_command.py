"""`manage.py rematerialize` is the out-of-band half of the redraw.

The mutation does it inline, which is right while a schema is being designed and
wrong once a category draws a hundred thousand entities: the redraw is unbounded
in the size of the graph and this service has no job queue. So the operator path
has to exist, and — like `reproject`, which someone reaches for at 3am — it has
to be distinguishable from a command that silently did nothing.

The interesting assertion is `--stale`. It selects on `__schema_version`, the
stamp `projector.project` writes onto every vertex, so a freshly projected graph
must report *no* work. A `--stale` that always finds something would make the
cheap check useless and push every operator back to the whole-graph sweep.
"""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core import models as core_models


@pytest.mark.django_db(transaction=True)
def test_requires_a_target(age_engine) -> None:
    """Same refusal as `reproject`: a sweep across every graph is not a default."""
    with pytest.raises(CommandError, match="--graph"):
        call_command("rematerialize", stdout=StringIO())


@pytest.mark.django_db(transaction=True)
def test_unknown_graph_is_an_error_not_a_silent_success(age_engine) -> None:
    """A typo must not report a successful redraw of nothing."""
    with pytest.raises(CommandError, match="No matching graphs"):
        call_command("rematerialize", graph="does-not-exist", stdout=StringIO())


@pytest.mark.django_db(transaction=True)
def test_dry_run_names_the_categories_it_would_redraw(test_graph: core_models.Graph, age_engine) -> None:
    """Node categories only — an edge carries nothing derived to go stale."""
    out = StringIO()
    call_command("rematerialize", graph=test_graph.name, dry_run=True, stdout=out)

    output = out.getvalue()
    assert f"would redraw {test_graph.age_name}.AIS" in output
    assert "IS_CONNECTED_TO" not in output, "Relations are edges; `project_edges` derives nothing onto them"


@pytest.mark.django_db(transaction=True)
def test_a_single_category_can_be_named(test_graph: core_models.Graph, age_engine) -> None:
    """Because the whole-graph sweep is the expensive thing this avoids."""
    out = StringIO()
    call_command("rematerialize", graph=test_graph.name, category="AIS", dry_run=True, stdout=out)

    output = out.getvalue()
    assert "AIS" in output
    assert "Cell" not in output


@pytest.mark.django_db(transaction=True)
def test_stale_finds_nothing_in_a_freshly_projected_graph(test_graph: core_models.Graph, age_engine) -> None:
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


# The companion to the test above — a node that derived *nothing*, which is the
# case that would make `--stale` cry wolf — needs the real write path to create
# it, so it lives in `tests/api/test_rematerialization.py`.


@pytest.mark.django_db(transaction=True)
def test_it_redraws_and_says_how_much(test_graph: core_models.Graph, age_engine) -> None:
    """The count in the output is the evidence that it ran."""
    out = StringIO()
    call_command("rematerialize", graph=test_graph.name, category="AIS", stdout=out)

    output = out.getvalue()
    assert f"redrawing {test_graph.age_name}.AIS" in output
    assert "vertices redrawn" in output
