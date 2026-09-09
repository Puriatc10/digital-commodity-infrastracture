# Local Infrastructure

This directory provides the local infrastructure required for the B2B Commodity Procurement & Trade Platform.

## Services

* **PostgreSQL:** The primary application database.
* **MinIO:** S3-compatible object storage for future document management.

## Setup

Ensure Docker and Docker Compose are installed.

Start the infrastructure:

```sh
docker compose up -d
```

This will run the services in the background and use persistent named volumes (`postgres_data` and `minio_data`) so your data is retained across restarts.

## Inspection & Health

To check the status and health of the services:

```sh
docker compose ps
```

To view the logs:

```sh
docker compose logs -f
```

### Accessing MinIO

The MinIO Console is accessible locally at `http://localhost:9001`. Log in using the `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` configured in your `.env` file (defaults are `minioadmin` / `minioadmin`).

## Stopping

To stop the services without destroying the data:

```sh
docker compose stop
```

To stop and remove the containers, but keep the data:

```sh
docker compose down
```

*(Note: To destroy the persistent data, you can use `docker compose down -v`, but use this with caution!)*
