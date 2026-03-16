from kante.types import Info
from datalayer import types, models, inputs
from datalayer.datalayer import get_current_datalayer


def request_media_upload(info: Info, input: inputs.RequestMediaUploadInput) -> types.MediaUploadGrant:
    """Request a signed SeaweedFS upload grant for a given key."""

    datalayer = get_current_datalayer()
    model = input.to_pydantic()
    grant = datalayer.generate_file_upload_url(model.datalayer, model.key, max_bytes=model.file_size)
    path = datalayer.build_store_path(model.datalayer, model.key)

    store, _ = models.MediaStore.objects.get_or_create(
        path=path,
        defaults={"key": model.key, "bucket": model.datalayer},
    )

    if store.key != model.key or store.bucket != model.datalayer:
        store.key = model.key
        store.bucket = model.datalayer
        store.path = path
        store.save(update_fields=["key", "bucket", "path"])

    return types.MediaUploadGrant(
        **grant.model_dump(),
        datalayer=model.datalayer,
        key=model.key,
        store=store.pk,
    )
