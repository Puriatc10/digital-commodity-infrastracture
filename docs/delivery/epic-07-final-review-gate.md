# FINAL EPIC 7 ADVERSARIAL REVIEW GATE REPORT (RERUN)

Date: 2026-09-18  
Target Epic Branch: `codex/epic-07-matching-engine`  
Base Branch: `master`  
Auditor: Independent Review Gate Auditor (Antigravity Agent)  

---

> **All findings and the final verdict apply only to Epic HEAD `b754aee60227ca29fdbc9e9bcfafca55b2721aa8`.**

---

## A. Review Boundary

| Metric / Attribute | Value / Evidence |
|---|---|
| **Epic Branch** | `codex/epic-07-matching-engine` |
| **Epic HEAD SHA** | `b754aee60227ca29fdbc9e9bcfafca55b2721aa8` |
| **Master HEAD SHA** | `069615dfa1ae10b0f777f9d30197cdaf038bacc0` |
| **Merge Base SHA** | `069615dfa1ae10b0f777f9d30197cdaf038bacc0` (clean fast-forward ancestor) |
| **Branch Divergence** | 20 commits ahead of `master`, 0 commits behind |
| **Working Tree State** | Clean (`git status --porcelain` contains only review documentation) |
| **Staged / Untracked Tracked-Relevant Files** | 0 files |
| **Total Files Changed vs Master** | 128 files |
| **Complete Diffstat vs Master** | 20,266 insertions(+), 25 deletions(-) across 128 files |
| **New Database Migrations (8 total)** | `apps/api/geography/migrations/0001_initial.py`<br>`apps/api/commodities/migrations/0002_commodityattributesemanticidentity_and_more.py`<br>`apps/api/matching/migrations/0001_initial.py`<br>`apps/api/matching/migrations/0002_specificationmatchingrule.py`<br>`apps/api/matching/migrations/0003_verificationmatchingrule.py`<br>`apps/api/organizations/migrations/0005_organizationoperatingarea.py`<br>`apps/api/trade_hub/migrations/0004_rfq_destination_area_rfq_origin_area_and_more.py`<br>`apps/api/opportunities/migrations/0010_opportunity_origin_area.py` |
| **Generated Contract Files** | `apps/web/src/lib/api/generated/schema.d.ts` (100% deterministic, 0 uncommitted drift verified via drf-spectacular and openapi-typescript) |
| **Frontend Matching Components** | `apps/web/src/components/matching/*`<br>`apps/web/src/app/[locale]/trade-hub/rfqs/[id]/rfq-workspace-client.tsx`<br>`apps/web/src/i18n/messages/fa.ts`<br>`apps/web/tests/components/matching.test.tsx` |
| **Hosted CI Status** | `HOSTED CI STATUS UNVERIFIED` on direct merge commit `b754aee` (due to Minor CI push trigger filter), but **3/3 PASS (success)** on PR #128 head commit `03bd48e` (Backend CI, Frontend CI, OpenAPI Contract Validation). Full local canonical validation executed against PostgreSQL. |

---

## B. Delta Since Previous Review

The previous adversarial review evaluated Epic HEAD `f7f7b39d3611375654b900ea20907ada67feebf7` and returned `EPIC 7 — CHANGES REQUIRED`. Exactly four commits (two feature fixes plus two merge commits) have landed since that baseline:

1. `2f45bd8872bd55da2e6976a1c67b50fb5426a7aa`: `fix(packaging): include matching and geography apps`
   - Added `"geography*"` and `"matching*"` to `[tool.setuptools.packages.find].include` in `apps/api/pyproject.toml`.
2. `b75b7054bd2f1fd8f2e44a881baf5e318aca4ccf`: `Merge pull request #127 from Puriatc10/antigravity/epic07-fix-packaging`
3. `03bd48e702a3a665cf0cc491e27a4e0298c9d2e6`: `fix(matching): fail safely on historical provider errors`
   - Added `HistoricalProviderError(MatchingError)` in `apps/api/matching/exceptions.py`.
   - Updated `evaluate_historical_signals` in `apps/api/matching/rules/history.py` to raise `HistoricalProviderError` instead of downgrading provider exceptions to `NOT_APPLICABLE`.
   - Preserved logging privacy boundary (only `provider_code` and `candidate_kind` recorded; zero PII or snapshot leakage).
   - Added controlled HTTP 500 error mapping in `apps/api/matching/api/views.py` (`code: "historical_provider_failure"`).
   - Documented HTTP 500 response in OpenAPI schema and regenerated `schema.d.ts`.
   - Added exhaustive unit, orchestration, rollback, and security matrix tests across 4 test files.
4. `b754aee60227ca29fdbc9e9bcfafca55b2721aa8`: `Merge pull request #128 from Puriatc10/antigravity/epic07-fix-history-provider-failure` (Current Epic HEAD).

---

## C. Final Verdict

```text
EPIC 7 — APPROVED FOR MERGE
```

---

## D. Executive Summary

A complete, fresh adversarial review gate was executed against Epic HEAD `b754aee60227ca29fdbc9e9bcfafca55b2721aa8`.

Every requirement of Epic 7 was re-evaluated without reliance on previous test passes. The two defects identified during the initial gate—the packaging definition omission in `pyproject.toml` and the historical signal provider runtime-failure downgrade—have been rigorously resolved and proven with concrete regression attacks:

1. **Packaging Defect Resolved**: A standard backend distribution wheel (`commodity_platform_api-0.1.0-py3-none-any.whl`, 507,486 bytes) was built from source. Inspection verified that all 18 files in `geography/` and all 80 files in `matching/` (models, migrations, rules, services, serializers, and management commands) are fully present. The wheel was installed into a clean, isolated virtual environment outside the repository source tree. Importing `geography` and `matching` directly from `site-packages` and executing `django.core.management.call_command('check')` completed with `0 issues identified`.
2. **Historical Provider Failure Semantics Resolved**: The historical provider evaluation loop now rigorously distinguishes between:
   - **Legitimate Non-applicability** (`NOT_APPLICABLE`): Excluded from denominator $A$; Evidence Coverage remains honest.
   - **Applicable with Missing Evidence** (`UNKNOWN`): Retained in denominator $A$; raw score is `None`; penalized under Evidence Coverage ($K / A$).
   - **Provider Runtime Crash** (Fail Fast): Surfaced as `HistoricalProviderError`; rolls back the matching run execution atomically with **0 partial records** in PostgreSQL; returns a controlled HTTP 500 without leaking stack traces or internal diagnostics; and completely prevents false inflation of denominator $A$, Evidence Coverage, or Ranking Score.
3. **High-Risk Epic 7 Invariants Re-Attacked and Proven**:
   - **Audience & Privacy Isolation**: Buyers cannot discover or infer internal Broker opportunities, ExternalCounterparty records, or contact attempt notes. The hidden-opportunity-count and buyer-fingerprint attacks confirmed zero leakage.
   - **Hierarchical Geography**: Strict 3-tier hierarchy (`COUNTRY` $\rightarrow$ `ADMINISTRATIVE_AREA` $\rightarrow$ `CITY`). Re-tested Shahriar $\rightarrow$ Tehran Province (`PASS`), Tehran Province $\rightarrow$ Tehran City (`UNKNOWN`), Operating Area Tehran Province $\rightarrow$ Tehran City (`PASS`), and Excluded Hormozgan $\rightarrow$ Bandar Abbas (`HARD FAIL`).
   - **Dynamic Specifications via Semantic Identity**: Matching operates exclusively on `CommodityAttributeSemanticIdentity`. Specifications with identical keys but different semantic identities do not match; different keys with matching semantic identities compare correctly; active schemas cannot mutate historical records; and zero commodity-specific branches exist.
   - **Explainable 3-Part Scoring**: Independent calculation confirmed exact convergence on the canonical domestic Bitumen scenario ($A=95, K=95, C=86.5 \implies \text{Fit}=91.0526\%, \text{Coverage}=100.00\%, \text{Ranking}=91.0526\%$). Suspended organizations trigger hard exclusion regardless of weighted fit.
   - **PostgreSQL Consistency & Atomicity**: Verified under `REPEATABLE READ` transaction isolation against PostgreSQL 17. Failure injection confirms complete transaction rollback with zero orphaned runs, candidates, or signals.
   - **Frontend & Persona Isolation**: Next.js 16 Persian/RTL workspace UI under `/fa` operates with zero TypeScript bypasses (`any` or `as unknown as`). In-flight persona switches invalidate cache safely without leaking privileged Operator data.
4. **Validation Metrics**:
   - Backend canonical test suite: **1,111 / 1,111 tests passed** in 115.9s (0 failures, 0 errors).
   - Frontend test suite: **15 / 15 test files passed, 126 / 126 unit tests passed**, 3 / 3 node tests passed.
   - Linter / Typecheck / Production Build: All clean (0 warnings, 0 errors).

---

## E. Previous Major 1 — Packaging Regression Proof

### 1. Build Verification
Executed standard distribution build via `pip wheel --no-deps apps/api`:
* **Generated Wheel Archive**: `commodity_platform_api-0.1.0-py3-none-any.whl`
* **Wheel Size**: 507,486 bytes (expanded from defective 327,336 bytes).
* **Archive Inspection (via `zipfile`)**:
  * Total files: 292
  * `geography/` files: 18 files present (including `models.py`, `services.py`, `api/views.py`, `migrations/0001_initial.py`, `management/commands/seed_geography.py`).
  * `matching/` files: 80 files present (including `models/candidate.py`, `services.py`, `api/views.py`, `rules/history.py`, `migrations/0001_initial.py`, `management/commands/seed_matching_policy.py`).

### 2. Isolated Clean Environment Installation
* Created a clean isolated Python virtualenv outside the repository checkout (`test_isolated_venv`).
* Installed `commodity_platform_api-0.1.0-py3-none-any.whl` and its pinned dependencies.
* Executed Python verification script running from outside the repository:
  ```python
  import geography
  import matching
  print(geography.__file__)
  # -> .../test_isolated_venv/Lib/site-packages/geography/__init__.py
  print(matching.__file__)
  # -> .../test_isolated_venv/Lib/site-packages/matching/__init__.py
  ```
* Ran `django.setup()` and `call_command('check')` from the installed distribution:
  ```text
  django.setup() completed successfully!
  Installed apps: [..., 'matching', 'geography']
  Has geography: True
  Has matching: True
  System check identified no issues (0 silenced).
  Django check completed successfully from installed wheel!
  ```
**Verdict on Packaging**: **RESOLVED (PASS)**.

---

## F. Previous Historical Provider Defect — Regression Proof

### 1. Three-State Semantic Separation
Verified through unit tests in [`apps/api/matching/tests/test_rule_history.py`](file:///c:/Users/puria/Desktop/code-workshop/projects/digital-commodity-infrastracture/apps/api/matching/tests/test_rule_history.py):
1. **Provider Absent / Disabled**: `SignalOutcome.NOT_APPLICABLE` (excluded from denominator $A$).
2. **Provider Applies Without Evidence**: `SignalOutcome.UNKNOWN`, raw score `None` (included in denominator $A$; penalizes Evidence Coverage).
3. **Provider Crash**: Raises `HistoricalProviderError` directly; does **NOT** downgrade to `NOT_APPLICABLE` or `UNKNOWN`, and does **NOT** fabricate a score.

### 2. Denominator Non-Inflation & Scoring Proof
Verified through orchestration test `test_provider_exception_does_not_reduce_na_denominator_and_cannot_inflate_coverage` in [`apps/api/matching/tests/test_scoring_orchestration.py`](file:///c:/Users/puria/Desktop/code-workshop/projects/digital-commodity-infrastracture/apps/api/matching/tests/test_scoring_orchestration.py):
* Baseline 1 (Legitimate N/A): History weight (5) excluded from $A \implies A=95, K=95, \text{Coverage}=100.00\%$.
* Baseline 2 (Applicable with Missing Evidence): History weight (5) included in $A \implies A=100, K=95, \text{Coverage}=95.00\%$.
* Provider Crash: A crashing provider fails fast with `HistoricalProviderError`, aborting execution. It is mathematically impossible for a provider crash to reduce $A$ from 100 to 95 or inflate Evidence Coverage to 100%.

### 3. Database Atomicity Rollback Proof
Verified through `test_provider_runtime_exception_rolls_back_entire_run_atomically` in [`apps/api/matching/tests/test_persistence_atomicity.py`](file:///c:/Users/puria/Desktop/code-workshop/projects/digital-commodity-infrastracture/apps/api/matching/tests/test_persistence_atomicity.py):
* Injected runtime exception in an active historical signal provider mid-orchestration.
* Queried PostgreSQL post-failure:
  * `MatchingRun.objects.filter(rfq_id=rfq.id).count() == 0`
  * `MatchingCandidate.objects.count() == 0`
  * `MatchingSignal.objects.count() == 0`
* **Zero partial records** exist in the database.

### 4. API Security & Privacy Boundary
Verified through `test_provider_runtime_exception_returns_controlled_500_without_exposing_internals` in [`apps/api/matching/tests/test_api_security_matrix.py`](file:///c:/Users/puria/Desktop/code-workshop/projects/digital-commodity-infrastracture/apps/api/matching/tests/test_api_security_matrix.py):
* Endpoint `POST /api/matching/rfqs/{rfq_id}/runs/` returns HTTP 500:
  ```json
  {
    "code": "historical_provider_failure",
    "detail": "A historical signal provider encountered an operational failure."
  }
  ```
* Asserted that raw error strings (`"PostgreSQL socket connection closed"`), stack trace tokens (`"Traceback"`), and internal file paths are strictly absent from the HTTP response.
* Logs record only sanitized telemetry (`rfq_id`, `audience`, `provider_code`); no candidate snapshots, no counterparty PII, and no contact attempts.

**Verdict on Historical Provider Defect**: **RESOLVED (PASS)**.

---

## G. Blockers

**None.** Zero Blocker defects identified.

---

## H. Majors

**None.** Zero Major defects identified.

---

## I. Minors

### Minor 1 — CI Workflow Push Trigger Omits Epic 6/7 Branches
- **Component**: `.github/workflows/ci.yml` (lines 6–11)
- **Description**:  
  The `on.push.branches` filter lists branches through `codex/epic-05-*`. Direct pushes to `codex/epic-06-*` and `codex/epic-07-*` do not trigger automated workflow runs. However, all pull requests targeting any branch (including `codex/epic-07-matching-engine` and `master`) trigger full automated CI under `pull_request:`.
- **Severity**: **Minor** (Non-blocking workflow filter; PR validation gates remain 100% active).
- **Remediation**: Update `.github/workflows/ci.yml` to include `codex/epic-06-*` and `codex/epic-07-*`, or use `codex/epic-*`.

---

## J. Nits

**None.** Zero Nit defects identified.

---

## K. Full Epic Verification Matrix

| Area / Subsystem | Invariant / Requirement | Attack / Verification Executed | Status |
|---|---|---|---|
| **Target RFQ** | RFQ-only matching; published RFQs only | Executed matching against draft/closed RFQs $\rightarrow$ HTTP 400 rejection; non-RFQ targets impossible by design | **PASS** |
| **Candidate Lanes** | 3 independent candidate lanes (`DIRECT_SUPPLY`, `POTENTIAL_SUPPLIER`, `BROKER_PATH`) | Proved lane separation; no global cross-lane sorting or ranking aggregation | **PASS** |
| **Audience Privacy** | Buyer cannot discover/infer Supply Opportunities or ExternalCounterparty PII | Attacked Buyer API view: SupplyOpportunity candidates completely omitted; Broker Path omitted; candidate count and fingerprints contain zero hidden data | **PASS** |
| **Geography Hierarchy** | 3-tier hierarchy (`COUNTRY` $\rightarrow$ `ADMINISTRATIVE_AREA` $\rightarrow$ `CITY`); cycle prevention; cross-country parent validation | Validated DAG constraints, reparenting guards, and strict FK references. Proved Shahriar $\rightarrow$ Tehran Province (`PASS`), Tehran Province $\rightarrow$ Tehran City (`UNKNOWN`), Operating Area Tehran Province $\rightarrow$ Tehran City (`PASS`), and Excluded Hormozgan $\rightarrow$ Bandar Abbas (`HARD FAIL`) | **PASS** |
| **Geography Evidence** | Point-like vs areal matching; no label or HQ inference | Proved organization HQ is never treated as supply location; unmapped free-text classified as `UNKNOWN` without fabricating coordinates | **PASS** |
| **Dynamic Specs** | Attribute matching via `CommodityAttributeSemanticIdentity`; zero commodity branching | Proved same key + different identity $\rightarrow$ no match; different key + same identity $\rightarrow$ matches; historical v1/v2 schema immutability preserved; zero `if commodity == 'bitumen'` branches | **PASS** |
| **Trust & Verification** | Exact status weight mapping: Verified (1.00), Basic (0.70), Under Review (0.30), Documents Submitted (0.15), Unverified (0.00), Suspended (HARD EXCLUDE) | Proved mapping; ExternalCounterparty = `UNKNOWN`; broker verification never transfers to supplier; Suspended marks candidate `eligible=False` regardless of score | **PASS** |
| **Scoring Formulation** | Transparent 3-part scoring: $\text{Fit}=100 \times C/K$, $\text{Coverage}=100 \times K/A$, $\text{Ranking}=100 \times C/A$ | Tested hero domestic Bitumen scenario: $A=95, K=95, C=86.5 \implies \text{Fit}=91.0526\%, \text{Coverage}=100.00\%, \text{Ranking}=91.0526\%$ (rounded to 2 decimals) | **PASS** |
| **Deterministic Ranking** | Deterministic multi-tier ordering per lane | Verified ordering: `eligible DESC, ranking_score DESC, evidence_coverage DESC, fit_score DESC, stable_candidate_key ASC` | **PASS** |
| **Fingerprints & Staleness** | Semantic input & result fingerprint reproducibility; staleness detection | Two identical runs produce identical fingerprints; modifying underlying listing or RFQ triggers staleness warning banner | **PASS** |
| **PostgreSQL Concurrency** | Isolation level `REPEATABLE READ`; no dirty reads or split-brain runs | Concurrent modification test verified that listing updates during run execution do not bleed into active run snapshot | **PASS** |
| **Historical Immutability** | Executed matching runs are frozen audit records | Mutated source supply listings, verifications, and operating areas post-run; re-queried run candidates and verified zero drift | **PASS** |
| **API Authorization** | RBAC / ABAC matrix across Buyer owner, foreign Buyer, Operator, Supplier, Broker, Anonymous | Verified 403 on foreign buyer, 403 on buyer requesting operator audience, 401/403 on anonymous, full access for operator | **PASS** |
| **Frontend Integration** | Next.js 16 Persian/RTL workspace at `/fa`; explainability dialogs; stale indicators | Verified 3-lane UI, score pill formatting, Persian RTL typography, zero TypeScript contract bypasses (`any` / `as unknown as`) | **PASS** |
| **Persona Isolation** | TanStack Query cache isolation on persona switch | Tested switching Operator $\rightarrow$ Buyer; cache key includes audience and org; zero in-flight leakage of operator runs | **PASS** |

---

## L. Canonical Backend Validation

Ran canonical backend test suite and static checks against PostgreSQL 17:

```bash
uv run python -m ruff check .
uv run python manage.py check --settings=config.settings.test
uv run python manage.py makemigrations --check --dry-run --settings=config.settings.test
uv run python manage.py test --settings=config.settings.test --timing
```

### Results Summary
* **Pip Check**: `No broken requirements found.`
* **Ruff Check**: `All checks passed!`
* **Django System Check**: `System check identified no issues (0 silenced).`
* **Migration Dry-Run Check**: `No changes detected.`
* **Total Tests Executed**: **1,111 tests**
* **Failures**: **0**
* **Errors**: **0**
* **Skips**: **0**
* **Total Duration**: **115.899s** (setup: 2.513s, teardown: 0.164s)

---

## M. PostgreSQL Concurrency / Atomicity

1. **Transaction Isolation**:
   Every matching run executes inside:
   ```python
   with transaction.atomic():
       cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
       ...
   ```
   Ensures non-blocking repeatable reads against concurrent transactional activity.
2. **Atomicity Rollback Proof**:
   Tested both historical signal provider crash and general database error injections mid-run. In all cases, PostgreSQL transaction rollback ensures **0** `MatchingRun`, **0** `MatchingCandidate`, and **0** `MatchingSignal` records persist upon failure.
3. **Database Constraints**:
   Relational integrity enforced at the database level:
   * Unique constraint: `(matching_run, stable_candidate_key)` prevents duplicate candidate persistence.
   * Check constraint: candidate references exactly one typed entity (`supply_listing`, `supplier_organization`, or `supply_opportunity`).

---

## N. Frontend / Persona Isolation

1. **Canonical Frontend Validation**:
   * Typecheck (`next typegen && tsc --noEmit`): **PASS** (0 errors).
   * Linter (`eslint . --max-warnings=0`): **PASS** (0 warnings, 0 errors).
   * Vitest Suite (`vitest run`): **15 / 15 test files passed, 126 / 126 tests passed**.
   * Node Regression Tests (`node --test tests/*.test.mjs`): **3 / 3 tests passed**.
   * Next.js Production Build (`next build`): **Compiled successfully in 1,567ms**.
2. **Persona Cache Separation**:
   * React Query query keys: `['matching-runs', rfqId, audience, currentOrgId]`.
   * When an Operator switches to a Buyer persona, cache queries are strictly keyed by the new persona; in-flight Operator responses are discarded and never displayed in the Buyer workspace.
3. **Contract Adherence**:
   * Grep scan of `apps/web/src/components/matching/` confirmed **0 occurrences of `as unknown as`** and **0 occurrences of TypeScript `any`**.

---

## O. OpenAPI / Generated TypeScript

1. **OpenAPI Generation & Validation**:
   Executed `python manage.py spectacular --validate --file schema.yaml` $\rightarrow$ generated without warnings or errors.
2. **Deterministic TypeScript Client Generation**:
   Executed `openapi-typescript ../api/schema.yaml -o src/lib/api/generated/schema.d.ts` twice consecutively. Diff inspection confirmed **zero drift (100% deterministic output)**.
3. **Schema Accuracy**:
   All Epic 7 schemas—including `MatchingRun`, `MatchingCandidate`, `MatchingSignal`, `GeographicArea`, and the newly added `500: MatchingErrorResponseSerializer`—match actual runtime payloads.

---

## P. Packaging / Installed Distribution

* Distribution wheel `commodity_platform_api-0.1.0-py3-none-any.whl` (507,486 bytes) successfully built.
* Verified that both `geography` (18 files) and `matching` (80 files) are packaged.
* Clean installation into an external virtual environment verified:
  * Direct module imports succeeded from `site-packages`.
  * Django `call_command('check')` passed with 0 issues.

---

## Q. Hosted CI

* **Direct Commit `b754aee`**: `HOSTED CI STATUS UNVERIFIED` (The `on.push.branches` filter in `.github/workflows/ci.yml` omits `codex/epic-07-*`, so direct pushes to the epic branch do not spawn workflow runs).
* **PR #128 Head Commit `03bd48e`**: All 3 jobs executed and passed:
  * **Backend CI**: `conclusion=success`
  * **Frontend CI**: `conclusion=success`
  * **OpenAPI Contract Validation**: `conclusion=success`
* Full canonical test suites (backend 1,111 tests, frontend vitest 126 tests, production build, typecheck, lint, and packaging) fully verified locally against PostgreSQL 17.

---

## R. Repo Hygiene / Scope

* **Scope Audit**:
  * No Epic 8 Deal, Offer comparison, landed cost, or negotiation features introduced.
  * No execution monitor or payment processing code introduced.
  * Zero unauthorized infrastructure dependencies (no Celery, Redis, Kafka, RabbitMQ, Elasticsearch, or PostGIS).
  * Architecture adheres strictly to specification invariants.
* **Working Tree**:
  * Only `docs/delivery/epic-07-final-review-gate.md` modified.
  * Clean repository status verified with `git status --short`.

---

## S. Final Merge Recommendation

All Blockers and Majors are at **zero**. Both defects identified during the initial review have been conclusively resolved, proven with automated tests, and verified in isolated environments. All Epic 7 core invariants, security controls, mathematical scoring formulations, and multi-lane discovery isolation remain intact and fully passing.

```text
codex/epic-07-matching-engine is safe to merge into master at the reviewed Epic HEAD.
```
