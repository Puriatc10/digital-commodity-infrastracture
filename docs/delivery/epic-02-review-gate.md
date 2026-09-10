## A. Epic Verdict

**EPIC 2 — APPROVED FOR MERGE**

Approval applies to `codex/epic-02-identity-organizations` **with the uncommitted review fixes**, not the original unchanged head. Owner review and authorization remain required before committing, pushing, or merging. Hosted CI has not been rerun on these fixes.

Review date: 2026-09-10. Original head: `1d7d005`. Local `master` and the merge base are `a79af44250659ff871503b863c2bf7faa471f9fc` (approved Epic 1). The initial working tree was clean. The complete merge-base diff contains 40 files and 2,153 insertions/4 deletions. Epic 2 is not merged into local `master`. Remote-tracking refs agreed at session start; no fresh remote CI status is asserted.

The owner's attached Epic 2 gate superseded AGENTS.md's stale Epic 1 scope. The roadmap, relevant specification sections, glossary, architecture, ADRs 0001/0002/0004/0008/0009, source-review record, and approved Epic 1 gate were reviewed. Recorded product-source ambiguities remain unresolved. No Epic 3 work, new branch, commit, push, merge, reset, rebase, or history rewrite was performed.

Complete original Epic 2 file inventory:

```text
.github/workflows/ci.yml
apps/api/config/settings/base.py
apps/api/config/urls.py
apps/api/identity/__init__.py
apps/api/identity/admin.py
apps/api/identity/apps.py
apps/api/identity/management/__init__.py
apps/api/identity/management/commands/__init__.py
apps/api/identity/management/commands/seed_demo_personas.py
apps/api/identity/migrations/0001_initial.py
apps/api/identity/migrations/0002_systemroleassignment.py
apps/api/identity/migrations/__init__.py
apps/api/identity/models.py
apps/api/identity/serializers.py
apps/api/identity/tests.py
apps/api/identity/urls.py
apps/api/identity/views.py
apps/api/organizations/__init__.py
apps/api/organizations/admin.py
apps/api/organizations/api/__init__.py
apps/api/organizations/api/permissions.py
apps/api/organizations/api/serializers.py
apps/api/organizations/api/views.py
apps/api/organizations/apps.py
apps/api/organizations/migrations/0001_initial.py
apps/api/organizations/migrations/0002_organizationcapability_check_valid_capability.py
apps/api/organizations/migrations/0003_organizationmembership_role_and_more.py
apps/api/organizations/migrations/__init__.py
apps/api/organizations/models.py
apps/api/organizations/tests.py
apps/api/organizations/tests_authorization.py
apps/api/organizations/urls.py
apps/web/src/app/[locale]/layout.tsx
apps/web/src/components/application-shell.tsx
apps/web/src/components/auth-status-bar.tsx
apps/web/src/components/demo-persona-switcher.tsx
apps/web/src/lib/api/client.ts
apps/web/src/lib/api/generated/schema.d.ts
apps/web/src/lib/auth-context.tsx
docs/adr/0009-authentication-architecture.md
```

## B. Findings

### Blocker

**Broken browser session/demo integration — fixed.** The documented frontend origin displayed `Auth Error`; direct browser fetch to `127.0.0.1:8000` failed while Django received the requests. There was no working CORS or same-origin arrangement. A separate executable probe of the installed `openapi-fetch` client showed POST `credentials=include` but no CSRF header: the custom fetch wrapper inspected `init.method`, although the library supplied the method in a `Request` object. The demo control also never bootstrapped the CSRF cookie. Consequently a clean browser could not enter the demo.

The fix uses same-origin browser requests, an environment-configured Next.js API proxy, middleware acting on the actual Request, current-cookie CSRF headers, and explicit demo bootstrap. Browser mutation testing then exposed a Next/Django trailing-slash redirect loop; the proxy now preserves both API URL forms and disables Next's slash normalization. Real browser persona switching, `/me`, authorized PATCH, logout, and missing-token rejection passed. Node regression tests exercise the actual typed client. The proxy follows Next's documented [rewrite](https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites) and [slash-handling](https://nextjs.org/docs/14/pages/building-your-application/routing/middleware) behavior.

### Major

| Finding | Observed behavior and impact | Root cause and fix | Regression validation |
| --- | --- | --- | --- |
| Anonymous login lacked CSRF enforcement | A real CSRF-enforcing Django client logged in without a token: 200 instead of 403. This bypassed the intended login-CSRF boundary. | `ensure_csrf_cookie` sets a cookie but does not enforce CSRF; DRF session authentication checks only authenticated requests. Added explicit `csrf_protect`. | Test failed on original code, then passed: tokenless login 403; bootstrap + matching token 200; logout destroys session. |
| Production session cookies lacked Secure | Production enabled Secure only for the CSRF cookie; the newly introduced session cookie inherited `Secure=False`. Session material could be sent over HTTP before a redirect. | Added `SESSION_COOKIE_SECURE=True` in production. Local development remains usable. | Production-settings subprocess checks verify Secure, HttpOnly, and SameSite=Lax. |
| Public demo password and production impersonation exposure | The seed created every account, including Product Admin, with a shared public password. Ordinary login remained available even with demo switching disabled. Production also accepted the demo flag. | New demo accounts have unusable passwords; seeding requires explicit demo enablement; production rejects the switcher flag. Identity migration 0003 retires the known public password only on the five reserved accounts. | Tests verify unusable seed passwords, flag parsing/production rejection, repeated seed counts, and historical-model migration behavior. Independently configured and unrelated account passwords remain intact. |
| Backend package omitted both new domains | Setuptools discovery still included only `config*`, leaving Identity/Organizations absent from a built distribution even though execution from the source directory worked. | Included `identity*` and `organizations*` in package discovery. | Built and inspected the wheel for both models and migrations. |
| API contract mismatches | Login's inferred response described the login input instead of session context; logout lacked its explicit 204 contract. PUT accepted an empty payload despite a required profile name in OpenAPI. | Explicit auth success/error schemas, write-only password, generated TypeScript update, and standard DRF PUT validation while retaining partial PATCH. | Empty PUT reproduced 200 on original code and now returns 400; PATCH remains 200. Validated generated schema and live login/logout/session contracts. |

DRF's login-CSRF and unauthenticated-403 semantics are documented in its [authentication guide](https://www.django-rest-framework.org/api-guide/authentication/). No custom 401/token scheme was introduced.

### Minor

All addressed:

- `/me` unnecessarily exposed `is_staff` and `is_superuser`. Removed from the response and generated contract; exact safe-field/context tests pass.
- Demo switching returned 200 and context for an inactive predefined account, although subsequent session authentication would reject that user. It now returns 404 before login; reproduced test passes.
- `/me` prefetched capabilities but then bypassed that cache with `values_list`. Four memberships produced seven serializer queries; using the prefetched objects produces three. Regression asserts that bound.
- Frontend retained invalid preference IDs in storage and had no automatic expired-session refresh. It now validates and replaces/clears the preference, tolerates blocked storage, refreshes on focus/every minute, and ignores superseded requests. Browser tests confirm a foreign ID is rejected, second-Organization selection persists, and an expired session clears without a page reload. Server/network failures have a separate error state.
- New reusable controls hard-coded English UI strings and duplicated the persona request union. They now use the Persian dictionary and generated request enum, with accessible selector labels and a visible switch-failure state.
- Setup instructions and agent/architecture context still described the pre-identity foundation. Updated relevant setup, migration, session, permission, and demo documentation. CI now includes the Epic 2 push pattern and frontend session tests, and uses the current proxy environment name.

### Nit

No additional findings raised. No unrelated formatting or architecture refactor was undertaken.

## C. Task-by-Task Functional Assessment

### T0201

Pass with fixes. Project-owned `identity.User` is configured by `AUTH_USER_MODEL` and created in Identity's initial migration. It uses unique email, no username, standard Django hashing, active/staff flags, and PermissionsMixin. User contains no Organization business fields. Normal and superuser managers work; invalid staff/superuser options are rejected. Product authorization does not inherit Django flags. Django admin is not exposed by this API; an admin UI was not added by this gate.

Email uniqueness is enforced for exact stored values; Django's manager normalizes the email domain. No broader case-folding/account-alias policy was invented. Invalid password, unknown account, and inactive account use the generic login error path. Inactive users and expired sessions cannot use `/me`. Login/logout/session/CSRF flows passed. Protected anonymous requests return **403**, consistent with existing tests and SessionAuthentication.

### T0202

Pass. User ↔ OrganizationMembership ↔ Organization is many-to-many. Commercial participation is a separate OrganizationCapability relationship, allowing Buyer/Supplier/Broker simultaneously. Membership and capability duplicates and invalid capability values were rejected by PostgreSQL. `trader` appears only as invalid-input test data or prohibited terminology, never as a domain choice.

### T0203

Pass. Membership roles are exactly Owner/Manager/Member/Viewer. The **viewer default is conservative and safe**: creating an unspecified membership grants read access, not profile modification. One user can be Owner in one Organization and Viewer in another; exercised in PostgreSQL and browser fixtures.

System roles are exactly Operator/Admin, independent of Organizations and Django staff/superuser. The real database **UniqueConstraint(user, role)** exists. Duplicate Operator and duplicate Admin assignments are each rejected; **one user can intentionally hold both**. No exclusivity restriction was added.

### T0204

Pass. Tests exercise endpoint behavior with real sessions and CSRF, in addition to the existing permission tests.

| Actor | Own Organization read | Own safe profile update | Foreign/system-wide access |
| --- | --- | --- | --- |
| Viewer | Yes | No, 403 | Hidden, 404 |
| Member | Yes | No, 403 | Hidden, 404 |
| Manager | Yes | Yes | Hidden, 404 |
| Owner | Yes | Yes | Hidden, 404 |
| Operator | Global read | No grant from system role | All Organizations readable, including inactive ones |
| Product Admin | Global read | Yes, safe fields only | Safe profile updates permitted globally |

An independently authorized Owner/Manager membership still grants its own edit permission to a user who also has an Operator assignment; Operator alone grants no write permission.

Normal-user querysets contain only active Organizations with active memberships. Foreign detail and update both return 404; inactive memberships provide no access. Inactive Organizations are absent from membership-based access and `/me`, while Operator/Admin retain explicit global visibility. Malicious memberships/roles/capabilities/system_roles/user/active-status payloads do not modify those relationships; only name, registration identifier, website, and country are writable. Buyer, Supplier, Broker, and accumulating all three capabilities never elevate a Viewer. No exposed system-role assignment API exists. Django superuser without product roles or membership receives no product Organization access.

### T0205

Pass with fixes. The actual browser obtains a CSRF cookie, sends session cookies and mutation headers through a same-origin request, and receives Django-authorized context. `/me` includes only the current user's safe identity, roles, active Organizations, membership roles, and capabilities. Unrelated users' memberships and roles, inactive memberships, and inactive Organizations are excluded.

Zero Organizations works for Operator/Admin; one is auto-selected; multiple can be selected. A manually injected foreign UUID is rejected. The only persisted application value is the selected Organization UUID; sessionStorage was empty, and no password, token, session ID, role override, or CSRF value was stored in Web Storage. The session cookie was not visible to JavaScript. Storage failure is harmless. Loading/authenticated/unauthenticated/error paths exist; browser expiry and offline error behavior were observed. Newer refresh responses supersede older requests by a request counter.

### T0206

Pass with fixes. The backend flag defaults false and parses false/0 correctly. Disabled GET and a valid-CSRF POST return 404; missing-CSRF POST can return 403 before unavailable handling. Production refuses the enabled flag. Only buyer/supplier/broker/operator/admin keys map to fixed reserved emails; arbitrary IDs, email, username, Organization IDs, unknown/case-varied values, and malformed JSON were rejected.

Each switch uses a normal Django login session for an active seeded user. The seed was run repeatedly on PostgreSQL, and counts across users, Organizations, memberships, capabilities, and system roles remained stable in regression tests. Assignments are Buyer→Manager/Buyer, Supplier→Owner/Supplier, Broker→Member/Broker; Operator/Admin have their respective product roles and no artificial Organization. They are not Django superusers. Clean-browser bootstrap and Buyer→Supplier→Broker→Operator→Admin→Buyer passed through the real UI and a browser-side API probe. Organization preference is cleared and recalculated across persona changes.

## D. PostgreSQL Validation

Actual database: Docker PostgreSQL **17.11**, accessed on loopback. Created an isolated `epic2_review_20260910` database; the owner's existing database and `.env` were preserved. No SQLite substitute was used.

| Check | Actual result |
| --- | --- |
| Empty database migrations | Entire contenttypes/auth/identity/organizations/sessions graph applied successfully. |
| Final migration consistency | `makemigrations --check --dry-run`: no changes. |
| Review security migration | Identity 0003 applied successfully; full tests rebuild the final graph from zero. |
| Duplicate membership / capability | PostgreSQL IntegrityError, including bulk inserts bypassing model validation. |
| Invalid capability / membership role | PostgreSQL IntegrityError. |
| Duplicate Operator / Admin assignments | Both rejected independently by PostgreSQL. |
| Invalid system role | PostgreSQL IntegrityError. |
| Both system roles on one user | Both coexist successfully. |
| Full original suite | 52 passed before fixes. |
| Initial additional review regressions | Five failures reproduced: login CSRF, inactive demo user, privilege flags, capability query count, shared seed password. PUT mismatch was reproduced separately. |
| Final full backend suite | **71 passed**, 82.243 seconds, system checks clean. |
| Password migration upgrade | Historical User model test is repeatable and preserves unrelated/custom passwords. |

Approved Epic 1 had no installed Django auth/session/admin applications and no application migration graph. It did not create the built-in auth User that commonly makes late AUTH_USER_MODEL changes problematic. Normal Epic 1 databases can apply this graph directly. An independently altered development database with a previously migrated built-in User should use a fresh disposable database; no speculative production-data conversion was built.

## E. Security Assessment

Authentication uses standard Django server sessions and password hashing. Production session/CSRF cookies are Secure; session cookies remain HttpOnly/SameSite=Lax. Host/trusted-origin configuration is explicit and contains no hard-coded production domain.

Anonymous login and demo switching enforce CSRF; authenticated logout and Organization mutations enforce it through SessionAuthentication. No application `csrf_exempt`, global CSRF disable, magic bypass header, JWT, bearer scheme, role override, or Web Storage credential mechanism exists.

Horizontal isolation, restricted profile writes, inactive membership behavior, capability separation, and product-role independence passed endpoint tests. `/me` no longer leaks Django privilege flags or foreign context. Demo impersonation is fixed-key, active-user-only, explicitly enabled locally, and rejected in production. Migration 0003 retires legacy public seed credentials during upgrade.

**No known unresolved Epic 2 security defect remains in the reviewed code before Epic 3.** This is a scoped application review, not validation of an unconfigured production ingress or a general penetration test.

## F. Browser Integration Validation

Used the actual in-app browser, Django `runserver` on `127.0.0.1:8000`, Next.js on port 3000, PostgreSQL review data, and process-only configuration matching the updated examples. Tested the production build with `npm run start` and the documented `npm run dev` flow. Local API settings had the demo flag explicitly enabled and exact localhost/loopback browser origins trusted. No real `.env` was edited.

| Browser check | Result |
| --- | --- |
| Original direct cross-origin fetch | Failed to fetch; application displayed Auth Error. |
| Same-origin CSRF bootstrap | 200; browser CSRF cookie present. |
| Clean browser → actual persona control | Successfully established Buyer session without an existing login. |
| Actual UI persona sequence | All six transitions showed the correct user, role, and Organization state. |
| Browser `/me` after every API switch | Correct actual seeded user/capability/system-role context. |
| Demo POST without/with CSRF | 403 / 200. |
| Authorized Organization PATCH without/with CSRF | 403 / 200, no redirect loop. |
| Logout without/with CSRF | 403 / 204; subsequent `/me` 403. |
| Ordinary password login | 200 for an isolated multi-Organization fixture using proper bootstrap. |
| Foreign persisted Organization UUID | Rejected and replaced by an authorized Organization. |
| Multiple-Organization selection | Selected second Organization; survived reload. |
| Operator/Admin zero Organizations | Rendered correctly without a selector/crash. |
| Storage inspection | Only Organization preference in localStorage; sessionStorage empty; only CSRF cookie visible to JavaScript. |
| Expired server session | Open application changed to unauthenticated automatically without reload. |
| Offline API transport | Separate localized error state appeared. |
| Persian layout | `lang=fa`, `dir=rtl`, no desktop horizontal overflow. |
| Swagger UI | Rendered real auth, health, and Organization operations through the same-origin proxy. |

Temporary browser diagnostic pages and transpilation probes were removed from source before the final clean build. Review helper scripts were removed and the temporary Django/Next.js servers stopped after validation. The isolated PostgreSQL review database is retained for owner inspection; existing databases and Docker services were preserved. Browser claims above are not inferred from curl or the Django test client.

## G. API / OpenAPI Validation

`npm run api:generate` passed Django `spectacular --validate --fail-on-warn` and openapi-typescript generation. Schema version is OpenAPI 3.0.3. Live schema/docs/health returned 200. Login's success schema is User, password is write-only, logout documents 204, `/me` documents the actual 403 behavior, and demo errors distinguish JSON objects from possible HTML CSRF failures. Standard PUT requirements now match the schema.

The client and persona request type derive from generated TypeScript; no parallel handwritten request/response DTOs were introduced. Organization-context and UI state types reference generated schemas.

Repeated generation after the final clean dependency installation was byte-identical (SHA256 `2342EE8C2BC804088397C7FAF893EB30F441AA18E667B887E6896F500499AB59`). Differences from original HEAD are intentional contract fixes, not unexplained drift. CI retains its generated-file diff check.

## H. Regression Results

| Gate | Result |
| --- | --- |
| Python runtime | 3.12.4; existing project environment. |
| PostgreSQL runtime | 17.11. |
| Node runtime | Supported Node 24.19.0 for final clean install/checks. An earlier install used system Node 20; it was superseded by the clean Node 24 run. |
| `pip check` | No broken requirements. |
| Ruff | All checks passed. |
| Django checks | No issues. |
| Fresh migrations / migration consistency | Passed. |
| Full PostgreSQL suite | 71 passed. |
| Backend package build | Wheel includes Identity, Organizations, and security migration. |
| Clean `npm ci` | Passed; zero reported vulnerabilities. |
| Frontend lint | Passed, zero warnings. |
| Frontend tests | 3 passed: actual client CSRF/credentials, selection validation, safe storage. |
| Frontend typecheck / production build | Passed. |
| Routing | `/` 307 to `/fa`; `/fa` 200; `/en`, `/xx`, `/fa/missing` 404. |
| Public API foundation | Health, schema, docs 200; Swagger rendered. |
| Authenticated API regression | Anonymous `/me` and Organization list 403. |
| Final whitespace check | `git diff --check` passed. |

CI uses PostgreSQL 17 and the unrestricted `python manage.py test` command, so new tests are discovered. It covers dependency consistency, Ruff, Django checks, migration consistency/migrations, backend tests, OpenAPI generation/drift, deterministic frontend install, lint, typecheck, build, and now frontend session regressions. Epic 2 push triggers were added; pull requests already triggered it. No hosted green result is claimed for the uncommitted fixes.

No tracked real `.env`, local database, bytecode, node_modules, venv, test artifact, temporary SQLite setting, or browser-probe file was introduced. Recognizable production credentials/token mechanisms were absent from the reviewed application changes. The legacy password literal remains only where needed for its security migration and test fixtures, not as an operational seed credential. No future commodity, RFQ, supply, matching, procurement, Offer, Deal, verification/KYC, execution/settlement, or extra-infrastructure module was added.

## I. Fixes Made

Every source/documentation/test file changed by this gate is listed below. All are uncommitted.

| File | Reason |
| --- | --- |
| `.env.example` | Document exact local trusted origins and disabled demo default. |
| `.github/workflows/ci.yml` | Add Epic 2 push trigger, frontend regression execution, and current proxy environment name. |
| `AGENTS.md` | Align the authorized review scope/branch with the owner's request. |
| `README.md` | Correct current implementation, integrated frontend setup, and CI scope. |
| `apps/api/README.md` | Document actual auth, permission, inactive-state, CSRF, demo, and migration behavior. |
| `apps/api/config/settings/base.py` | Environment-controlled CSRF trusted origins. |
| `apps/api/config/settings/production.py` | Secure session cookies and reject demo impersonation in production. |
| `apps/api/identity/management/commands/seed_demo_personas.py` | Require explicit demo enablement and create unusable passwords. |
| `apps/api/identity/migrations/0003_retire_shared_demo_password.py` | Retire the former public password on reserved demo accounts during upgrade. |
| `apps/api/identity/serializers.py` | Remove Django privilege flags, use prefetched capabilities, mark login password write-only. |
| `apps/api/identity/tests.py` | Explicitly enable demo in the existing seed test. |
| `apps/api/identity/test_review_gate.py` | Add 19 PostgreSQL security, integrity, profile-contract, seed, and upgrade regressions. |
| `apps/api/identity/views.py` | Enforce login CSRF, reject inactive personas, correct auth/OpenAPI responses. |
| `apps/api/organizations/api/views.py` | Restore standard PUT validation consistent with OpenAPI. |
| `apps/api/pyproject.toml` | Package Identity/Organizations and their migrations. |
| `apps/web/.env.example` | Document server-only same-origin API proxy target. |
| `apps/web/README.md` | Document integrated setup, session/context behavior, and checks. |
| `apps/web/next.config.ts` | Proxy same-origin API traffic while preserving Django trailing slashes. |
| `apps/web/package.json` | Add Node-based frontend regression command. |
| `apps/web/src/components/application-shell.tsx` | Pass locale dictionary to new controls. |
| `apps/web/src/components/auth-status-bar.tsx` | Localized session/role/Organization labels and accessible selector. |
| `apps/web/src/components/demo-persona-switcher.tsx` | CSRF bootstrap, generated persona type, safe context reset, localization/error display. |
| `apps/web/src/i18n/messages/fa.ts` | Persian session and persona messages. |
| `apps/web/src/lib/api/client.ts` | Same-origin credentialed requests and CSRF middleware acting on actual Request objects. |
| `apps/web/src/lib/api/generated/schema.d.ts` | Regenerated corrected backend contract. |
| `apps/web/src/lib/auth-context.tsx` | Accurate error/unauthenticated states, expired-session refresh, race guard, preference validation. |
| `apps/web/src/lib/organization-preference.ts` | Small tested preference boundary; only validated Organization IDs, optional storage. |
| `apps/web/tests/session.test.mjs` | Actual client request/CSRF and Organization preference/storage regressions. |
| `docs/adr/0009-authentication-architecture.md` | Record implemented session transport and security semantics. |
| `docs/adr/README.md` | Index the existing authentication ADR and current Epic 2 state. |
| `docs/architecture/overview.md` | Correct implemented domain state and link reviewed permission/session behavior. |
| `docs/delivery/epic-02-review-gate.md` | Preserve this review's findings, validation evidence, file inventory, and merge conditions. |

No authoritative product specification/roadmap changes, dependency-version upgrades, new services, generic RBAC framework, or future business features were included.

## J. Remaining Risks

**Acceptable deployment/future work:** production TLS termination, ingress forwarding, and actual domain/origin configuration must be validated in the eventual deployment environment. This gate tested real first-party HTTP development transport and production security settings, not an unconfigured production host. A deliberately modified pre-Epic-2 local database using the built-in auth User needs a fresh disposable database as documented.

**Actual merge conditions:** review and include all uncommitted fixes, including generated types and Identity migration 0003, then run hosted CI on the authorized revision. Upgrading an existing demo database must apply migrations; merely copying code does not retire old database password hashes. The original unchanged `1d7d005` is not approved. No remaining known code defect blocks the reviewed fixed revision.

## K. Architecture Assessment

Conforms to Django modular monolith, PostgreSQL source of truth, server-side sessions plus CSRF, server-side authorization, User/Organization separation, distinct capability/membership-role/system-role layers, backend-authoritative OpenAPI, and frontend permission/context state as UX only. Demo impersonation uses real users and assignments and is excluded by production settings. The first-party transport uses the existing Next.js server, adding no infrastructure dependency. Multi-commodity extensibility and all later-epic boundaries remain intact.

## L. Merge Recommendation

`codex/epic-02-identity-organizations` is safe to merge into `master` **with all listed review fixes**, after owner review/authorization and CI on that revision. Approval does not apply to the original unchanged head.

No commit, push, merge, additional branch, or Epic 3 implementation was performed.
