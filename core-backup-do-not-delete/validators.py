from core import models, inputs, manager
import strawberry 

def validate_structure_definition(
    structure_definition: inputs.CategoryDefinitionInput, graph: models.Graph
) -> None:
    
    
    if structure_definition.category_filters:
        categories = models.StructureCategory.objects.filter(
            id__in=structure_definition.category_filters,
        )
        if not categories.exists():
            raise ValueError("Category filters must be valid category IDs")
        assert len(categories) == len(structure_definition.category_filters), "Category filters must be valid category IDs"

    if structure_definition.identifier_filters:
        for identifier in structure_definition.identifier_filters:
            if not isinstance(identifier, str):
                raise ValueError("Identifier filters must be a list of identifier IDs")

            models.StructureCategory.objects.get_or_create(
                graph=graph,
                age_name=manager.build_structure_age_name(identifier),
                defaults=dict(
                    identifier=identifier,
                    description=f"Identifier filter for {identifier}",
                    purl=None,
                    store=None,
                ),
            )[0]

    if structure_definition.tag_filters:
        tags = models.CategoryTag.objects.filter(
            value__in=structure_definition.tag_filters,
        )
        if not tags.exists():
            raise ValueError("Tag filters must be valid tag values")
        assert len(tags) == len(structure_definition.tag_filters), "Tag filters must be valid tag values"

    return strawberry.asdict(structure_definition)


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
        
    
    
    return strawberry.asdict(entity_definition)
