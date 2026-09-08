# Django API

T0102 provides Django 6, Django REST Framework, environment-based PostgreSQL settings, and `GET /api/health`. The response is HTTP 200 with `{"status":"ok"}`. This public JSON endpoint reports application liveness without accessing the database.

## Setup

Use Python 3.12 or newer supported by Django 6.0 and a running PostgreSQL 14+ database with an existing database/user. PostgreSQL is the only configured database. Local infrastructure provisioning is T0104; these commands connect to an instance you already provide.

From the repository root, create an ignored `.env` by copying `.env.example` if `.env` does not already exist. Replace the secret-key and database-password placeholders, and set `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, and `POSTGRES_USER` for your instance. To generate a secret after installation, run `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` and put it in `.env` as a single-quoted value.

PowerShell, from the repository root:

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
cd apps/api
py -3.12 -m venv .venv
.venv/Scripts/Activate.ps1
python -m pip install -e .
```

POSIX shell, from the repository root:

```sh
if [ ! -e .env ]; then
    cp .env.example .env
fi
cd apps/api
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

With the virtual environment active, run from `apps/api`:

| Command | Purpose |
| --- | --- |
| `python manage.py check` | Run Django system checks. |
| `python manage.py migrate` | Connect to PostgreSQL and run pending migrations. |
| `python manage.py runserver` | Start the local API at `http://127.0.0.1:8000`. |
| `python manage.py test tests` | Run the health endpoint tests. |
| `python -m pip check` | Check installed dependency compatibility. |

Visit `http://127.0.0.1:8000/api/health` to verify the response. There are no application models or auth/session/admin apps yet, so `migrate` currently reports no migrations to apply. Health tests use Django's `SimpleTestCase`: no database queries or seed data are permitted. Run `migrate` separately to validate actual PostgreSQL connectivity.

## Configuration

`manage.py` defaults to `config.settings.local`. Local settings load the repository-root `.env`; existing process environment variables take precedence. Required values are `DJANGO_SECRET_KEY`, `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`. The host defaults to `127.0.0.1` and port to `5432`.

`DJANGO_DEBUG` is a boolean (`true`/`false`); it defaults to true locally and false in production. `DJANGO_ALLOWED_HOSTS` is a comma-separated list of hostnames without schemes or ports, defaulting to loopback hosts locally.

ASGI/WSGI entry points default to `config.settings.production`, which reads only the process environment. Set `DJANGO_SETTINGS_MODULE=config.settings.production` when running management commands for production. Production rejects debug mode and missing/wildcard allowed hosts, and redirects HTTP to HTTPS. Configure TLS and trusted proxy handling for the actual deployment before use; no proxy headers are trusted by this foundation. Production server/deployment tooling is outside T0102.

DRF renders/parses JSON. Authentication backends are empty and anonymous users do not load Django auth models. The default permission denies anonymous access; only the health view explicitly allows it. Authentication and business authorization remain future work.

## Structure and dependencies

```text
apps/api/
  manage.py
  pyproject.toml
  README.md
  config/
    __init__.py
    asgi.py
    wsgi.py
    urls.py
    views.py
    settings/
      __init__.py
      base.py
      local.py
      production.py
  tests/
    __init__.py
    test_health.py
```

This uses Django's conventional layout without a `src` path shim. Future domain apps belong directly under `apps/api`, beside `config`; create and register each app only in its authorized task, and extend package discovery in `pyproject.toml` at that point. No placeholder domain apps or shared service/repository layers are needed.

Direct dependencies are pinned in `pyproject.toml`:

| Package | Reason |
| --- | --- |
| Django 6.0.8 | Required framework, settings, server entry points, migrations, and built-in test runner. |
| djangorestframework 3.18.1 | Required REST framework; JSON responses and HTTP method handling. |
| psycopg[binary] 3.3.5 | PostgreSQL adapter with bundled native client, avoiding local compiler/libpq setup. |
| django-environ 0.14.0 | Typed environment values and local `.env` loading without a custom parser. |

Setuptools is the build backend for standard `pip install -e .`; no separate test runner, schema generator, or production server dependency is introduced. Transitive dependencies are resolved by pip; there is no complete dependency lock yet.
