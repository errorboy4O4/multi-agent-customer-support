# Spec: Multi-Agent Customer Support System, v1

*Built from docs/decisions.md D1–D14 (25–26 Nov 2026). Where the spec and the decisions log disagree, the log wins.*

## 1. What it is
A support system for a fictional Indian fashion D2C store (D2). A router sends each customer message to an orders agent or a refunds agent. The agents call real tools against a seeded Postgres database. Every refund waits for a human on an approval screen. Angry customers, technical issues, complaints and other hard cases go to a human inbox with a summary. One number-free principle: **no money moves without a human, and the framework never decides about money** (D2a, D6).

## 2. Goals (v1)
1. **Agents:**
   - The router plus two specialists (orders, refunds), built as LangGraph nodes and edges we write ourselves, with an explicit step limit (D6).
   - A single-agent baseline graph using the same tools, wrapper and policy code (D6).
2. **Tools:** plain Python functions (D7):
   - `get_order`, `list_my_orders`, `check_refund_eligibility`, `request_refund`, `request_exchange` and `create_handoff`, with a separate allowed-tools list for each agent.
   - The customer always comes from the session (D3, D7, D11).
3. **Policies:**
   - The D2a policy table is enforced by deterministic code: a 7-day window, items that can't be returned, the coupon split, COD vs prepaid refund method, RTO, and damaged items going to a handoff.
   - Every refund needs human approval (D2a, rule A).
4. **Money safety enforced by the database:**
   - two schemas (D10);
   - idempotency in three places: a retried request returns the same row, an item is locked by any refund that wasn't rejected, and approval and payout each happen once (D10);
   - exchanges are idempotent (D7).
5. **Handoff:** seven reason codes (D7 plus D14), the two_failed count kept in code, angry judged by the agent from a written rule (D14).
6. **LLM wrapper:**
   - One small in-app module, and graph nodes never name a provider (D8).
   - The live app runs on free tiers with a single fallback (Gemini Flash-Lite as the candidate, Groq gpt-oss as the fallback; D8, D9).
   - Every call is logged (D8).
7. **Frontend:** React, Vite and TypeScript (D11):
   - a chat widget with a "continue as" picker;
   - a staff approval screen and a handoff inbox under /staff.
8. **Eval:**
   - 50 scripted conversations: order 10, eligible refund 10 (including labelled exchange tests), ineligible refund 8, attacks 10 (including a labelled idempotency test), handoff 7, multi-intent 5 (D5a, D7).
   - About 10 of them in Hinglish (D5b).
   - Graded by code checks (D3).
9. **Comparison:** single agent vs router and specialists, on the same 50 tests, the same pinned model and the same settings (D3, D9).
10. **Deployment:** a public demo on Render, Vercel and Neon, reseeded on startup, with quota caps and a separate demo API key (D13).
11. **Repo:** one public repo; CI runs only tests that don't call a model, and never an LLM (D12).

## 3. Non-goals (v1)
- **Excluded by D1:** crash recovery and checkpointing, circuit breakers, an MCP server, Redis, Langfuse, WhatsApp and email, load testing, a `search_kb` agent.
- **Phase 2 notes:**
  - an LLM judge, with a calibration gate first (D3);
  - an auto-approve threshold (D2a B);
  - `cancel_order` (D7 C);
  - a separate gateway service (D8 C);
  - splitting models by role (D9);
  - an append-only money ledger (D10 C);
  - live evals in CI (D12 C);
  - a keep-warm ping (D13 B).
- **Known limitations, stated in the README:**
  - no Devanagari (D5b);
  - "COD disabled after 2+ RTOs" isn't implemented (D7);
  - damaged-item photos aren't verified (D2a);
  - no real login, and the staff screens are unprotected (D11).
- **§7.11 (the industry edition and system-design depth) is out of v1.**

## 4. Success criteria
v1 is done when **all** of the following hold:

**A. Guarantees proven by tests (CI, every push; D12)**
1. Calling `request_refund` directly with an ineligible order, the wrong customer or a duplicate request creates no approval request (D3, tightening 1).
2. Two simultaneous `request_refund` calls produce exactly one refund-request row, and two simultaneous approvals produce exactly one payout (D10, D12).
3. `get_order` returns a generic not-found for another customer's order (D7).
4. The string checker passes its own unit tests (D3).
5. Graph tests pass with a scripted fake model: routing, hitting the step limit counted as a fail, and each agent's tool list (D6, D7, D12).
6. The reset script restores the identical seed, including restarted ID sequences (D10).

**B. Eval run and reported exactly as D3 requires**
1. Each approach is run 3 times on one pinned model, with the prompt version, test order, seed DB and sampling pinned (D3).
2. Results are reported as "X passed of N valid, E errors", as the mean and range over 3 runs, never the best run. There is a breakdown per category with the reason for each fail (D3). A run with more than 2 errors is invalid and redone (D3).
3. "Resolved without human" is reported per category only (D3).
4. English vs Hinglish pass rates are reported, with the caveat that the gap is a signal, not proof (D5b).
5. Exchange tests get their own results breakdown (D7).
6. Tokens and latency are reported per approach, from the LLM call log (D8, D10).
7. Results files sit in `evals/results/`, linked to the logs by `run_id` (D10, D12).
8. Manual tone review of the refund and attack transcripts is done (D3).

**C. Checks before the eval (first build milestone; D9)**
1. The tool-call check runs on both Flash-Lite and Groq gpt-oss. Its pass threshold is written into the milestone plan before it runs.
2. Real requests and tokens per conversation are measured. They feed D4's eval-model decision and D13's quota caps.

**D. Demo and README**
1. The deployed demo works end to end: chat → refund request → staff approval → payout recorded. It also shows a handoff appearing in the inbox (D11, D13).
2. The README has:
   - the architecture diagram;
   - the decisions and rejected options (from docs/decisions.md);
   - the measured results only;
   - the pinned versions (D6);
   - the statement that the test mix is weighted toward risky cases and is not real traffic (D5a);
   - the known limitations listed in §3.

**No number appears in the README or anywhere results are quoted unless it came from a measured run (project rule: never invent results).**

## 5. Constraints
- ₹0 during development. Paid eval credit (≤$5, Haiku 5.5) is decided only at the eval milestone (D4, §5).
- Keys live only in `.env`, and the repo is public from the first push (§8, D12).
- Pinned versions; upgrades only as a recorded decision (D6, D12).

## 6. Open items carried into the plan
- The coverage table mapping each D2a rule to its test IDs (open item 4), due with the 50 tests.
- The D9 tool-call pass threshold, written before the check runs.
- The exact model IDs, after you check AI Studio and the Groq console (D9).
- The quota-cap numbers, from measured data (D13).
- Whether forced tool choice works on Gemini and Groq (D14).
- **Results wording outside the README:** done (26 Nov 2026). It matches D3: "resolved without human handoff" is reported per category only.
- **First-commit calls:** whether context.md goes public, and keeping the PDF out of the repo (noted before D13).
