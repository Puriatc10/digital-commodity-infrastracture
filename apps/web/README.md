# Frontend — Identity and Organization Context

Next.js App Router, TypeScript, Tailwind CSS, and shadcn/ui. The Persian demo is served at `/fa` with RTL direction; `/en` remains inactive. API security is enforced by Django. The selected Organization is only a UI preference.

## Local setup

Use Node.js 22.13+ (Node 24 LTS recommended). From `apps/web`:

```sh
npm ci
```

Copy `.env.example` to `.env.local` if it does not already exist. For an existing Epic 1 setup, replace `NEXT_PUBLIC_API_BASE_URL` with:

```dotenv
API_PROXY_TARGET=http://127.0.0.1:8000
```

Run Django using the [backend guide](../api/README.md), then `npm run dev` and open `http://localhost:3000/fa`. Requests use the browser's own origin; Next.js forwards `/api` to Django. API trailing slashes are preserved to avoid redirect loops. No browser CORS exception is required. The root Django `.env` must contain the exact browser origin in `DJANGO_CSRF_TRUSTED_ORIGINS` (see the root example). Changing the port requires updating that list. Restart development servers after configuration changes; rebuild for `npm run start`.

In production, route `/api` and the frontend under one HTTPS origin using the deployment ingress, or configure the server-only proxy target at build time. Configure the actual allowed hosts/trusted origins and TLS termination for the deployment. Do not copy development origins to production. No frontend secret or authentication token belongs in browser storage.

## Session behavior

`AuthProvider` reads the backend-generated `/api/auth/me` contract. It distinguishes loading, unauthenticated (401/403), authenticated, and transport/server error states. Refresh runs on window focus and every minute; newer requests supersede older responses. The backend checks the session on every protected request.

Zero Organizations is supported, including Operator/Admin. One Organization is selected automatically; multiple Organizations have a selector. Only an Organization UUID is persisted, checked against each fresh authorized response, and cleared when unauthenticated or after switching personas. Unavailable browser storage does not prevent authentication.

The typed client includes cookies and copies the current CSRF cookie into `X-CSRFToken` for unsafe requests. Before password login, call `bootstrapCsrf()` then the generated `/api/auth/login` operation. The demo control bootstraps CSRF itself, switches to a seeded account, clears the Organization preference, and reloads. Enable and seed the demo only using the backend guide. Disabled demo controls are hidden based on the backend endpoint; hiding is not a security boundary.

## Commands

| Command | Purpose |
| --- | --- |
| `npm run dev` | Start local Next.js. |
| `npm run lint` | ESLint, zero warnings. |
| `npm run typecheck` | Generate route types and check TypeScript. |
| `npm test` | Real client request/CSRF and Organization preference regressions, using Node's test runner. |
| `npm run build` | Build production assets. |
| `npm run start` | Serve a completed build. Stop the development server first. |
| `npm run api:generate` | Export/validate Django OpenAPI, then regenerate TypeScript. Requires the backend virtual environment active and Django environment configured. No API server is needed. |

Contracts come from `src/lib/api/generated/schema.d.ts`; do not manually edit them or duplicate DTOs. `schema.yaml` is an ignored intermediate. CI repeats generation and rejects drift. The scoped Redocly `js-yaml` override retains the approved Epic 1 dependency fix.

## Epic 3 specification components

`CommoditySpecificationForm` and `CommoditySpecificationView` consume generated `CommoditySchemaVersion` metadata. Pass the record's explicit historical schema to the View; neither component fetches or infers an active schema. The Form emits flat values with canonical enum strings and units retained in metadata. Decimal input in an integer field is preserved for backend rejection, never truncated. Its optional `errors` property accepts field-keyed messages from the caller. Client constraints are input hints; backend validation remains authoritative.

Labels/options come from the supplied schema. Shared renderer messages and presentation-group translations live in `src/i18n/commodity-messages.ts`; `/en` remains inactive. Both renderers support Persian RTL. The Form passes direction to the select portal and uses unique field IDs per instance.

Run `npm test` for the three session regressions and `npm run test:components` for all specification Form/View and API-fixture integration tests. Both commands run in Frontend CI. The shared fixture is verified against actual PostgreSQL seed/API output by Backend CI; change it only through the backend procedure. This closes the gap where handwritten metadata fixtures could pass tests while differing from the actual API.
