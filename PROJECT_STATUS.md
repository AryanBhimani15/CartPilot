# CartPilot AI — Project Status

**Last updated:** 2026-08-25 (Claude, tech lead — post T-001…T-003 review)
**Target:** Razorpay AI Builder Internship 2026 — AI Growth & Agentic Commerce

---

## Current phase

**Phase 1 complete, reviewed.** T-001, T-002 and T-003 are merged (`a6c1600`). Claude has
reviewed them and applied fixes on top; three follow-ups are queued as T-003a/b/c.

Phase 2 (T-004, hybrid search) is **gated on T-003b** — embedding a polluted document set would
be work thrown away.

---

## What works

- `make setup / db / seed / dev / test / types / typecheck / lint` all run clean
- `GET /api/v1/health` performs a real Postgres round-trip
- Full typed schema + Alembic migration; enum create/drop verified over repeated up/down cycles
- Idempotent, deterministic catalog seed (31 products / 217 variants / 3 offers), stable IDs
- `/shop` and `/dashboard` render; the visual direction is distinctive, not templated
- **Verified green:** 7 pytest tests, `mypy --strict app`, ruff, eslint, tsc

---

## What is broken / at risk

Findings from the T-001…T-003 review, highest severity first.

| # | Finding | Severity | State |
|---|---|---|---|
| 1 | `RIV-STRIDE-34` — the flagship demo shoe — was **out of stock in UK 9**. Stockouts were hash-derived (`digest % 13`), so 22/217 variants were zero by accident. The seed test only checked stock summed across sizes, so it passed. | Demo-breaking | **Fixed by Claude** |
| 2 | `make types` was a no-op: the generator fetched the OpenAPI schema, discarded it, and wrote a hardcoded `HealthResponse` string. It would have silently produced wrong types from T-004 onward. | Hallucinated functionality | **Fixed by Claude** |
| 3 | `make test` runs against the **dev** database and `test_seed_catalog` writes to it. Confirmed: a test run left all 217 variants in dev `cartpilot`. | High — compounds | **T-003a** |
| 4 | Every product gets shoe sizes UK 6–12: a foam roller in UK 9, a GPS watch in UK 11. Shoe-only `attrs` on every category pollute `product_document()`, which feeds `search_tsv` and T-004 embeddings. | High — blocks T-004 | **T-003b** |
| 5 | Catalog is 31 SKUs against a spec of 180–220. Too thin for retrieval to discriminate or for T-012 precision@k to mean anything. | Medium | **T-003c** |
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

**Claude's next action:** review T-001–T-003 against their acceptance criteria, especially the
full migration's enum lifecycle and catalog taxonomy, then direct T-004.

---

## Demo readiness

**2 / 10.** The foundation and demo-load-bearing catalog are working, but the core customer
experience, agent, policy layer, and Razorpay flow remain. The realistic path to a credible
5-minute demo is still T-004→T-009, then T-010→T-013.
