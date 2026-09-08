# B2B Commodity Procurement & Trade Platform

A Bitumen-focused procurement and trade platform designed for future commodity extensibility. The approved architecture uses a Django 6/DRF modular monolith, PostgreSQL, and a Next.js/TypeScript frontend with a Persian RTL demo.

## Current state

T0101 establishes the monorepo layout and baseline files. Application setup, database setup, Docker services, and CI are scheduled in later tasks. There is no application to run, build, or test yet.

## Repository structure

```text
apps/
  api/                 Django API location (T0102)
  web/                 Next.js frontend location (T0103)
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

Prerequisites for this task are Git, repository access, and a text editor. Application runtime and service setup are deferred to their respective tasks.

```text
git clone https://github.com/Puriatc10/digital-commodity-infrastracture.git
cd digital-commodity-infrastracture
```

From the repository root, optionally create an ignored local environment file. The template currently contains comments only; no application consumes environment variables yet. Preserve an existing `.env` when repeating setup.

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

Keep credentials in ignored local configuration. Add documented environment keys to `.env.example` when the relevant setup task defines them, using placeholders rather than secrets.

## Root commands

Run these from the repository root:

| Command | Purpose |
| --- | --- |
| `git status --short` | Review tracked changes and new files. |
| `git diff` | Review changes to tracked files; inspect new files separately. |
| `git diff --check` | Check tracked changes for whitespace errors. |
| `git ls-files` | List files already tracked by Git. |

Application start/build/test commands will be documented when implemented. T0102 covers Django, T0103 covers Next.js, T0104 covers local Docker services, and T0106 covers CI. T0101 does not install dependencies or add runtime commands.

## Project context

Read [AGENTS.md](AGENTS.md) and the assigned GitHub issue before making changes. Use the [Product Specification](docs/product/product-spec.md) for scope, the [Delivery Roadmap](docs/delivery/roadmap.md) for tasks and acceptance criteria, and the [Architecture Overview](docs/architecture/overview.md) for relevant design constraints. Domain terminology is in the [glossary](docs/domain/glossary.md); decisions are indexed in [ADRs](docs/adr/README.md).
