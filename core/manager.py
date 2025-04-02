import string
from core import models, enums, age, inputs


def rebuild_graph(graph: models.Graph):

    for item in graph.entity_categories.all():
        age.create_age_entity_kind(graph.age_name, item.age_name)

    for item in graph.measurement_categories.all():
        age.create_age_measurement_kind(graph.age_name, item.age_name)

    for item in graph.relation_categories.all():
        age.create_age_relation_kind(graph.age_name, item.age_name)

    for item in graph.structure_categories.all():
        age.create_age_structure_kind(graph.age_name, item.age_name)


def rebuild_default_views(graph: models.Graph):

    for item in graph.ontology.generic_categories.all():

        # Create a measurement view for each entity

        age.create_default_entity_view(graph.age_name, item.age_name)

    for item in graph.ontology.measurement_categories.all():
        age.create_default_measurement_view(graph.age_name, item.age_name)

    for item in graph.ontology.relation_categories.all():
        age.create_default_relation_view(graph.age_name, item.age_name)

    for item in graph.ontology.structure_categories.all():
        age.create_default_structure_view(graph.age_name, item.age_name)


def clean_string(text):
    return "".join(c for c in text if c in string.ascii_letters)


def clean_relation_string(text):
    return "".join(c for c in text if c in string.ascii_letters + "_")


def build_graph_age_name(label: str):
    return clean_string(label.replace(" ", "_").replace("-", "_").lower())


def build_entity_age_name(label: str):
    return clean_string(label.replace(" ", "_").replace("-", "_").lower())


def build_metric_age_name(label: str):
    return clean_string(label.replace(" ", "_").replace("-", "_").lower())


def build_structure_age_name(identifier: str):
    return clean_string(identifier.replace(" ", "_").replace("-", "_").lower())


def build_relation_age_name(label: str):
    return label.replace(" ", "_").replace("-", "_").upper()


def build_measurement_age_name(label: str):
    return label.replace(" ", "_").replace("-", "_").lower()


def build_protocol_event_age_name(label: str):
    return label.replace(" ", "").replace("-", "").lower() + "Event"


def build_reagent_age_name(label: str):
    return label.replace(" ", "").replace("-", "").lower() + "Event"


def build_protocol_event_age_name(label: str):
    return label.replace(" ", "").replace("-", "").lower() + "NaturalEvent"


def build_step_age_name(label: str):
    return label.replace(" ", "_").replace("-", "_").lower()


def build_participant_age_name(label: str):
    return "AS_" + label.replace(" ", "_").replace("-", "_").upper()


def create_default_structure_queries_for_structure(
    structure_category: models.StructureCategory, entity: age.RetrievedEntity
):

    # Should create a query that takes all self-referencing relations as measurements
    # and returns it as a table
    node_query = f"""
    MATCH (n:{entity.age_name}) -[r]-> (n)
    
    RETURN n
    """

    return None






def set_age_sequence(category: "models.Category", sequence_id: str | None = None, auto_create: bool = True):
    if sequence_id:
        index = models.GraphSequence.objects.get(id=sequence_id)
        category.sequence = index
        category.save()
    else:
        if not auto_create:
            pass
        
        graph_id = category.graph.id
        index, created = models.GraphSequence.objects.get_or_create(
            graph_id=graph_id,
            index=category.age_name.lower() + "_sequence",
            defaults=dict(
                description=f"Sequence for {category.age_name}",
                label="Sequence for " + category.age_name,
                graph=category.graph,
                min_value=0,
                start_value=0,
                max_value=None,
                cycle=False,
                step_size=1,
            ),
        )
        
        if created:
            try:
                age.create_age_sequence(index)
            except Exception as e:
                index.delete()
                raise e
            
        category.sequence = index
        category.save()
            

    return index




def set_position_info(category: "models.NodeCategory", input: inputs.NodeCategoryInput):
    if input.position_x:
        category.position_x = input.position_x
    if input.position_y:
        category.position_y = input.position_y
    if input.height:
        category.height = input.height
    if input.width:
        category.width = input.width
    if input.color:
        category.color = input.color
        
    category.save()