"""The service's `config.yaml` validates against its own schema.

Standalone — needs no database; run with ``uv run pytest tests/guards/test_config_validates.py``.
"""

from kraph_server.configuration import Settings


def test_config_yaml_validates():
    """The service's own config.yaml parses into the typed schema."""
    s = Settings()
    assert s.postgres.db_name
    assert s.redis.host


def test_env_override(monkeypatch):
    """Env vars override the YAML file (nested via ``__``)."""
    monkeypatch.setenv("POSTGRES__PASSWORD", "from-env-test")
    assert Settings().postgres.password == "from-env-test"


def test_django_settings_read_the_config():
    """`DEBUG`, `ALLOWED_HOSTS` and the proxy trust come from the config, not from literals.

    History: `DEBUG = True` and `ALLOWED_HOSTS = ["*"]` were hardcoded while
    `django.debug` / `django.hosts` / `django.use_x_forwarded_host` were parsed and
    read by nothing — production served full tracebacks.
    """
    from django.conf import settings

    parsed = Settings()
    # pytest-django forces DEBUG=False and appends "testserver" to the hosts under the runner.
    assert set(parsed.django.hosts) <= set(settings.ALLOWED_HOSTS)
    assert settings.USE_X_FORWARDED_HOST == parsed.django.use_x_forwarded_host
    if parsed.django.use_x_forwarded_host:
        assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    else:
        assert settings.SECURE_PROXY_SSL_HEADER is None
    assert settings.PROJECTION_LAG_THRESHOLD == parsed.projection.lag_threshold
