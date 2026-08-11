"""A metric resolves against the schema of the graph *recording* it.

The failure this guards against only exists because evidence is now shared.
`ensure_structure` dedupes on `(organization, identifier, object)` and keeps
whichever category first created the row, so a structure introduced by graph A
and measured through graph B carries A's `StructureCategory`. Reading the acting
graph off `structure.category.graph` therefore resolves B's measurement against
A's schema — gating on A's permissions and filing any auto-created
`MetricCategory` under A, where B cannot see it.

`test_structure_dedup` proves the sharing but never records a metric through the
second graph, which is exactly why this needed its own test.
"""

import pytest
from authentikate.models import Organization

from core import models as core_models
from evidence import models as evidence_models
from evidence import writer


@pytest.fixture
def shared_structure(
    organization: Organization,
    roi_category_a: core_models.StructureCategory,
    assertion: evidence_models.Assertion,
) -> evidence_models.Structure:
    """One structure, introduced by graph A."""
    return writer.ensure_structure(organization, roi_category_a, "roi-shared", assertion)


def test_a_second_graph_reaches_the_same_structure(
    organization: Organization,
    shared_structure: evidence_models.Structure,
    roi_category_b: core_models.StructureCategory,
    assertion: evidence_models.Assertion,
) -> None:
    """Graph B resolving the same datum finds A's row rather than making its own."""
    again = writer.ensure_structure(organization, roi_category_b, "roi-shared", assertion)

    assert again.pk == shared_structure.pk
    # The row keeps the category that introduced it — which is precisely why the
    # acting graph cannot be inferred from it.
    assert again.category_id == roi_category_b.pk or again.category_id == shared_structure.category_id
    assert again.category.graph_id != roi_category_b.graph_id


def test_metric_category_belongs_to_the_recording_graph(
    organization: Organization,
    shared_structure: evidence_models.Structure,
    graph_b: core_models.Graph,
    roi_category_b: core_models.StructureCategory,
    assertion: evidence_models.Assertion,
) -> None:
    """The defect, stated directly.

    Graph B records a measurement on a structure graph A introduced. The
    resulting `MetricCategory` must belong to B — the graph whose schema declared
    the measurement — not to A.
    """
    category_b = core_models.MetricCategory.objects.create(
        graph=graph_b,
        structure_category=roi_category_b,
        key="vector_length",
        age_name="vector_length",
    )

    metric = writer.record_metric(
        organization,
        shared_structure,
        category_b,
        key="vector_length",
        value=45.2,
        assertion=assertion,
    )

    assert metric.category.graph_id == graph_b.pk, "A metric recorded through graph B resolved against another graph's schema"
