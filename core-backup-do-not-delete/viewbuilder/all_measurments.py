from core import models, enums


def all_informed_measurements_view_builder(structure: models.StructureCategory):
    return f"""
        MATCH (n) -> [r] -> (m)
        WHERE r.informed_by = "{structure.identifier}"
        
        
    """


def all_measurements_for_generic_node(node: models.GenericCategory):

    measurements = node.ontology.measurement_categories.filter(target=node).values_list(
        "age_name", flat=True
    )

    # Return all measurements that are connected to this node as a table of
    # index: node_id
    # values: [measurment_a_value] [measurement_b_value] ...
    return f"""
        MATCH (n:{node.age_name}) -[r]-> (m)
        WHERE r.age_name IN {measurements}
        WITH n, collect({{"measurement": r.age_name, "value": m.value}}) as measures
        RETURN n.id as node_id, 
               [x in measures | x.value] as measurement_values,
               [x in measures | x.measurement] as measurement_names
    """
