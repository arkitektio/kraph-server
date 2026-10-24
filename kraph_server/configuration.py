"""Typed, fully-documented configuration schema for the **kraph** service.

Owned by this service. Values resolve (highest precedence first) from init
kwargs, environment variables (nested via ``__`` — e.g. ``POSTGRES__PASSWORD``),
then the YAML file (``config.yaml`` where the service runs by default; override with
``ARKITEKT_CONFIG_FILE``). Secret fields have **no default**: loading fails fast
with a ``ValidationError`` if they are not supplied via config or environment.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from arkitekt_datalayer.configuration import DatalayerBucket, DatalayerSettings

from arkitekt_service.server import settings as shared
from arkitekt_service.server.settings import DjangoSettings, InstanceSettings, PostgresSettings, ServiceSettings
from authentikate.base_models import AuthentikateSettings

class RedisSettings(shared.RedisSettings):
    """Redis connection (channel layer / cache)."""

    channel_prefix: str = Field(default="kraph", description="Key prefix for the channels_redis channel layer. Must be unique per service: every service on a shared redis used to send under the same prefix, so identically-named groups (e.g. \"files\") delivered one service's events to another's subscribers.")


class KraphDatalayerSettings(DatalayerSettings):
    """The datalayer block: kraph stores images of graphs, categories and terms as media."""

    session_name: str = Field(default="kraph", description="Prefix of every STS session kraph assumes, so an object store's audit log names it.")
    media: DatalayerBucket = Field(description="Bucket for media / general file storage. Required for this service.")


class ProjectionSettings(BaseModel):
    """How the projection's health is judged."""

    lag_threshold: int = Field(
        default=1000,
        ge=0,
        description="The `/ht` health check warns when a consistent view is more than this many assertions behind its organization's log.",
    )


class RekuestHookSettings(BaseModel):
    """How this process reaches the hub's rekuest as a hook agent (``kraph_server.hook_agent``)."""

    rekuest_url: str = Field(default="http://rekuest:80/rekuest", description="Where runs are reported: rekuest's agents' endpoint on the internal network (`agi/http/<agent>`).")
    agent: str = Field(default="kraph", description="The name rekuest knows the agent by: its `rekuest.hook_agents[].name`.")
    max_skew: int = Field(default=30, description="Clock skew (seconds) tolerated on a signed request; tokens themselves live 60 s.")


class FeedPeerSettings(BaseModel):
    """Another service's change feed, read with this instance's key."""

    url: str = Field(description="Its `_feed` endpoint on the internal network, with its path.")
    identifier: str = Field(description="Its identifier in the hub's trust bundle: whom the read is addressed to.")


class Settings(ServiceSettings):
    """Top-level, validated configuration for the kraph service."""

    django: DjangoSettings = Field(description="Core Django settings.")
    postgres: PostgresSettings = Field(description="PostgreSQL connection.")
    redis: RedisSettings = Field(description="Redis connection.")
    authentikate: AuthentikateSettings = Field(description="Token-verification config (authentikate).")
    datalayer: KraphDatalayerSettings = Field(description="S3 storage connection and buckets.")
    projection: ProjectionSettings = Field(default_factory=ProjectionSettings, description="Projection health thresholds.")
    rekuest_hook: Optional[RekuestHookSettings] = Field(default=None, description="How this process reaches the hub's rekuest as a hook agent. Without it the agent's endpoints answer 503 and nothing is ingested.")
    instance: Optional[InstanceSettings] = Field(default=None, description="This instance's key and the hub trust bundle: it signs the agent's reports and the reads of mikro's feed.")
    mikro: Optional[FeedPeerSettings] = Field(default=None, description="mikro's change feed of metrics, which `ingest_metrics` reads. Without it the action ingests nothing.")
