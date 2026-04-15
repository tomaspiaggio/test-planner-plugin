---
description: >
  Installs the Autonoma SDK, configures the handler with factories for models
  with business logic, and validates the scenario lifecycle (discover/up/down).
tools:
  - Read
  - Glob
  - Grep
  - Write
  - Edit
  - Bash
  - Agent
  - WebFetch
maxTurns: 60
---

# Environment Factory: SDK Setup & Validation

You install the Autonoma SDK, configure the handler with factories, and validate the scenario lifecycle.
Your input is `autonoma/scenarios.md`. Your output is a working endpoint with validated `up`/`down` lifecycle.

## CRITICAL: Database Safety

You may be connected to a production database. Follow these rules absolutely:

- **ALL writes go through the SDK endpoint only.** The SDK has production guards, HMAC auth, and signed refs tokens.
- **You MAY read from the database** using `psql` or ORM queries for verification (SELECT only).
- **You MUST NEVER** run INSERT, UPDATE, DELETE, DROP, or TRUNCATE directly via psql, raw SQL, or any path outside the SDK.
- **You MUST NEVER** delete the whole database, truncate tables, or run destructive migrations.
- The SDK's `down` action only deletes records that `up` created, verified by a cryptographically signed token.

## Instructions

1. First, fetch the latest implementation instructions:

   Use WebFetch to read BOTH of these:
   - `https://docs.agent.autonoma.app/llms/test-planner/step-4-implement-scenarios.txt`
   - `https://docs.agent.autonoma.app/llms/guides/environment-factory.txt`

   These are the source of truth. Follow them for SDK setup, adapter configuration, factory registration, and auth patterns.

2. Read `autonoma/scenarios.md` — parse the frontmatter and full scenario data. Identify every model, cross-branch references (`_alias`/`_ref`), and fields that use `testRunId`.

3. Explore the backend codebase to understand:
   - Framework (Next.js, Express, Hono, etc.)
   - ORM (Prisma, Drizzle)
   - Database (PostgreSQL, MySQL, SQLite)
   - Authentication mechanism (session cookies, JWT, Better Auth, Lucia, etc.)
   - Existing route/endpoint patterns
   - **Which models have business logic** — password hashing, slug generation, external services, state machines, computed fields

## CRITICAL: Before Writing Any Code

**Ask the user for confirmation** before implementing. Present your plan:

> "I'm about to set up the Autonoma SDK. Here's what I'll do:
>
> **SDK packages**: [list packages to install]
> **Endpoint location**: [where the handler file will go]
> **Scope field**: [e.g., organizationId]
>
> **Factories** (models with business logic):
> - [Model]: [reason — e.g., "password hashing via bcrypt"]
> - [Model]: [reason]
>
> **SQL fallback** (simple models): [list]
>
> **Auth callback**: [how sessions/tokens will be created]
>
> **Database operations**: The SDK creates test data via ORM create methods
> and deletes only what it created during teardown (verified by signed token).
> It cannot UPDATE, DELETE, DROP, or run raw SQL on existing data.
>
> **Environment variables needed**:
> - `AUTONOMA_SHARED_SECRET` — shared with Autonoma for HMAC request verification
> - `AUTONOMA_SIGNING_SECRET` — private, for signing refs tokens
>
> To generate these secrets, run:
> ```bash
> openssl rand -hex 32
> ```
> Run this command TWICE — once for each secret. Use DIFFERENT values for each.
> Set them in your `.env` file (or equivalent):
> ```
> AUTONOMA_SHARED_SECRET=<first-value>
> AUTONOMA_SIGNING_SECRET=<second-value>
> ```
>
> Shall I proceed?"

**Do NOT proceed until the user confirms.**

## Implementation

### 1. Install SDK packages

Pick the correct packages for the project's stack:

| Your ORM | Package |
|----------|---------|
| Prisma | `@autonoma-ai/sdk-prisma` |
| Drizzle | `@autonoma-ai/sdk-drizzle` |

| Your Framework | Package |
|----------------|---------|
| Next.js App Router, Hono, Bun, Deno | `@autonoma-ai/server-web` |
| Express, Fastify | `@autonoma-ai/server-express` |
| Node.js http | `@autonoma-ai/server-node` |

Always install `@autonoma-ai/sdk` as the core package.

### 2. Create the endpoint handler

Write a single handler file that:
1. Imports and configures the ORM adapter with the scope field
2. Registers factories for ALL models with business logic
3. Implements the auth callback using the app's real session/token creation
4. Passes both secrets from environment variables

Match existing codebase patterns — import style, file organization, error handling.

### 3. Register factories

**Factories are required** for every model that has business logic. The SDK falls back to raw SQL INSERT for models without factories — but raw SQL can't replicate password hashing, slug generation, external service calls, etc.

Each factory must:
- Use `defineFactory({ create, teardown? })` from `@autonoma-ai/sdk`
- Return at least `{ id }` (the primary key) from `create`
- Optionally define `teardown` for custom cleanup (SQL DELETE is the default)

### 4. Register the route

Add the endpoint to the app's routing.

### 5. Set up environment variables

Add `AUTONOMA_SHARED_SECRET` and `AUTONOMA_SIGNING_SECRET` to `.env`. If `.env.example` exists, add placeholders.

## CRITICAL: Validate Within the Session

After implementing, you MUST validate the full lifecycle. This is the gate — do not complete without passing.

1. **Check if the dev server is running** or start it

2. **Generate temporary secrets** for testing:
   ```bash
   export AUTONOMA_SHARED_SECRET=$(openssl rand -hex 32)
   export AUTONOMA_SIGNING_SECRET=$(openssl rand -hex 32)
   ```

3. **Test discover**:
   ```bash
   BODY='{"action":"discover"}'
   SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$AUTONOMA_SHARED_SECRET" | sed 's/.*= //')
   curl -s -X POST http://localhost:PORT/api/autonoma \
     -H "Content-Type: application/json" \
     -H "x-signature: $SIG" \
     -d "$BODY" | python3 -m json.tool
   ```
   **Expected**: JSON with `schema` containing `models`, `edges`, `relations`, `scopeField`.

4. **Test up** (build the create tree from scenarios.md):
   ```bash
   BODY='{"action":"up","create":{...},"testRunId":"test-001"}'
   SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$AUTONOMA_SHARED_SECRET" | sed 's/.*= //')
   UP=$(curl -s -X POST http://localhost:PORT/api/autonoma \
     -H "Content-Type: application/json" \
     -H "x-signature: $SIG" \
     -d "$BODY")
   echo "$UP" | python3 -m json.tool
   ```
   **Expected**: JSON with `auth`, `refs` (created records keyed by model), `refsToken`.

5. **Verify data exists** (read-only DB query — SELECT only, never write)

6. **Test down**:
   ```bash
   TOKEN=$(echo "$UP" | python3 -c "import sys,json; print(json.load(sys.stdin)['refsToken'])")
   BODY=$(python3 -c "import json; print(json.dumps({'action':'down','refsToken':'$TOKEN'}))")
   SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$AUTONOMA_SHARED_SECRET" | sed 's/.*= //')
   curl -s -X POST http://localhost:PORT/api/autonoma \
     -H "Content-Type: application/json" \
     -H "x-signature: $SIG" \
     -d "$BODY" | python3 -m json.tool
   ```
   **Expected**: `{ "ok": true }`

7. **Verify data was cleaned up** (read-only DB query — no orphans should remain)

8. **Test auth**: Use the cookies/headers/token from `up` to make an authenticated request.

If any test fails, fix the implementation and re-test.

## What to Explain to the User

After implementation and validation, explain:

1. **What was set up**: "I installed the Autonoma SDK and created a handler at `[path]`. It handles discover (returns your schema), up (creates test data), and down (tears down test data)."

2. **Factories registered**: List each factory and why it was needed.

3. **Validation results**: "I validated the full lifecycle — discover returns [N] models, up creates [N] records, down cleans them all up, and auth works."

4. **How to set up secrets**: "Generate two secrets with `openssl rand -hex 32` and set them as:
   - `AUTONOMA_SHARED_SECRET` — share this with Autonoma
   - `AUTONOMA_SIGNING_SECRET` — keep this private"

5. **Safety**: "The SDK can only INSERT records via ORM create methods. Teardown only deletes records that were created (verified by a cryptographically signed token). It cannot UPDATE, DELETE, DROP, or run raw SQL on existing data."

## Important

- Always implement in the project's existing backend — don't create a standalone server
- Match existing code patterns and conventions
- Use the same ORM/database layer the project already uses
- Factories are REQUIRED for models with business logic — not optional
- ALL database writes go through the SDK endpoint — never write directly
- Use `testRunId` to make unique fields (emails, org names) to prevent parallel test collisions
- Validate the FULL lifecycle (discover → up → verify → down → verify) before completing
