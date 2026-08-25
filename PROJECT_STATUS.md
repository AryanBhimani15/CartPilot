# CartPilot AI — Project Status

**Last updated:** 2026-08-25 (Codex, implementation — T-005 commerce write layer)
**Target:** Razorpay AI Builder Internship 2026 — AI Growth & Agentic Commerce

---

## Current phase

**Phase 3 deterministic write layer complete.** T-004 is reviewed and T-005 now owns every
cart, offer, inventory, and order-state write. T-006 (policy engine) is unblocked; T-004a remains
an independent retrieval-quality follow-up.

---

## What works

- Hybrid catalog search: hard SQL constraints → semantic + lexical → RRF → transparent business
  re-rank, with a per-hit `score_breakdown` for the audit trail
- **Arch support is now a hard filter** — the flagship demo query returns 8/8 stability or
  motion-control shoes, all in budget, all in stock (was 6/8 neutral)
- `match_reasons` computed from filters and catalog rows, never model-authored (D-012)
- Embedding cache keyed on content hash; seed-time refresh; numpy index preloaded at startup
- Deterministic commerce services: cart item prices are snapshotted; offers are recalculated from
  seeded database rows only; order creation atomically reserves stock; failure/expiry releases it;
  verified payment capture decrements it
- Cart fingerprints hash canonical line-item commitments and totals. Active checkout locks cart
  edits, so later stock release/capture always acts on the frozen line items
- Database checks enforce `stock_qty >= 0` and `0 <= reserved_qty <= stock_qty`; a concurrent
  same-cart add on a last unit produces one committed item and one `STOCK_UNAVAILABLE` rejection
- Isolated test database; dev DB provably unchanged across runs
- 140 products / 703 variants, coherent prose, declared stockouts
- **Verified green:** 26 pytest, `mypy --strict app`, ruff, eslint, tsc, OpenAPI codegen; inventory
  constraint migration downgrade/upgrade cycles pass twice on the isolated test database

---

## What is broken / at risk

| # | Finding | Severity | State |
|---|---|---|---|
| 1 | `DeterministicEmbeddingProvider` hardcoded shopper-phrase → catalog-vocabulary mappings (`flat feet` → `stability, motion_control`). This provider is the **default for `make eval`** (D-005), so it would have manufactured CartPilot's relevance advantage in T-012 and reported it as semantic retrieval. | Critical — fabricated metric | **Fixed by Claude** |
| 2 | Arch support was a soft ranking signal: 6 of the top 8 hits on the flagship demo query were neutral shoes. The test asserted only `>= 2` non-neutral, calibrated to what the system produced rather than to a correct result. | High — wrong demo output | **Fixed by Claude** (D-013) |
| 3 | N+1 queries: one `SELECT` per candidate for sizes, 141 round-trips per unfiltered search, in the hot path of every agent tool call. | Medium | **Fixed by Claude** |
| 4 | The semantic arm is **untested**. All 18 T-004 tests passed with the domain mapping deleted, and lexical scores 0 on the flagship query — so the suite exercises filters and lexical only. | Medium | **T-004a** |
| 5 | Generated rows inherit archetype titles ("Cloudline 5 Series 5" on a stability shoe) | Low | T-014 |
| 6 | `products.sku` / `offers.code` globally unique rather than per-merchant | Low | Accept |
| 7 | `NullPool` on the API server, not just CLI/pytest | Low | T-014 |

**Razorpay test credentials and an LLM API key are still `REPLACE_ME`.** Needed before T-007/T-009.
An `EMBEDDING_API_KEY` is also needed to demo real semantic quality (D-014).

---

## What Claude changed in this pass

- `api/app/catalog/embeddings.py` — removed the query→catalog vocabulary injection; `_tokens` is
  now domain-agnostic
- `api/app/catalog/search.py` — `SearchFilters.arch_support` as a hard SQL filter (D-013);
  `match_reasons` follows the filter rather than a substring of the query; N+1 size lookup
  replaced with one grouped query
- `api/app/api/catalog.py` — endpoint exposes `arch_support`; OpenAPI + `web/types/api.ts` regenerated
- `api/tests/test_search.py` — flat-feet test now asserts **all** hits satisfy arch support;
  new test blocks reintroduction of the synonym table; new test proves neutral shoes are excluded
- `DECISIONS.md` — D-013 (hard filters for constraint-bearing intent), D-014 (two AI vendors),
  D-015 (keep the pgvector fail-fast adapter)

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

1. **T-006** policy engine — Codex
2. **Aryan**: obtain Razorpay test-mode credentials and an LLM API key before Phase 3 ends

**Claude's next action:** review T-005's cart-lock/reservation lifecycle and transaction boundary,
then direct T-006.

---

## Demo readiness

**4 / 10.** The foundation, coherent catalog, retrieval tool, and deterministic commerce layer
are working. The policy layer, agent, customer experience, and Razorpay flow remain. The realistic
path to a credible 5-minute demo is T-006→T-009, then T-010→T-013.
