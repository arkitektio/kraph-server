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



async def load_generic_cateogries(age_names):
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
            await models.GenericCategory.objects.aget(
                ontology=graphs[graph_name].ontology,
                age_name=age_name,
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


async def load_relation_category(age_names):
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
            await models.RelationCategory.objects.aget(
                ontology=graphs[graph_name].ontology,
                age_name=age_name,
            )
        )

    return gotten

async def load_measurement_category(age_names):
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
            await models.MeasurementCategory.objects.aget(
                ontology=graphs[graph_name].ontology,
                age_name=age_name,
            )
        )

    return gotten


async def load_step_category(age_names):
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
            await models.StepCategory.objects.aget(
                ontology=graphs[graph_name].ontology,
                age_name=age_name,
            )
        )

    return gotten



async def graph_loader_func(graph_names):
    
    gotten = []
    
    for i in graph_names:
        gotten.append(
            await models.Graph.objects.aget(age_name=i)
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


async def node_view_loaders(node_ids):
    
    gotten = []
    
    for i in node_ids:
        gotten.append(
            await models.NodeView.objects.filter(node_id=i)
        )
    
    return gotten

async def load_protocolstep_templates(node_ids):
    
    gotten = []
    
    for i in node_ids:
        gotten.append(
            await models.ProtocolStepTemplate.objects.aget(node_id=i)
        )
        # TODO: WE REALLY NEED TO RETURN THE NODES ACCORDING TO THE IDS
    
    return gotten


expression_loader = DataLoader(load_fn=load_expressions)
generic_category_loader = DataLoader(load_fn=load_generic_cateogries)
structure_category_loader = DataLoader(load_fn=load_structure_cateogries)
relation_category_loader = DataLoader(load_fn=load_relation_category)
protocolstep_template_loader = DataLoader(load_fn=load_protocolstep_templates)
measurement_category_loader = DataLoader(load_fn=load_measurement_category)
step_category_loader = DataLoader(load_fn=load_step_category)
graph_loader = DataLoader(load_fn=graph_loader_func)

metric_key_loader = DataLoader(load_fn=metric_key_loader)
node_view_loader = DataLoader(load_fn=node_view_loaders)