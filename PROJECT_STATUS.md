# CartPilot AI — Project Status

**Last updated:** 2026-08-25 (Codex, implementation — T-003 follow-ups)
**Target:** Razorpay AI Builder Internship 2026 — AI Growth & Agentic Commerce

---

## Current phase

**Phase 1 complete and reviewed. T-004 is unblocked.** T-003a/b/c merged (`939b450`), reviewed,
and one catalog-coherence defect fixed on top.

---

## What works

- Isolated test database: `make test` runs against `cartpilot_test`, rejects a dev/test URL
  collision, rolls back DB-writing tests. **Verified**: dev `products` count and `max(updated_at)`
  are byte-identical across two consecutive runs
- Category-aware variants: 140 products / 703 variants. **Verified**: zero non-footwear UK-size
  variants, footwear attrs nested under `attrs.footwear`, and the GPS-watch search document
  contains no footwear vocabulary
- Deterministic seed with declared stockouts and guaranteed demo-path stock
- Full typed schema, Alembic migrations, enum + variant-axis lifecycle verified over repeat cycles
- `GET /api/v1/health` real Postgres round-trip; `/shop` and `/dashboard` render
- **Verified green:** 13 pytest, `mypy --strict app`, ruff, eslint, tsc

---

## What is broken / at risk

| # | Finding | Severity | State |
|---|---|---|---|
| 1 | Catalog expansion reassigned `arch_support`/`terrain`/`cushioning` per row but inherited the archetype's description, so **36 of 59 running shoes had prose contradicting their own attributes** (`VAYU-CONTROL-1-E10`: "for runners needing motion control", `arch_support: neutral`). Would have poisoned T-004 embeddings and put visible contradictions on demo product cards. | High — would have corrupted Phase 2 | **Fixed by Claude** |
| 2 | Price floors were applied with `max()`, collapsing rows onto identical values — 23 distinct prices across 59 shoes, 4 at exactly ₹3,500. Makes budget-boundary behaviour look artificial. | Medium | **Fixed by Claude** |
| 3 | Generated rows inherit the archetype *title* ("Cloudline 5 Series 5" on a stability shoe). Model names assert nothing about fit, so cosmetic only. | Low | T-014 polish |
| 4 | `products.sku` / `offers.code` globally unique rather than per-merchant | Low | Accept; revisit if a second merchant appears |
| 5 | `NullPool` applies to the API server, not just CLI/pytest | Low | T-014 |
| 6 | No `CHECK` constraints on `stock_qty >= 0` / `reserved_qty <= stock_qty` | Low | Fold into T-005 |

**Razorpay test credentials and an LLM API key are still `REPLACE_ME`.** Needed before T-007/T-009.

---

## What Claude changed in this pass

- `api/app/db/seed/catalog.py` — generated running-shoe descriptions are composed from the
  attributes actually assigned to the row (`running_shoe_description()`); `spread_price()`
  replaces floor clamps so prices don't pile up
- `api/tests/test_seed_catalog.py` — three regression tests: prose never contradicts attributes,
  prices are not clustered on a floor, and the motion-control demand gap is preserved
- Result: contradictions 36 → **0**; distinct running-shoe prices 23 → **56**; demand gap intact
  (cheapest motion-control shoe ₹3,631)

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
