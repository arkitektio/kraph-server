from strawberry.dataloader import DataLoader
from core import models
from authentikate.models import User


PKType = int | str


async def load_metric_categories(ids: list[PKType]) -> list[models.MetricCategory]:
    """Loader function to fetch MetricCategory objects by their IDs."""
    gotten = []
    for i in ids:
        gotten.append(
            await models.MetricCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_users(ids: list[PKType]) -> list[User]:
    """Loader function to fetch User objects by their IDs."""
    
    gotten = []
    for i in ids:
        gotten.append(
            await User.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_entity_categories(ids: list[PKType]) -> list[models.EntityCategory]:
    """Loader function to fetch EntityCategory objects by their IDs."""
    gotten = []
    for i in ids:
        gotten.append(
            await models.EntityCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_structure_categories(ids: list[PKType]) -> list[models.StructureCategory]:
    """Loader function to fetch StructureCategory objects by their IDs."""
    gotten = []
    for i in ids:
        gotten.append(
            await models.StructureCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_natural_event_categories(ids: list[PKType]) -> list[models.NaturalEventCategory]:
    """Loader function to fetch NaturalEventCategory objects by their IDs."""
    gotten = []
    for i in ids:
        gotten.append(
            await models.NaturalEventCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_protocol_event_categories(ids: list[PKType]) -> list[models.ProtocolEventCategory]:
    """ Loader function to fetch ProtocolEventCategory objects by their IDs. """
    gotten = []
    for i in ids:
        gotten.append(
            await models.ProtocolEventCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_measurement_categories(ids: list[PKType]) -> list[models.MeasurementCategory]:
    """Loader function to fetch MeasurementCategory objects by their IDs."""
    gotten = []
    for i in ids:
        gotten.append(
            await models.MeasurementCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_relation_categories(ids: list[PKType]) -> list[models.RelationCategory]:
    """Loader function to fetch RelationCategory objects by their IDs."""
    gotten = []
    for i in ids:
        gotten.append(
            await models.RelationCategory.objects.aget(
                id=i,
            )
        )

    return gotten


async def load_structure_relation_categories(ids: list[PKType]) -> list[models.StructureRelationCategory]:
    """Loader function to fetch StructureRelationCategory objects by their IDs."""
    gotten = []
    for i in ids:
        gotten.append(
            await models.StructureRelationCategory.objects.aget(
                id=i,
            )
        )

    return gotten



async def graph_loader_func(graph_names: list[PKType]) -> list[models.Graph]:
    """ Loader function to fetch Graph objects by their names. """
    gotten = []

    for i in graph_names:
        gotten.append(await models.Graph.objects.aget(age_name=i))

    return gotten


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
