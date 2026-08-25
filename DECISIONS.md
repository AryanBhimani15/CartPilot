# Architecture Decision Record — CartPilot AI

Append-only. Newest last. Do not rewrite an accepted decision; supersede it with a new one.

Format: **D-NNN — Title** · Status · Date · Context / Decision / Consequences.

---

## D-001 — Monorepo: `api/` (FastAPI) + `web/` (Next.js), no shared build tooling
**Accepted · 2026-08-25**

**Context.** Two languages, one product, one submission. A polyglot build system (Nx, Bazel,
Turborepo) would cost setup time and buy nothing at this scale.

**Decision.** Plain directories. A root `Makefile` is the only orchestration layer.
The Python↔TypeScript contract is enforced by generating `web/types/api.ts` from FastAPI's
OpenAPI schema, not by a shared package.

**Consequences.** Trivial onboarding (`make setup && make dev`). Type drift is impossible
because the frontend types are generated. Cost: no shared lint config.

---

## D-002 — Money is integer paise everywhere
**Accepted · 2026-08-25**

**Context.** Razorpay's API is paise-native. Floats produce ₹0.01 discrepancies that surface
in a payments demo at exactly the wrong moment. `Decimal` leaks serialisation ambiguity across
the JSON boundary.

**Decision.** `int` paise in DB, services, tool payloads and API responses. Field names are
suffixed `_paise` without exception. Formatting to `₹4,999` happens only in `web/lib/money.ts`.

**Consequences.** No rounding class of bugs. Slightly noisier field names — accepted, because
the suffix makes unit errors visible in code review.

---

## D-003 — Postgres 14 local, no Docker, no Supabase for development
**Accepted · 2026-08-25**

**Context.** Inspection of the dev machine: Postgres 14.22 (Homebrew) running, **Docker not
installed**, pgvector not installed. Supabase adds a network dependency and rate limits to
every local test and every eval run.

**Decision.** Develop against local Postgres via `DATABASE_URL`. Schema is defined solely by
Alembic migrations, using no Postgres-15+ and no extension-dependent features, so the same
migrations apply unchanged to Supabase or any managed Postgres if we host for judging.

**Consequences.** Zero infra setup. `make db` creates the database and runs migrations.
Deployment portability is preserved. Cost: no pgvector locally — see D-004.

---

## D-004 — `VectorIndex` interface; numpy in-process index is the default
**Accepted · 2026-08-25**

**Context.** The catalog is ~200 SKUs. pgvector is unavailable locally (D-003) and installing
it is an extra dependency for judges reproducing the build. A brute-force cosine over a
200×1024 float32 matrix is a single numpy matmul — well under a millisecond, and *exact*,
where an HNSW index is approximate.

**Decision.** Retrieval sits behind a `VectorIndex` protocol (`upsert`, `search(query_vec, k, ids_filter)`).
Ship `NumpyVectorIndex` (embeddings stored as `float4[]` in Postgres, loaded at startup,
rebuilt on catalog change) as the default. Keep `PgVectorIndex` as a documented, tested-by-
interface alternative activated by `VECTOR_BACKEND=pgvector`.

**Consequences.** No infra risk, exact recall, faster tests. Honest talking point in interview:
*"brute force is optimal at this cardinality; the interface exists so scaling is a config change."*
Must not be described as pgvector in the README. Revisit above ~50k SKUs.

---

## D-005 — Embeddings behind `EmbeddingProvider`; deterministic provider for tests and eval
**Accepted · 2026-08-25**

**Context.** Eval results must be byte-reproducible and CI must run without API keys, but the
demo should use genuine semantic embeddings.

**Decision.** `EmbeddingProvider` protocol with `embed_documents` / `embed_query`. Two impls:
a hosted provider (model + provider chosen via `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` env —
**Codex must verify the exact model id against live provider docs before pinning it**), and
`DeterministicEmbeddingProvider` (seeded hashing projection) used by `pytest` and by
`make eval` unless `EVAL_USE_REAL_EMBEDDINGS=1`.

**Consequences.** Tests are hermetic and free. Eval is reproducible. Cost: eval semantic
quality under the deterministic provider is a floor, not a ceiling — the eval report must
state which provider produced the run.

---

## D-006 — Claude for the agent, behind an `LLMProvider` abstraction
**Accepted · 2026-08-25**

**Context.** The agent needs reliable, schema-validated tool calling. Provider lock-in is a
credibility risk in an interview; a full LangChain-style abstraction is over-engineering.

**Decision.** A thin `LLMProvider` protocol — `complete(messages, tools, system) -> AssistantTurn`
with a normalised `tool_calls` shape. `AnthropicProvider` (default: `claude-sonnet-5`) is the
only implementation we ship, plus `StubLLMProvider` for deterministic integration tests.
No agent framework. The loop is ~120 lines we can defend line by line.

**Consequences.** Swapping providers means writing one adapter. Tool-call semantics are
normalised at the boundary, so `orchestrator.py` contains zero vendor-specific branching.

---

## D-007 — Policy engine is deterministic Python, outside the model's reach
**Accepted · 2026-08-25**

**Context.** "Ask the model nicely not to exceed the budget" is not a safety mechanism, and
reviewers know it. Prompt-level constraints fail under adversarial or merely confused input.

**Decision.** Every write tool passes through `policy.engine.pre_tool` and `post_tool`.
Rules are pure functions with stable `rule_id`s. Decisions are `Allow | Deny | RequireConfirmation`,
persisted for every call. The model receives only a structured error envelope and a remediation
hint — it cannot see, disable, or argue with the rules.

**Consequences.** Budget/stock/discount guarantees hold even against a jailbroken prompt.
`policy_violations` on the dashboard is a real metric. Cost: some legitimate flows need an
explicit confirmation round-trip — that is the intended product behaviour.

---

## D-008 — Payment authorisation requires a server-minted, cart-bound confirmation token
**Accepted · 2026-08-25**

**Context.** The single most important safety property of an agentic checkout: the agent must
not be able to authorise a payment on its own, and a confirmation must not survive the cart
changing underneath it.

**Decision.** `confirm_token = HMAC-SHA256(SECRET, session_id | action | cart_fingerprint | exp)`,
5-minute TTL, single-use, server-stored. Minted **only** by an explicit user UI action on
`POST /cart/confirm`. `create_razorpay_order` and `place_order` are denied without a valid token
whose `cart_fingerprint` equals the cart's current hash. Any qty, price or line-item change
re-hashes the cart and invalidates outstanding tokens.

**Consequences.** Price drift, quantity edits and silent substitutions all become structurally
impossible to slip past confirmation, rather than prompt-dependent. This is the headline
technical answer to "how do you make an agent safe with someone's money."

---

## D-009 — Razorpay webhook is authoritative; the browser callback is a hint
**Accepted · 2026-08-25**

**Context.** The client-side Razorpay handler is attacker-controlled and unreliable (tab close,
network drop). Treating it as truth is the classic Razorpay integration bug.

**Decision.** Terminal payment state transitions only on a signature-verified source: the
`X-Razorpay-Signature` webhook, or a server-side reconciliation fetch. `/checkout/verify`
performs its own HMAC check on `order_id|payment_id`, re-validates the amount against the order
row, and is idempotent on `razorpay_payment_id`. Both paths converge on the same state machine.
For local demos, unreachable webhooks are covered by a polling reconciler.

**Consequences.** Correct under tab-close and replay. Costs one extra reconciliation path,
which doubles as the demo's resilience story.

---

## D-010 — Three-class data provenance, enforced in the schema
**Accepted · 2026-08-25**

**Context.** The brief's hardest constraint: never let simulated or seeded numbers read as
production performance. Convention alone will fail under demo pressure.

**Decision.** `is_demo` on every fact table; `is_simulated` required-true on `eval_runs`;
`provenance` on every analytics API response; a provenance chip on every dashboard metric card;
a non-dismissible **"Simulated evaluation results."** banner on `/evaluation`. The eval result
JSON schema requires the literal `"simulated": true`, so an undeclared eval artifact cannot
be produced.

**Consequences.** Honesty is structural rather than remembered. Small schema overhead.

---

## D-011 — Deterministic rule-based customer simulator, not an LLM
**Accepted · 2026-08-25**

**Context.** An LLM-driven shopper makes eval runs non-reproducible, slow and expensive — and
lets the evaluated system and the evaluator share failure modes.

**Decision.** Personas are data (budget, needs, price sensitivity, upsell propensity, labelled
relevant SKUs). Responses come from seeded `random.Random(seed)` + explicit acceptance
predicates. Same seed ⇒ identical results. Both arms face the identical persona sequence.

**Consequences.** Byte-reproducible, free, fast, and defensible as a fair A/B. Cost: simulated
language is less varied than real users — the eval report must state this limitation explicitly
rather than hide it.

---

## D-012 — Explanations are computed, then narrated
**Accepted · 2026-08-25**

**Context.** "The AI explains its recommendation" is where these demos usually become a
hallucination showcase — the model inventing arch support or drop figures that aren't in the data.

**Decision.** Retrieval emits `match_reasons: string[]` derived from actual constraint
satisfaction (`"₹4,299 — under your ₹5,000 budget"`, `"stability build for flat feet"`,
`"in stock in UK 9"`). The UI renders these strings directly. The model may narrate them but
product facts in the system prompt are restricted to fields present in the tool result.

**Consequences.** Product claims are traceable to catalog rows. `NO_PHANTOM_SKU` covers the
identity case; this covers the attribute case.
