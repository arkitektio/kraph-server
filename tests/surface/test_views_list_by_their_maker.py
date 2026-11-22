"""A member's views are listable by who made them and when (C4, C7).

A member's profile merges what they made across services, newest first. A view
answers that with `GraphFilter.creator` (a lok sub), `GraphOrder.createdAt`, and
a `createdAt` on the view itself; `graphStats` counts and buckets by the same
column.

History: `GraphStats` was built over a `created_at` column `Graph` did not
have, and the stats factory attached `series` after strawberry had read the
class, so no stats type ever offered a series and every field aggregate on a
view raised a FieldError.
"""

from datetime import timedelta

import kante
import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone
from kante.context import HttpContext

from core.models import Graph
from tests.support.reads import GRAPH_STATS, GRAPHS_BY
from tests.support.writes import execute


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_graph_stats_bucket_by_creation(api_schema: kante.Schema, test_graph: Graph, api_context: HttpContext) -> None:
    data = await execute(api_schema, api_context, GRAPH_STATS)

    assert data["graphStats"]["count"] == 1
    assert sum(bucket["count"] for bucket in data["graphStats"]["series"]) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_members_views_are_theirs_newest_first(api_schema: kante.Schema, test_graph: Graph, api_context: HttpContext) -> None:
    def make_an_older_view() -> str:
        older = Graph.objects.create(name="older", user_id=test_graph.user_id, organization_id=test_graph.organization_id, membership_id=test_graph.membership_id)
        Graph.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=3))
        return str(Graph.objects.get(pk=test_graph.pk).user.sub)

    sub = await sync_to_async(make_an_older_view)()

    data = await execute(api_schema, api_context, GRAPHS_BY, {"creator": sub})

    assert [graph["name"] for graph in data["graphs"]] == [test_graph.name, "older"]
    assert all(graph["createdAt"] for graph in data["graphs"]), "The database stamps a new view"

    nobody = await execute(api_schema, api_context, GRAPHS_BY, {"creator": "nobody-has-this-sub"})
    assert nobody["graphs"] == []
