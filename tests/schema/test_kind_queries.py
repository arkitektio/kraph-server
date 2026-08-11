"""The organization's vocabulary, through the API.

Replaces `test_structure_category.py` and `test_metric_category.py`, which
queried `structureCategories` / `metricCategories` — root fields whose only
tenant fence was the client happening to pass `CategoryFilter.graph`. Kinds have
no graph to filter on, so the fields now have explicit resolvers that scope to
the request's organization, and that scoping is what these tests check.
"""

from typing import Set

import pytest
from asgiref.sync import sync_to_async
from authentikate.models import Organization
from kante.context import HttpContext

from api.schema import schema
from core.enums import ValueKind
from core.models import Graph
from evidence import models as evidence_models
from evidence import writer

STRUCTURE_KINDS = """
    query StructureKinds {
        structureKinds { id identifier label }
    }
"""

METRIC_KINDS = """
    query MetricKinds {
        metricKinds { id key valueKind structureKind { identifier } }
    }
"""


@sync_to_async
def _seed(organization: Organization) -> None:
    roi = writer.ensure_structure_kind(organization, "@mikro/roi")
    roi.label = "TEST_ROI"
    roi.save()

    nucleus = writer.ensure_structure_kind(organization, "@mikro/nucleus")
    nucleus.label = "TEST_NUCLEUS"
    nucleus.save()

    writer.ensure_metric_kind(organization, roi, "vector_length", ValueKind.FLOAT)


@sync_to_async
def _seed_other_organization() -> Organization:
    other, _ = Organization.objects.get_or_create(slug="a-different-tenant")
    writer.ensure_structure_kind(other, "@secret/thing")
    return other


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_structure_kinds_lists_the_organizations_vocabulary(test_graph: Graph, authenticated_context: HttpContext) -> None:
    """Both kinds, with no graph named anywhere in the query."""
    await _seed(test_graph.organization)

    result = await schema.execute(STRUCTURE_KINDS, context_value=authenticated_context)

    assert result.errors is None, result.errors
    identifiers: Set[str] = {item["identifier"] for item in result.data["structureKinds"]}
    assert {"@mikro/roi", "@mikro/nucleus"} <= identifiers


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_metric_kinds_name_the_structure_they_describe(test_graph: Graph, authenticated_context: HttpContext) -> None:
    """A measurement term is meaningless without the thing it measures."""
    await _seed(test_graph.organization)

    result = await schema.execute(METRIC_KINDS, context_value=authenticated_context)

    assert result.errors is None, result.errors
    kinds = {item["key"]: item for item in result.data["metricKinds"]}
    assert "vector_length" in kinds
    assert kinds["vector_length"]["structureKind"]["identifier"] == "@mikro/roi"
    assert kinds["vector_length"]["valueKind"] == "FLOAT"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_another_organizations_kinds_are_not_returned(test_graph: Graph, authenticated_context: HttpContext) -> None:
    """The check that matters.

    Removing `CategoryFilter.graph` removed the only thing that had ever scoped
    these fields, so a missing resolver would leak every tenant's vocabulary to
    every caller — and nothing would have looked wrong.
    """
    await _seed(test_graph.organization)
    await _seed_other_organization()

    result = await schema.execute(STRUCTURE_KINDS, context_value=authenticated_context)

    assert result.errors is None, result.errors
    identifiers: Set[str] = {item["identifier"] for item in result.data["structureKinds"]}
    assert "@secret/thing" not in identifiers, "Another organization's vocabulary must never appear"
    assert await evidence_models.StructureKind.all_objects.filter(identifier="@secret/thing").acount() == 1
