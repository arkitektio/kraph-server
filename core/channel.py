from kante.channel import build_channel
from pydantic import BaseModel


class EntityCategoryAction(BaseModel):
    category: str
    action: str


entity_category_broadcast, entity_listen = build_channel(EntityCategoryAction, "entity")
