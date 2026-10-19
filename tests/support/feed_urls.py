"""kraph's urls, and in-process stand-in for mikro's feed at ``/_feed`` (bodies from `feeds.BODIES`)."""

from arkitekt_service.feed.publisher import FeedPublisher

from kraph_server.urls import urlpatterns as kraph_urlpatterns
from tests.support import feeds

publisher = FeedPublisher("live.arkitekt.mikro")
publisher.feed("@mikro/metric", readers=["live.arkitekt.kraph"], render=lambda entries: {e.object: feeds.BODIES[e.object] for e in entries if e.object in feeds.BODIES})

urlpatterns = [*kraph_urlpatterns, *publisher.urls]
