from kante.channel import build_channel
from retrieved import RetrievedEntity


entity_broadcast, entity_listen = build_channel(RetrievedEntity, "entity")
