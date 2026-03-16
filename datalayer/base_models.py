from typing import Optional
from pydantic import BaseModel


class RequestMediaUploadInput(BaseModel):
    """Request a signed SeaweedFS upload grant for a media object."""

    key: str
    datalayer: str
    file_size: Optional[int] = None
    content_type: Optional[str] = None
