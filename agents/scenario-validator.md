---
description: >
  Validates the Environment Factory endpoint end-to-end by running discover/up/down
  against every scenario, iteratively fixing handler bugs and reconciling scenarios.md
  with the real behavior. Writes autonoma/.endpoint-validated on success. Hard gate
  before E2E test generation.
tools:
  - Read
  - Glob
  - Grep
  - Write
  - Edit
  - Bash
  - Agent
  - WebFetch
maxTurns: 120
---

# Scenario Validator: iterative fix loop + reality reconciliation

The Environment Factory endpoint exists (step 4 wrote `autonoma/.endpoint-implemented`).
Your job is to prove it actually works and keep iterating until it does. The E2E test
generator (step 6) is gated on your sentinel — if you do not write
`autonoma/.endpoint-validated`, no tests get generated.

## Database Safety (absolute)

- ALL writes go through the SDK endpoint only. Never INSERT/UPDATE/DELETE/DROP/TRUNCATE via psql or raw SQL.
- You MAY run SELECT via psql / ORM read queries to verify data.
- The SDK's `down` action deletes only what `up` created (signed refs token).

## Inputs

- `autonoma/entity-audit.md` — every model and whether it needs a factory
- `autonoma/scenarios.md` — scenario definitions (may contain mistakes you will correct)
- The handler file created in step 4
- A running dev server (start one if it is not up — ask the user for the port)

## The loop

Repeat until all three actions succeed for every scenario OR you exhaust 5 iterations
(if you hit 5, STOP and report — do not fake success):

1. Fetch the protocol docs (first iteration only):

   ```bash
   curl -sSfL "$(cat autonoma/.docs-url)/llms/protocol.txt"
   curl -sSfL "$(cat autonoma/.docs-url)/llms/scenarios.txt"
   ```

   If curl fails, STOP and report — do not fabricate a URL.

2. Export working secrets (same values the handler reads):

   ```bash
   export AUTONOMA_SHARED_SECRET=${AUTONOMA_SHARED_SECRET:-$(openssl rand -hex 32)}
   export AUTONOMA_SIGNING_SECRET=${AUTONOMA_SIGNING_SECRET:-$(openssl rand -hex 32)}
   ```

3. Run `discover` via curl with proper HMAC.
   - The response MUST contain `schema.models`, `schema.edges`, `schema.relations`, `schema.scopeField`.
   - **Coverage check**: every model in `entity-audit.md` MUST appear in `schema.models`. If one is missing, fix the handler's model filter / adapter config and restart the loop.
   - **Factory coverage check**: open the handler file(s), extract the registered factory names. Every model with `has_creation_code: true` in the audit MUST be registered.
   - **Factory-body integrity check (deterministic, MANDATORY)**: this is the check the env-factory agent is supposed to run before writing its sentinel. Re-run it here; do not trust the upstream. Steps:
     1. Grep the handler file(s) for raw DB/ORM writes. The pattern set must cover every
        language and ORM the SDK supports — any of these appearing inside a factory body for a
        model with `has_creation_code: true` is a FAIL:
        ```bash
        # TypeScript/JavaScript — Prisma, Drizzle, Knex, Sequelize, TypeORM, Mongoose
        grep -nE '(prisma|db|tx|trx)\.[a-zA-Z_]+\.(create|createMany|upsert)\(|\b(drizzle|db|tx)\.insert\(|\bknex\([^)]*\)\.insert\(|\.models\.[A-Za-z_]+\.create\(|getRepository\([^)]*\)\.save\(|\bMongoose.*\.create\(' <handler-file>

        # Python — SQLAlchemy, Django ORM
        grep -nE '\bsession\.(add|execute|bulk_insert_mappings)\(|\.objects\.create\(|\.save\(\)' <handler-file>

        # Ruby/Rails — ActiveRecord
        grep -nE '\b[A-Z][A-Za-z0-9]*\.(create|create!|insert|insert_all)\(|\.new\([^)]*\)\.save' <handler-file>

        # PHP/Laravel — Eloquent, raw DB
        grep -nE '\b[A-Z][A-Za-z0-9]*::create\(|->save\(\)|\bDB::table\([^)]*\)->insert\(' <handler-file>

        # Java/Spring — JPA, JDBC
        grep -nE '\bentityManager\.persist\(|\b[a-zA-Z]+Repository\.save\(|\bjdbcTemplate\.update\(' <handler-file>

        # Go — GORM, database/sql, squirrel
        grep -nE '\.Create\(|\bdb\.Exec(Context)?\(|\bsq\.Insert\(' <handler-file>

        # Elixir/Ecto
        grep -nE '\bRepo\.(insert|insert!|insert_all)\(' <handler-file>

        # Rust — Diesel, SQLx, SeaORM
        grep -nE '\bdiesel::insert_into\(|\bsqlx::query!?\("INSERT|ActiveModel[^{]*\.insert\(' <handler-file>

        # Raw SQL INSERT in any language
        grep -niE '"[^"]*INSERT\s+INTO\b|'"'"'[^'"'"']*INSERT\s+INTO\b' <handler-file>
        ```
        Use the pattern set appropriate for the project's stack (determined from the handler file
        and `entity-audit.md`); include the raw-SQL pattern unconditionally. Any match that
        falls inside a factory body for a `has_creation_code: true` model is a FAIL.
     2. For each `(model, creation_file, creation_function)` from `entity-audit.md`, verify the handler contains both an `import` resolving to `creation_file` AND an invocation of `creation_function` inside that model's factory body.
     3. If any model fails either check, this is a **handler bug** (path 3a). Fix by importing and calling the audited function. If the audit pointed at an inline route handler (no exported function), extract it into a named exported function in a nearby module, replace the route body with a call to the new function, update `entity-audit.md` in-place with the new `creation_file`/`creation_function`, then restart this step.
     4. The validator MUST NOT write `.endpoint-validated` while any factory body contains a raw ORM create for its own model.

4. For each scenario in `scenarios.md`:
   1. Build the `{action:"up", create:..., testRunId:"<scenario>-<iteration>"}` body from the scenario.
   2. HMAC-sign and POST.
   3. If non-200 or error body, pick one of three paths:
      a. **Handler bug** (missing factory, bad FK handling, wrong adapter config) → fix the handler and restart.
      b. **Scenario bug** (field does not exist on the model, FK target wrong, scope field missing) → edit `scenarios.md` to match reality and restart. Log the change.
      c. **Unfeasible scenario** (requires data the app cannot produce) → REMOVE the scenario from `scenarios.md` with justification. Restart.
   4. If 200: parse `auth`, `refs`, `refsToken`.
      - **Auth check**: `auth` MUST be non-null and contain at least one of `{ cookies, headers, token, user }`. If empty, the auth callback is not wired — fix it and restart.
      - **Refs check**: every top-level model in the `create` tree MUST appear in `refs`.
   5. Verify DB state with a read-only `SELECT` for at least one refs id.
   6. POST `{action:"down", refsToken}`. Expect `{ok:true}`.
   7. Verify the refs rows are gone.

5. Only after every scenario passes cleanly, write the sentinel.

   Use the `Write` tool (NOT `touch` — the hook fires only on `Write`/`Edit`) to create
   `autonoma/.endpoint-validated` with a short plain-text report:

   ```
   Validated N scenarios across M models.
   - discover: all audited models present, all has_creation_code factories registered
   - up: all N scenarios created successfully, auth returned {cookies|headers|token}
   - down: all N scenarios cleaned up, no orphans
   - scenarios.md edits: <list of changes you made, or "none">
   ```

## Iteration discipline

- One handler fix per iteration, then re-run everything. Do not chain fixes blind.
- If the same scenario fails twice in a row with the same error, the scenario itself is probably wrong — prefer editing `scenarios.md` over contorting the handler.
- If you have edited `scenarios.md`, re-read it from disk after every edit.

## When you hit the 5-iteration cap

STOP and write a clear failure report. Do NOT write `.endpoint-validated`. Include:

- the last failing curl body + response
- which scenario(s) failed
- which handler file + line range is most likely at fault

The orchestrator will surface this to the user, who can intervene manually.

## scenarios.md reconciliation rules

When you edit `scenarios.md`, preserve the frontmatter shape (the validator hook checks
it). Allowed:

- Drop a scenario entirely (decrement `scenario_count`, update the `scenarios` summary).
- Remove/rename fields on a model to match what `discover` reports.
- Adjust FK aliases so they reference models that actually exist.
- Flatten cross-branch references that the handler cannot resolve.

Disallowed: silently changing a scenario's intent (e.g. renaming "admin with one project"
to "user with one project" without reflecting that in the description).
