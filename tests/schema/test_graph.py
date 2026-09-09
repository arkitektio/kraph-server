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


@pytest.mark.django_db(transaction=True)
def test_deleting_an_image_does_not_delete_the_view(test_graph: Graph) -> None:
    """`Graph.image` and `Category.image` cascaded *from* the media store: deleting
    a picture deleted the view, its categories and its whole projection."""
    from datalayer.models import MediaStore

    store = MediaStore.objects.create(key="graph.png", bucket="media", kind="MEDIA")
    test_graph.image = store
    test_graph.save(update_fields=["image"])
    category = test_graph.categories.first()
    category.image = store
    category.save(update_fields=["image"])

    # A queryset delete: the model's `delete()` would also try the object store.
    MediaStore.objects.filter(pk=store.pk).delete()

    test_graph.refresh_from_db()
    category.refresh_from_db()
    assert test_graph.image is None and category.image is None
