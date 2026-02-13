from kante.types import Info
from datalayer import types, models, inputs
from datalayer.datalayer import get_current_datalayer
from django.conf import settings


def upload_media(info: Info, input: inputs.RequestMediaUploadInput) -> types.PresignedPostCredentials:
    """Request upload credentials for a given key"""

    datalayer = get_current_datalayer()
    model = input.to_pydantic()

    response = datalayer.s3v4.generate_presigned_post(
        Bucket=settings.MEDIA_BUCKET,
        Key=model.key,
        Fields=None,
        Conditions=None,
        ExpiresIn=50000,
    )

    print(response)

    path = f"s3://{settings.MEDIA_BUCKET}/{model.key}"

    store, _ = models.MediaStore.objects.get_or_create(path=path, key=model.key, bucket=settings.MEDIA_BUCKET)

    aws = {
        "key": response["fields"]["key"],
        "x_amz_algorithm": response["fields"]["x-amz-algorithm"],
        "x_amz_credential": response["fields"]["x-amz-credential"],
        "x_amz_date": response["fields"]["x-amz-date"],
        "x_amz_signature": response["fields"]["x-amz-signature"],
        "policy": response["fields"]["policy"],
        "bucket": settings.MEDIA_BUCKET,
        "datalayer": model.datalayer,
        "store": store.pk,
    }

    return types.PresignedPostCredentials(**aws)
