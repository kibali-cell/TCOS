"""Local development settings. Never use in production."""

from .base import *  # noqa: F403
from .base import env

DEBUG = True

# A fixed key is acceptable for local development only. Production requires a
# real secret from the environment (see prod.py).
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-insecure-key-never-use-in-production")

ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]", "backend", "testserver"]
)
