# CartPilot AI — Project Status

**Last updated:** 2026-08-25 (Codex, implementation — T-006 policy engine)
**Target:** Razorpay AI Builder Internship 2026 — AI Growth & Agentic Commerce

---

## Current phase

**T-006 merged (`07fe4d4`), reviewed, two defects fixed on top.** T-007 (agent orchestrator) is
unblocked. T-005a still required before T-009.

---

## What works

- Nine policy rules with stable IDs, first-deny-wins, each with a failure-path test
- HMAC-signed, hashed-at-rest, expiring confirmation tokens bound to session + action + cart
  fingerprint; minted only by `POST /api/v1/cart/confirm`
- **Confirmation tokens are now genuinely single use** — the execution gate consumes them
  atomically with the action (this was missing; see below)
- Forged, expired and cart-mismatched tokens deny payment and the guarded action does not run
- Policy decisions persisted to `agent_steps`, one row per step, updated rather than duplicated
- Concurrency-safe commerce layer; hybrid search with hard filters; coherent 140-SKU catalog
- **Verified green:** 44 pytest, `mypy --strict app`, ruff, eslint, tsc

---

## What is broken / at risk

| # | Finding | Severity | State |
|---|---|---|---|
| 1 | **Single use did not exist.** `consume_confirmation_token()` was never called anywhere, and the execution gate validated without consuming — so one confirmation authorised unlimited payment executions. This is the exact property D-008 exists to provide. | Critical | **Fixed by Claude** — gate now consumes atomically |
| 2 | **`PolicyContext` is fail-open by omission.** Every field defaults permissively, so a tool adapter that forgets one silently disables the rule reading it. | High — and T-007 writes all these adapters | **Fixed by Claude** (`REQUIRED_FACTS`) + T-007 acceptance criteria |
| 3 | The gate keys off tool *name* (`PAYMENT_TOOLS`). A renamed or newly added payment tool silently loses its confirmation requirement. | Medium | T-007 acceptance: assert the set matches the registry |
| 4 | No `order_items` table — orders re-derive contents from the mutable cart; blocks T-010 product analytics | High | **T-005a**, before T-009 |
| 5 | Semantic retrieval arm untested | Medium | T-004a |
| 6 | Archetype titles, global SKU uniqueness, `NullPool` on the API server | Low | T-014 |

**Razorpay test credentials and an LLM API key are still `REPLACE_ME`.** Needed now for T-007.

---

## What Claude changed in this pass

- `api/app/policy/engine.py` — `execute_if_allowed` consumes the confirmation token for payment
  tools, in the same transaction as the action; a payment tool without a consumable token is denied
- `api/app/policy/rules.py` — `REQUIRED_FACTS` rule, ordered **last** so specific denials still win
- `api/app/policy/confirmation.py` — `populate_existing=True` on consume (defensive; see note),
  corrected a docstring that described the old consumption boundary
- `api/tests/test_policy.py` — four tests: token is single use; a valid token cannot be replayed
  through the gate; a payment tool with no stated total is denied; two concurrent requests cannot
  both consume one token (with a barrier forcing genuine overlap)

**Reported honestly:** the `populate_existing` hardening on token consume is defensive by analogy
with the T-005 oversell. Unlike that case it was **not** reproducible here — ablation passed with
and without it. It is kept because reading locked rows fresh is a property worth depending on,
not because it fixed a demonstrated bug.

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
