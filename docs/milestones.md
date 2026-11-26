# Milestones: Multi-Agent Customer Support System, v1

*Built from docs/spec.md and docs/decisions.md D1–D14. Approved 26 Nov 2026. One week per milestone is an estimate, not a measurement (D1 estimated 6–8 weeks). Each milestone gets its own detailed task plan just before its code starts.*

## Notes that apply across milestones

- **M1 checks the models on canned tool results.** The check uses the six real tool definitions (D7), but each tool returns a prepared ("canned") result, so it can run before the database exists. This tests what D9 is asking: does the model pick the right tool with valid arguments? It also tackles the biggest risk first.
- **The M1 request and token numbers are early estimates**, taken from draft prompts and canned results. D4's eval-model decision and D13's quota caps use the numbers re-measured on the real graph in M5. This is consistent with D4 ("decide at the eval milestone with measured token counts"). No decision changes.

## D9 model check: check set and pass threshold (written before the check runs)

- **Check set:** 20 single-step cases. Each case has a customer message, the tool the model should call, and the key arguments it should pass. The set includes cases where `request_refund` must *not* be called and cases where `create_handoff` must be called. Each model (Flash-Lite and Groq gpt-oss) runs the full set 3 times.
- **A malformed tool call counts as a fail** (D3).
- **Pass threshold (T1), per model:** a mean of at least 90% over the 3 runs, **and** zero cases where `request_refund` is called when it shouldn't be.
- Rejected thresholds: T2, 100% in every run (one random slip would fail a small free model); T3, a mean of at least 80% (it lets an unreliable model through to the eval).
- Cost: 20 cases × 3 runs × 2 models = 120 short runs. Going by the reported limits (D9), that should fit in one day's free quota.

---

## M1. Setup and the model check (D9)

1. Set up the repo:
   - `git init`, then `.gitignore` with `.env`, then `.env.example`, then the first commit;
   - create the public GitHub repo and turn on secret scanning and push protection (D12);
   - decide the two first-commit questions: whether context.md goes public, and keeping the PDF out of the repo.
2. Set up the backend project and CI:
   - uv project in `backend/` with ruff, pyright and pytest;
   - a CI workflow (lint, type-check, tests) that passes.
3. LLM wrapper (D8): the provider comes from config, and each call's provider, model, tokens and latency are recorded. In M1 these are written into the check's results file; database logging arrives in M2.
4. The user checks the AI Studio and Groq limits and the retirement dates, then pins the model IDs (D9).
5. Confirm forced tool choice on Gemini and Groq (D14).
6. The six tool definitions (D7) with canned results, the 20-case check set, and the threshold above written down before anything runs.
7. Run the check on both models, plus 5 scripted multi-turn conversations per model to measure requests and tokens. Save everything under `evals/results/`.

**Verify:**
- CI passes on GitHub;
- `git check-ignore .env` confirms `.env` is ignored;
- the results file shows pass/fail per model against the threshold written beforehand;
- the user reviews the results;
- if a model fails, the follow-up is a recorded decision (D9).

## M2. Database, seed and policy code

1. Postgres in Docker. The `store` and `log` schemas (D10) plus `store.sessions` (D11), with all the constraints:
   - unique customer fields;
   - one payout per refund request;
   - one exchange per item;
   - the refund-item lock (D10 rule b).
2. A seed generator with a fixed seed: about 40 products, 50 customers and 200 orders, covering every status (D2a).
3. The reset script (TRUNCATE … RESTART IDENTITY, then reseed).
4. A pure policy module (D2a): the window, items that can't be returned, the coupon split, COD vs prepaid, RTO, and damaged items going to a handoff.
5. The wrapper logs to `log.llm_calls`.

**Verify:**
- policy unit tests;
- resetting twice gives identical data (compared by hashing the tables);
- tests that each constraint rejects bad rows;
- CI passes with the Postgres service.

## M3. Tools against the database and money safety

1. The six real tools:
   - the customer comes from the session;
   - another customer's order returns a generic not-found;
   - `request_refund` and `request_exchange` are idempotent;
   - `create_handoff` uses the seven reason codes;
   - every tool call is written to `log.tool_calls` with its error class (D14).
2. Approval and payout as plain server functions, not tools (D6).

**Verify:**
- D3 tightening 1 tests: an ineligible order, the wrong customer and a duplicate request each create no approval request;
- the concurrency tests: one refund-request row, one payout (D10);
- CI passes.

## M4. Graphs

1. The router, orders, refunds and handoff nodes; the baseline graph; the step limit; each agent's tool list (D6, D7).
2. The two_failed count and the forced handoff; the angry definition in the prompts (D14).
3. Load and save conversations and messages (D6).
4. Test the fallback switch in both directions before turning fallback on (D8, addition 2).

**Verify:**
- graph tests with the scripted fake model pass in CI;
- a manual smoke test of a few live conversations from the command line;
- the result of the fallback test is recorded.

## M5. The 50 tests and the eval harness

1. Draft the 50 tests for the user's review:
   - the Hinglish tests flagged;
   - the exchange and idempotency tests labelled;
   - the coverage table (open item 4).
2. The harness:
   - a reset and a new session for each test;
   - the turn limit;
   - checks for expected state, forbidden state and required order;
   - the string checker and its unit tests;
   - error and rerun handling;
   - the run-validity rule;
   - results files with `run_id`;
   - the $5 cap, if the paid path is chosen (D3, D4).
3. Re-measure requests and tokens on the real graph, then make **D4's eval-model decision** and record it.

**Verify:**
- the checker's unit tests;
- a fake-model dry run produces the pass or fail it should for two known cases;
- the user approves the 50 tests;
- the D4 decision is recorded.

## M6. API and frontend

1. FastAPI: sessions, chat, staff approvals and handoffs; CORS; the three quota caps, with IP addresses stored only hashed (D13).
2. React app:
   - the "continue as" picker;
   - the chat;
   - the "waking the server…" screen with up to about 2 minutes of retries;
   - sending a lost session back to the picker;
   - the personal-data notice;
   - the `/staff` approval screen and the handoff inbox.
3. Frontend CI: `tsc` and a build.
4. The eval runs start in parallel whenever the daily quota allows.

**Verify:**
- CI passes;
- a manual end-to-end check on the user's machine: chat → refund request → approval → payout row; plus a handoff showing up in the inbox.

## M7. Eval runs, deployment and README

1. Finish 3 runs per approach. Do the manual tone review (D3).
2. Deploy: Render, Vercel and Neon, the reseed flag, the separate demo key, a check of whether Groq's limits can be split the same way, keys set in the Render environment (D13).
3. README: the diagram, the decisions, the measured results, the pinned versions, the statement about the test mix, the limitations (spec §4 D).

**Verify:**
- the results table is generated from the files;
- the deployed demo runs the end-to-end flow after a cold start;
- every success criterion in spec §4 is ticked off.
