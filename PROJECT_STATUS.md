# CartPilot AI — Project Status

**Last updated:** 2026-08-25 (Codex, implementation — T-006 policy engine)
**Target:** Razorpay AI Builder Internship 2026 — AI Growth & Agentic Commerce

---

## Current phase

**Phase 3 safety core complete.** T-005 is reviewed and concurrency-safe; T-006 supplies the
deterministic gates that T-007 will attach before every agent-driven commerce mutation. T-005a
remains required before T-009.

---

## What works

- Cart price snapshots, database-only offer recalculation, canonical cart fingerprints
- Reservation lifecycle: reserve at order creation, release on failure, decrement on capture
- DB `CHECK` constraints reject invalid stock/reservation states
- **Cart-lock ordering is correct** — all three mutation paths take `_locked_cart()` before
  `_ensure_cart_is_editable()`, so a concurrent `create_order` serialises on the cart row
- **Concurrent checkout of the last unit from two carts now yields exactly one order**
  (this was broken; see below)
- All nine policy rules evaluate over typed facts rather than model text; denials include stable
  rule IDs and user-safe remediation. Pre/post checks can persist their outcome into `agent_steps`
- `POST /api/v1/cart/confirm` is the public confirmation minting path. Tokens are HMAC-signed,
  cart-fingerprint-bound, expire after five minutes, and are stored hashed for single use
- Invalid payment confirmation is an executable gate: forged, expired, or cart-mismatched tokens
  deny `place_order` before the guarded payment callable can execute
- Hybrid catalog search with hard filters incl. arch support; isolated test DB; coherent catalog
- **Verified green:** 40 pytest, `mypy --strict app`, ruff, eslint, tsc, OpenAPI codegen

---

## What is broken / at risk

| # | Finding | Severity | State |
|---|---|---|---|
| 1 | **Oversell under concurrent checkout.** `reserve_stock()` takes `SELECT … FOR UPDATE`, but `_cart_lines()` had already loaded those variants into the session's identity map earlier in `create_order()`. Without `populate_existing=True` SQLAlchemy returned the cached **pre-lock** instance, so `reserved_qty` was read stale and the row lock protected nothing. Two concurrent checkouts both succeeded on `stock_qty=1`. | Critical — sells inventory that does not exist | **Fixed by Claude** |
| 2 | The shipped concurrency test exercised concurrent `add_to_cart` on one cart. Carts deliberately don't reserve inventory, so that path never reaches `reserve_stock()` — the oversell risk lives entirely at order creation and was untested. | High — masked #1 | **Fixed by Claude** (new test) |
| 3 | `capture_order_stock()` / `release_order_reservation()` never verified `order.cart_fingerprint` before moving stock, though the field exists precisely to detect that drift. | Medium | **Fixed by Claude** (tripwire) |
| 4 | **No `order_items` table.** Orders re-derive their contents from the mutable cart. Not exploitable today thanks to the cart lock, but the invariant lives in convention across two modules — and it blocks T-010 product-level analytics entirely. | High — blocks T-010, must precede T-009 | **T-005a** |
| 5 | Semantic retrieval arm untested | Medium | T-004a |
| 6 | `_locked_variants` relies on `ORDER BY id` for lock ordering; safe with a PK index scan, theoretically not if Postgres chooses seq-scan + sort | Low | Note only |
| 7 | Generated rows inherit archetype titles; global SKU uniqueness; `NullPool` on the API server | Low | T-014 |

**Razorpay test credentials and an LLM API key are still `REPLACE_ME`.** Needed before T-007/T-009.

---

## What Claude changed in this pass

- `api/app/commerce/inventory.py` — `populate_existing=True` on the locked select, so
  `FOR UPDATE` reads post-lock values instead of the identity map's stale copy
- `api/tests/test_commerce.py` — new test driving two real concurrent `create_order()` calls on
  separate connections for one unit of stock. **Verified deterministic**: fails 3/3 without the
  fix, passes 3/3 with it
- `api/app/commerce/orders.py` — `_assert_cart_still_matches_order()`; capture and release now
  verify the fingerprint before moving stock
- `TASKS.md` — T-005a (order line items), sequenced before T-009

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

1. **T-007** tool registry + agent orchestrator + SSE — Codex
2. **Aryan**: obtain Razorpay test-mode credentials and an LLM API key before Phase 3 ends

**Claude's next action:** review the policy rule ordering, confirmation-token validation, and the
payment execution gate before directing T-007.

---

## Demo readiness

**5 / 10.** The foundation, coherent catalog, retrieval tool, commerce layer, and deterministic
policy core are working. The agent, customer experience, Razorpay flow, and reporting remain. The
realistic path to a credible 5-minute demo is T-007→T-009, then T-010→T-013.
