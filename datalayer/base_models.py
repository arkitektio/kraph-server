from typing import Optional
from pydantic import BaseModel


class RequestMediaUploadInput(BaseModel):
    """Requests a pre-signed S3 URL for uploading media files. The client can then use this URL to upload the file directly to S3, and the server can later access it for processing. This is used for uploading files that will be used as properties in graph"""

    key: str
    datalayer: str
    file_size: Optional[int] = None
    content_type: Optional[str] = None
