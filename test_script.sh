#!/bin/bash
cd apps/api
DJANGO_SECRET_KEY=dummy POSTGRES_DB=dummy POSTGRES_USER=dummy POSTGRES_PASSWORD=dummy uv run pytest
