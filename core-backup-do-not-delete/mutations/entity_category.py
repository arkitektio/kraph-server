from kante.types import Info

import strawberry
from core import types, models, enums, manager, inputs
from core import age



def entity_category_creator(
    info: Info,
    graph_id: str,
    label: str,
    description: str | None = None,
    purl: str | None = None,
    color: list[int] | None = None,
    image_id: str | None = None,
    property_definitions: list | None = None,
    descriptors: list[inputs.DescriptorInput] | None = None,
    tags: list[str] | None = None,
    pin: bool | None = None,
    sequence: str | None = None,
    auto_create_sequence: bool = False,
    position_x: float | None = None,
    position_y: float | None = None,
    height: float | None = None,
    width: float | None = None,
) -> types.EntityCategory:
    """Core creator function for entity categories."""
    if color:
        assert len(color) == 3 or len(color) == 4, "Color must be a list of 3 or 4 values RGBA"

    media_store = None
    if image_id:
        media_store = models.MediaStore.objects.get(id=image_id)

    vocab, created = models.EntityCategory.objects.update_or_create(
        graph_id=graph_id,
        age_name=manager.build_entity_age_name(label),
        defaults=dict(
            description=description,
            purl=purl,
            store=media_store,
            label=label,
            instance_kind=enums.InstanceKind.ENTITY,
            property_definitions=property_definitions or [],
        ),
    )

    if descriptors:
        vocab.descriptors.clear()
        for descriptor in descriptors:
            descriptor_obj, _ = models.Descriptor.objects.get_or_create(key=descriptor.key, defaults={"description": descriptor.description})
            vocab.descriptors.add(descriptor_obj)

    if position_x is not None:
        vocab.position_x = position_x
    if position_y is not None:
        vocab.position_y = position_y
    if height is not None:
        vocab.height = height
    if width is not None:
        vocab.width = width
    if any([position_x is not None, position_y is not None, height is not None, width is not None]):
        vocab.save()

    age.create_age_entity_kind(vocab)
    manager.set_age_sequence(vocab, sequence, auto_create=auto_create_sequence)

    if tags:
        vocab.tags.clear()
        for tag in tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag, graph_id=graph_id)
            vocab.tags.add(tag_obj)

    if pin is not None:
        if pin:
            vocab.pinned_by.add(info.context.request.user)
        else:
            vocab.pinned_by.remove(info.context.request.user)

    return vocab


def create_entity_category(
    info: Info,
    input: inputs.EntityCategoryInput,
) -> types.EntityCategory:
    """GraphQL mutation wrapper for creating entity categories."""
    return entity_category_creator(
        info=info,
        graph_id=input.graph,
        label=input.label,
        description=input.description,
        purl=input.purl,
        color=input.color,
        image_id=input.image,
        property_definitions=[strawberry.asdict(x) for x in input.property_definitions] if input.property_definitions else None,
        tags=input.tags,
        pin=input.pin,
        sequence=input.sequence,
        auto_create_sequence=input.auto_create_sequence or False,
        position_x=input.position_x,
        position_y=input.position_y,
        height=input.height,
        width=input.width,
    )


def update_entity_category(info: Info, input: UpdateEntityCategoryInput) -> types.EntityCategory:
    item = models.EntityCategory.objects.get(id=input.id)

    if input.color:
        assert len(input.color) == 3 or len(input.color) == 4, "Color must be a list of 3 or 4 values RGBA"

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

    if input.tags:
        item.tags.clear()
        for tag in input.tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag, graph=item.graph.id)
            item.tags.add(tag_obj)

    if input.pin is not None:
        if input.pin:
            item.pinned_by.add(info.context.request.user)
        else:
            item.pinned_by.remove(info.context.request.user)

    item.save()
    return item


def delete_entity_category(
    info: Info,
    input: DeleteEntityCategoryInput,
) -> strawberry.ID:
    item = models.EntityCategory.objects.get(id=input.id)
    item.delete()
    return input.id
