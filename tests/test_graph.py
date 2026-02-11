import pytest
from core.models import Graph
from api.schema import schema
from kante.context import HttpContext

@pytest.mark.skip(reason="Requires full database migrations and backend stack - legacy test")
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_graph(db, authenticated_context: HttpContext):

    graph = await Graph.objects.acreate(
        name="Test Model",
        description="This is a test model",
        user=authenticated_context.request.user,
        organization=authenticated_context.request.organization,
        membership=authenticated_context.request.membership,
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


