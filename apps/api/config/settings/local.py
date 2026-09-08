"""Local development settings, with an optional repository-root .env."""

from pathlib import Path

import environ

env_file = Path(__file__).resolve().parents[4] / ".env"
if env_file.is_file():
    environ.Env.read_env(env_file, overwrite=False)

from .base import *  # noqa: E402, F403

DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]"]
)
