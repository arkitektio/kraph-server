from kante.types import Info
import strawberry
from core import types, models, age


@strawberry.input
class EntityRelationInput:
    left: strawberry.ID
    right: strawberry.ID
    kind: strawberry.ID


@strawberry.input
class DeleteEntityRelationInput:
    id: strawberry.ID



def create_entity_relation(
    info: Info,
    input: EntityRelationInput,
) -> types.EntityRelation:
    
    kind = models.LinkedExpression.objects.get(id=input.kind)
    

    left_graph, left_id = input.left.split(":")
    right_graph, right_id = input.right.split(":")

    assert left_graph == right_graph, "Cannot create a relation between entities in different graphs"


    retrieve = age.create_age_relation(kind.graph.age_name, kind.age_name, left_id, right_id)




    return types.EntityRelation(_value=retrieve)




@strawberry.input
class RoiEntityRelationInput:
    left_roi: strawberry.ID
    right_roi: strawberry.ID
    kind: strawberry.ID


def create_roi_entity_relation(
    info: Info,
    input: RoiEntityRelationInput,
) -> types.EntityRelation:
    

    kind = models.LinkedExpression.objects.get(id=input.kind)

    left_roi = models.ROI.objects.get(id=input.left_roi)
    right_roi = models.ROI.objects.get(id=input.right_roi)

    if not left_roi.entity:
        raise ValueError("Left ROI does not have an entity")
    if not right_roi.entity:
        raise ValueError("Right ROI does not have an entity")
    

    left_graph, left_id = left_roi.entity.split(":")
    right_graph, right_id = right_roi.entity.split(":")

    print("Creating relation between", left_graph, left_id, right_graph, right_id)

    assert left_graph == right_graph, "Cannot create a relation between entities in different graphs"


    retrieve = age.create_age_relation(kind.graph.age_name, kind.age_name, left_id, right_id)


    return types.EntityRelation(_value=retrieve)













def delete_entity_relation(
    info: Info,
    input: DeleteEntityRelationInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id

