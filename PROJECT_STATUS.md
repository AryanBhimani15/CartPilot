# CartPilot AI — Project Status

**Last updated:** 2026-08-25 (Codex, implementation)
**Target:** Razorpay AI Builder Internship 2026 — AI Growth & Agentic Commerce

---

## Current phase

**Phase 1 — Foundation.** T-001 through T-003 are complete. The repo now has a FastAPI +
Next.js scaffold, an Alembic-owned PostgreSQL schema, and a deterministic seed catalog. Next is
T-004 (hybrid product retrieval).

---

## What works

- `make setup` installs the Python and web dependencies and creates `.env` from the fake-value
  template when absent. `make db`, `make seed`, `make test`, `make types`, `make lint`, and
  `make typecheck` are available.
- `GET /api/v1/health` performs a real async Postgres query and returned
  `{"status":"ok","db":"ok"}` locally.
- `/shop` and `/dashboard` build and render cleanly as Phase 1 placeholders.
- The core schema contains all §4 tables, named native PostgreSQL enums, required GIN/uniqueness
  indexes, BigInteger paise fields, and the required provenance columns.
- Migration upgrade/downgrade was exercised twice. The migration explicitly manages native enum
  lifecycle so a downgrade does not block a subsequent clean upgrade.
- `make seed` is deterministic and idempotent: 31 products, 217 size-specific variants, and
  three offers. Its database-backed test verifies stable IDs, deliberate out-of-stocks, the
  stability/budget demo path, cross-sells, and trademark exclusion.
- Final local checks passed: 5 pytest tests, strict backend mypy, Ruff, web ESLint, web TypeScript,
  and a production Next build.

---

## What is broken / at risk

| Risk | Impact | Mitigation |
|---|---|---|
| Agent, retrieval, checkout and analytics are not implemented yet | No end-to-end commerce demo yet | Proceed in task order starting T-004 |
| No Razorpay test credentials in `.env` yet | Blocks Phase 4 | **Aryan**: create a Razorpay test account and supply `key_id` / `key_secret` / webhook secret before T-009 |
| Local webhooks are unreachable from Razorpay | Payment state may not converge in a local demo | D-009 polling reconciler (T-009); optionally a tunnel during the live demo |
| No LLM/embedding API keys configured | Blocks T-004, T-007 | Deterministic providers keep tests and eval running without keys (D-005) |
| Scope creep into "AI insights" narrative panels | Credibility | Explicitly in the TASKS.md do-not-build backlog |

---

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
