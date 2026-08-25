# CartPilot AI — Canonical Architecture

> Status: **authoritative**. Codex and Claude both read this before substantial changes.
> Changing anything in "Invariants" requires a new entry in `DECISIONS.md`.

---

## 1. Product thesis

Turn natural-language purchasing intent into a completed Razorpay transaction, while
measurably increasing merchant conversion and average order value.

Two surfaces, one backend:

- **Customer**: conversational commerce (`/shop`)
- **Merchant**: AI Growth Dashboard + evaluation report (`/dashboard`, `/evaluation`)

---

## 2. Request flow

```
Customer
   │  natural language
   ▼
Conversation UI (Next.js, SSE stream)
   │  POST /api/v1/chat/{session_id}/messages
   ▼
Agent Orchestrator (api/app/agent/orchestrator.py)
   │  Claude tool-use loop, bounded
   ▼
Tool Registry ── schema validation (Pydantic)
   │
   ▼
Policy Engine · PRE-check  ──► DENY / REQUIRE_CONFIRMATION ──┐
   │ ALLOW                                                    │
   ▼                                                          │
Commerce Services (deterministic Python — the only writers)   │
   │                                                          │
   ▼                                                          │
Policy Engine · POST-check ──► rollback + DENY ───────────────┤
   │ ALLOW                                                    │
   ▼                                                          ▼
PostgreSQL  ·  Razorpay (test mode)          Structured tool-result envelope
   │                                                          │
   └──────────► audit trail + analytics events ◄──────────────┘
```

### Invariant #1 — the LLM never mutates state
The model emits *tool calls*. Every write to cart, order, inventory, offer or payment
state happens in `api/app/commerce/**` or `api/app/payments/**`, executed by Python,
validated by policy, recorded in the audit log. There is no code path where model text
becomes a database write.

### Invariant #2 — money is integer paise
`int`, never `float`, never `Decimal` at the boundary. Razorpay's API is paise-native.
Formatting to `₹` happens only in the presentation layer (`web/lib/money.ts`).

### Invariant #3 — payment truth comes from Razorpay
The browser's checkout callback is a *hint*. Authoritative payment state transitions
only on a signature-verified webhook, or a server-side `payments.fetch` reconciliation.

### Invariant #4 — nothing simulated is presented as real
Every synthetic number carries a machine-readable provenance flag end to end. See §9.

---

## 3. Repository layout

```
CartPilot/
├── ARCHITECTURE.md  TASKS.md  PROJECT_STATUS.md  DECISIONS.md  README.md
├── Makefile              # one-command dev: make setup / db / seed / dev / test / eval
├── .env.example
├── docs/
│   ├── architecture.excalidraw.svg
│   └── _inbox/           # scratch, not part of the build
│
├── api/                          # FastAPI backend — the whole brain
│   ├── pyproject.toml
│   ├── alembic/                  # migrations (single source of schema truth)
│   └── app/
│       ├── main.py               # app factory, middleware, router mounting
│       ├── config.py             # pydantic-settings; fails loudly on missing secrets
│       ├── domain/               # pure types. NO I/O, NO imports from other layers.
│       │   ├── money.py          # Paise newtype + helpers
│       │   ├── enums.py          # OrderStatus, PaymentStatus, SessionOutcome...
│       │   └── errors.py         # ToolError taxonomy
│       ├── db/
│       │   ├── session.py        # async engine + session dependency
│       │   └── models.py         # SQLAlchemy 2.0 typed ORM
│       ├── catalog/              # Phase 2 — product intelligence
│       │   ├── embeddings.py     # EmbeddingProvider protocol + impls
│       │   ├── index.py          # VectorIndex protocol (numpy default, pgvector opt)
│       │   ├── search.py         # hybrid retrieval: filters + vector + lexical
│       │   └── ranking.py        # fusion + business re-rank, explainable
│       ├── commerce/             # deterministic services — the ONLY state writers
│       │   ├── cart.py  inventory.py  offers.py  orders.py
│       │   └── fingerprint.py    # cart hashing for confirmation binding
│       ├── policy/               # Phase 3 — agent safety
│       │   ├── decisions.py      # Allow | Deny | RequireConfirmation
│       │   ├── rules.py          # each rule is a pure function + a rule_id
│       │   └── engine.py         # pre_tool / post_tool evaluation
│       ├── agent/
│       │   ├── orchestrator.py   # bounded tool-use loop, SSE emitter
│       │   ├── prompts.py        # system prompt, versioned
│       │   ├── llm/              # provider abstraction (base.py, anthropic.py)
│       │   └── tools/
│       │       ├── schemas.py    # Pydantic in/out models per tool
│       │       ├── registry.py   # name -> (schema, handler, policy hooks)
│       │       └── handlers/     # thin adapters onto commerce/ + catalog/
│       ├── payments/
│       │   ├── client.py         # Razorpay SDK wrapper (test mode)
│       │   ├── signature.py      # HMAC-SHA256 verification
│       │   └── webhooks.py       # idempotent event handling
│       ├── analytics/
│       │   ├── events.py         # append-only event emitter
│       │   └── queries.py        # every dashboard number = one SQL query here
│       └── api/                  # HTTP routers only. No business logic.
│           └── chat.py catalog.py cart.py checkout.py webhooks.py analytics.py evaluation.py
│
├── eval/                         # Phase 6 — reproducible, clearly-labelled simulation
│   ├── personas.py  simulator.py  metrics.py  run.py
│   ├── arms/ baseline.py  cartpilot.py
│   └── results/<run_id>.json
│
└── web/                          # Next.js 15 App Router + TS + Tailwind + shadcn
    ├── app/(customer)/shop/      ├── app/(merchant)/dashboard/
    ├── app/(merchant)/evaluation/
    ├── components/{chat,commerce,dashboard,ui}/
    ├── lib/{api.ts,money.ts,sse.ts}
    └── types/api.ts              # generated from OpenAPI — never hand-written
```

**Dependency rule (enforced in review):**
`api/` → `domain/` only downward. `commerce/` may import `domain/` + `db/`.
`agent/` may import everything below it. **Nothing imports `agent/` except `api/`.**
`domain/` imports nothing from the app. Circular imports are a review blocker.

---

## 4. Data model (core tables)

| Table | Purpose | Notes |
|---|---|---|
| `merchants` | tenant root | single merchant for demo, but FK everywhere |
| `products` | SKU, title, brand, category, `price_paise`, attrs JSONB | `attrs` holds use_case, arch_support, drop_mm… |
| `product_variants` | size/colour, `stock_qty` | inventory lives here, not on product |
| `product_embeddings` | `product_id`, `model`, `dim`, `vector` | `float4[]` today; pgvector-ready |
| `offers` | code, type, value, min_cart, applicable_scope | **only** source of discounts |
| `sessions` | `id`, merchant, started_at, outcome, `is_demo` | one conversation |
| `messages` | role, content, tool_calls JSONB | full transcript |
| `agent_steps` | **audit trail**: step_no, tool, args, result, policy_decision, latency_ms, tokens | demo-critical |
| `carts` / `cart_items` | `unit_price_paise` snapshotted at add-time | price drift detection |
| `orders` | `amount_paise`, status, `razorpay_order_id`, `cart_fingerprint` | |
| `payments` | `razorpay_payment_id`, status, `signature_verified`, raw payload | idempotent on payment id |
| `session_events` | append-only funnel events | the ONLY source for dashboard metrics |
| `eval_runs` / `eval_sessions` | simulated results, `is_simulated=true NOT NULL` | §9 |

Every fact-bearing table carries `is_demo BOOLEAN NOT NULL DEFAULT false`.

---

## 5. Product search (Phase 2)

Three signals, fused — **not** an embedding-only toy:

1. **Hard structured constraints** → SQL `WHERE`. Budget, category, in-stock, size,
   brand. These are *filters*, never soft scores. A ₹5,000 budget can never be
   out-ranked by a ₹8,000 shoe with a great vector score.
2. **Semantic similarity** → cosine over embeddings of a composed product document
   (`title · brand · category · use_case · attributes · description`).
3. **Lexical** → Postgres `tsvector` / `ts_rank` for exact brand & model tokens, where
   embeddings are famously weak.

Fusion: **Reciprocal Rank Fusion** over (2) and (3), then a small, transparent business
re-rank (in-stock boost, margin tiebreak, review-count tiebreak). Every returned product
carries `match_reasons: string[]` derived from *actual* constraint satisfaction — this is
what the UI shows and what the model quotes. Explanations are computed, not generated.

`VectorIndex` is an interface. Default impl is numpy in-process (see `DECISIONS.md` D-004).

---

## 6. Agent (Phase 3)

**Loop**: `max_steps=8`, `max_wall_clock=30s`, `max_consecutive_errors=2`.
Exceeding any bound ends the turn with a graceful user-facing message — never a silent
hang, never an infinite retry.

**Tool result envelope** — the model *only* ever sees this shape:

```jsonc
{ "ok": true,  "data": { … }, "notice": "optional user-safe note" }
{ "ok": false, "error": { "code": "BUDGET_EXCEEDED",
                          "message": "user-safe explanation",
                          "remediation": "what the agent should try instead" } }
```

Raw exceptions, stack traces and SQL errors never reach the model or the user.

**Tools** (12): `search_products`, `get_product`, `compare_products`, `check_inventory`,
`create_cart`, `add_to_cart`, `remove_from_cart`, `recommend_upsell`, `apply_offer`,
`create_razorpay_order`, `check_payment_status`, `place_order`.

Read tools are unrestricted. Write tools are policy-gated. `create_razorpay_order` and
`place_order` additionally require a **confirmation token** (§7).

Every iteration writes one `agent_steps` row *before* returning to the model. The audit
trail is a first-class demo artifact, not logging.

---

## 7. Policy engine (agent safety)

Deterministic Python. Runs regardless of what the model says. Each rule is a pure
function returning a decision with a stable `rule_id` for analytics.

```python
Allow()
Deny(rule_id, code, message, remediation)
RequireConfirmation(rule_id, prompt, token)
```

| rule_id | Enforcement |
|---|---|
| `BUDGET_CEILING` | cart total ≤ session budget stated by the user; deny `add_to_cart` otherwise |
| `STOCK_AVAILABLE` | variant stock ≥ requested qty, re-checked at order creation |
| `NO_PHANTOM_SKU` | every product id must resolve; blocks hallucinated products |
| `DISCOUNT_FROM_DB` | discount amount recomputed server-side from `offers`; model-supplied values ignored |
| `PRICE_DRIFT` | `unit_price_paise` snapshot ≠ current price → re-confirm |
| `CART_FINGERPRINT` | confirmation token bound to cart hash; any change invalidates it |
| `CONFIRM_BEFORE_PAY` | `create_razorpay_order` / `place_order` require a valid, unexpired token |
| `NO_SILENT_SUBSTITUTION` | swapping an item the user named requires explicit confirmation |
| `MAX_CART_VALUE` | merchant-configured absolute ceiling — blast radius limit |

**Cart fingerprint**: `sha256(canonical_json([{variant_id, qty, unit_price_paise}…]) + total_paise)`.
**Confirmation token**: `HMAC-SHA256(SECRET, session_id | action | fingerprint | exp)`, 5-min TTL,
single-use, stored server-side. The model can *request* confirmation; only the **user's UI
action** mints the token. This is the structural reason the agent cannot self-authorise a payment.

Every decision — allow and deny — is persisted. `policy_violations` on the dashboard is a
real count from real rows.

---

## 8. Payments (Phase 4)

```
place_order (policy OK, token valid)
  └─► orders row  status=created, cart_fingerprint frozen
      └─► Razorpay Orders API  → razorpay_order_id      [amount in paise]
          └─► browser: Razorpay Checkout (TEST key_id only)
              ├─ handler callback ──► POST /checkout/verify  (HMAC of order_id|payment_id)
              └─ webhook ──────────► POST /webhooks/razorpay (X-Razorpay-Signature)
                                      idempotent on razorpay_payment_id
                                      ↑ AUTHORITATIVE state transition
```

- `key_secret` and webhook secret exist **only** server-side; the client receives `key_id` only.
- Both verify paths are idempotent and converge to the same terminal state.
- Failure states are explicit and surfaced in the UI: `failed`, `timeout`, `signature_mismatch`,
  `amount_mismatch`. Amount is re-validated against the order row before capture is accepted.
- `check_payment_status` reads the DB, and only the DB.

---

## 9. Provenance — real vs. demo vs. simulated (Invariant #4)

Three distinct classes, never blended:

| Class | Flag | Where it shows |
|---|---|---|
| **Live** | `is_demo=false, is_simulated=false` | produced by actual use in this session |
| **Seeded demo** | `is_demo=true` | catalog + backfilled history so the dashboard isn't empty |
| **Simulated evaluation** | `is_simulated=true` | `eval_runs` only |

- Every analytics API response carries `"provenance": "live" | "live+demo" | "simulated"`.
- The dashboard renders a live/demo toggle and a provenance chip on every metric card.
- `/evaluation` renders a **persistent, non-dismissible banner: "Simulated evaluation results."**
- The eval JSON schema makes `"simulated": true` a required literal — it is structurally
  impossible to emit an eval result that doesn't declare itself.

---

## 10. Analytics (Phase 5)

`session_events` is append-only; the dashboard is a set of SQL aggregations in
`analytics/queries.py`. One function per dashboard number. If a number can't be traced to a
query in that file, it does not ship.

Funnel: `session_started → intent_captured → products_shown → product_selected →
upsell_offered → upsell_accepted → checkout_started → payment_succeeded`.

Derived insights (all data-backed, none LLM-authored):
unmet demand (searches with 0 in-budget in-stock results, bucketed by price band),
upsell lift (AOV with vs. without an accepted upsell), intent→conversion by cluster,
cross-sell pairs, abandonment stage distribution.

---

## 11. Evaluation (Phase 6)

Two arms over identical seeded personas and an identical catalog:

- **baseline** — keyword `ILIKE` search, top-N by popularity, one static site-wide upsell.
- **cartpilot** — intent extraction → hybrid retrieval → agentic selection → contextual upsell.

The customer simulator is **deterministic and rule-based** (seeded `random.Random(seed)`),
not an LLM, so runs are byte-reproducible. Persona defines budget, needs, price sensitivity,
upsell propensity, and an acceptance predicate.

`make eval` → `eval/results/<run_id>.json` → surfaced at `/evaluation`. Metrics: conversion,
AOV, revenue, upsell acceptance, recommendation relevance (precision@k vs. persona-labelled
relevant SKUs), tool success rate, checkout completion, **policy violations**, task completion.

---

## 12. Conventions

- **API**: `/api/v1/*`, snake_case JSON. Errors: RFC 9457 problem+json.
- **Types**: `web/types/api.ts` is generated from the FastAPI OpenAPI schema (`make types`).
  Hand-written duplicates of backend types are a review blocker.
- **Streaming**: chat is SSE with typed events — `token`, `tool_start`, `tool_result`,
  `policy`, `products`, `cart`, `confirmation_required`, `done`, `error`.
- **Config**: `pydantic-settings`. Missing required secret = startup failure, never a silent default.
- **Tests**: `pytest` for api + eval, `vitest` for web utils. Policy engine and money maths
  require unit tests. Agent loop requires an integration test with a stubbed LLM.
- **No secrets in the repo.** `.env.example` documents every variable with a fake value.
