# M2: Database, Seed and Policy Code — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status (27 Nov 2026):** the owner accepted all six recommended options in "Decisions before code" and the smaller choices. Execution is the M1 way: native implementation in this session, then a fresh reviewer on the whole branch. Code starts after the owner has reviewed the scenario table (Task 4) and the smaller choices in this file.

**Goal:** Postgres with the `store` and `log` schemas, where the database itself enforces the money rules (D10). Also a fixed-seed fake store (D2, D2a), a reset that rebuilds the identical seed, a pure policy module for every D2a rule, and LLM calls logged to `log.llm_calls` (D8).

**Architecture:**
- **Database:** Postgres runs in Docker locally and as a service container in CI. The schema is a few numbered `.sql` migration files, applied by a small runner.
- **Policy:** `support.policy` is pure Python with no database access. It takes plain dataclasses of facts plus an explicit `now`, and returns verdicts and amounts.
- **Seed:** a pure builder produces the rows from hand-written scenario orders plus random filler made from a fixed seed. The policy module computes every amount in it.
- **Reset:** truncates every `store` table, restarting the IDs, and loads the seed again.
- **Logging:** the wrapper hands each `CallRecord` to an optional callback, and the callback writes it to `log.llm_calls`.

**Tech Stack:** Python 3.12, uv, psycopg 3 (if decision 1 = A), Postgres in Docker (`docker compose`), pytest, ruff, pyright, and GitHub Actions with a `postgres` service.

**Spec:** `docs/milestones.md` (M2), `docs/decisions.md` (D2, D2a, D10, D11 addition 1; also D3, D7, D8, D12, D13 and D14 where cited), `docs/spec.md` §2.3–2.4 and §4 A6.

---

## Decisions before code (the owner decides; Claude recommends)

Each of these changes what gets built. The tasks below are written for the recommended option, and a different answer changes the tasks it names.

**1. How the code talks to Postgres, and how the schema is applied.** (Tasks 1–6)
- **A. psycopg 3 with plain SQL, numbered `.sql` migration files, and a runner of about 40 lines.** Recommended. D10's whole story is SQL constraints, so the schema should be the SQL you explain in the interview. There's no ORM layer to defend. The runner records each file's checksum, so an edited old migration is caught.
- B. SQLAlchemy 2 Core plus Alembic: typed table objects, the standard migrations tool, and a stronger resume keyword. But it's a second layer to learn, and the constraints are still SQL in the end.
- C. SQLModel or the SQLAlchemy ORM: the least SQL to write. But it hides exactly the part the project is about, the database enforcing the money rules. Not recommended.
- Sub-point under A: sync psycopg for now. M3's concurrency tests use two connections in threads, and FastAPI (M6) can run sync code in its thread pool. Async is an M6 decision if it's ever needed.

**2. How money is stored.** (Tasks 2–5)
- **A. Whole paise as `BIGINT` in the database and `int` in Python.** Recommended. It's exact, needs no `Decimal`, and the coupon split's rounding becomes a visible integer rule. Rupees appear only when text is shown to a person.
- B. `NUMERIC(10,2)` with `Decimal`: reads like rupees, but every computation has to avoid float, and rounding happens implicitly.

**3. How the database enforces the refund-item lock (D10 rule b: an item can't be in two refund requests unless every earlier one was rejected).** (Task 2)
- **A. Copy the request's status onto each `refund_request_items` row through a composite foreign key `(refund_request_id, request_status) → refund_requests (id, status) ON UPDATE CASCADE`, plus a partial unique index on `(order_item_id) WHERE request_status <> 'rejected'`.** Recommended. Postgres keeps the copy in sync itself, and a unique index can't race: two simultaneous requests for one item produce exactly one row. No trigger is needed. Interview line: "the item's claim is a unique index that ignores rejected requests."
- B. A trigger that checks for an existing active claim before each insert. It works only with explicit row locking, and it races under concurrent calls unless that locking is right. It's harder to prove.
- C. Code only, with check-then-insert. D10 already rejected this (option B there).
- The same idea is used for payouts under A: `payouts (refund_request_id, request_status, amount_paise, refund_method) → refund_requests (id, status, amount_paise, refund_method) ON UPDATE RESTRICT`, with `CHECK (request_status = 'approved')`. A payout can then only copy an approved request's exact amount and method. Once a payout exists, the request can't be changed, for example to rejected. `UNIQUE (refund_request_id)` keeps it to one payout per request (D10).

**4. How the seed is built.** (Task 4)
- **A. About 25 hand-written scenario orders, plus random filler from a fixed seed to reach 200.** Recommended. Each scenario is one D2a rule (the table in Task 4) with a stable order ID that M5's tests can target. Changing the filler can't move a scenario. Scenarios include seeded history: a pending, an approved, a rejected and a paid-out refund request, and one exchange. That history is what "where's my refund?" (D7 addition 3) and the item-lock tests need.
- B. Fully random from the fixed seed, with tests that check coverage. Less to write, but M5's tests would have to search for matching orders, and a change to the generator can silently move them.
- Sub-point: names come from hand-written lists (50 first names and 50 surnames, paired without repeats), not the Faker library. That means no new dependency, uniqueness is guaranteed by construction (D3 leak check), and the output doesn't change when Faker is upgraded.

**5. What "now" is.** (Tasks 3–5)
- **Recommended: the policy never reads the clock; every function takes `now` as an argument.** The seed is built around a fixed anchor, `STORE_NOW = 2026-12-01 12:00 IST`, so eligibility doesn't drift from day to day. An eval run that spans several days of free quota then sees the same verdicts (D3: same seed DB).
- Not decided here: whether the deployed demo uses the anchor or the real date at reseed. That's an M7 (D13) question. Because `now` is a parameter, either answer works without touching the policy code.
- Calendar rule: "7 days from delivery" means up to the end of the 7th calendar day after delivery, in IST. A delivery on 24 Nov can be returned until 1 Dec, 23:59:59 IST. The 48-hour damage rule is exactly 48 hours. IST is a fixed +05:30 offset (India has no daylight saving), so no `tzdata` package is needed on Windows.

**6. COD refunds: D2a says "bank/UPI transfer on request", but D7's `request_refund(order_id, item_ids, reason)` has no way to ask for it.** (Task 3)
- **A. In v1 a COD refund is always store credit, and a request for a bank transfer goes to a human (a handoff).** Recommended. Record this as a deviation from D2a, and list it as a README limitation. The tool schema the M1 check measured stays as it is. **Chosen 27 Nov 2026.** It's recorded as **D15** in `docs/decisions.md` (the D2a text is unchanged) and in `docs/spec.md` §3's known limitations, which the README's limitations list is built from (spec §4 D).
- B. Add an optional `refund_to` argument to `request_refund`. That changes a D7 schema after M1 measured it, adds a second money path to protect, and needs its own decision.

**Smaller choices this plan makes. Say if you disagree with any of them:**
- **Damaged items.** A damaged or wrong item always goes to a handoff (D2a: v1 can't verify photos). The policy only answers whether the report is within 48 hours, so the human sees it. The LLM never chooses between a refund and a handoff for damage.
- **Exchanged and non-returnable items.** An item that was already exchanged can't be refunded. Non-returnable items can't be exchanged either. The exchange window is the same 7 days.
- **Prepaid RTO.** The refund covers the whole order, including shipping (D2a). Asking for only some items gets the verdict `rto_whole_order_only`, and the agent can ask again with all items.
- **Cancelled orders.** These are not refundable through the agent (D7: cancellation goes to a human). Seeded prepaid cancelled orders are assumed to have been refunded at cancellation, and v1 shows no refund record for them.
- **Coupon split.** Proportional to item price, rounded by the largest-remainder method, with ties going to the earlier item. The shares always add up exactly to the coupon.
- **Shipping fee.** ₹99 below ₹999 after the coupon, otherwise free. It's refunded only for a prepaid RTO (D2a).
- **All-or-nothing refund requests.** If any requested item isn't eligible, the whole request's amount is 0. The per-item verdicts let the agent ask again with only the eligible items (Task 3, `RefundDecision`).
- **The owner approved two of these knowingly (27 Nov 2026):** the ₹99/₹999 shipping rule (a new number D2a never set) and all-or-nothing refund requests.
- **"Unused, tags on".** Code can't check this. It's left to the human approver.
- **Statuses.** Stored as `text` with a `CHECK`, not Postgres `ENUM` types. A later migration can then add a value without `ALTER TYPE`.
- **Fake contact details.** Phone numbers are `+91 5xxxx xxxxx`. Indian mobile numbers start with 6–9, so these can't be anyone's real mobile. Emails are `@example.com`, a reserved domain (§8: no real personal data).

### The store name ("Saanjh"): no rename decision is needed before M2's seed data

I checked Muse's point that M2's seed data will use the store name, and it doesn't hold:
- **The D10 schema has nowhere for the name to go.** It has no store table and no store-name column.
- **Nothing else in the seed needs it.** With the choices above, customer emails use `example.com` and coupon codes are generic (`WELCOME10`, `FLAT200`).
- **Where the name actually appears:** today only in `evals/model_check/system_prompt.md`. Later it appears in the M4 agent prompts, the M6 UI and the README.

**Recommendation:** keep the name out of all seed data, with a test that fails if it appears (Task 4). The rename then becomes a prompt and UI change.

**Update, 27 Nov 2026: the rename is required before M4's prompts are written.** "Saanjh" is already used by real Indian fashion businesses, for example the "Saanjh by Lea" label (leaclothingco.com) and a Pune ethnic-wear outfitter. D2 says the store is fictional. The new name must be checked the same way before it's used.
- The M1 files that use "Saanjh" (`evals/model_check/system_prompt.md`) stay as they are, because they're part of the pre-registered check.
- The guard test in Task 4 stays and checks for "saanjh" (and the new name, once chosen).

---

## Global Constraints

- Keys and connection strings with passwords stay only in `.env`. `.env.example` has placeholders and the local Docker URLs only (context.md §8, D12).
- Never print a connection string with its password. Show it as `user@host:port/db`.
- CI never calls an LLM and needs no secrets. The Postgres service container uses throwaway credentials written in `ci.yml` (D12).
- Versions are pinned by `uv.lock`, and the Postgres image by its major version. Upgrades only as a recorded decision (D6, D12).
- No foreign key from `log` into `store`. Log rows keep customer and order IDs as plain values. `store → log` is allowed (D10 tightening 1).
- Each order item is one unit; there's no quantity column (D10).
- Customers have unique full names, phone numbers, emails and addresses (D3, D10).
- Seed data is entirely fake, with no real personal data (§8). It contains no store name (see above).
- Money is integer paise (decision 2).
- Every timestamp is `timestamptz`. Policy functions refuse naive datetimes.
- The policy module imports nothing from `support.db`, psycopg or LangChain (D6: unit-testable without them).
- Handoff reason codes are exactly the seven in `support.tools.schemas.HandoffReason` (D7, D14).

## Review Focus

1. **Timestamps in UTC or with no time zone.** Expected: the window is counted in IST calendar days whatever offset the timestamp carries, and a naive datetime raises `ValueError` instead of silently being treated as local time. Tested in `test_window_uses_ist_calendar_days_for_utc_input` and `test_naive_datetime_rejected` (Task 3).
2. **Coupon rounding on awkward prices.** Expected: the shares add up to exactly the coupon for any prices, with no paisa lost or created. Tested in `test_coupon_shares_always_sum_exactly`, over 500 generated cases from a fixed seed (Task 3).
3. **Empty or repeated `item_ids`.** Expected: `ValueError`, never a refund computed twice for one item. M3 maps it to `invalid_argument`. Tested in `test_decide_refund_rejects_empty_and_duplicate_ids` (Task 3).
4. **Pointing a reset or the test suite at the wrong database.** Expected: tests refuse any database whose name doesn't end in `_test`. The reset prints its target as `user@host:port/db`, never the password, before it truncates anything. Tested in `test_guard_refuses_non_test_database` (Task 1) and `test_describe_target_hides_password` (Task 5).
5. **An already-applied migration file edited later.** Expected: the runner refuses to start and names the file, instead of skipping it silently. Tested in `test_changed_applied_migration_is_refused` (Task 1).

---

### Task 1: Postgres in Docker, the migration runner, test database and CI

**Files:**
- Create: `docker-compose.yml` (repo root), `docker/initdb/01-test-db.sql`, `backend/src/support/db/__init__.py`, `backend/src/support/db/connection.py`, `backend/src/support/db/migrate.py`, `backend/src/support/db/migrations/` (empty until Task 2), `backend/tests/db/conftest.py`
- Modify: `.env.example` (add `DATABASE_URL` and `TEST_DATABASE_URL` with the local Docker values), `backend/pyproject.toml` (add psycopg and a `db` pytest marker), `.github/workflows/ci.yml`
- Test: `backend/tests/db/test_migrate.py`, `backend/tests/db/test_connection.py`

**Interfaces:**
- Produces:
  - `database_url(var: str = "DATABASE_URL") -> str`: loads `.env`, and raises `ConfigError` (from `support.llm.config`) naming the variable if it's missing.
  - `describe_target(url: str) -> str`: returns `user@host:port/dbname`, without the password.
  - `connect(url: str) -> psycopg.Connection`
  - `apply_migrations(conn, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]`: applies the `NNN_*.sql` files not yet recorded in `public.schema_migrations (version text primary key, checksum text not null, applied_at timestamptz not null default now())`, in name order, each in its own transaction. Returns the versions it applied. Raises `MigrationError` if an applied file's SHA-256 has changed.
  - CLI: `uv run python -m support.db.migrate` (run from `backend/`, against `DATABASE_URL`).
  - Test fixtures in `conftest.py`: `db_url` (session scope), `fresh_db` (session scope: drops `store`, `log` and `public.schema_migrations`, then applies all migrations), and `conn` (per test: a connection inside a transaction that is rolled back afterwards).

- [ ] **Step 1: Check, then pin, the Postgres major version.** Use the newest major that Neon's free plan offers (D13 deploys to Neon), checked on Neon's site at the start of this task. Write it in `docker-compose.yml` (`postgres:<major>`), in `ci.yml`, and in this step's line.
- [ ] **Step 2: `docker-compose.yml`:**
  - one `postgres` service on port 5432, user and password `support`/`support`, database `support_dev`;
  - a named volume;
  - `docker/initdb/01-test-db.sql` creates `support_test`.

  `.env.example` gets `DATABASE_URL=postgresql://support:support@localhost:5432/support_dev` and `TEST_DATABASE_URL=postgresql://support:support@localhost:5432/support_test`. These are local, throwaway credentials, and the file comments say so. The owner copies these two lines into `.env`; Claude doesn't open `.env`.
- [ ] **Step 3: Add psycopg 3** with `uv add "psycopg[binary]"`; the lockfile pins the version. Check that `uv_build` ships the `.sql` files inside the package: `uv build` and list the wheel's contents. If they're missing, configure the build to include them.
- [ ] **Step 4: Write failing tests.**
  - `test_database_url_missing_names_variable`: with the variable unset, the `ConfigError` message contains `TEST_DATABASE_URL`.
  - `test_describe_target_hides_password` (Review Focus 4; first used by Task 5): `describe_target("postgresql://u:secret@h:5432/d_test") == "u@h:5432/d_test"`, and `"secret"` doesn't appear in it.
  - `test_guard_refuses_non_test_database` (Review Focus 4): the fixture's guard raises for `.../support_dev` and accepts `.../support_test`.
  - `test_migrations_apply_in_order_once` (marked `db`): two temporary files `001_a.sql` and `002_b.sql` are applied in that order. The second call returns `[]`.
  - `test_changed_applied_migration_is_refused` (Review Focus 5): edit `001_a.sql` after it was applied, and `MigrationError` names `001_a.sql`.
- [ ] **Step 5: Implement** `connection.py`, `migrate.py` and `conftest.py`.
  - When `TEST_DATABASE_URL` is unset, the `db` tests **skip** locally with a clear reason, but **fail** when `REQUIRE_DB=1` is set. CI sets it, so a missing database can never pass CI as a skip.
- [ ] **Step 6: CI.** Add a `postgres:<major>` service with a health check (`pg_isready`), `POSTGRES_DB=support_test` and the throwaway credentials. Set the job env to `TEST_DATABASE_URL=postgresql://support:support@localhost:5432/support_test` and `REQUIRE_DB=1`.
- [ ] **Step 7: Run locally.** `docker compose up -d`, then from `backend/` run `uv run pytest -q`, `uv run ruff check . ../evals`, `uv run ruff format --check . ../evals` and `uv run pyright`.
  Expected: everything passes, the new `db` tests run and none skip, and pyright reports 0 errors.
- [ ] **Step 8: Commit, then push only with the owner's yes, and check CI.** `git commit -m "chore(db): Postgres in Docker, migration runner, CI service"`

### Task 2: The `store` schema and its constraints (D10, D11)

**Files:**
- Create: `backend/src/support/db/migrations/001_store.sql`
- Test: `backend/tests/db/test_store_constraints.py`

**Interfaces:**
- Produces: these tables in schema `store`. All IDs are `GENERATED BY DEFAULT AS IDENTITY` integers unless shown as `text`. Every timestamp is `timestamptz`, and every money column is `bigint` paise.
  - `customers (id, full_name UNIQUE, phone UNIQUE, email UNIQUE, address UNIQUE, created_at)`
  - `products (id, name, category, price_paise CHECK > 0, final_sale bool, custom_printed bool)`, where `category` is one of `tshirt, shirt, hoodie, joggers, jeans, kurta, dress, shorts, innerwear, socks`
  - `product_variants (id, product_id, size, stock CHECK >= 0, UNIQUE (product_id, size), UNIQUE (product_id, id))`
  - `orders (id text PK like 'ORD-1001', customer_id, status, payment_method, placed_at, shipped_at, delivered_at, rto_at, cancelled_at, coupon_code null, coupon_discount_paise CHECK >= 0, shipping_fee_paise CHECK >= 0, UNIQUE (id, customer_id))`
    - `status` is one of `placed, shipped, out_for_delivery, delivered, rto, cancelled, returned`.
    - `payment_method` is one of `cod, upi, card`.
    - `CHECK ((status IN ('delivered','returned')) = (delivered_at IS NOT NULL))`.
  - `order_items (id text PK like 'ITM-1001-1', order_id, variant_id, unit_price_paise CHECK > 0, UNIQUE (order_id, id))`
  - `refund_requests (id, order_id, customer_id, status, amount_paise CHECK > 0, refund_method, reason text, created_at, decided_at null, UNIQUE (id, status), UNIQUE (id, status, amount_paise, refund_method))`
    - `FK (order_id, customer_id) → orders (id, customer_id)`: the database refuses a request for someone else's order.
    - `status` is one of `pending, approved, rejected`; `refund_method` is one of `original_payment, store_credit`.
  - `refund_request_items (refund_request_id, order_id, order_item_id, request_status, PK (refund_request_id, order_item_id))`
    - `FK (refund_request_id, request_status) → refund_requests (id, status) ON UPDATE CASCADE`
    - `FK (order_id, order_item_id) → order_items (order_id, id)`
    - `FK (refund_request_id, order_id) → refund_requests (id, order_id)`, which needs `UNIQUE (id, order_id)` on `refund_requests`
    - partial `UNIQUE (order_item_id) WHERE request_status <> 'rejected'`
  - `payouts (id, refund_request_id UNIQUE, request_status CHECK = 'approved', amount_paise, refund_method, created_at)`
    - `FK (refund_request_id, request_status, amount_paise, refund_method) → refund_requests (…) ON UPDATE RESTRICT`
    - There's no `customer_id` here: a store-credit balance (D10) joins through `refund_requests`, so a payout can't name a different customer from its request.
  - `exchanges (id, order_id, order_item_id UNIQUE, customer_id, product_id, new_variant_id, created_at)`
    - `FK (order_id, customer_id) → orders`
    - `FK (order_id, order_item_id) → order_items`
    - `FK (product_id, new_variant_id) → product_variants (product_id, id)`
    - Not enforced by the database: that `product_id` is the original item's product, because that would take a path through `order_items → product_variants`. M3's `request_exchange` checks it in code and tests it.
  - `handoffs (id, customer_id, order_id null, reason, summary, status DEFAULT 'open', conversation_id null, created_at)`
    - `reason` is one of the seven D14 codes; `status` is one of `open, closed`.
    - The FK to `log.conversations` is added in Task 6's migration, once that table exists.
  - `sessions (token text PK, customer_id FK, created_at)` (D11 addition 1)

- [ ] **Step 1: Write failing tests.** Each test inserts into a savepoint (`with conn.transaction():`) and expects the named psycopg error. The base rows are inserted at the start of each test, because the seed arrives in Task 4.
  - `test_customer_fields_unique`: duplicating `full_name`, then `phone`, `email` and `address`, each raises `UniqueViolation`.
  - `test_refund_item_locked_by_pending_request`: a second pending request containing the same item raises `UniqueViolation`.
  - `test_refund_item_free_after_rejection`: set the first request to `rejected`, and a new request with the item succeeds.
  - `test_unrejecting_conflicting_request_fails`: setting a rejected request back to pending while another active request holds the item raises `UniqueViolation`.
  - `test_refund_item_must_belong_to_request_order` raises `ForeignKeyViolation`.
  - `test_refund_request_customer_must_own_order` raises `ForeignKeyViolation`.
  - `test_one_payout_per_refund_request` raises `UniqueViolation`.
  - `test_payout_requires_approved_request`: a payout for a pending request raises `CheckViolation` or `ForeignKeyViolation`.
  - `test_payout_amount_must_match_request` raises `ForeignKeyViolation`.
  - `test_paid_request_cannot_be_rejected`: updating the status after a payout raises `ForeignKeyViolation` (RESTRICT).
  - `test_one_exchange_per_item` raises `UniqueViolation`.
  - `test_exchange_variant_must_be_same_product` raises `ForeignKeyViolation`.
  - `test_checks_reject_bad_values`: stock −1, a price of 0, status `'lost'`, and a `delivered` order with no `delivered_at` each raise `CheckViolation`.
  - `test_handoff_reason_codes`: all seven codes are accepted, and `'other'` raises `CheckViolation`.
- [ ] **Step 2: Run them. Expect failures** (the tables don't exist).
- [ ] **Step 3: Write `001_store.sql`.** Each constraint gets a one-line comment naming the rule it enforces (D10 a/b/c, D3, D11).
- [ ] **Step 4: Run all the checks** (same commands as Task 1, Step 7). Expected: they all pass.
- [ ] **Step 5: Commit.** `git commit -m "feat(db): store schema with DB-enforced money rules (D10)"`

### Task 3: The policy module (D2a)

**Files:**
- Create: `backend/src/support/domain.py` (the enums shared by policy, seed and later the tools), `backend/src/support/policy.py`
- Test: `backend/tests/policy/test_policy.py`, `backend/tests/db/test_enum_drift.py`

**Interfaces:**
- Produces, in `domain.py`:
  - `IST = timezone(timedelta(hours=5, minutes=30))`
  - `StrEnum`s whose values match the Task 2 `CHECK` lists exactly: `OrderStatus`, `PaymentMethod`, `RefundMethod`, `Category`
- Produces, in `policy.py`:
  - Constants: `RETURN_WINDOW_DAYS = 7`, `DAMAGE_REPORT_HOURS = 48`
  - `@dataclass(frozen=True) ItemFacts(item_id: str, unit_price_paise: int, category: Category, final_sale: bool, custom_printed: bool, size: str, refund_locked: bool, exchanged: bool)`
  - `@dataclass(frozen=True) OrderFacts(order_id: str, status: OrderStatus, payment_method: PaymentMethod, delivered_at: datetime | None, coupon_discount_paise: int, shipping_fee_paise: int, items: tuple[ItemFacts, ...])`
  - `class Verdict(StrEnum)`: `eligible, not_in_order, not_delivered, window_expired, non_returnable, already_requested, already_exchanged, order_cancelled, cod_rto_nothing_to_refund, rto_whole_order_only, same_size, size_unavailable, out_of_stock`
  - `@dataclass(frozen=True) RefundDecision(eligible: bool, verdicts: dict[str, Verdict], amount_paise: int, refund_method: RefundMethod | None, includes_shipping: bool)`. The request is all-or-nothing: `eligible` only if every requested item is eligible, and otherwise `amount_paise == 0`. The per-item verdicts let the agent explain and ask again.
  - `is_non_returnable(item: ItemFacts) -> bool`: innerwear, socks, `final_sale` or `custom_printed`.
  - `coupon_shares(prices_paise: Sequence[int], coupon_paise: int) -> list[int]`: largest remainder, ties to the earlier index. Raises `ValueError` if the coupon is negative or larger than the total.
  - `within_return_window(delivered_at: datetime, now: datetime) -> bool`
  - `damage_report_in_time(delivered_at: datetime, now: datetime) -> bool`
  - `refund_method_for(payment: PaymentMethod) -> RefundMethod`: `cod → store_credit`, and `upi`/`card → original_payment` (decision 6).
  - `decide_refund(order: OrderFacts, item_ids: Sequence[str], now: datetime) -> RefundDecision`
  - `decide_exchange(order: OrderFacts, item_id: str, new_size: str, stock_by_size: Mapping[str, int], now: datetime) -> Verdict`. `stock_by_size` holds that product's sizes; a size missing from it gives `size_unavailable`.
  - The verdict order for an item, first match wins: `not_in_order` → order-level verdicts (`not_delivered` for placed, shipped and out_for_delivery; `order_cancelled`; the RTO rules) → `already_requested` → `already_exchanged` → `non_returnable` → `window_expired` → `eligible`.

- [ ] **Step 1: Write failing tests**, with these exact values:
  - `test_coupon_shares_examples`: `coupon_shares([100000, 50000], 30000) == [20000, 10000]`, `coupon_shares([33300, 33300, 33300], 10000) == [3334, 3333, 3333]`, and `coupon_shares([49900], 0) == [0]`.
  - `test_coupon_shares_rejects_bad_coupon`: −1, and more than the total, each raise `ValueError`.
  - `test_coupon_shares_always_sum_exactly` (Review Focus 2): 500 random price lists and coupons from `random.Random(7)`. The shares add up to the coupon, and each share is between 0 and its price.
  - `test_item_refunds_sum_to_amount_paid_for_items`: for a 3-item order with prices `[33300, 33300, 33300]` and a ₹100.00 coupon, refunding each item on its own gives amounts that add up to exactly `99900 − 10000 = 89900`, whatever the order of the requests. The same holds for the 500 random orders in the next test. Shipping isn't part of this sum: it's refunded only for a prepaid RTO (D2a).
  - `test_window_boundary_ist`: delivered `2026-11-24 22:00 IST`. Checked at `2026-12-01 23:59:59 IST` it's `True`; at `2026-12-02 00:00 IST` it's `False`.
  - `test_window_uses_ist_calendar_days_for_utc_input` (Review Focus 1): delivered `2026-11-24 18:30 UTC` (25 Nov 00:00 IST), so `2026-12-02 12:00 IST` is still within the window.
  - `test_naive_datetime_rejected` (Review Focus 1): a naive `delivered_at` or `now` raises `ValueError`.
  - `test_damage_48h_boundary`: delivered `2026-11-29 10:00 IST`. Exactly 48 h later is `True`; 48 h plus 1 minute is `False`.
  - `test_refund_delivered_prepaid_with_coupon`: 2 items, ₹1,000.00 and ₹500.00, coupon ₹300.00, UPI, inside the window. Refunding the first item gives eligible, amount `80000`, `original_payment`, and `includes_shipping False`.
  - `test_refund_cod_is_store_credit`: the same order paid by COD gives `store_credit`.
  - `test_refund_mixed_items_not_eligible`: a tee plus socks gives `eligible False`, `amount_paise 0`, and the verdicts `{tee: eligible, socks: non_returnable}`.
  - `test_refund_order_level_verdicts`:
    - placed, shipped and out_for_delivery give `not_delivered`;
    - cancelled gives `order_cancelled`;
    - a COD RTO gives `cod_rto_nothing_to_refund`;
    - a prepaid RTO with only some items gives `rto_whole_order_only`;
    - a prepaid RTO with all items gives eligible, the amount = prices − coupon + shipping, and `includes_shipping True`.
  - `test_refund_item_verdicts`: a locked item gives `already_requested`; an exchanged item gives `already_exchanged`; final sale and custom printed give `non_returnable`; 8 days after delivery gives `window_expired`; an unknown item ID gives `not_in_order`.
  - `test_decide_refund_rejects_empty_and_duplicate_ids` (Review Focus 3): `[]` and `["ITM-1-1", "ITM-1-1"]` each raise `ValueError`.
  - `test_exchange_verdicts`:
    - eligible when the new size is in stock;
    - `same_size`;
    - `size_unavailable`;
    - `out_of_stock` when the stock is 0;
    - `already_exchanged`;
    - `non_returnable`;
    - `window_expired`;
    - `not_delivered`.
  - `test_enums_match_check_constraints` (marked `db`, in `backend/tests/db/test_enum_drift.py`): checks each enum in both directions against the database.
    - It reads each `CHECK` definition with `pg_get_constraintdef` and extracts the quoted literals (Postgres shows `IN (...)` as `= ANY (ARRAY['a'::text, ...])`).
    - It asserts set equality for `orders.status ↔ OrderStatus`, `orders.payment_method ↔ PaymentMethod`, `refund_requests.refund_method ↔ RefundMethod`, `products.category ↔ Category` and `handoffs.reason ↔ HandoffReason`.
    - The seed load in Task 5 only catches an enum value missing from a `CHECK`, and only for values the seed uses. This test also catches a `CHECK` value the enum lacks (added at the owner's review, 27 Nov 2026).
  - `test_policy_imports_nothing_from_db_or_llm`: in a fresh subprocess (`sys.executable -c ...`, because the test process has already imported these), importing `support.policy` leaves `psycopg`, `langchain_core` and `support.db` out of `sys.modules`.
- [ ] **Step 2: Run them. Expect failures.**
- [ ] **Step 3: Implement** `domain.py` and `policy.py`. Each D2a rule gets a one-line comment citing it.
- [ ] **Step 4: Run all the checks.** Expected: they all pass.
- [ ] **Step 5: Commit.** `git commit -m "feat(policy): pure D2a policy module with exact-paise coupon split"`

### Task 4: The seed builder (D2a seed data)

**Files:**
- Create: `backend/src/support/seed/__init__.py`, `backend/src/support/seed/names.py`, `backend/src/support/seed/catalog.py` (the 40 products and their variants, hand-written), `backend/src/support/seed/scenarios.py`, `backend/src/support/seed/build.py`
- Test: `backend/tests/seed/test_build.py`

**Interfaces:**
- Consumes: `support.domain` and `support.policy` (`coupon_shares`, `refund_method_for`, `decide_refund`, `OrderFacts`).
- Produces:
  - `SEED = 20261127` and `STORE_NOW = datetime(2026, 12, 1, 12, 0, tzinfo=IST)`
  - Frozen row dataclasses matching Task 2's columns one to one: `CustomerRow`, `ProductRow`, `VariantRow`, `OrderRow`, `OrderItemRow`, `RefundRequestRow`, `RefundRequestItemRow`, `PayoutRow`, `ExchangeRow`
  - `@dataclass(frozen=True) Seed` with one tuple per table
  - `build_seed(seed: int = SEED, now: datetime = STORE_NOW) -> Seed`: pure, with no database access.
  - `order_facts(seed: Seed, order_id: str) -> OrderFacts`: builds the policy's input from seed rows. M3 writes the database version of it.
  - `SCENARIOS: tuple[Scenario, ...]`, where `Scenario(order_id, customer_index, rule, expect_refund: Verdict | None, expect_exchange: Verdict | None)`
- Numbers:
  - 40 products, 50 customers, 200 orders.
  - Order statuses: delivered 110, shipped 20, placed 15, rto 15, cancelled 15, returned 15, out_for_delivery 10. Scenarios count toward these.
  - Payment methods: about one third each of COD, UPI and card.
  - Scenarios are `ORD-1001` to `ORD-1025`, owned by customers 1–5 (the "continue as" picker set, D11). The filler is `ORD-1026` to `ORD-1200`, spread over all 50 customers.
  - Item IDs are `ITM-<order number>-<n>`.

The scenarios, one rule each (dates are relative to `STORE_NOW`):

| Order | Rule | Expected verdict at `STORE_NOW` |
|---|---|---|
| 1001 | delivered 2 days ago, UPI, 1 tee | refund eligible, original payment |
| 1002 | delivered 3 days ago, COD, 2 items, coupon | partial refund eligible, store credit, coupon share deducted |
| 1003 | delivered 10 days ago | `window_expired` |
| 1004 | delivered 7 calendar days ago (last day) | eligible |
| 1005 | delivered 8 calendar days ago | `window_expired` |
| 1006 | socks, inside the window | `non_returnable` |
| 1007 | innerwear plus tee, inside the window | mixed: not eligible as a whole |
| 1008 | final-sale dress | `non_returnable` |
| 1009 | custom-printed tee | `non_returnable` |
| 1010 | delivered 1 day ago (damage report still in time) | eligible; `damage_report_in_time` True |
| 1011 | prepaid RTO, card, 2 items | whole-order refund including shipping |
| 1012 | COD RTO | `cod_rto_nothing_to_refund` |
| 1013 | placed (cancellation goes to a human) | `not_delivered` |
| 1014 | shipped | `not_delivered` |
| 1015 | out for delivery | `not_delivered` |
| 1016 | cancelled | `order_cancelled` |
| 1017 | returned, with a paid-out refund | `already_requested` |
| 1018 | delivered, with a pending refund request | `already_requested` |
| 1019 | delivered, with an approved request and no payout yet | `already_requested` |
| 1020 | delivered, with a rejected refund request | eligible again |
| 1021 | delivered, item already exchanged | refund `already_exchanged`, exchange `already_exchanged` |
| 1022 | delivered 2 days ago, the requested size has stock 0 | exchange `out_of_stock` |
| 1023 | delivered 2 days ago, the requested size in stock | exchange eligible |
| 1024 | delivered 4 days ago, UPI, 3 items, coupon | partial refund of 2 items, rounding case |
| 1025 | delivered 20 days ago, COD | `window_expired` |

- [ ] **Step 1: Write failing tests.**
  - `test_counts_and_status_mix`: exactly 40, 50 and 200, and the status counts above.
  - `test_every_status_and_payment_present`: all 7 statuses and all 3 payment methods appear.
  - `test_customer_fields_unique_and_fake`: names, phones, emails and addresses are unique. Every phone matches `^\+91 5\d{4} \d{5}$`, and every email ends in `@example.com`.
  - `test_build_is_deterministic`: `build_seed() == build_seed()`, and `build_seed(seed=1) != build_seed()`.
  - `test_scenarios_match_policy`: for each scenario, `decide_refund` (all its items) or `decide_exchange` at `STORE_NOW` gives the expected verdict in the table.
  - `test_seeded_amounts_come_from_policy`: every seeded refund request's amount equals `decide_refund`'s amount for its items, computed as if no lock existed.
  - `test_no_store_name_in_seed`: no string field in the seed contains `saanjh`, ignoring case (the store-name note).
  - `test_rows_satisfy_schema_rules`: no item is in two non-rejected requests, there's at most one exchange per item, and `delivered_at` is set if and only if the status is delivered or returned. This mirrors Task 2's constraints, so a bad seed fails here first with a clear message.
- [ ] **Step 2: Run them. Expect failures.**
- [ ] **Step 3: Implement.**
  - The filler uses only `random.Random(seed)`.
  - Every timestamp is derived from `now`.
  - Seeded refund requests, payouts and exchanges carry explicit `created_at` values (never `now()` from the database), so the table hashes in Task 5 stay identical.
- [ ] **Step 4: Run all the checks.** Expected: they all pass.
- [ ] **Step 5: The owner reviews** `scenarios.py`, plus a printed sample of 10 customers and 10 filler orders, before committing. (The owner checks the Hinglish naturalness later in M5; there's no customer-facing text here.)
- [ ] **Step 6: Commit.** `git commit -m "feat(seed): fixed-seed store builder with 25 named scenarios"`

### Task 5: Loading the seed and the reset script

**Files:**
- Create: `backend/src/support/seed/load.py`, `backend/src/support/db/reset.py`
- Test: `backend/tests/db/test_reset.py`

**Interfaces:**
- Consumes: `build_seed`, `Seed`, `connect`, `database_url` and `describe_target`.
- Produces:
  - `load_seed(conn, seed: Seed) -> None`: inserts with explicit IDs, then sets every identity sequence in `store` to `max(id)`.
  - `reset_store(conn, seed: Seed | None = None) -> None`: one transaction. It truncates every table in schema `store` (`TRUNCATE … RESTART IDENTITY CASCADE`) and then calls `load_seed`. The table list is read from `pg_tables WHERE schemaname = 'store'`, never kept by hand (D10, option B's rejection reason).
  - `table_hashes(conn, schema: str = "store") -> dict[str, str]`: `md5(string_agg(t::text, '|' ORDER BY t::text))` for each table.
  - CLI: `uv run python -m support.db.reset` prints `resetting store on <describe_target(url)>`, then the row counts.
- Also: `conftest.py`'s `fresh_db` now resets the store after the migrations. The Task 2 tests switch their base rows to scenario orders where that makes them shorter. Optional; leave them alone if it doesn't help.

- [ ] **Step 1: Write failing tests** (marked `db`, using their own autocommit connection).
  - `test_reset_twice_identical_hashes`: reset, hash, reset, hash, and the two hash sets are equal (milestones M2 verify).
  - `test_reset_restarts_identity`: after a reset, insert a refund request; after a second reset, insert the same request; it gets the same `id` both times, and that `id` is the seeded maximum plus 1 (D10 note, spec §4 A6).
  - `test_reset_clears_runtime_rows`: rows added to `sessions`, `handoffs` and `refund_requests` after a reset are gone after the next one.
  - `test_reset_keeps_log_rows`: a row in `log.llm_calls` survives a reset (D10). This test is added in Task 6, once that table exists.
  - `test_db_counts_match_seed`: the row counts in the database equal the lengths of the `Seed` tuples.
- [ ] **Step 2: Run them. Expect failures.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run all the checks**, then run the CLI once against `support_dev`. Expected: the tests pass, and the CLI prints the target without a password and the counts 50 / 40 / 200.
- [ ] **Step 5: Commit.** `git commit -m "feat(db): seed loader and deterministic reset (RESTART IDENTITY)"`

### Task 6: The `log` schema, and the wrapper logging to `log.llm_calls` (D8, D10)

**Files:**
- Create: `backend/src/support/db/migrations/002_log.sql`, `backend/src/support/db/llm_log.py`
- Modify: `backend/src/support/llm/wrapper.py` (`invoke_with_record` gets `on_record`), `backend/tests/db/test_reset.py` (add `test_reset_keeps_log_rows`)
- Test: `backend/tests/db/test_llm_log.py`, plus additions to `backend/tests/llm/test_wrapper.py`

**Interfaces:**
- Produces these tables in schema `log`. None has a foreign key into `store`.
  - `conversations (id, customer_id bigint (plain value), run_id text null, test_id text null, architecture text null CHECK IN ('router','single'), created_at)`
  - `messages (id, conversation_id FK, seq int, role CHECK IN ('user','assistant','tool','system'), content text, tool_calls jsonb null, created_at, UNIQUE (conversation_id, seq))`
    - `tool_calls jsonb` keeps the raw calls as received, which covers the M1 review's carried-forward item 2.
  - `tool_calls (id, conversation_id FK, message_id FK null, turn int, tool_name text, args jsonb, result jsonb, error_class text null CHECK IN ('not_found','invalid_argument','not_allowed'), created_at)`
    - These are D14's counting classes plus the allow-list rejection. M3 may add values in a new migration.
  - `llm_calls (id, conversation_id FK null, provider, model, input_tokens int null, output_tokens int null, latency_ms double precision, error_class text null CHECK IN ('rate_limit','server','timeout','tool_use_failed'), failed_generation text null, created_at)`
  - Also in the same migration: `ALTER TABLE store.handoffs ADD FOREIGN KEY (conversation_id) REFERENCES log.conversations (id)` (D10 allows `store → log`).
- `insert_llm_call(conn, record: CallRecord, conversation_id: int | None = None) -> int`: returns the new row's ID.
- `invoke_with_record(model, messages, cfg, *, on_record: Callable[[CallRecord], None] | None = None)`: calls `on_record` once for every `CallRecord` it produces (a success, a retryable error, or `tool_use_failed`), before returning. An unclassified exception still propagates without a record, as before. If `on_record` itself raises, the error propagates: a call that wasn't logged must not look as if it was (D4 needs complete token counts). The M4 graph supplies `lambda r: insert_llm_call(conn, r, conversation_id)`. The wrapper never imports `support.db`.

- [ ] **Step 1: Write failing tests.**
  - `test_on_record_called_for_success_and_retryable_error` (no database, with M1's fake model): one call per invoke, carrying the same record that's returned.
  - `test_on_record_error_propagates`
  - `test_wrapper_does_not_import_db`: in a fresh subprocess, importing `support.llm.wrapper` leaves `support.db` and `psycopg` out of `sys.modules`.
  - `test_insert_llm_call_round_trip` (`db`): the values read back equal the record's values, including `None` tokens (never written as 0) and `failed_generation`.
  - `test_llm_call_error_class_check` (`db`): `'oops'` raises `CheckViolation`. Also, using the same constraint reader as `test_enums_match_check_constraints`, the `llm_calls.error_class` `CHECK` list equals `get_args(ErrorClass)` from the wrapper.
  - `test_log_has_no_fk_into_store` (`db`): a query on `information_schema.table_constraints` / `constraint_column_usage` finds no foreign key from `log` into `store` (D10 tightening 1).
  - `test_reset_keeps_log_rows` (`db`, in `test_reset.py`).
- [ ] **Step 2: Run them. Expect failures.**
- [ ] **Step 3: Implement.** The M1 runner (`evals/model_check/run_check.py`) is unchanged: `on_record` defaults to `None`, and all 139 existing tests must still pass.
- [ ] **Step 4: Run all the checks.** Expected: they all pass, and CI passes with the Postgres service.
- [ ] **Step 5: Commit.** `git commit -m "feat(db): log schema; wrapper logs each call to log.llm_calls (D8)"`

### Task 7: Close M2

- [ ] **Step 1: The fresh whole-branch review** on the most capable model, as in M1. Report its findings before fixing anything.
- [ ] **Step 2: Record what M2 decided and deferred** in this plan:
  - anything decided during the build;
  - the demo's "now" question, for M7;
  - the store rename, required before M4.

  (The six decision answers and D15 are already recorded.)
- [ ] **Step 3: The owner approves the new context.md §10 wording.** Then edit it (context.md is git-ignored, so the edit stays local).
- [ ] **Step 4: Commit and push**, each with the owner's yes.

---

## M2 done when (from milestones.md)

- The policy unit tests pass (Task 3).
- Two resets give identical table hashes (Task 5).
- A test shows each constraint rejecting bad rows (Task 2, Task 6).
- CI passes with the Postgres service (Task 1, Task 6).
- The wrapper logs to `log.llm_calls` (Task 6).
