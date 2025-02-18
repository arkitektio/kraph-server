from strawberry.dataloader import DataLoader
from core import models


async def load_expressions(age_names):
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
            await models.Expression.objects.aget(
                ontology=graphs[graph_name].ontology,
                age_name=age_name,
            )
        )

    return gotten


async def metric_key_loader(keys):
    """
    Asynchronously loads metric keys and retrieves corresponding LinkedExpression objects.

    Args:
        keys (list of str): A list of keys where each key is a string in the format "graph_name:age_name".

    Returns:
        list: A list of LinkedExpression objects corresponding to the provided keys.

    Raises:
        DoesNotExist: If no LinkedExpression object is found for a given key.
        MultipleObjectsReturned: If multiple LinkedExpression objects are found for a given key.
    """
    gotten = []

    for i in keys:
        graph_name, age_name = i.split(":")

        gotten.append(
            await models.Expression.objects.aget(
                graph__age_name=graph_name,
                age_name=age_name,
            )
        )

    return gotten


expression_loader = DataLoader(load_fn=load_expressions)


metric_key_loader = DataLoader(load_fn=metric_key_loader)
