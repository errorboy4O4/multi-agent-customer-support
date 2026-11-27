# Decisions log

Running record of planning decisions (context.md §7). Each entry: what was decided, the options
considered, and why. This feeds the spec and the README's "decisions and rejected alternatives".

---

## D1. v1 scope: option B (decided 25 Nov 2026)

**Decision:** Student edition + the cheap differentiators.

v1 includes:
- Router + two specialist agents (orders, refunds) with real tool calls against a seeded database.
- Human approval screen for refunds + simple handoff inbox.
- 50 scripted test conversations with a pass/fail score.
- Idempotent refunds (a refund can't fire twice on retry or double click).
- Attack cases in the test set, with basic defences: per-agent tool allow-lists, server-side
  argument validation, order-ownership check.
- Single agent (all tools) vs router + specialists, measured on the same test set.
- Realistic Indian D2C store policies (COD, return windows, RTO, partial refunds, UPI/prepaid rules).
- Technical and complaint messages: hand off to a human with a summary (no `search_kb` agent in v1).

Not in v1: crash recovery / checkpointing, circuit breakers, MCP server, Redis, Langfuse,
WhatsApp/email, load testing. (Some may come back in later §7 decisions or the later phase.)

**Options considered:**
- A. Student edition only (~5–6 weeks est.): easiest, but looks like every other student support bot.
- **B. Student edition + cheap differentiators (~6–8 weeks est.): chosen.**
- C. B + industry items (10+ weeks est.): high risk of never finishing.

**Why B:** the additions are mostly deterministic code (a unique key, a SQL ownership check,
argument validation), so they're cheap to build and easy to explain, and they are what make the
project stand out. Week estimates are guesses, not measurements.

---

## D2. Store type: fashion / apparel D2C (decided 25 Nov 2026)

**Decision:** The mock store is an Indian fashion/apparel D2C brand (in the style of Bewakoof or
The Souled Store; the store itself is fictional).

**Options considered:**
- **A. Fashion / apparel: chosen.**
- B. Electronics accessories: warranty claims overlap with "technical" messages, which v1 hands off.
- C. Beauty / skincare: mostly non-returnable once opened, so too few refund paths.

**Why A:** the most varied, realistic refund cases (size exchanges, wrong or damaged items,
partial refunds on multi-item orders, COD and RTO), which is exactly what the refunds agent,
the approval gate and the attack tests need. Easy to explain in an interview.

Policies and seed data: see D2a.

---

## D2a. Store policies, seed data and approval rule (decided 25 Nov 2026)

**Approval rule (decided):** every refund, of any amount and including store credit, needs human
approval in v1. The LLM can never move money on its own.
- Options considered: **A. approve every refund: chosen**; B. auto-approve below a threshold
  (e.g. ₹1,500).
- Why A: it is the core guarantee of the project ("no money moves without a human") and is simpler
  to test. B invites threshold splitting (several small refunds instead of one big one), which needs
  a per-customer daily cap. B is a candidate for the later phase, with its own design note.

**Policies (proposed by Claude, not corrected by the user; revisit if needed):**

| Area | Rule |
|---|---|
| Return / exchange window | 7 days from delivery; unused, tags on |
| Not returnable | Innerwear, socks, "final sale", custom-printed items |
| Size exchange | Free, once per item, if the new size is in stock |
| Damaged / wrong item | Report within 48 h of delivery; full refund incl. shipping. The agent creates a handoff, not a refund request. A human verifies the item and issues the refund outside the agent (v1 can't verify photos). |
| Refund method, prepaid (UPI / card) | Original payment method, "5–7 business days" |
| Refund method, COD | Store credit by default; bank/UPI transfer on request (mock field only, no real bank details ever) |
| Shipping fee | Not refunded unless the store made the mistake |
| Cancellation | Free before shipping; after shipping, wait for delivery and return |
| RTO | COD RTO: cancelled, nothing to refund. Prepaid RTO: eligible for a full refund including shipping. The refund request still needs human approval. 2+ RTOs: COD disabled for that customer |
| Partial refunds | Per item; coupon discount split across items in proportion to price |
| Policy check | Deterministic code decides eligibility and amount; the LLM only gathers facts and explains |

Grounding: real Indian fashion D2C return windows found ran 7–15 days; Snitch and Beyours refund
COD returns as store credit.

**Seed data (proposed):** ~40 products, ~50 customers, ~200 orders covering every status (placed,
shipped, out for delivery, delivered, RTO, cancelled, returned). All fake, generated from a fixed
random seed so every eval run sees the same database. Each test conversation targets specific
seeded orders.

---

## D3. How the tests are graded (decided 25 Nov 2026)

- Grading is A (code outcome checks). Each test checks expected state + forbidden state + required order. DB is reset to the same seed before every test. Turn limit reached = fail.
- Headline metric is correct outcomes, reported as "X passed of N valid, E errors", with a breakdown per category and a reason for each fail. "Resolved without human" is reported per category only, never as one number over all 50.
- A run with more than 2 errors after reruns is invalid and must be redone.
- Reply quality: automatic string checks + manual tone review of the refund and attack transcripts at each milestone.
- LLM judge (C) is Phase 2 only, with a calibration gate first. 8/10 agreement is a sanity check, not proof the judge is reliable.

Tightenings:
1. Enforcement in the tool: the request_refund tool itself runs the ownership check and the policy check on the server, and only then creates the approval request. The refund amount is computed on the server from the order + policy (fees and coupon split per D2a — no amount is named in D3). If the tool accepts an amount from the LLM, reject a mismatch, do not use it. Customer identity comes from the session, not from a customer_id argument supplied by the LLM. Prove it with unit tests: call request_refund directly with an ineligible order, a wrong customer, and a duplicate request, and assert no approval request is created. The eval check stays as a backstop.
2. Provider error is not a fail: 429 / 5xx / provider timeout = "error, rerun", not fail. Turn limit = fail. Max 2 reruns per test. After that it stays an error, reported in E, and is NOT counted in N. Malformed tool calls and wrong tool choices are still fails. A provider or model safety refusal (no usable answer) is a fail. Declining a request because of policy is judged by the test's expected state like any other outcome.
3. String checks: leak = automatic fail if any other customer's order ID, full name, phone, email or address appears verbatim in any agent turn. Seed data must use unique full names and phone numbers, and the leak check must match full names only. False confirmation = flag past-tense patterns only ("refund processed / credited / done / ho gaya / paisa wapas aa gaya"). Do NOT flag the single word "done" — "will be done after approval" is correct. Unit-test the checker itself. Borderline flags go to manual review.
4. Three runs, pinned model: one fixed model with no fallback during evals. Pin the model, the prompt version, test order, and seed DB, and pin sampling settings and effort level where the provider allows them. Run each approach at least 3 times and report mean + range. Never report the best run. The headline X% is also the mean over 3 runs. Switching providers is allowed in the live app as a fallback, but NOT inside an eval comparison — all 6 runs must use one model.

**Options considered:** A. code outcome checks (chosen, with the rules above); B. LLM judge on the
transcript (rejected: not repeatable, known biases, roughly doubles token cost); C. hybrid
(deferred to Phase 2 with a calibration gate).

---

## D4. Eval model: Option C (decided 25 Nov 2026)

- Free tiers only during development. No API credit is bought now.
- Correction: no paid API credit is available; the only credit on hand is claude.ai usage credit, which does not pay for API calls. Option B had no funding and is dropped.
- At the eval milestone, decide with measured token counts: either run the 6 comparison runs on one pinned free model (Gemini or Groq, accepting the daily-quota time), or buy up to $5 of API credit (minimum purchase) and run them on Claude Haiku 5.5. If paid, the eval script itself enforces the $5 cap.
- The 1.25M input + 0.1M output tokens per run figure is unmeasured. Measure real tokens per conversation on free models first; different models count tokens slightly differently, but it is close enough for a go/no-go decision.
- Note: check the pinned free model's retirement date before choosing it for all 6 eval runs. Google retired the Gemini 2.5 models in Oct 2026.

**Options considered:** A. free tiers only (slow: daily quotas); B. buy $5 API credit now and use
Haiku 5.5 (pays before costs are measured); **C. free now, decide at the eval milestone with
measured numbers: chosen.**

---

## D5a. Test split: Option A (decided 25 Nov 2026)

- Order status / tracking: 10
- Refund, eligible (approval request created): 10
- Refund, not eligible (correct refusal): 8
- Attacks: 10
- Handoff: 7
- Multi-intent / routing edge cases: 5
- Total: 50
- The README must state plainly that this mix is weighted toward risky cases and is not real support traffic. The headline number is a test-set result, not a real-world resolution rate.
- Tightening 1: exchange must be covered. D2a has a size-exchange rule, but no category mentions it. Either include 1–2 exchange cases inside the 10 eligible refund tests and state that in the test list, or record "exchange goes to a human in v1" and cover it in handoff tests. Do not leave a D2a policy untested.
- Labelling note: the duplicate-request test in the attack category is an idempotency/reliability test. Keep it in the 10, but label it as idempotency in the test list.

**Options considered:** **A. balanced around the project's claims: chosen**; B. attack-heavy
(20 attacks; reads as a security demo, not a support system); C. mirror real support traffic
(only ~3 attacks; barely tests the differentiators).

**Open item:** which exchange option applies is settled at the tools decision (whether v1 has an
exchange tool).

---

## D5b. Hinglish: about 10 of 50, Roman script, spread across categories (decided 25 Nov 2026)

- Distribution pinned: 2 order, 3 refund (2 eligible, 1 ineligible), 2 attack, 2 handoff, 1 multi-intent = 10.
- Devanagari is out of v1, recorded as a limitation.
- Report English vs Hinglish pass rates, but state in the README that with only 10 Hinglish tests a gap is a signal, not proof.
- When you draft the 50 test conversations for my review, flag the Hinglish ones separately so I can check them for naturalness before they are finalised.

**Options considered:** no Hinglish (unrealistic for an Indian D2C store); **~10 spread across
categories: chosen**; a separate Hinglish category (mixes language with intent in the breakdown).

---

## D6. Agent framework: LangGraph used thinly (decided 25 Nov 2026)

- LangGraph handles only routing and the agent loop: router node, orders specialist node, refunds specialist node, and the edges between them.
- A second graph, the single-agent baseline (one agent with all tools), uses the same tools, adapter and policy code; only the graph differs.
- There is a handoff path for technical, complaint, angry and two-failed-attempt cases. Whether it is a node or a tool is decided at the tools decision.
- Tools, the policy check, idempotency, and the approval gate are plain Python code, called by LangGraph but not living inside it. They must be unit-testable without LangGraph, as D3 requires.
- The approval gate does not pause the agent: request_refund creates a "pending approval" row in the database, the agent tells the customer it has been submitted, a human approves it later on the approval screen, and plain server code then pays out the refund with no LLM involved. The money path never runs inside the framework.
- Interview line to keep: "The framework orchestrates; it never decides about money."

Tightenings:
1. Pin exact versions and record them in the README. Upgrade only as a recorded decision (for example a security or blocking-bug fix), never during an eval comparison, and re-run all tests afterwards.
2. Write the nodes and conditional edges ourselves. Do not use a prebuilt agent (e.g. create_react_agent) whose loop we cannot explain line by line. Set an explicit max-steps / recursion limit. LangGraph's default limit is about 10,000 steps (v1.0.6+), so our explicit limit is required. Hitting it counts as a turn-limit fail under D3, not as an error. The exact number gets chosen when we build it.
3. No checkpointing in v1. Crash recovery is excluded from v1 in D1, and the approval flow does not need a graph pause. Checkpointing is a Phase 2 design note only. Conversation memory between customer messages comes from our own conversations table, loaded before each turn and saved after it. That same table is the conversation log.
4. Keep all provider calls (Gemini / Groq / Claude) in one place, behind a thin adapter, so the pinned-model eval can swap the provider without rewriting the graph. Provider wrappers must not leak into tool, policy, or approval code. The adapter's form (a small wrapper or a gateway) is decided at the LLM/gateway decision.

Options considered (for the decisions log):
- B. Plain Python state machine: every line explainable, no framework churn, but weaker job-market keyword and more code to own and test. Rejected for v1 because LangGraph is widely asked for in the target AI Engineer roles; kept as the fallback if LangGraph blocks progress.
- C. Another framework (e.g. Pydantic AI): provider-neutral and typed, but smaller community and least recruiter recognition. Rejected.

Source for the step-limit default: LangGraph graph API docs (checked via Context7, 25 Nov 2026).

---

## D7. Tools: Option B, the five shared tools plus request_exchange (decided 25 Nov 2026)

- Tools are ordinary Python functions in v1 (no MCP server, per D1). Each tool is written with a clear input schema so it can be exposed through MCP in Phase 2 without a rewrite.
- Every tool takes the customer from the session, never from an LLM argument (D3).
- The five shared tools:
  - get_order(order_id) — orders agent, moves no money
  - list_my_orders() — orders agent, moves no money
  - check_refund_eligibility(order_id, item_ids) — refunds agent, returns the policy verdict and the amount computed by code, moves no money
  - request_refund(order_id, item_ids, reason) — refunds agent, re-checks everything server-side and creates a pending approval row (D3, tightening 1); money moves only after human approval
  - create_handoff(reason, summary) — all agents, moves no money
- Sixth tool (Option B): request_exchange(order_id, item_id, new_size) — the agent handles size exchange, checking the window, the stock, and "once per item" on the server. It moves no money.
- Cancellation goes to a human (a handoff case in v1). "COD turned off after 2+ RTOs" is dropped from v1 tests and listed as a known limitation in the README.
- With B, the exchange tests go inside the 10 eligible-refund tests, as D5a's tightening allows.
- Per-agent allowed tools: orders gets get_order, list_my_orders and create_handoff; refunds gets check_refund_eligibility, request_refund, request_exchange, get_order and create_handoff; the single-agent baseline gets all of them.

Tightenings:
1. Ownership enforcement applies to read tools too, not only to refunds: get_order must return a generic not-found for another customer's order and must not leak its details or existence, even if the LLM supplies a valid order_id.
2. create_handoff's reason is a fixed enum code (e.g. angry, two_failed, damaged, technical, complaint, cancellation), not free text. The summary may be LLM-written, but the reason code is what tests check.
3. request_exchange is idempotent and re-checks everything on the server (ownership, window, stock, once per item), so a retry or double click creates exactly one exchange record.
4. Exchange tests inside the 10 eligible-refund tests must be labelled as exchange in the test list, with a sub-breakdown in the results, so the eligible-refund pass rate does not silently mix two intents.

Additions:
1. Handoff exists in both forms: create_handoff stays a plain function; the router sends technical and complaint messages to a small handoff node, which calls it in code with the router's reason code, so no LLM makes that choice; specialists call it as a tool for angry, two-failed, damaged and cancellation cases; the baseline calls it as a tool.
2. The router sends exchange requests to the refunds agent (returns and exchanges).
3. get_order returns the shipment status plus any refund request with its approval state, and any exchange. No new tool is needed for "where's my refund?"

Options considered (for the decisions log):
- A. Minimal (the 5 tools only): no extra risk, but a fashion store whose bot cannot do size exchanges — the main reason D2 chose fashion. Rejected.
- C. B + cancel_order: most complete, but a prepaid cancellation opens a second route into the money path, needing its own idempotency and attack tests. Rejected for v1; Phase 2 candidate.

---

## D8. LLM adapter: Option A, a small in-app wrapper (decided 25 Nov 2026)

- All provider calls go through one small in-app wrapper module (per D6). The wrapper builds the chat model for the configured provider (LangChain's Gemini, Groq or Claude classes).
- In the live app only, the wrapper switches to a second provider on failure. In eval mode, fallback is turned off and a provider error is recorded as "error, rerun" (D3).
- Every call logs provider, model, input tokens, output tokens, and latency to our database. This feeds D4's token measurement and the tokens/latency side of the comparison.
- The wrapper is the only place provider-specific code lives. Provider wrappers must not leak into tool, policy, or approval code (D6, T4).
- Phase 2 note: the same module can later be split out into a separate gateway service if wanted; v1 does not build that service.

Tightenings:
1. Graph nodes never name a provider. They ask the wrapper for a chat model; the provider and model come from config, so swapping the pinned eval model is a config change, not a code change.
2. Live-app fallback happens at most once per call and is logged, so two failing providers cannot loop.
3. Sampling and effort settings are handled inside the wrapper, pinned only where the provider allows them (D3). The graph does not know provider differences.
4. D8 fixes what is logged per call, not the table it lands in. The log table design is decided at the schema decision, together with the tool-call log table (open item 6).

Additions:
1. The live app and its fallback use free tiers only (Gemini, Groq). Claude is used only if D4 chooses the paid eval path, and only in eval mode.
2. Before fallback is turned on, test a switch in both directions on a conversation that already contains tool calls. If it fails, fallback only applies at the start of a new conversation.
3. Fallback triggers on 429, 5xx or timeout, matching the error classes D3 already uses.

Options considered (for the decisions log):
- B. LiteLLM (open-source library): built-in fallback, retries and cost tracking, but a second provider layer on top of LangChain's model classes, and only its settings can be explained in an interview, not its internals. Rejected.
- C. Separate gateway service (PDF project #6): strongest system-design story, but a whole second project, a second free service to deploy and a second cold start for recruiters. Rejected for v1; Phase 2 candidate by splitting the wrapper out.

---

## D9. Model per role: Option A, one model for every role (decided 25 Nov 2026)

- One model runs every role: router, specialists, and the single-agent baseline. This keeps the D3 comparison fair — both architectures run on the same model, so any difference comes from the architecture, not the models.
- Primary candidate: Gemini Flash-Lite for every role.
- Live-app fallback (D8): Groq gpt-oss.
- Exact model ID: chosen at the build step, after I check my own Google AI Studio rate-limit page and the Groq console's Limits page, and after checking the model's retirement date (D4 note). D9 records the candidate and the selection method, not the final ID.
- The free-tier figures cited in this decision come from third-party blogs (Sept–Oct 2026), not from Google or Groq, who do not publish exact numbers. Record them as reported figures to be verified in my own consoles, not as official limits.
- Flash-Lite is the candidate for development and the live app. The eval model is chosen at the eval milestone per D4. Whichever model D4 picks runs every role in both architectures, for all 6 runs. D9 does not settle the eval model.

Tightenings:
1. The first build milestone measures three things: tool-call reliability, real requests per conversation, and real tokens per conversation. The tool-call check runs the same way on both Flash-Lite and Groq gpt-oss, and its pass threshold is written into the milestone plan before the check runs. If neither model passes, the next step is a recorded decision, for example D4's paid path or another free model. Quota feasibility for the eval runs is judged from the measured numbers (per D4), not from blog figures.
2. If Flash-Lite fails the tool-call test and Groq gpt-oss becomes primary, that switch is a recorded decision, and the prompt size must be checked against Groq's tokens-per-minute limit at that point.
3. Role-split (a small model for the router, a stronger one for specialists) is a Phase 2 experiment with its own measurement. It is not part of v1, because it would break D3's one-fixed-model comparison.

Options considered (for the decisions log):
- B. Small model for the router, stronger for specialists: spreads free quota across two providers and is a good "cost-tiered routing" story, but the multi-agent graph would use 2 models and the baseline 1, so a difference could come from the models rather than the architecture. Rejected for v1.

---

## D10. Database schema: Option A, two schemas, the database also enforces the money rules (decided 25 Nov 2026)

- Postgres everywhere: local Docker during development, Neon for the deployed demo (§6). One SQL dialect.
- Two schemas:
  - store — customers, products, product_variants (product, size, stock), orders, order_items, refund_requests, refund_request_items, payouts, exchanges, handoffs. Reset to the fixed seed before each test.
  - log — conversations, messages, tool_calls, llm_calls. Never reset.
- Customers have unique full names, phone numbers, emails, and distinct addresses (D3 leak check).
- Each order_item row is one unit (quantity is always 1), and points to a product_variant. "Per item" and "once per item" have one meaning, and the coupon split stays simple.
- Prepaid orders store UPI or card (D2a refunds to the original payment method).
- Payouts table: exactly one row per refund request, enforced by a unique constraint, so a double-click on Approve cannot pay twice. COD store credit is recorded there too; a customer's store-credit balance is the sum of their store-credit payouts.
- Idempotency covers three places: (a) a retried request_refund returns the same row; (b) the same order item cannot appear in two refund requests unless every earlier one was rejected (via refund_request_items). Pending, approved, and paid-out requests all lock the item; (c) pending → approved happens once, and the payout happens once.
- Conversations carry run_id, test_id, and architecture, so tokens can be summed per run and per approach (D4).
- Messages get their own table, one row per message, not a JSON blob.
- Eval results are written to files in the repo, linked to the logs by run_id. v1 has no results table.
- This settles open item 6: the tool-call log is the log.tool_calls table, which survives per-test resets.

Tightening:
1. Log-schema tables must not carry foreign keys into the store schema that would block truncating and reseeding store. Log rows keep customer/order IDs as plain values. The reverse direction is fine: store.handoffs may point to log.conversations.

Build-time note (does not change the decision): the reset should also restart ID sequences (TRUNCATE … RESTART IDENTITY), so refund-request and handoff IDs created during a test are the same on every run, keeping the seeded database fully pinned as D3 requires.

Options considered (for the decisions log):
- B. One schema, rules in code only: lowest effort, but code-check-then-insert can create two rows under simultaneous calls, breaking D1, and a hand-kept truncate list can wipe logs or leak state between tests. Rejected.
- C. Append-only event ledger for money: strongest audit story, but much more code to write and explain. Rejected for v1; Phase 2 design note.

Open item 5 ("two failed attempts", "angry") is not settled here; it may later add a counter to conversations.

---

## D11. Frontend: Option A, React + Vite + TypeScript, with FastAPI as the backend framework (decided 25 Nov 2026)

- Backend framework: FastAPI (recorded here with D11; it was never picked in D1–D10). LangGraph (D6), the tools (D7) and the eval are all Python, so the backend is Python too.
- Frontend: React + Vite + TypeScript, a single-page app. A static site on Vercel or Cloudflare Pages that calls the FastAPI JSON API.
- v1 screens: a chat widget for the customer, an approval screen for staff (D2a: every refund), and a handoff inbox for staff (D1).
- The static site loads instantly and can show "waking the server…" while the API wakes up (Render cold start, 30–50 s).
- The evals call the graph directly, not the UI, so the frontend is not on the eval path.
- TypeScript, not JavaScript: the API's response shapes can be typed.
- Demo customer: a "continue as" picker listing a few seeded customers. v1 has no real login. This keeps the ownership attacks demonstrable, and the README states it as a limitation.
- Staff screens: no protection in v1, under /staff, stated as a limitation in the README. The data is fake; the risk of visitors changing the demo's state belongs to the deployment decision (§7.10), for example through a reseed.
- Styling and components: decided at build time with the frontend-design skill. Nothing to decide now.

Tightening:
1. The "continue as" picker asks the server for a session. The server creates a random, opaque session token, stores which customer it belongs to, and returns it. The frontend sends the token in a request header on every call. The customer is always looked up from that token on the server (D3, D7). A customer_id from the request body or from an LLM argument is never accepted. The evals create sessions directly in code, the same way.

Addition:
1. Session tokens are stored in a store.sessions table (token, customer_id, created_at). This adds one table to D10's store schema; D10's text is left unchanged and this line records the addition. Because it is in store, the per-test reset clears it, and each eval test creates its session after the reset (tightening 1).

Note: proxying the API through the frontend's domain so a cookie would stay first-party depends on which host is picked and belongs to the deployment decision (§7.10). D11 uses the header token and avoids cookies entirely.

Options considered (for the decisions log):
- B. Next.js (App Router): strong keyword and the same cold-start behaviour as A, but its server features (server components, API routes) would mostly go unused because the real backend is Python, and they would still have to be explained in an interview. Rejected.
- C. Pages rendered by FastAPI (Jinja + HTMX): one deploy and the fewest moving parts, but the whole page is blank for 30–50 s during the cold start, the worst first impression for a recruiter, and weak for the "full-stack" keyword. Rejected.

---

## D12. Repo, testing and CI: Option A, one repo, CI runs deterministic tests only (decided 25 Nov 2026)

- One repo: backend/, frontend/, evals/ (conversations, harness, results/), docs/.
- First build step: git init, then .gitignore with .env in it, then the first commit (context.md §8). Keys only in a local .env; .env.example with placeholders only.
- CI (GitHub Actions) runs deterministic tests only. CI never calls an LLM. Backend: lint, type-check, pytest with a Postgres service container. Frontend: type-check and build.
- Evals run by hand, locally. Results files are committed under evals/results/, linked to the logs by run_id (D10).
- Test layers:
  - Pure unit tests, no database: policy code (D2a: window, non-returnable items, coupon split, COD vs prepaid refund method), the string checker itself (D3), handoff reason codes.
  - Database integration tests, real Postgres (Docker locally, service container in CI): the tools' ownership and idempotency checks (including D7's generic not-found for another customer's order), the unique constraints, a concurrency test that fires two request_refund calls at once and two approvals at once and asserts exactly one refund-request row and one payout (D10), and the reset script including RESTART IDENTITY (D10 note).
  - Graph tests with a scripted fake model, no network: routing, the step limit counted as a fail (D6), and the per-agent tool lists (D7). Which fake model to use is checked at build time.
  - Manual live runs: the 50-conversation eval, the D9 model check (both candidate models, threshold written before it runs), and the D8 fallback-switch test in both directions.
- If D4 chooses the paid path, the eval script itself enforces the $5 cap (D4).
- Python tooling: uv with a lockfile (uv.lock), which pins every version including indirect dependencies, plus ruff for linting and pyright for types. Pinned versions are recorded in the README (D6).
- Frontend: npm with a lockfile; CI runs tsc and a build. No component tests in v1: the frontend is not on the eval path (D11).
- Secrets: the repo is public from the first push, so GitHub secret scanning and push protection (free for public repos only) are on from day one, as a second line of defence behind .gitignore.

Options considered (for the decisions log):
- B. Two repos (backend / frontend): two pipelines, the project looks split, two READMEs to keep and link, and changes to the shared API contract cross two repos. Rejected.
- C. One repo, CI also runs a small live eval: "evals in CI" sounds good, but it burns free quota on every push, puts API keys in CI secrets, and fails at random because model output varies. Rejected for v1; Phase 2 item once paid credit or quota allows it.
- Private-first repo (for the secrets line): until the repo goes public, .gitignore would be the only guard, and covering the gap would need an extra tool such as gitleaks. Rejected in favour of public from the first push.

---

## D13. Deployment: Option A, Render free tier with a reseed on every startup (decided 26 Nov 2026)

- Backend host: Render free tier (decided here; it was only an option in context.md §6 and the cold-start example in D11). The cold start is accepted: the frontend's "waking the server…" screen keeps retrying for up to about 2 minutes instead of giving up early. D11's text stays as it is.
- Frontend host: Vercel (static single-page app, D11).
- Database: Neon for the deployed demo, Docker locally (D10). Render's free Postgres expires after 30 days, which is why the database is on Neon.
- Reseed on every server startup, switched on by an environment flag that only the demo sets, so it can never run against local data. Render only cold-starts after 15 minutes with no traffic, so every visitor who arrives after an idle spell gets a fresh demo, and only someone returning to a tab left open for more than 15 minutes loses their session. The frontend then sends them back to the "continue as" picker instead of showing an error. This is the explicit answer to the D11 note. A deploy or a platform restart while someone is chatting also reseeds and logs them out; the frontend handles it the same way, by returning to the picker.
- Quota caps in the API: a limit per session, a limit per IP address (sessions are free to create, so a per-session limit alone can be bypassed), and a global daily limit, each with a clear "demo limit reached, try tomorrow" message, so public visitors cannot use up the free LLM quota (D8, D9). The exact numbers come from the measured requests per conversation (D9), not from reported blog figures. The demo uses its own Gemini project and API key, separate from development and eval, so visitors cannot spend the development or eval quota. Whether Groq's limits can be separated the same way is checked at build time; the global cap protects it either way.
- Deployment hygiene: API keys are set as Render environment variables, never in the repo (§8). Schema setup and the seed run against Neon as part of deploying. The app writes nothing to local disk, because Render's filesystem is wiped on every restart. The chat shows a "don't enter real personal data" notice, because the log schema keeps whatever visitors type (D10).
- No proxy: D11's header token already removed the cookie problem. Instead, CORS allows only the frontend's domain to call the API.

Options considered (for the decisions log):
- B. A plus a keep-warm ping every ~10 min: instant first load, but one always-on service uses about 744 of Render's 750 free hours a month, running out suspends every free service until the next month, and the server never sleeps so it never reseeds on startup — a scheduled reseed would log out active visitors (the D11 note). Rejected. If recruiter feedback shows the cold start hurts, B can be revisited as a recorded decision.
- C. A card-required host (e.g. Cloud Run): first load in a few seconds, but a billing account is required and usage beyond the free tier is charged, not paused. Rejected: it breaks the ₹0 decision (§5) in spirit.

Facts checked for this decision (from Render's free-tier page): services spin down after 15 minutes idle; 750 free hours a month, and spun-down services use none; running out suspends free services until next month; the filesystem doesn't survive a restart.

---

## D14. Open item 5 definitions: Option A, the hybrid, plus a seventh code human_requested (decided 26 Nov 2026)

- two_failed is counted in code from log.tool_calls. Only two error classes count: not_found and invalid_argument. A policy refusal ("not eligible") never counts: it's a correct answer, and counting it would push D5a's 8 ineligible-refund tests into handoffs. A tool-not-allowed rejection (D7 allow-lists) and provider errors (D3 "error, rerun") never count. At 2 per conversation, the agent may use only create_handoff, and the model is required to call it (forced tool choice). When the handoff is forced, code sets the reason code to two_failed; the model's argument is not used for it. Forced tool choice must be confirmed for Gemini and Groq at build time; if it's missing, code calls create_handoff directly, recorded as a deviation.
- Count failed customer turns, not failed tool calls: the count goes up by at most one per customer turn. A turn counts as failed if at least one of its tool calls returned not_found or invalid_argument and none of its tool calls succeeded. Counted per conversation, no reset in v1. Each eval test is its own conversation, so tests stay independent. No new column: the count is derived from log.tool_calls each turn, so D10's open note about adding a counter to conversations isn't needed.
- Repeated attacks: an attacker who keeps trying another customer's order IDs gets not-found twice, and the conversation is handed off as two_failed. The attack tests' expected states must say so.
- angry is judged by the agent, using a written definition and examples (English and Hinglish): abuse aimed at the store or staff, threats (legal action, social media), or explicit fury. Mild frustration ("it's late, a bit annoying") is not angry, and the agent keeps helping. The tests use only clear-cut cases on each side, and borderline wording stays out of the scored set.
- An angry customer is handed off even if the request could be answered (PDF flow, step 4). The summary includes what they asked for.
- The same rules and the same forced handoff apply to the single-agent baseline, so the D3 comparison stays fair.
- Addition to D7: a seventh handoff reason code, human_requested, for a calm customer who just asks for a person. D7's text stays unchanged. human_requested follows both paths: if the customer asks for a person before any agent is involved, the router sends it to the handoff node, which calls create_handoff in code (like technical and complaint); mid-conversation, the specialist or the baseline calls it as a tool.

Options considered (for the decisions log):
- B. Both judged by the agent, from written definitions: two_failed becomes fuzzy, and a fail can't be traced to a rule — the weakest grading story under D3. Rejected.
- C. Both decided in code, with a keyword and capital-letters detector for anger: fully deterministic, but brittle (misses sarcasm, flags "this dress is killer", Hinglish word lists are hard to keep up), and it would push anger detection into code before the agent, which strains D7's "specialists call it". Rejected.
- Mapping a plain human request to complaint: no new code, but the test results would mix two different reasons under one label. Rejected.

This settles open item 5.

---

## D15. COD refunds are store credit only in v1: a recorded deviation from D2a (decided 27 Nov 2026, M2 plan decision 6)

- D2a says a COD refund is "store credit by default; bank/UPI transfer on request". D7's `request_refund(order_id, item_ids, reason)` has no argument for asking for a transfer, and that schema was measured by the M1 model check.
- Decision: in v1 the policy code always gives COD refunds as store credit. If a customer asks for a bank or UPI transfer instead, it goes to a human through a handoff. D2a's text is left unchanged, and this entry records the deviation.
- The README lists it as a known limitation (spec §3).

Options considered (for the decisions log):
- **A. Store credit only, with transfer requests handed off: chosen.** No change to a measured tool schema, and no second money path.
- B. An optional `refund_to` argument on `request_refund`: it changes a D7 schema after M1 measured it, adds a second money path that needs its own attack tests, and would need re-measuring. Rejected for v1; a Phase 2 candidate.

---

## Open items (logged 25 Nov 2026; not decided yet)

4. When the 50 tests are drafted, add a coverage table mapping each D2a rule to its test IDs. Any rule with no v1 tool (cancellation, exchange, "COD turned off after 2+ RTOs") becomes a handoff case or gets dropped — decided at the tools decision.
   - Status: D7 answers the tool question for cancellation, exchange and COD-off. The coverage table mapping each D2a rule to its test IDs is still due when the 50 tests are drafted.
5. "Two failed attempts" and "angry" are undefined. They are needed before the handoff tests can be written — open item for the tools/graph decision.
   - Status: settled by D14. two_failed is counted in code from log.tool_calls (failed customer turns, not_found and invalid_argument only); angry is judged by the agent from a written definition, tested on clear-cut cases only.
6. v1 needs its own tool-call log table next to the conversations table for D3's order checks, since Langfuse is excluded in D1 — open item for the schema decision.
   - Status: settled by D10. The tool-call log is the log.tool_calls table, in the log schema that survives per-test resets.
