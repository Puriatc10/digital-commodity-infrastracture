# Epic 3 Review Gate — 2026-09-11

## A. Epic Verdict

**EPIC 3 — APPROVED FOR MERGE**

> Approval applies only with the listed uncommitted Review Gate fixes.

The unchanged original HEAD is not approved. Owner review, authorized commit/push, and passing hosted CI on the resulting revision are required before merge. No commit, push, merge, new branch, or Epic 4 implementation was performed.

## B. Review Boundary

- Branch: `codex/epic-03-dynamic-commodity-model`.
- Original/current committed HEAD: `92b214fc8bfb5034bc7150639147527cebf17ad4`.
- Local master and merge base: `2debb465ad9d816270e1698ceac773a06f266102`.
- Initial working tree: clean. Original merge-base diff: **46 files, 14,259 insertions / 3,755 deletions**, dominated by the npm lockfile and 2,198-line Design Contract.
- `git ls-remote` verified that both remote heads match these local hashes. Epic 3 has not been merged into remote or local master. GitHub check-runs lookup returned HTTP 403, rate limit exceeded; no hosted-green assertion is made.
- T0301–T0308 are represented in the complete branch history, including task merges #27, #29, #33, #36, #38, #32, #39, and #41. Representative implementation commits: `878db2a`, `350b229`, `60ae452`, `d491bbd`, `d18e00a`, `f1ab246`, `88bbe8e`, `b18dab8`, plus their corrections/merge history. Review was not limited to T0308.
- Reviewed the product specification's commodity, architecture, locale, quality and testing requirements; roadmap direction and all T0301–T0308 criteria; complete Epic 3 Design Contract; glossary; architecture/source-review records; ADRs 0001/0002/0003/0004/0008 and the approved Epic 1/2 gates. The owner's attached review request supersedes the stale documentation-only authorization. Product requirements and unrelated source ambiguities were not changed.

Original scope inventory: commodities models/Admin/services/read APIs, one `commodities/0001_initial` migration, five backend commodity test modules, two seed commands, two generic React components, four UI primitives, two component test files and Vitest setup, generated TypeScript, root OpenAPI snapshot, dependency manifests/locks, CI, and architecture/product/delivery documentation. Config changes only register the commodities app and URLs. No Epic 4 implementation was found.

## C. Findings

### Blocker

**Historical mutation/deletion and active-pointer integrity — fixed locally.** A Draft attribute could move into a Published schema. Cached Draft/Published relations allowed late attribute creation, deletion, retirement of the active schema, and activation of a Retired schema. Commodity cascade deletion and queryset/Admin bulk deletion bypassed model `delete()` guards. These operations could destroy or reinterpret historical semantics. Root causes were checking cached objects, checking only the old attribute parent, and relying exclusively on per-instance deletion methods. Fixes read persisted relationships, lock definition mutations transactionally, check both attribute parents, and use `pre_delete` guards covering Django's deletion collector. The new PostgreSQL probes originally produced **12 failures across 13 tests including subtests**; the final expanded regressions pass and compare persisted rows after rejection.

**Actual API/Form/View metadata mismatch — fixed locally.** Seeds/API use enum `value` and `minimum`/`maximum`/`minLength`/`maxLength`; handwritten frontend DTOs/fixtures expected `canonical_value` and other constraint names. Actual seeded options therefore did not provide usable canonical select values, the View missed localized labels, and bounds were ignored. Root cause: untyped JSON metadata and duplicated frontend assumptions. Added nested backend serializers, regenerated TypeScript, removed handwritten metadata DTOs, corrected both renderers, and added shared fixtures verified against actual PostgreSQL seed/API output and consumed in React tests. Both commodities now pass the same integration path.

### Major

- **Integer truncation — fixed.** The Form converted `15.9` to `15`; an existing test endorsed that incorrect behavior. It now preserves `15.9` for backend rejection, with updated interaction regression evidence.
- **Definition publication accepted ambiguous/invalid metadata — fixed.** Duplicate enum values and invalid numeric constraints could be frozen into Published history. Publication now checks v1 metadata structure, unique canonical enum strings, constraint types/bounds, option ordering metadata, and generated JSON Schema validity before persisting state. PostgreSQL tests prove rejected publication leaves the schema Draft.
- **Lifecycle/concurrency gaps — fixed.** Draft could skip directly to Retired; services trusted caller snapshots; simultaneous clones could choose the same next version. Current-state checks, commodity/schema row locks, guarded transitions and atomic operations address these. Two real PostgreSQL concurrent-connection tests prove distinct complete clones and mutually consistent retirement/activation. Failure injection proves clone and publish+activate rollback.
- **Structured errors lost field identity — fixed.** Parsing third-party English error prose returned a mangled name for apostrophes and only one of several unknown fields. Errors now use structural information and application-owned messages, with stable per-field codes/order. Regression covers multiple unknown keys including an apostrophe.
- **Commodities omitted from built package — fixed.** Setuptools package discovery listed only config/identity/organizations. Added commodities; a built wheel was inspected and contains its models, migration and seed commands.

### Minor

- Added Epic 3 push trigger; PR CI and component-test execution already existed. Removed conditional backend test-class discovery so removal of validator functions cannot silently skip their tests.
- Added typed 403/404 OpenAPI response entries, field-error accessibility, unique IDs for repeated Forms, explicit select RTL direction, shared localized renderer text/group headings, and safe handling of arbitrary group names.
- Canonical commodity codes now remain stable through supported saves. Finite JSON-number semantics are checked. New schemas cannot start Retired.
- Removed the redundant tracked root `schema.yml`; canonical generation uses ignored `apps/api/schema.yaml` and tracked generated TypeScript.
- Updated stale authorization and usage documentation without altering the Product Specification or substantive roadmap acceptance criteria.

### Nit

No style-only refactors requested. Non-blocking Vite configuration-loader warning remains. Existing unused frontend form-library dependencies can be evaluated separately; no dependency upgrade/removal was needed for correctness.

## D. T0301 Assessment — Models

Pass with fixes. CommodityDefinition has UUID identity, unique canonical stable code, Persian/English names, active flag, timestamps and nullable active-version reference. It is platform-level, with no Organization ownership, inventory or transaction fields. CommoditySchemaVersion has commodity FK, explicit version, timestamps and Draft/Published/Retired status. CommodityAttributeDefinition has version FK, key, localized labels, five limited types, required flag, unit/enum/validation metadata, display group and sort order.

PostgreSQL enforces unique code, unique commodity/version, unique schema/key, status/type membership, FKs and nonnegative positive-integer fields. Bulk inserts bypassing Django validation prove all five requested uniqueness/status/type constraints reject invalid records. Active ownership/state, code stability, lifecycle semantics and immutability are application-enforced. No commodity-specific columns were found.

## E. T0302 Assessment — Lifecycle

Pass with fixes. Draft attributes remain editable/deletable. Draft→Published and non-active Published→Retired succeed. Published→Draft, Retired→Published/Draft, repeated publication, Draft→Retired and creation as Retired reject without changing persisted rows. A new Published record is permitted through the guarded model path, with definition validation; normal services/seeds start Draft.

Published and Retired schema commodity/version and all attribute semantics remain protected, including key, both labels, type, required, units, enums, validation, grouping and order. Attribute insertion/reparenting and Django deletion/cascade paths are guarded. Setup can have no active schema; only a same-commodity Published schema can be selected. Retirement rejects an active schema without clearing it. Publish+activate v2 leaves v1 Published and unchanged. Clone creates new schema/attribute IDs and copies metadata into a Draft; changing v2 does not affect v1.

Transactions cover publication/activation, retirement and complete cloning. Commodity locks serialize version allocation and active changes; schema/attribute locks protect edits and reparenting. Concurrent clone and retire/activate tests use separate PostgreSQL connections. Injected failures roll back state; no distributed locking infrastructure was added. Database deadlock/serialization errors remain transaction failures that callers may retry, not partially committed operations.

**Trust boundary:** model saves, lifecycle services, Admin form restrictions, and Django model/queryset/cascade deletion guards. Admin status is read-only and lifecycle functions are used after draft edits. Admin is not mounted as a product endpoint; deletion collector regressions cover the underlying bulk path. `QuerySet.update`, `bulk_create`, `bulk_update`, `save_base`, raw SQL and historical migration models remain privileged bypasses, not supported production mutation APIs. PostgreSQL has no semantic-immutability triggers. Seed conflict tests deliberately demonstrate a bulk-update bypass and historical preservation on reseeding. This is not protection against a DBA.

## F. T0303 Assessment — Validation

Pass with fixes. Relational definitions alone generate deterministic Draft-7 JSON Schema, ordered by attribute sort order/key; no independent per-commodity JSON Schema exists. It supports string, number, integer, boolean and canonical string enums. JSON booleans do not satisfy integer/number fields; decimals do not satisfy integer fields. Finite-number handling rejects NaN/infinity.

Required presence, optional absence, required/optional explicit null rejection, unknown-field rejection, localized-enum rejection, inclusive numeric minima/maxima and string-length boundaries are executed in PostgreSQL-backed tests. Payloads remain flat and units remain metadata. Structured errors have stable field/code/application-message semantics; codes include required, invalid_type, invalid_enum, unknown_field, min_value/max_value and min_length/max_length. Optional never implies nullable.

The validator accepts an explicit schema version and never reads the active pointer. Version-evolution tests prove divergent v1/v2 rules, including validation after v1 retirement. Frontend hints are not a second authoritative validator.

## G. T0304 Assessment — Bitumen

Pass. Published/active Bitumen v1 has seven representative attributes: penetration_grade (required enum), penetration, softening_point, ductility, flash_point, solubility and loss_on_heating. Numeric metadata uses appropriate units and compact bounds; labels are localized and order explicit. Canonical grades remain the existing `40/50`, `60/70`, `85/100` values; Persian display labels differ.

Repeated PostgreSQL seeding preserves counts and semantics. Conflict tests deliberately change existing Published labels through a privileged bypass, then prove reseeding preserves them and does not replace a newer active v2. Existing Published seed data is preserved with a warning rather than rewritten to match seed code. The same generator/validator handles valid and invalid Bitumen payloads. This is a representative demo definition, not an exhaustive standards database.

## H. T0305 Assessment — Extensibility

Pass. Base Oil v1 has two required enums (base_oil_group and viscosity_grade), viscosity_at_40c, viscosity_index, flash_point and pour_point, including cSt and negative-temperature examples. Its six-field shape differs materially from Bitumen. It uses the same models, lifecycle, generator, validator, API, Form and View, with no specification-field migration or engine redesign.

A temporary third-commodity test definition uses quality, string, integer, numeric and boolean semantics through the generic engine. Generic component fixtures exercise all five types and arbitrary group names. **A third commodity can be added as definition data without a model, migration, validator class, endpoint or component change.**

## I. T0306 Assessment — API & OpenAPI

Pass with fixes. Actual paths are `/api/commodities/`, `/api/commodities/{code}/schema/`, and `/api/commodity-schemas/{uuid}/`. Discovery excludes inactive commodities and sorts by code; no Organization capability/membership filtering applies to the platform catalog. Setup commodities can appear without an active schema. Active retrieval follows the explicit same-commodity Published pointer, never newest/Draft/Retired fallback; missing/invalid pointer returns 404. Inactive commodity schemas remain addressable for reference inspection by code/UUID; future instance creation must check commodity usability.

Historical retrieval includes Published/Retired and excludes Draft. Authenticated POST/PUT/PATCH/DELETE return 405; anonymous GET returns 403 on all three endpoints. Only reference metadata is exposed. Query-count tests under force-authentication prove 1 query for discovery, 4 for active detail and 2 for historical detail, independent of attribute count. Attributes are prefetched; enum metadata is in-row JSON, with no N+1 lookup.

Backend nested serializers now type the actual metadata; generated TypeScript follows them. Error responses include 403 and applicable 404. Repeated canonical generation is byte-identical for the final contract. Intentional generated changes must be committed with the fixes before CI drift checks can pass.

## J. T0307 Assessment — Dynamic Form

Pass with fixes. One generated-contract component renders all five types and both actual seeded commodity schemas. It emits flat canonical values, displays units as metadata, consumes backend constraint names, shows required indicators and field errors, and respects grouping/order/Persian labels. Explicit RTL reaches the select portal; unique IDs permit multiple forms. Integer decimals are preserved, not truncated. Tests exercise actual input, switch and select interactions in jsdom. Caller-provided error messages attach accessibly to fields. Backend remains authoritative.

## K. T0308 Assessment — Dynamic View & Integration

Pass with fixes. The generic View displays localized labels/options, units, string/number/integer/boolean values, stable grouping/order and an em dash for missing values. It receives its schema explicitly and does not fetch active definitions.

Shared fixtures are built from real PostgreSQL seeds, validated payloads and authenticated API responses; backend CI compares them and frontend CI renders them with generated types. Bitumen and Base Oil use the same components. Historical fixtures demonstrate clone v2, altered labels/options, publish/activate v2, retire v1, and render both versions with their own supplied meanings. Backend evolution tests separately prove changed required/enum rules and immutable v1 rows. No fake persisted specification entity connects the layers.

## L. PostgreSQL Evidence

Actual runtime: PostgreSQL **17.11** in the existing local Docker service; Python **3.12.4**. Created isolated `epic3_review_20260911`; preserved owner databases and real `.env` files. No SQLite was used.

| Check | Result |
| --- | --- |
| Empty database migration graph | All contenttypes/auth/identity/organizations/sessions/commodities migrations applied successfully. |
| `makemigrations --check --dry-run` | Passed; no changes detected, including after fixes. |
| Seed commands, twice each | Passed; final counts **2 commodities / 2 schema versions / 13 attributes**. |
| PostgreSQL constraints | All requested duplicate/status/type failures rejected using bulk inserts. |
| Lifecycle, persisted-state and concurrency regressions | Passed. |
| Original complete backend suite | **140 passed**, 103.602 seconds; did not detect reproduced gate defects. |
| Final complete backend suite | **162 passed**, 124.891 seconds; includes **91 commodity / 71 foundation-identity-organization tests**. |
| Dependency consistency / Ruff / Django checks | Passed. |
| Package build | Isolated wheel build passed; inspected commodities models, migration and seed files. |

An initial non-isolated wheel attempt failed because setuptools was absent from the runtime environment; the declared isolated build succeeded. An initial system npm launcher used Node 20 despite PATH, so clean installation was repeated with explicit Node 24 invocation. Final frontend validation used the supported runtime. These were environment corrections, not passing results attributed to failed commands.

## M. Multi-Commodity Architecture Audit

Source occurrences of Bitumen/Base Oil are seed definitions, tests/fixtures, documentation/demo data, or a generic model help-text example (also copied into generated OpenAPI). No generic production validator/API/Form/View branches on commodity identity. There are no BitumenValidator/BaseOilValidator or commodity-specific Form/View classes. A third commodity is definition data; no engine change is required.

## N. Historical Integrity Assessment

**No implemented supported path silently substitutes today's active version for an explicitly supplied historical version after these fixes.** Validator queries the supplied version's attributes; historical API queries the requested UUID and permits Retired; View uses only its schema prop. v1→v2 and retirement tests cover each boundary. This guarantee relies on using guarded application mutation paths; privileged bulk/raw database edits can rewrite definitions and are outside that boundary.

## O. Test Quality & CI Discovery

| Suite | Canonical command | GitHub Actions job |
| --- | --- | --- |
| `commodities/tests.py`: models, lifecycle, API, validator | `python manage.py test` | `backend` / Backend CI, PostgreSQL 17 |
| `test_bitumen.py`, `test_base_oil.py`: seeds and payload semantics | `python manage.py test` | `backend` |
| `test_epic_integration.py`: version evolution and catalog flow | `python manage.py test` | `backend` |
| `test_review_gate.py`: integrity attacks, rollback, constraints, negative paths, concurrency | `python manage.py test` | `backend` |
| `test_contract_fixtures.py`: actual API examples versus shared fixture | `python manage.py test` | `backend` |
| Form/View and API-integration component files | `npm run test:components` | `frontend` / Frontend CI |
| Existing session regressions | `npm test` | `frontend` |
| OpenAPI validation and generated TypeScript drift | `npm run api:generate`, then generated-file `git diff --exit-code` | `contract` / OpenAPI Contract Validation |

No discovered automated suite is orphaned. Component tests were already wired into CI; the actual defects were misleading fixtures, endorsed integer truncation and conditional backend discovery. Added tests target those failures rather than coverage percentage. The new fixture path exists in the normal full repository checkout used by CI.

Gate-only operational checks: remote-head inspection, package-wheel content inspection, isolated local seed counts and production HTTP routing. These validate the review environment/artifact rather than introduce standalone test suites. Admin UI is not mounted, so no real Admin-browser exercise was run; underlying model and collector protections are covered. No broad Playwright infrastructure was added for this foundation.

## P. API / Contract Validation

`npm run api:generate` successfully ran `spectacular --validate --fail-on-warn` and openapi-typescript. Health/schema/Swagger tests pass in the full backend suite. Nested metadata names/types and historical retrieval are represented. The existing typed openapi-fetch client is preserved. Manual frontend metadata DTOs were removed; public error formatting is owned by the application. Repeated final generation was byte-identical. The removed root OpenAPI snapshot was redundant, not a commodity JSON Schema source.

## Q. Frontend Validation

Node **24.19.0**, supported by the documented >=22.13 requirement. Clean locked dependency installation passed with that runtime. `npm test`: **3 passed**. `npm run test:components`: **18 passed in 3 files**. ESLint, TypeScript and production build all passed.

Actual HTTP checks against the production server: `/`→307 `/fa`; `/fa`→200 with `lang="fa"` and `dir="rtl"`; `/en`, `/xx`, `/fa/missing`→404. The temporary server was stopped. **No real-browser inspection was performed in this gate.** Form/View interactions, select options, switches, numeric edits, required/error metadata and historical rendering were tested using React Testing Library/jsdom, not claimed as browser tests. RTL HTML and production routing were checked over HTTP; visual overflow/focus geometry were not newly tested.

## R. Epic 1 / Epic 2 Regression

All 71 foundation/identity/organization tests remain green in the full suite, including health/schema/docs, sessions, CSRF, auth/me, Organization isolation/capabilities, demo-persona production safety and review regressions. All three frontend session/client/storage tests pass. Auth context, transport, role semantics and unrelated production settings were not changed. Production routes and Persian RTL HTML passed the HTTP checks above. Existing approved browser evidence was not misrepresented as newly executed.

## S. Architecture Failure-condition Audit

| Failure condition | Final result |
| --- | --- |
| Commodity-specific core columns | Absent. |
| Commodity-specific validator/Form/View | Absent. |
| Independent manually maintained commodity JSON Schema | Absent; generator derives definitions. |
| Fake specification-instance table | Absent. |
| Premature JSONB indexes | Absent; one relational engine migration only. |
| Generic Schema Builder | Absent. |
| Active-version historical reinterpretation | Absent in supported paths after fixes. |

The 24 requested invariants conform within the documented trust boundary: data-defined commodity knowledge, definition/value separation, relational source, derived schema, immutable Published/Retired semantics, same-commodity Published active state, historical retrieval/version-aware authoritative validation, unknown/null/enum/unit/flat-payload rules, Bitumen/Base Oil genericity, and absence of specialized validators/components/fake storage/indexes/builder.

No RFQ, Supply Listing, Opportunity, Offer, Matching, Deal, inventory/pricing/transaction fields, Organization-owned commodities, workflow engine, AI, Redis, Kafka, RabbitMQ, Elasticsearch, Temporal, Kubernetes or microservices were introduced.

## T. Fixes Made

Every changed file is uncommitted:

| File | Reason |
| --- | --- |
| `.github/workflows/ci.yml` | Epic 3 push trigger. |
| `AGENTS.md` | Current review authorization and Git restrictions. |
| `apps/api/README.md` | Definition lifecycle, API, trust boundary, seeds and fixture procedure. |
| `apps/api/commodities/admin.py` | Read-only lifecycle status; domain functions handle transitions. |
| `apps/api/commodities/models.py` | Fresh-state guards, transaction locks, stable codes, transition and cascade/queryset deletion protection. |
| `apps/api/commodities/services.py` | Current-state lifecycle/clone operations, publication metadata checks, stable structured errors and finite numbers. |
| `apps/api/commodities/serializers.py` | Backend-authoritative nested metadata contract. |
| `apps/api/commodities/views.py` | Active ownership guard and documented error responses. |
| `apps/api/commodities/tests.py` | Unconditional validator test discovery. |
| `apps/api/commodities/test_review_gate.py` (new) | Integrity/constraint/rollback/concurrency/negative-path regressions. |
| `apps/api/commodities/test_contract_fixtures.py` (new) | PostgreSQL seed/validator/API-to-frontend fixture verification. |
| `apps/api/pyproject.toml` | Include commodities in built packages. |
| `apps/web/README.md` | Generic renderer semantics and CI test commands. |
| `apps/web/src/components/commodity/commodity-specification-form.tsx` | Correct generated metadata, integer values, RTL, error accessibility, grouping and IDs. |
| `apps/web/src/components/commodity/commodity-specification-view.tsx` | Correct localized enum metadata, shared text and safe grouping. |
| `apps/web/src/i18n/commodity-messages.ts` (new) | Localized generic renderer text/group headings. |
| `apps/web/src/lib/api/generated/schema.d.ts` | Regenerated metadata/error contract. |
| `apps/web/tests/components/commodity-specification-form.test.tsx` | Actual metadata names and decimal-preservation expectation. |
| `apps/web/tests/components/commodity-specification-view.test.tsx` | Actual generated metadata fixtures. |
| `apps/web/tests/components/commodity-api-integration.test.tsx` (new) | Both real commodity schemas, historical labels, accessibility and arbitrary-group tests. |
| `apps/web/tests/fixtures/commodity-schemas.json` (new) | Generated normalized API examples; checked by backend CI. |
| `docs/delivery/roadmap.md` | Superseded authorization paragraph; acceptance criteria unchanged. |
| `docs/delivery/epic-03-review-gate.md` (new) | This evidence/report. |
| `schema.yml` (deleted) | Remove redundant, noncanonical generated snapshot. |

No migration, dependency lockfile, Product Specification or seed definition was changed. The large apparent test diff is principally removing indentation around conditional discovery. No real `.env`, bytecode, database, node_modules, virtual environment or temporary browser fixture is tracked. Targeted token/private-key-pattern and artifact-name scans found no added secrets/generated junk; this is not a comprehensive secret-history audit. Final `git diff --check` passed.

## U. Remaining Risks

### Actual merge risks

The original HEAD contains reproduced defects. Include and review all listed fixes and generated/test fixtures; commit/push only with owner authorization. Hosted CI must pass on that resulting revision. Hosted checks could not be independently read due to GitHub rate limiting. No known unresolved blocking Epic 3 code defect remains within the documented supported-operation boundary.

### Acceptable future/deployment work

Privileged database maintenance must honor semantic immutability; no DBA-proof triggers were promised. Future real business records must retain their original schema version and validate server-side. Production ingress/TLS/domain configuration and eventual Hero Flow/browser tests remain their respective delivery work. Draft metadata can be incomplete while editing; publication validates the supported structural/validation metadata. Package/operational checks were local review checks. Canonical pip CI does not consume the added uv lock; transitive version resolution remains an existing deployment consideration. Missing Epic 4 functionality is not an Epic 3 defect.

## V. Architecture Assessment

Conforms with the fixes: Django modular monolith, PostgreSQL source of truth, relational versioned definitions, derived JSON Schema, immutable Published semantics within guarded paths, explicit historical schema-version integrity, backend-authoritative validation and OpenAPI, commodity-agnostic backend/frontend, Persian RTL and no premature infrastructure. Metadata serializers describe the wire representation; relational definitions still determine individual commodity semantics. No product redesign or low-code platform was introduced.

## W. Merge Recommendation

`codex/epic-03-dynamic-commodity-model` is safe to merge into `master` **only after all listed uncommitted review fixes are reviewed, authorized, committed, pushed, and CI passes on the resulting revision**. Do not merge the unchanged original HEAD. No commit, push or merge was performed, and Epic 4 was not begun.
