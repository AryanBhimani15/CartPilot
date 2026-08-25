# CartPilot AI — Project Status

**Last updated:** 2026-08-25 (Codex, implementation — T-003 follow-ups)
**Target:** Razorpay AI Builder Internship 2026 — AI Growth & Agentic Commerce

---

## Current phase

**Phase 1 complete, reviewed.** T-001 through T-003c are complete. Phase 2 may now start at
T-004: seed documents are category-aware and the catalog has enough product depth for retrieval.

---

## What works

- `make setup / db / seed / dev / test / types / typecheck / lint` all run clean
- `GET /api/v1/health` performs a real Postgres round-trip
- Full typed schema + Alembic migration; enum create/drop verified over repeated up/down cycles
- Idempotent, deterministic catalog seed (140 products / 703 variants / 3 offers), stable IDs
- `make test` creates and uses only `cartpilot_test`; it rejects equal dev/test URLs, rolls back
  per-test writes, and verifies dev table counts plus `max(updated_at)` are unchanged.
- Category-aware variants: footwear uses UK sizes, socks/apparel use S/M/L/XL, insoles use S/M/L,
  and recovery/hydration/GPS products use One Size. Footwear-only facts live in `attrs.footwear`.
- `/shop` and `/dashboard` render; the visual direction is distinctive, not templated
- **Verified green:** 10 pytest tests, `mypy --strict app`, ruff, eslint, tsc

---

## What is broken / at risk

Findings from the T-001…T-003 review, highest severity first.

| # | Finding | Severity | State |
|---|---|---|---|
| 1 | `RIV-STRIDE-34` — the flagship demo shoe — was **out of stock in UK 9**. Stockouts were hash-derived (`digest % 13`), so 22/217 variants were zero by accident. The seed test only checked stock summed across sizes, so it passed. | Demo-breaking | **Fixed by Claude** |
| 2 | `make types` was a no-op: the generator fetched the OpenAPI schema, discarded it, and wrote a hardcoded `HealthResponse` string. It would have silently produced wrong types from T-004 onward. | Hallucinated functionality | **Fixed by Claude** |
| 3 | Tests previously wrote to the dev database. | High — compounds | **Fixed (T-003a)** |
| 4 | Non-footwear previously used shoe variants and polluted retrieval documents. | High — blocked T-004 | **Fixed (T-003b)** |
| 5 | Catalog previously had only 31 products. | Medium | **Fixed (T-003c: 140 products / 59 running shoes)** |
| 6 | `mypy --strict` ran on `app/db app/domain` only; the wider app had an error. | Low | **Fixed by Claude** |
| 7 | `products.sku` and `offers.code` are globally unique rather than unique per `merchant_id`. | Low | Accept for now; revisit if a second merchant appears |
| 8 | `NullPool` is used for the API server, not just for CLI/pytest — a new connection per request. | Low | Revisit under T-014 |
| 9 | No `CHECK` constraints on `stock_qty >= 0` / `reserved_qty <= stock_qty`. | Low | Fold into T-005 oversell work |

Still outstanding from before: **Razorpay test credentials and an LLM API key are placeholders**
(`.env` holds `REPLACE_ME`). Needed before T-007/T-009. Tests and eval run without them by design.

---

## What Claude changed in this pass

- `api/app/db/seed/catalog.py` — stockouts are now **declared** (`DELIBERATE_OUT_OF_STOCK`),
  never hash-derived; `DEMO_PATH_SKUS` are guaranteed in stock in every size
- `api/tests/test_seed_catalog.py` — two new tests: demo-path SKUs stocked in *every* size
  (not summed), and every zero-stock variant is declared. The second test immediately caught
  two further accidental stockouts, which is why the hash path was removed entirely
- `api/scripts/generate_openapi_types.py` — now emits the real schema to `web/types/openapi.json`
- `Makefile` — `make types` runs `openapi-typescript` for genuine codegen; `typecheck` covers `app`
- `web/package.json` — added `openapi-typescript` devDependency; `web/types/api.ts` regenerated
- `api/app/main.py` — annotated `lifespan` so `mypy --strict app` is clean
- `TASKS.md` — added T-003a/b/c; T-004 now requires a category-aware embedding document

**Spec bug owned:** T-003's "~180–220 SKUs" lived in *Details*, not *Acceptance*. Codex met the
acceptance block as written. T-003c encodes the count as a threshold assertion instead.

## Recent decisions

D-001…D-012 recorded in `DECISIONS.md`. The four that matter most:

- **D-004** — numpy in-process vector index by default, `VectorIndex` interface for pgvector.
  ~200 SKUs make brute-force cosine exact *and* faster than an approximate index, with zero infra.
- **D-007 / D-008** — safety is a deterministic policy engine plus a server-minted,
  cart-fingerprint-bound confirmation token. The agent structurally **cannot** authorise its own
  payment, and any change to the cart invalidates an outstanding confirmation.
- **D-009** — the signature-verified webhook is authoritative; the browser callback is a hint.
- **D-010** — three-class provenance (`live` / `is_demo` / `is_simulated`) enforced in the schema
  and in every analytics response, so simulated numbers cannot be mistaken for production data.

---

## Current demo path

Not yet executable. Target flow, in the order it will be shown:

1. `/dashboard` — AI-assisted revenue, conversion, AOV, upsell revenue (seeded demo data, chip-labelled)
2. `/shop` — *"I need running shoes under ₹5,000 for daily 5 km runs and I have flat feet."*
3. Agent calls `search_products`; cards render computed `match_reasons`; tool timeline visible
4. *"compare the first two"* → `compare_products` → tradeoff table
5. Selection → `add_to_cart` → contextual `recommend_upsell` (orthotic insoles / anti-blister socks)
6. *"show me something at ₹6,500"* → **`BUDGET_CEILING` denies it, visibly** ← the safety beat
7. *"checkout"* → cart review → explicit user confirmation mints the token
8. Razorpay test-mode checkout → webhook verifies → order `paid`
9. Return to `/dashboard`: the new session appears in live metrics
10. `/evaluation`: baseline vs CartPilot, under the "Simulated evaluation results." banner
11. Session drill-down: the full `agent_steps` audit trail, policy decisions included

Step 6 is the differentiator. Most submissions demo a chatbot that buys something; showing the
agent being *stopped by deterministic policy* is what makes this read as engineering.

---

## Next priorities

1. **T-004** hybrid search — Codex
5. **Aryan**: obtain Razorpay test-mode credentials and an LLM API key before Phase 3 ends

**Claude's next action:** review T-003a/b/c, especially test-database containment and category-
aware seed documents, then direct T-004.

---

## Demo readiness

**2 / 10.** The foundation and demo-load-bearing catalog are working, but the core customer
experience, agent, policy layer, and Razorpay flow remain. The realistic path to a credible
5-minute demo is still T-004→T-009, then T-010→T-013.
