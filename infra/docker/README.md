# Local Infrastructure

This directory provides the local infrastructure required for the B2B Commodity Procurement & Trade Platform.

## Services

* **PostgreSQL 17:** The primary application database.
* **MinIO:** S3-compatible object storage for future document management.

## Setup

Ensure Docker and Docker Compose v2 are installed. Create the repository-root `.env` from `.env.example` and choose local credentials as described in the [root setup guide](../../README.md). All commands below run from the repository root and explicitly use that file, so Django and Compose share database configuration.

Start the infrastructure:

```sh
docker compose --env-file .env -f infra/docker/docker-compose.yml up -d --wait
```

This will run the services in the background and use persistent named volumes (`postgres_data` and `minio_data`) so your data is retained across restarts.

Ports bind to `127.0.0.1` only: PostgreSQL uses `POSTGRES_PORT` (default 5432), MinIO API uses 9000, and the console uses 9001. PostgreSQL's volume mounts at `/var/lib/postgresql/data`; MinIO's at `/data`. Healthchecks use `pg_isready` and MinIO's `/minio/health/live`. No bucket is automatically created and no application storage integration is included.

If running from this directory, use `docker compose --env-file ../../.env up -d --wait`. Plain `docker compose up` here does not load the repository-root environment. Changing PostgreSQL database/user/password variables after a volume is initialized does not modify its existing database credentials; preserve the matching values or deliberately migrate the database configuration.

## Inspection & Health

To check the status and health of the services:

```sh
docker compose --env-file .env -f infra/docker/docker-compose.yml ps
```

To view the logs:

```sh
docker compose --env-file .env -f infra/docker/docker-compose.yml logs -f
```

### Accessing MinIO

The MinIO Console is accessible locally at `http://localhost:9001`. Log in using the `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` configured in your `.env` file (defaults are `minioadmin` / `minioadmin`).

## Stopping

To stop the services without destroying the data:

```sh
docker compose --env-file .env -f infra/docker/docker-compose.yml stop
```

To stop and remove the containers, but keep the data:

```sh
docker compose --env-file .env -f infra/docker/docker-compose.yml down
```

*(Note: To destroy the persistent data, you can use `docker compose down -v`, but use this with caution!)*
