import pytest
from api.schema import schema
from core.models import Graph
from kante.context import HttpContext


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_graph(db: object, authenticated_context: HttpContext) -> None:
    graph: Graph = await Graph.objects.acreate(
        name="Test Model",
        description="This is a test model",
        user=authenticated_context.request.user,
        organization=authenticated_context.request.organization,
        membership=authenticated_context.request.membership,
    )

    query: str = f"""
        query {{
            graph(id: {graph.pk}) {{
                id
                name
            }}
        }}
    """

    sub = await schema.execute(
        query,
        context_value=authenticated_context,
    )

    assert sub.data, sub.errors

    assert sub.data["graph"]["name"] == "Test Model"
