# Frontend foundation — Epic 1

Next.js App Router, TypeScript, Tailwind CSS, and a minimal shadcn/ui shell. Only the Persian demo at `/fa` is enabled. There are no business modules, user accounts, data, or API calls.

## Setup and commands

Use Node.js 22.13+ (Node 24 LTS recommended) and npm. The lockfile is the dependency source for repeatable installs. No root JavaScript workspace/package-manager convention existed, so this app uses npm locally without additional monorepo tooling.

From this directory:

```sh
npm ci
npm run dev
```

Open `http://localhost:3000/fa`. `/` redirects to `/fa`; `/en` and unsupported locales return 404. Stop the server with Ctrl+C.

| Command | Purpose |
| --- | --- |
| `npm run dev` | Start the development server. |
| `npm run lint` | Run Next.js Core Web Vitals and TypeScript ESLint rules, with zero warnings. |
| `npm run typecheck` | Generate Next.js route types, then run strict TypeScript checks without emitting JavaScript. |
| `npm run build` | Build the production application. |
| `npm run start` | Serve the production build. Run after `build`, with the dev server stopped. |
| `npm run api:generate` | Validates and exports Django's schema, then generates TypeScript definitions. Requires the backend virtual environment active, installed backend dependencies, and Django environment configuration; no running API server is needed. Do not manually edit `src/lib/api/generated/schema.d.ts`. |

All commands also work from the repository root using `npm --prefix apps/web ...`. Lint is separate from the production build. The shell needs no environment variables or backend services. Before using the typed API client, copy this directory's `.env.example` to `.env.local` and set `NEXT_PUBLIC_API_BASE_URL` to the backend origin. The client rejects missing configuration; the root Django/Compose `.env` is not loaded by Next.js. Public values are embedded at build time; rebuild after changing the origin, and never expose secrets through `NEXT_PUBLIC_*`.

The scoped `js-yaml` 4.3.2 override under `@redocly/openapi-core` fixes [GHSA-2883-xcg3-v3hh](https://github.com/advisories/GHSA-2883-xcg3-v3hh). Remove it once the upstream generator dependency pins a patched parser.

Turbopack is scoped to this app directory. Next.js automatic agent-file generation is disabled so running the dev server preserves the existing repository guidance. ESLint 9 is pinned for compatibility with the React plugin used by the current Next.js lint preset; npm marks that ESLint major deprecated. Upgrade when the preset's plugins support ESLint 10 without peer-dependency overrides.

## Structure

```text
src/
  app/
    [locale]/
      layout.tsx           Root HTML language/direction and locale validation
      page.tsx             Persian foundation page
      [...path]/page.tsx   Route localized path misses to the not-found boundary
      not-found.tsx        Localized missing-page content
    globals.css            Tailwind entry and shared visual tokens
  components/
    application-shell.tsx  Presentation shell receiving localized messages
    ui/
      button.tsx           shadcn Button, trimmed to used variants
      card.tsx             shadcn Card primitives used by the shell
  i18n/
    config.ts              Locale directions, enabled locales, default locale
    messages.ts            Typed dictionary lookup
    messages/fa.ts         Persian strings, including metadata and accessibility
  lib/utils.ts             clsx + tailwind-merge helper
```

The root layout is under `[locale]` so language and direction come from the URL, with no client-side document mutation. Pages/layouts use Server Components. Reusable shell/UI components contain no translated literals; they receive messages or children. Spacing/borders use logical properties so the same components work in RTL and LTR.

## Localization

`locales` defines `fa → rtl` and `en → ltr`; `enabledLocales` contains only `fa`. English translations and an English UI are intentionally absent.

When English is authorized, add a dictionary satisfying `Messages`, register it in `dictionaries`, and add `en` to `enabledLocales`. The layout and reusable shell will use its language, direction, and translated props without rewriting components. This is a simple typed dictionary, not an ICU/pluralization or translation-management framework. Add those capabilities only when actual copy requires them.

Vazirmatn Arabic-subset font files are served locally from the installed Fontsource package at weights 400, 500, and 600. No Google Fonts download is required during build or page rendering. The font stack also provides Latin fallbacks for future English content.

## UI and API boundaries

`components.json` configures shadcn's TypeScript/RSC foundation with RTL and Tailwind v4 CSS variables. Button and Card are manually adopted from the official shadcn registry, keeping only used primitives/variants. The Button uses the individual Radix Slot package for a semantic anchor; the full Radix catalog, icons, and animation libraries are not installed. These primitives inherit document direction and do not need a direction provider; evaluate that requirement when adding direction-sensitive interactive primitives later.

The shell has a single real navigation link to its foundation page and an in-page “about” anchor. It has no authentication, persona switching, dashboard navigation, simulated actions, or business records. The frontend imports no Django internals and defines no backend DTOs. T0105 provides generated types in `src/lib/api/generated/schema.d.ts` and a handwritten `openapi-fetch` client in `src/lib/api/client.ts`; the shell does not call it yet. Browser cross-origin requests and authentication are not configured in this foundation and must be addressed when actual UI integration is authorized.

CI uses the same `npm run api:generate` command and checks the generated types with `git diff --exit-code`. The backend schema file is an ignored intermediate, and the generated frontend file is committed.

## Manual verification

After starting the app, confirm `/fa` loads, the HTML root has `lang="fa" dir="rtl"`, the sidebar is on the right on desktop, the narrow layout does not overflow, and the keyboard skip link and “about” anchor work. Confirm `/` redirects to `/fa` and `/en` is unavailable. Repeat the page check with `npm run start` after building. No test framework was introduced solely for this bootstrap.

Implementation references: [Next.js installation](https://nextjs.org/docs/app/getting-started/installation), [App Router localization](https://nextjs.org/docs/app/guides/internationalization), [Tailwind with Next.js](https://tailwindcss.com/docs/installation/framework-guides/nextjs), and [shadcn RTL configuration](https://ui.shadcn.com/docs/rtl/next).
