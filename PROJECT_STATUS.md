# CartPilot AI — Project Status

**Last updated:** 2026-08-25 (Claude, tech lead)
**Target:** Razorpay AI Builder Internship 2026 — AI Growth & Agentic Commerce

---

## Current phase

**Phase 1 — Foundation.** Not started. The repository contained no code at the time of this
inspection: a single stray file whose *filename* was the demo prompt (an accidental shell
redirect), holding a truncated copy of the project brief. It has been moved to
`docs/_inbox/original-brief-fragment.md`. Git has been initialised.

Architecture, decisions and the work queue are now fixed. Codex starts at **T-001**.

---

## What works

Nothing is running yet. Confirmed about the environment:

- Postgres **14.22** (Homebrew) is running and accepting connections on `:5432`
- Node **v25.6.1** / npm 11.9.0, Python **3.12.5**, git 2.50.1
- **Docker is not installed**; **pgvector is not installed** — both shaped D-003 and D-004

---

## What is broken / at risk

| Risk | Impact | Mitigation |
|---|---|---|
| Nothing implemented; 7 phases to go | Schedule | Sequenced queue in `TASKS.md`; phases 1–4 are the demo spine, 5–6 are the differentiator |
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

1. **T-001** repo scaffold + one-command dev — Codex, now
2. **T-002** schema + migrations — Codex
3. **T-003** synthetic catalog — Codex (demo-load-bearing; the acceptance criteria are exact)
4. **T-004** hybrid search — Codex
5. **Aryan**: obtain Razorpay test-mode credentials and an LLM API key before Phase 3 ends

**Claude's next action:** review T-001–T-003 on completion against the acceptance criteria,
then update this file and `TASKS.md`.

---

## Demo readiness

**0 / 10.** Architecture is settled and the queue is unambiguous, which is the cheapest time to
get those right — but no code exists. Realistic path to a credible 5-minute demo is
T-001→T-009 (spine), then T-010→T-013 (the growth + evaluation story that differentiates this
from a shopping chatbot).
