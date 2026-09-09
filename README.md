# B2B Commodity Procurement & Trade Platform

A Bitumen-focused procurement and trade platform designed for future commodity extensibility. The approved architecture uses a Django 6/DRF modular monolith, PostgreSQL, and a Next.js/TypeScript frontend with a Persian RTL demo.

## Current state

Epic 1 (T0101–T0106) provides the monorepo, Django API and public health endpoint, Persian RTL Next.js shell at `/fa`, PostgreSQL 17/MinIO Docker services, generated OpenAPI types and typed client, and GitHub Actions checks. Business modules and authentication remain outside this foundation.

## Repository structure

```text
apps/
  api/                 Django API foundation (T0102)
  web/                 Next.js frontend foundation (T0103)
docs/
  product/             Authoritative Product Specification
  delivery/            Authoritative Delivery Roadmap
  domain/              Domain glossary
  architecture/        Architecture overview and source review
  adr/                 Architecture decision records
infra/
  docker/              Local infrastructure location (T0104)
scripts/               Location for future repository scripts
AGENTS.md              Repository guidance for scoped tasks
README.md              Local setup and repository map
.editorconfig          Shared editor formatting defaults
.env.example           Environment template without secrets
.gitignore             Local/generated artifact exclusions
```

Empty implementation directories contain `.gitkeep` files so Git retains the layout. The existing documentation remains the source of truth.

## Local setup

Prerequisites are Git, Docker with Compose v2, Python 3.12+ supported by Django 6, and Node.js 22.13+ (Node 24 LTS recommended) with npm. See the [backend setup guide](apps/api/README.md) for installation, configuration, migrations, server, and test commands.

Frontend development requires Node.js 22.13+ (Node 24 LTS recommended) and npm. See the [frontend setup guide](apps/web/README.md). The frontend shell runs independently; it needs no database, backend server, or environment variables.

```text
git clone https://github.com/Puriatc10/digital-commodity-infrastracture.git
cd digital-commodity-infrastracture
```

From the repository root, create an ignored local environment file for Django. Preserve an existing `.env` when repeating setup, and replace template placeholders with local values before running the backend.

PowerShell:

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
```

POSIX shell:

```sh
if [ ! -e .env ]; then
    cp .env.example .env
fi
```

Keep credentials in ignored local configuration. Django local settings load the root `.env` without overriding process environment variables; production settings use process environment only. `.env.example` documents Django, PostgreSQL, and local MinIO values. Start infrastructure from the repository root using the same file:

```sh
docker compose --env-file .env -f infra/docker/docker-compose.yml up -d --wait
docker compose --env-file .env -f infra/docker/docker-compose.yml ps
```

PostgreSQL and MinIO bind to loopback, with persistent named volumes. PostgreSQL uses `POSTGRES_PORT` (default 5432); MinIO uses ports 9000 and 9001. Follow the backend guide to install dependencies, check/migrate, and run the API, and the frontend guide to install dependencies and run `/fa`. These setup steps require local environment configuration but no source edits.

## Root commands

Run these from the repository root:

| Command | Purpose |
| --- | --- |
| `git status --short` | Review tracked changes and new files. |
| `git diff` | Review changes to tracked files; inspect new files separately. |
| `git diff --check` | Check tracked changes for whitespace errors. |
| `git ls-files` | List files already tracked by Git. |

Frontend commands from the repository root:

```sh
npm --prefix apps/web ci
npm --prefix apps/web run dev
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
npm --prefix apps/web run start
```

Open `http://localhost:3000/fa`. Run `start` after a successful production build, with the development server stopped. Backend commands are documented in [apps/api/README.md](apps/api/README.md) and run from `apps/api`. Local Docker services are documented in [infra/docker/README.md](infra/docker/README.md).

With the backend virtual environment active and its dependencies installed, regenerate the API contract from the repository root:

```sh
npm --prefix apps/web run api:generate
git diff --exit-code -- apps/web/src/lib/api/generated/schema.d.ts
```

This validates the Django schema and generates TypeScript without a running API server. CI runs backend Ruff/checks/migration consistency/migrations/tests against PostgreSQL, frontend deterministic install/lint/typecheck/build, and this contract drift check on pull requests and pushes to `master` or Epic 1 branches.

## Project context

Read [AGENTS.md](AGENTS.md) and the assigned GitHub issue before making changes. Use the [Product Specification](docs/product/product-spec.md) for scope, the [Delivery Roadmap](docs/delivery/roadmap.md) for tasks and acceptance criteria, and the [Architecture Overview](docs/architecture/overview.md) for relevant design constraints. Domain terminology is in the [glossary](docs/domain/glossary.md); decisions are indexed in [ADRs](docs/adr/README.md).
