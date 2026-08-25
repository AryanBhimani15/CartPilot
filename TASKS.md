# CartPilot AI — Work Queue

Legend: `[ ]` pending · `[-]` in progress · `[x]` done · `[!]` blocked
Owner: **CODEX** unless marked otherwise. Claude = tech lead / reviewer.

Rules for Codex:
1. Read `ARCHITECTURE.md` and `DECISIONS.md` before starting a task.
2. Do the tasks **in order**. They are dependency-sequenced.
3. Do not add features that aren't in a task. Extra scope is rejected in review.
4. Flip the checkbox and add a one-line note when done. If blocked, use `[!]` + why.
5. Every task's acceptance criteria must be *demonstrably* true, not "should work".

---

## PHASE 1 — FOUNDATION  ◄ current

### `[x]` T-001 — Repo scaffold, config, one-command dev
**Objective.** `git clone && make setup && make dev` brings up API + web with zero manual steps.

**Files.** `Makefile`, `.env.example`, `.gitignore`, `README.md` (stub),
`api/pyproject.toml`, `api/app/{main.py,config.py}`, `web/` (Next.js 15, TS, Tailwind, shadcn init).

**Details.**
- `api`: FastAPI + uvicorn, SQLAlchemy 2.0 (async, `asyncpg`), Alembic, pydantic-settings, pytest.
- `config.py` uses `pydantic-settings`; required secrets have **no defaults** — a missing
  `RAZORPAY_KEY_SECRET` must crash at startup with a clear message (D-003 / §12).
- `.env.example` documents every var with an obviously-fake value. Never commit a real key.
- CORS locked to `http://localhost:3000` in dev, driven by config.
- `Makefile` targets: `setup db seed dev dev-api dev-web test types eval lint`.
- `make types` regenerates `web/types/api.ts` from `/openapi.json`.

**Acceptance.**
- `make setup` succeeds on a clean machine with Postgres 14 running and no Docker.
- `GET /api/v1/health` returns `{"status":"ok","db":"ok"}` with a real DB round-trip.
- `web` renders a placeholder `/shop` and `/dashboard` with no console errors.
- Removing a required env var makes the API fail to start with a named error.

Completed 2026-08-25 — `make setup`, API health with a real Postgres round-trip, and both placeholder routes verified locally; config validation is covered by pytest.

---

### `[x]` T-002 — Database schema + migrations
**Objective.** The full data model from `ARCHITECTURE.md` §4, as typed SQLAlchemy 2.0 models
and one Alembic migration.

**Files.** `api/app/db/models.py`, `api/app/db/session.py`, `api/alembic/versions/0001_*.py`,
`api/app/domain/{money.py,enums.py,errors.py}`.

**Details.**
- All money columns `BigInteger`, named `*_paise` (D-002). No `Float`, no `Numeric`, anywhere.
- `is_demo BOOLEAN NOT NULL DEFAULT false` on every fact table (D-010).
- Indexes: `products(merchant_id, category)`, `products(price_paise)`,
  `product_variants(product_id, size)`, `session_events(session_id, created_at)`,
  **unique** `payments(razorpay_payment_id)` (idempotency, D-009),
  GIN on `products.search_tsv` and on `products.attrs`.
- `agent_steps` captures: session_id, step_no, tool_name, args JSONB, result JSONB,
  policy_rule_id, policy_decision, latency_ms, input/output tokens, error_code.
- Enums live in `domain/enums.py` and map to native PG enums.
- No Postgres 15+ syntax, no extensions (D-003).

**Acceptance.**
- `alembic upgrade head` then `alembic downgrade base` runs clean, twice in a row.
- `mypy --strict api/app/db api/app/domain` passes.
- A unit test asserts no column in the metadata is `Float`/`Numeric`.

Completed 2026-08-25 — full typed core schema and native PostgreSQL enums landed in `0001`; upgrade/downgrade cycles, strict mypy, and money-type assertions pass.

---

### `[x]` T-003 — Synthetic merchant catalog (demo-load-bearing)
**Objective.** A realistic Indian D2C sportswear catalog that makes the scripted demo work and
gives the eval something honest to measure.

**Files.** `api/app/db/seed/catalog.py`, `api/app/db/seed/data/products.json`,
`api/app/db/seed/offers.py`, `Makefile:seed`.

**Details.**
- ~180–220 SKUs across: running shoes, training shoes, socks, insoles, apparel, recovery
  (foam rollers), hydration, GPS watches. Invented but plausible brand names — do **not** use
  real trademarks (Nike/Adidas/Asics) in seed data.
- Each product: `title, brand, category, subcategory, price_paise, description`, and `attrs`
  JSONB with `use_case` (`daily_easy_runs`/`speed`/`trail`/`gym`), `arch_support`
  (`neutral`/`stability`/`motion_control`), `cushioning`, `drop_mm`, `weight_g`,
  `terrain`, `gender`, `rating`, `review_count`.
- Variants: UK 6–12 with **realistic uneven stock**, including deliberate out-of-stocks —
  the `STOCK_AVAILABLE` policy needs something real to catch.
- **The demo path must be satisfiable and non-trivial.** For "running shoes under ₹5,000,
  daily 5 km, flat feet" there must be:
  - ≥3 genuinely good `stability` shoes in ₹3,200–4,999 with stock,
  - ≥1 excellent `stability` shoe at ~₹6,500 (proves `BUDGET_CEILING` actually bites),
  - ≥2 tempting-but-wrong `neutral` shoes under ₹5,000 (proves ranking isn't just price sort),
  - credible cross-sells: anti-blister socks ₹499, orthotic insoles ₹899, foam roller ₹1,299.
- Offers: 2–3 real rows (e.g. `RUNSTRONG10` 10% over ₹4,000 cap ₹600; a socks bundle).
  These are the **only** discounts that may ever exist (D-007).
- Seed is idempotent and deterministic (fixed seed, stable ids) — re-running never duplicates.

**Acceptance.**
- `make seed` twice ⇒ identical row counts and identical ids.
- A test asserts each demo-path guarantee above holds against the seeded DB.
- No real-world trademark appears in `products.json`.

Initial completion 2026-08-25 — the original acceptance block passed. Catalog depth, test isolation,
and category-aware seed corrections are completed in T-003a/b/c below.

Reviewed 2026-08-25 (Claude) — acceptance block satisfied as written. Three gaps found that the
acceptance criteria failed to encode; split into T-003a/b/c below. Claude directly fixed the
demo-breaking stock bug (see PROJECT_STATUS.md).

---

---

### `[x]` T-003a — Isolate the test database
**Objective.** `make test` must not read or write the development database.

**Files.** `api/tests/conftest.py`, `Makefile`, `.env.example`, `api/app/config.py`.

**Problem found in review.** `test: db` runs pytest against `DATABASE_URL`, and
`test_seed_catalog` calls `seed_catalog()` — so running the suite rewrites dev data. Verified:
after a test run the dev `cartpilot` database held all 217 seeded variants. Every future task
adds DB tests, so this compounds until the suite is untrustworthy.

**Details.**
- Add `TEST_DATABASE_URL` (required when `APP_ENV=test`), default `..._test`.
- `conftest.py`: session-scoped fixture that creates the test DB if absent, runs
  `alembic upgrade head`, and **refuses to run if the resolved URL equals `DATABASE_URL`**.
- Per-test isolation via a transaction rolled back after each test, so tests don't leak into
  each other. Seed tests that need committed data get an explicit opt-in fixture.

**Acceptance.**
- `make test` leaves the dev database byte-identical (verify row counts + `max(updated_at)`).
- A test asserting `TEST_DATABASE_URL != DATABASE_URL` fails the run when they match.
- The suite passes twice consecutively from a clean and from a seeded dev DB.

Completed 2026-08-25 — `make test` creates and migrates `cartpilot_test`, rejects equal URLs, snapshots the dev DB before/after the suite, and rolls back each database-writing test.

---

### `[x]` T-003b — Category-aware variant axes and attribute schema
**Objective.** Stop modelling every product as a shoe.

**Files.** `api/app/db/seed/catalog.py`, `api/app/db/seed/data/products.json`,
`api/app/domain/enums.py`, `api/app/db/models.py`, `api/tests/test_seed_catalog.py`.

**Problem found in review.** `SIZES = UK 6…UK 12` is applied to **every** product, so the seed
contains a foam roller in UK 9, a GPS watch in UK 11, and hydration flasks in seven shoe sizes
(31 × 7 = the reported 217 "variants"). Every variant is also `colour="Graphite"`. Separately,
`attrs` forces shoe-only fields onto everything: a GPS watch carries
`arch_support: "neutral"`, `cushioning: "low"`, `drop_mm: 0`, `terrain: "road"`.

This breaks three things downstream: `check_inventory` and the cart UI ask for a UK size on a
foam roller; the T-003 upsell (`RIV-SOCK-AB`) forces a shoe-size choice on socks; and
`product_document()` — which feeds both `search_tsv` and the T-004 embeddings — injects
`"neutral road"` into the text of every watch, roller and flask, adding pure noise to retrieval.

**Details.**
- Variant axis per category: `running_shoes`/`training_shoes` → UK 6–12;
  `socks`/`apparel` → S/M/L/XL; `insoles` → S/M/L; `recovery`/`hydration`/`gps_watches` →
  a single `One Size` variant. Colours should vary per category, not be a constant.
- Split `attrs` into a shared block (`use_case`, `gender`, `rating`, `review_count`) and a
  category-specific block (`footwear: {arch_support, cushioning, drop_mm, terrain, weight_g}`).
  Filters must key off the category-specific block only.
- `product_document()` becomes category-aware: compose only the fields that exist for that
  category. This is the input to T-004 embeddings — get it right before anything is embedded.

**Acceptance.**
- No non-footwear product has a `UK *` variant; a test asserts this per category.
- `product_document("KORA-GPS-ONE")` contains no footwear vocabulary
  (`arch_support`, `terrain`, `drop`, `cushioning`).
- Demo-path stock guarantees and `DELIBERATE_OUT_OF_STOCK` still hold after the axis change.
- Adding `RIV-SOCK-AB` to a cart requires a sock size, not a shoe size.

Completed 2026-08-25 — variants now use footwear/apparel/one-size axes with varied category colours; `attrs.footwear` and category-aware documents prevent non-footwear retrieval pollution.

---

### `[x]` T-003c — Expand the catalog to ~150 SKUs
**Objective.** Give retrieval and the evaluation something real to discriminate between.

**Files.** `api/app/db/seed/data/products.json`, `api/tests/test_seed_catalog.py`.

**Problem found in review.** T-003 specified ~180–220 SKUs; the seed ships **31**. The
acceptance block only checked the demo-path guarantees, so this passed review mechanically —
a spec bug on Claude's side, now corrected here. At 31 SKUs only ~12 are running shoes, so
hybrid search has almost nothing to rank, precision@k in T-012 is measured over a candidate
set too small to be meaningful, and "unmet demand" analytics in T-010 has no tail to find.

**Details.**
- Target ~150 SKUs. Depth matters more than breadth: ~55 running shoes spanning
  neutral/stability/motion-control × road/trail × ₹2,500–12,000, so budget and arch filters
  each have real competition to resolve.
- Include genuine near-misses: right arch support but over budget, right price but wrong
  use case, right everything but out of stock.
- Include a deliberate demand gap for T-010 (e.g. **no** motion-control shoe under ₹3,500)
  so "unmet demand" surfaces a real finding rather than an empty table.
- Do this **after** T-003b so the new rows use the corrected attribute schema.

**Acceptance.**
- ≥140 products; ≥50 in `running_shoes`; every category ≥4 SKUs.
- All existing demo-path guarantee tests still pass unchanged.
- Hard-coded count assertions in tests are replaced by threshold assertions
  (`>= 140`, not `== 31`), so the catalog can grow without editing tests.

Completed 2026-08-25 — deterministic expansion produces 140 products, including 59 running shoes; threshold tests cover category breadth and the deliberate no-motion-control-under-₹3,500 demand gap.

## PHASE 2 — PRODUCT INTELLIGENCE

### `[ ]` T-004 — Embeddings, `VectorIndex`, hybrid search
**Objective.** Retrieval that fuses hard constraints + semantic + lexical, and explains itself.

**Files.** `api/app/catalog/{embeddings.py,index.py,search.py,ranking.py}`,
`api/app/api/catalog.py`, `api/tests/test_search.py`.

**Details.**
- `EmbeddingProvider` protocol + hosted impl + `DeterministicEmbeddingProvider` (D-005).
  **Verify the exact hosted model id against live provider docs before pinning it.**
- Embedded document is **category-aware** (T-003b): shared fields for every product, footwear
  fields only for footwear. Do not embed anything until T-003b lands — re-embedding a
  polluted document set is wasted work.
- `NumpyVectorIndex` default; `PgVectorIndex` behind `VECTOR_BACKEND` (D-004).
- `search_products(query, filters, k)`: filters are **hard SQL WHERE** (budget, category,
  in_stock, size, brand, gender); vector + `ts_rank` are fused by RRF; then a transparent
  business re-rank. Each hit returns `match_reasons: string[]` computed from actual
  constraint satisfaction (D-012) and a `score_breakdown` for the audit trail.
- Re-embedding runs on seed and on catalog mutation; embeddings cached in `product_embeddings`
  keyed by `(product_id, model, content_hash)` so `make seed` doesn't re-bill.

**Acceptance.**
- Golden test: "running shoes under ₹5,000 for daily 5 km runs, flat feet" returns ≥3 hits,
  **all** `price_paise <= 500000`, **all** in stock, and ≥2 with `arch_support != neutral`.
- The ₹6,500 stability shoe never appears when `max_price_paise=500000`.
- Query "GPS watch" outranks lexically — proves the lexical arm contributes.
- Tests run with no network and no API key (deterministic provider).
- `mypy --strict` clean on `catalog/`.

---

## PHASE 3 — AGENT

### `[ ]` T-005 — Commerce services + cart fingerprint
**Objective.** The deterministic write layer. Nothing else may write commerce state.
**Files.** `api/app/commerce/{cart.py,inventory.py,offers.py,orders.py,fingerprint.py}`, tests.
**Details.** Cart items snapshot `unit_price_paise` at add-time. Offers recomputed server-side
from the `offers` table only. `fingerprint(cart) = sha256(canonical_json(items)+total)` (D-008).
Stock reserved (not decremented) at order creation; decremented on payment success; released on
failure/expiry.
**Acceptance.** Unit tests for: budget maths in paise, offer cap behaviour, fingerprint changes
on qty/price/line-item change and *only* on those, stock reservation release on failure.
Concurrent `add_to_cart` on the last unit oversells zero times.

### `[ ]` T-006 — Policy engine
**Objective.** Implement all 9 rules in `ARCHITECTURE.md` §7 as pure functions with `rule_id`s.
**Files.** `api/app/policy/{decisions.py,rules.py,engine.py}`, `api/tests/test_policy.py`.
**Details.** `pre_tool` / `post_tool`; every decision persisted; confirmation tokens minted only
by `POST /api/v1/cart/confirm` from an explicit user action (D-008).
**Acceptance.** One test per `rule_id`, each proving the *deny* path. Specifically: a forged /
expired / cart-mismatched token is rejected; a model-supplied `discount_paise` is ignored in
favour of the recomputed value; `place_order` with any invalid token cannot reach Razorpay.

### `[ ]` T-007 — Tool registry + agent orchestrator + SSE
**Objective.** The bounded tool-use loop. ~120 defensible lines, no agent framework (D-006).
**Files.** `api/app/agent/**`, `api/app/api/chat.py`, `api/tests/test_orchestrator.py`.
**Details.** All 12 tools; Pydantic in/out; envelope shape from §6; `max_steps=8`,
30s wall clock, 2 consecutive errors; one `agent_steps` row per iteration written *before*
returning to the model; SSE event types per §12.
**Acceptance.** Integration test with `StubLLMProvider` drives the full demo path end to end
with no network. A tool raising an exception yields a clean `ok:false` envelope — never a 500,
never a stack trace to the client. A model loop that never terminates is cut off at 8 steps
with a graceful message.

### `[ ]` T-008 — Customer conversational commerce UI
**Objective.** `/shop`. The surface judges spend the most time looking at.
**Files.** `web/app/(customer)/shop/**`, `web/components/{chat,commerce}/**`, `web/lib/sse.ts`.
**Details.** Streaming chat; product cards rendering `match_reasons`; comparison table;
live cart preview; a visible **tool/action timeline** (this is what makes it read as *agentic*
rather than as a chatbot); explicit confirmation UI that mints the token; skeleton loaders and
real error states. Keyboard accessible, screen-reader labelled, responsive from 375px.
**Acceptance.** Full demo path works against the real API. No `any` in components. Every async
surface has loading + error + empty states. Lighthouse a11y ≥ 95 on `/shop`.

---

## PHASE 4 — PAYMENTS

### `[ ]` T-009 — Razorpay test-mode checkout
**Objective.** Real money movement in test mode, correct under failure.
**Files.** `api/app/payments/**`, `api/app/api/{checkout.py,webhooks.py}`, `web/components/commerce/Checkout.tsx`.
**Details.** Per `ARCHITECTURE.md` §8 and D-009. `key_secret` server-only. HMAC verify on both
paths. Idempotent on `razorpay_payment_id`. Amount re-validated against the order row.
Polling reconciler for local runs where the webhook can't reach us.
**Acceptance.** Test-mode card completes and the order reaches `paid`. Replaying the same
webhook twice produces exactly one payment row and no double state transition. A tampered
signature is rejected with 400 and logged. Closing the checkout tab mid-payment still converges
to the correct terminal state via reconciliation. `key_secret` appears in **zero** client bundles
(assert via a grep test over `.next/`).

---

## PHASE 5 — MERCHANT GROWTH

### `[ ]` T-010 — Analytics events + query layer
**Files.** `api/app/analytics/{events.py,queries.py}`, `api/app/api/analytics.py`.
**Details.** Emit funnel events from the services (never from the model). One function per
dashboard number (§10). Every response carries `provenance` (D-010).
**Acceptance.** Each metric has a test with a hand-built fixture and an expected value. No
metric is computed in the frontend. A test asserts the API never returns a metric without a
`provenance` field.

### `[ ]` T-011 — Merchant AI Growth Dashboard
**Files.** `web/app/(merchant)/dashboard/**`, `web/components/dashboard/**`.
**Details.** AI-assisted revenue, conversion, AOV, upsell revenue, sessions; funnel chart;
top intents; unmet-demand table; recommendation performance; policy-violation count. Recharts.
Live/demo toggle + provenance chip on every card (D-010). Drill into a session's audit trail.
**Acceptance.** Every number traces to a function in `analytics/queries.py`. Toggling to
live-only with no live sessions shows a real empty state, not fabricated numbers.

---

## PHASE 6 — EVALUATION

### `[ ]` T-012 — Simulator, arms, metrics, reproducible runs
**Files.** `eval/**`, `api/app/api/evaluation.py`.
**Details.** Per §11 and D-011. `make eval SEED=42` writes `eval/results/<run_id>.json`
containing required literal `"simulated": true`, the seed, the embedding provider used, catalog
hash, git sha, and per-arm metrics. ≥40 personas per arm.
**Acceptance.** Same seed ⇒ byte-identical results file (excluding a timestamp field). Both arms
face an identical persona sequence. The results schema rejects a payload lacking `simulated: true`.
Policy violations are reported for both arms.

### `[ ]` T-013 — `/evaluation` report page
**Details.** Baseline vs CartPilot comparison, non-dismissible **"Simulated evaluation results."**
banner, methodology + stated limitations section (including the D-011 language-variety caveat).
**Acceptance.** The banner cannot be dismissed and is visible in any screenshot of the page.

---

## PHASE 7 — POLISH

### `[ ]` T-014 — README, architecture diagram, demo script, final pass
**Details.** Setup in ≤5 commands, architecture SVG, 5-minute demo script with the exact
utterances, honest limitations section, responsive/error-state sweep.
**Acceptance.** A stranger with Postgres and API keys reaches the working demo from the README
alone. `make test` green. No `TODO` or dead code in shipped paths.

---

## Backlog (explicitly NOT scheduled — do not build)
Multi-tenant auth, real inventory sync, mobile app, i18n, product image generation, RAG over
reviews, voice input, an "AI insights" LLM-written narrative panel (violates D-010/§10).
