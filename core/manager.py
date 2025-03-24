from core import models, enums, age, inputs

def rebuild_graph(graph: models.Graph):
    
    for item in graph.ontology.generic_categories.all():
       age.create_age_entity_kind(graph.age_name, item.age_name)

    for item in graph.ontology.measurement_categories.all():
        age.create_age_relation_kind(graph.age_name, item.age_name)
        
    for item in graph.ontology.relation_categories.all():
        age.create_age_relation_kind(graph.age_name, item.age_name)
        
    for item in graph.ontology.structure_categories.all():
        age.create_age_entity_kind(graph.age_name, item.age_name)


 
 
 
def build_generic_age_name(label: str):
    return label.replace(" ", "_").replace("-", "_").lower()       
        
def build_structure_age_name(identifier:str):
    return identifier.replace(" ", "_").replace("-", "_").lower()

def build_relation_age_name(label: str):
    return label.replace(" ", "_").replace("-", "_").upper()

def build_measurement_age_name(label: str):
    return label.replace(" ", "_").replace("-", "_").lower()

    
    
def create_default_structure_queries_for_structure(structure_category: models.StructureCategory, entity: age.RetrievedEntity):
    
    # Should create a query that takes all self-referencing relations as measurements
    # and returns it as a table
    node_query = f"""
    MATCH (n:{entity.age_name}) -[r]-> (n)
    
    RETURN n
    """
    
    return None
    
    