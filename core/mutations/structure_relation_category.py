from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, manager, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings


@strawberry.input(description="Input for creating a new expression")
class StructureRelationCategoryInput(inputs.CategoryInput):
    label: str = strawberry.field(description="The label/name of the expression")
    source_definition: inputs.StructureCategoryDefinitionInput = strawberry.field(
        default=None,
        description="The source definition for this expression",
    )
    target_definition: inputs.StructureCategoryDefinitionInput = strawberry.field(
        default=None,
        description="The target definition for this expression",
    )
    


@strawberry.input(description="Input for updating an existing expression")
class UpdateStructureRelationCategoryInput(inputs.UpdateCategoryInput):
    label: str | None = strawberry.field(
        default=None, description="New label for the expression"
    )


@strawberry.input(description="Input for deleting an expression")
class DeleteStructureRelationCategoryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to delete"
    )



def validate_structure_category_definition(
    definition: inputs.StructureCategoryDefinitionInput, graph: models.Graph) -> None:
    
    if definition.category_filters:
        categories = models.StructureCategory.objects.filter(
            id__in=definition.category_filters,
        )
        if not categories.exists():
            raise ValueError(
                "Category filters must be valid category IDs"
            )
        assert len(categories) == len(definition.category_filters), (
            "Category filters must be valid category IDs"
        )
        
    if definition.identifier_filters:
        identifiers = models.StructureCategory.objects.filter(
            identifier__in=definition.identifier_filters, graph=models.Graph.objects.get(id=graph.id)
        )
        if not identifiers.exists():
            raise ValueError(
                "Identifier filters must be valid identifier IDs"
            )
        assert len(identifiers) == len(definition.identifier_filters), (
            "Identifier filters must be valid identifier IDs"
        )
        
    if definition.tag_filters:
        tags = models.CategoryTag.objects.filter(
            value__in=definition.tag_filters,
        )
        if not tags.exists():
            raise ValueError(
                "Tag filters must be valid tag values"
            )
        assert len(tags) == len(definition.tag_filters), (
            "Tag filters must be valid tag values"
        )
        
    return strawberry.asdict(definition)
    
    

def create_structure_relation_category(
    info: Info,
    input: StructureRelationCategoryInput,
) -> types.StructureRelationCategory:

    graph = models.Graph.objects.get(
        id=input.graph,
    )
    if input.color:
        assert (
            len(input.color) == 3 or len(input.color) == 4
        ), "Color must be a list of 3 or 4 values RGBA"

    if input.image:
        media_store = models.MediaStore.objects.get(
            id=input.image,
        )
    else:
        media_store = None
        
        
        
        
        

    vocab, created = models.StructureRelationCategory.objects.update_or_create(
        graph=graph,
        age_name=manager.build_relation_age_name(input.label),
        defaults=dict(
            description=input.description,
            purl=input.purl,
            store=media_store,
            label=input.label,
            source_definition=validate_structure_category_definition(input.source_definition, graph),
            target_definition=validate_structure_category_definition(input.target_definition, graph),
        ),
    )

    age.create_age_relation_kind(
        vocab,
    )
    manager.set_age_sequence(
        vocab,
        input.sequence,
        auto_create=input.auto_create_sequence,
    )

    if input.tags:
        vocab.tags.clear()
        for tag in input.tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag)
            vocab.tags.add(tag_obj)

    return vocab

def update_structure_relation_category(
    info: Info, input: UpdateStructureRelationCategoryInput
) -> types.StructureRelationCategory:
    item = models.StructureRelationCategory.objects.get(id=input.id)

    if input.color:
        assert (
            len(input.color) == 3 or len(input.color) == 4
        ), "Color must be a list of 3 or 4 values RGBA"

    if input.image:
        media_store = models.MediaStore.objects.get(
            id=input.image,
        )
    else:
        media_store = None

    item.label = input.label if input.label else item.label
    item.description = input.description if input.description else item.description
    item.purl = input.purl if input.purl else item.purl
    item.color = input.color if input.color else item.color
    item.store = media_store if media_store else item.store

    item.save()
    return item


def delete_structure_relation_category(
    info: Info,
    input: DeleteStructureRelationCategoryInput,
) -> strawberry.ID:
    item = models.StructureRelationCategory.objects.get(id=input.id)
    item.delete()
    return input.id
