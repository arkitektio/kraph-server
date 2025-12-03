from strawberry.dataloader import DataLoader
from core import models
from django.contrib.auth import get_user_model


async def load_reagent_categories(ids):
    gotten = []
    for i in ids:
        gotten.append(
            await models.ReagentCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_label_templaters(ids):
    gotten: list[models.NodeCategory] = []
    for i in ids:
        gotten.append(
            await models.NodeCategory.objects.aget(
                id=i,
            )
        )

    templaters = []

    for cat in gotten:
        node_templater = []

        for i in cat.defined_properties:
            if i.use_as_label:
                node_templater.append(i.key)

        templaters.append(node_templater)

    return templaters


async def load_metric_categories(ids):
    gotten = []
    for i in ids:
        gotten.append(
            await models.MetricCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_users(ids):
    gotten = []
    for i in ids:
        gotten.append(
            await get_user_model().objects.aget(
                id=i,
            )
        )

    return gotten


async def load_entity_categories(ids):
    gotten = []
    for i in ids:
        gotten.append(
            await models.EntityCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_structure_categories(ids):
    gotten = []
    for i in ids:
        gotten.append(
            await models.StructureCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_natural_event_categories(ids):
    gotten = []
    for i in ids:
        gotten.append(
            await models.NaturalEventCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_protocol_event_categories(ids):
    gotten = []
    for i in ids:
        gotten.append(
            await models.ProtocolEventCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_measurement_categories(ids):
    gotten = []
    for i in ids:
        gotten.append(
            await models.MeasurementCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_relation_categories(ids):
    gotten = []
    for i in ids:
        gotten.append(
            await models.RelationCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_structure_relation_categories(ids):
    gotten = []
    for i in ids:
        gotten.append(
            await models.StructureRelationCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_structure_cateogries(age_names):
    """
    Asynchronously loads linked expressions based on the provided age names.

    Args:
        age_names (list of str): A list of strings where each string is in the format "graph_name:age_name".

    Returns:
        list: A list of LinkedExpression objects that match the provided age names.

    Raises:
        models.LinkedExpression.DoesNotExist: If no LinkedExpression object is found for the given age names.
    """

    gotten = []
    graphs = {}

    for i in age_names:
        graph_name, age_name = i.split(":")

        if graph_name not in graphs:
            graphs[graph_name] = await models.Graph.objects.select_related("ontology").aget(age_name=graph_name)

        gotten.append(
            await models.StructureCategory.objects.aget(
                ontology=graphs[graph_name].ontology,
                age_name=age_name,
            )
        )

    return gotten


async def graph_loader_func(graph_names):
    gotten = []

    for i in graph_names:
        gotten.append(await models.Graph.objects.aget(age_name=i))

    return gotten


reagent_category_loader = DataLoader(load_fn=load_reagent_categories)
entity_category_loader = DataLoader(load_fn=load_entity_categories)
structure_category_loader = DataLoader(load_fn=load_structure_categories)
natural_event_category_loader = DataLoader(load_fn=load_natural_event_categories)
metric_category_loader = DataLoader(load_fn=load_metric_categories)
protocol_event_category_loader = DataLoader(load_fn=load_protocol_event_categories)

relation_category_loader = DataLoader(load_fn=load_relation_categories)
structure_relation_category_loader = DataLoader(load_fn=load_structure_relation_categories)
measurement_category_loader = DataLoader(load_fn=load_measurement_categories)
graph_loader = DataLoader(load_fn=graph_loader_func)
user_loader = DataLoader(load_fn=load_users)
label_loader_templaters = DataLoader(load_fn=load_label_templaters)
