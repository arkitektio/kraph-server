from django.db.models.signals import post_save
from django.dispatch import receiver
from core import models


@receiver(post_save, sender=models.StructureCategory)
def create_structure_query(sender, instance, created, **kwargs):

    if created:
        node_query = models.NodeQuery.objects.create(
            graph=instance.graph,
            query="""
            MATCH path = (n)-[*1..3]-(m)
            WHERE id(n) = %s
            RETURN path
            """,
            name="Related Nodes",
            description="Just everything",
            kind="PATH",
        )

        node_query.relevant_for_nodes.add(instance)
