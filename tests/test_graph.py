import pytest
from core.models import Graph
from django.contrib.auth import get_user_model
from authentikate.models import Client, Organization, User
from kraph_server.schema import schema
from guardian.shortcuts import get_perms
from asgiref.sync import sync_to_async
from kante.context import HttpContext

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_graph(db, authenticated_context: HttpContext):

    graph = await Graph.objects.acreate(
        name="Test Model",
        description="This is a test model",
        user=authenticated_context.request.user,
        organization=authenticated_context.request.organization,
    )

    query = """
        query {
            graph(id: 1) {
                id
                name
            }
        }
    """

    sub = await schema.execute(
        query,
        context_value=authenticated_context,
    )

    assert sub.data, sub.errors

    assert sub.data["graph"]["name"] == "Test Model"
