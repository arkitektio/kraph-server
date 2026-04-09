from kante.types import Info
from typing import cast
from datalayer import types, inputs
from datalayer.datalayer import get_current_datalayer
from datalayer import models

def request_media_upload(
    info: Info, input: inputs.RequestMediaUploadInput
) -> types.MediaUploadGrant:
    """Request temporary S3 upload credentials for a media file."""
    del info
    dl = get_current_datalayer()
    input_model = getattr(input, "to_pydantic")()
    return types.MediaUploadGrant(**dl.generate_media_upload_grant(input_model).model_dump())
    

def finish_media_upload(
    info: Info, input: inputs.FinishMediaUploadInput
) -> types.MediaStore:
    """Mark the MediaStore as populated after a successful upload."""
    del info
    dl = get_current_datalayer()
    input_model = getattr(input, "to_pydantic")()
    return cast(
        types.MediaStore, dl.finish_media_upload(input_model)
    )


def request_media_access(
    info: Info, input: inputs.RequestMediaAccessInput
) -> types.MediaAccessGrant:
    """Request temporary S3 read credentials for a media file."""
    del info
    dl = get_current_datalayer()
    model = input.to_pydantic()
    
    store = models.MediaStore.objects.get(id=model.store_id)
    return types.MediaAccessGrant.from_pydantic(dl.generate_media_access_grant(store))