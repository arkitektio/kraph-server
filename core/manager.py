from core import models, enums, age, inputs

def rebuild_graph(graph: models.Graph):
    
    for item in graph.ontology.expressions.all():
        
        if item.kind == enums.ExpressionKind.ENTITY:
            age.create_age_entity_kind(graph.age_name, item.age_name)

        elif item.kind == enums.ExpressionKind.RELATION:
            age.create_age_relation_kind(graph.age_name, item.age_name)

        elif item.kind == enums.ExpressionKind.METRIC:
            age.create_age_relation_kind(graph.age_name, item.age_name)

        elif item.kind == enums.ExpressionKind.RELATION_METRIC:
            age.create_age_relation_kind(graph.age_name, item.age_name)

        
        
def build_age_name(label: str, kind: enums.ExpressionKind):
    if kind == enums.ExpressionKind.ENTITY.value:
            return label.replace(" ", "_").replace("-", "_").lower()
    elif kind == enums.ExpressionKind.RELATION.value:
        return label.replace(" ", "_").replace("-", "_").upper()
    elif kind == enums.ExpressionKind.RELATION_METRIC.value:
        return label.replace(" ", "_").replace("-", "_").upper()
    elif kind == enums.ExpressionKind.METRIC.value:
        return label.replace(" ", "_").replace("-", "_").lower()
    elif kind == enums.ExpressionKind.STRUCTURE.value:
        return label.replace(" ", "_").replace("-", "_").lower()
    else:
        raise ValueError(f"Unknown kind {kind}")