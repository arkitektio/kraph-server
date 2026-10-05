"""Typed, fully-documented configuration schema for the **kraph** service.

Owned by this service. Values resolve (highest precedence first) from init
kwargs, environment variables (nested via ``__`` — e.g. ``POSTGRES__PASSWORD``),
then the YAML file (the mount's ``config.yaml`` by default; override with
``ARKITEKT_CONFIG_FILE``). Secret fields have **no default**: loading fails fast
with a ``ValidationError`` if they are not supplied via config or environment.
"""

import dataclasses
import os
import typing
from collections.abc import Mapping
from typing import List, Optional

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from authentikate.base_models import AuthentikateSettings

_DEFAULT_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml"
)


class AdminSettings(BaseModel):
    """Django superuser created on first boot."""

    username: str = Field(description="Superuser login name.")
    password: str = Field(description="Superuser password. Secret — must be set.")
    email: Optional[str] = Field(default=None, description="Superuser email address.")


class DjangoSettings(BaseModel):
    """Core Django framework settings."""

    secret_key: str = Field(description="Django SECRET_KEY for cryptographic signing. Secret — must be set.")
    debug: bool = Field(default=False, description="Enable Django debug mode (never in production).")
    log_level: str = Field(default="INFO", description="Root logger level (e.g. DEBUG, INFO, WARNING). The LOG_LEVEL env var overrides it.")
    enable_rich_logging: bool = Field(default=False, description="Render console logs with rich (colours, boxed tracebacks). A dev convenience; off by default, as plain one-line records suit container logs.")
    hosts: List[str] = Field(default_factory=lambda: ["*"], description="ALLOWED_HOSTS entries.")
    use_x_forwarded_host: bool = Field(default=True, description="Trust the X-Forwarded-Host header behind a reverse proxy.")
    admin: Optional[AdminSettings] = Field(default=None, description="Superuser provisioned on first boot.")
    csrf_trusted_origins: List[str] = Field(default_factory=lambda: ["http://localhost", "https://localhost"], description="CSRF_TRUSTED_ORIGINS for unsafe (POST) requests.")
    force_script_name: str = Field(default="", description="URL path prefix (FORCE_SCRIPT_NAME) this service is served under.")


class PostgresSettings(BaseModel):
    """PostgreSQL database connection (Django ``DATABASES['default']``)."""

    model_config = ConfigDict(extra="allow")

    engine: str = Field(default="django.db.backends.postgresql", description="Django database backend (PostgreSQL).")
    db_name: str = Field(description="Database name.")
    username: str = Field(description="Database user.")
    password: str = Field(description="Database password. Secret — must be set.")
    host: str = Field(description="Database host.")
    port: int = Field(default=5432, description="Database port.")


class RedisSettings(BaseModel):
    """Redis connection (channel layer / cache)."""

    model_config = ConfigDict(extra="allow")

    host: str = Field(description="Redis host.")
    port: int = Field(default=6379, description="Redis port.")
    channel_prefix: str = Field(default="kraph", description="Key prefix for the channels_redis channel layer. Must be unique per service: every service on a shared redis used to send under the same prefix, so identically-named groups (e.g. \"files\") delivered one service's events to another's subscribers.")


class DatalayerBucket(BaseModel):
    """A single S3 bucket binding within the datalayer."""

    model_config = ConfigDict(extra="allow")

    bucket: str = Field(description="S3 bucket name.")


class DatalayerSettings(BaseModel):
    """S3 storage connection and buckets (the datalayer module; replaces the old top-level ``s3`` block)."""

    model_config = ConfigDict(extra="allow")

    access_key: str = Field(description="S3 access key. Secret — must be set.")
    secret_key: str = Field(description="S3 secret key. Secret — must be set.")
    host: Optional[str] = Field(default=None, description="S3 endpoint host.")
    port: Optional[int] = Field(default=None, description="S3 endpoint port.")
    protocol: str = Field(default="http", description="S3 endpoint protocol (http or https).")
    region: str = Field(default="us-east-1", description="S3 region name.")
    media: DatalayerBucket = Field(description="Bucket for media / general file storage. Required for this service.")
    zarr: Optional[DatalayerBucket] = Field(default=None, description="Bucket for Zarr arrays.")
    parquet: Optional[DatalayerBucket] = Field(default=None, description="Bucket for Parquet tables.")
    bigfile: Optional[DatalayerBucket] = Field(default=None, description="Bucket for large binary files.")


class ProjectionSettings(BaseModel):
    """How the projection's health is judged."""

    lag_threshold: int = Field(
        default=1000,
        ge=0,
        description="The `/ht` health check warns when a consistent view is more than this many assertions behind its organization's log.",
    )


class Settings(BaseSettings):
    """Top-level, validated configuration for the kraph service."""

    model_config = SettingsConfigDict(env_nested_delimiter="__", extra="ignore")

    django: DjangoSettings = Field(description="Core Django settings.")
    postgres: PostgresSettings = Field(description="PostgreSQL connection.")
    redis: RedisSettings = Field(description="Redis connection.")
    authentikate: AuthentikateSettings = Field(description="Token-verification config (authentikate).")
    datalayer: DatalayerSettings = Field(description="S3 storage connection and buckets.")
    projection: ProjectionSettings = Field(default_factory=ProjectionSettings, description="Projection health thresholds.")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Precedence: explicit init kwargs > environment variables > YAML file.
        path = os.environ.get("ARKITEKT_CONFIG_FILE", _DEFAULT_CONFIG)
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=path),
            file_secret_settings,
        )


@dataclasses.dataclass(frozen=True)
class Unread:
    """What a config file says that this release does not read as written."""

    unknown: list[str]
    """Keys no setting claims, as dotted paths: a misspelling, or a key of another release."""
    renamed: list[tuple[str, str]]
    """Keys still read under a former name, with the name they have now."""

    def __bool__(self) -> bool:
        """Whether there is anything to say."""
        return bool(self.unknown or self.renamed)


def config_path() -> str:
    """The YAML file the settings are read from."""
    return os.environ.get("ARKITEKT_CONFIG_FILE", _DEFAULT_CONFIG)


def _models_of(annotation: object) -> list[type[BaseModel]]:
    """This module's settings models an annotation holds: itself, or inside ``Optional[...]`` / ``list[...]``.

    Only this module's: a block another package defines (``authentikate``) is that package's to
    judge, and its aliases are spellings, not former names.
    """
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation] if annotation.__module__ == __name__ else []
    return [model for inner in typing.get_args(annotation) for model in _models_of(inner)]


def _names(model: type[BaseModel]) -> dict[str, str]:
    """Every key ``model`` reads, to the field's own name: its fields and their former names."""
    names: dict[str, str] = {}
    for name, field in model.model_fields.items():
        names[name] = name
        alias = field.validation_alias
        for former in alias.choices if isinstance(alias, AliasChoices) else [alias]:
            if isinstance(former, str):
                names[former] = name
    return names


def _unread(model: type[BaseModel], written: Mapping[str, object], path: str, into: Unread) -> None:
    # A block that passes its extras on (a connection's driver options) and the top level,
    # which every service of a hub shares the shape of, are open: nothing there is unknown.
    closed = model.model_config.get("extra") != "allow" and not issubclass(model, BaseSettings)
    names = _names(model)
    for key, value in written.items():
        where = f"{path}{key}"
        name = names.get(key)
        if name is None:
            if closed:
                into.unknown.append(where)
            continue
        if name != key:
            into.renamed.append((where, f"{path}{name}"))
        for inner in _models_of(model.model_fields[name].annotation):
            for index, item in enumerate(value) if isinstance(value, list) else [(None, value)]:
                if isinstance(item, dict):
                    _unread(inner, item, f"{where}." if index is None else f"{where}[{index}].", into)


def unread(written: Mapping[str, object] | None = None) -> Unread:
    """What the config file (or ``written``) says that this release does not read as written.

    A setting nobody reads is silent by nature: the service starts, with the default. This is
    what makes it loud — a system check at boot, and ``validate_settings --strict``, which an
    installer runs against a release before it moves a hub to it.
    """
    if written is None:
        try:
            with open(config_path(), encoding="utf-8") as file:
                loaded: object = yaml.safe_load(file)
        except OSError:
            loaded = None
        written = loaded if isinstance(loaded, dict) else {}
    found = Unread(unknown=[], renamed=[])
    _unread(Settings, written, "", found)
    return found
