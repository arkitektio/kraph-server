from core import models, enums, inputs, manager
import strawberry 

def validate_structure_definition(
    structure_definition: inputs.CategoryDefinitionInput, graph: models.Graph
) -> None:
    
    
    validated = []
    
    for i in structure_definition.category_filters:
        try:
            if i.startswith("@"):
                validated.append(models.StructureCategory.objects.get_or_create(
                    graph=graph,age_name=manager.build_structure_age_name(i),
                    defaults=dict(
                        description="",
                        purl="",
                        store=None,
                        identifier=i,
                    ),
                )[0].id)
            else:   
                validated.append(models.StructureCategory.objects.get(
                    id=i,
                ).id)
        except models.StructureCategory.DoesNotExist:
            raise ValueError(f"StructureCategory with id {i} does not exist. This is an invalid structure definition.")
        
    
    thedicted = strawberry.asdict(structure_definition)
    thedicted["category_filters"] = validated
    
    return thedicted    


def validate_entity_definition(
    entity_definition: inputs.CategoryDefinitionInput, graph: models.Graph,
) -> None:
    
    
    validated = []
    
    for i in entity_definition.category_filters:
        try:
            validated.append(models.EntityCategory.objects.get(
                id=i,
            ).id)
        except models.EntityCategory.DoesNotExist:
            raise ValueError(f"EntityCategory with id {i} does not exist. This is an invalid entitiy definition.")
        
    
    thedicted = strawberry.asdict(entity_definition)
    thedicted["category_filters"] = validated
    
    return thedicted