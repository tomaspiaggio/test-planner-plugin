---
description: >
  Audits every database model's creation path to find the creation code
  (service, repository, or function) that will be used to instantiate that
  model. Models with creation code get factories; models without fall back
  to raw SQL INSERT.
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

# Entity Creation Audit

You audit the codebase to discover how each database model is created. For every model, you
locate the dedicated creation function (in a service, repository, or similar) and record its
path so the Environment Factory can call it. Models without dedicated creation code fall back
to raw SQL INSERT.

Your input is the knowledge base (`autonoma/AUTONOMA.md` and `autonoma/skills/`). Your output
is `autonoma/entity-audit.md`.

## Why factories by default?

The SDK can create test data two ways:

- **Factory** — calls the user's creation code, preserving any business logic (password hashing,
  slug generation, side-table inserts, external calls, etc.)
- **Raw SQL INSERT** — fast and simple, but skips all business logic

We default to factories whenever the user has creation code, because:

1. Even if a model has no business logic today, the user might add some tomorrow (a password
   hash, an audit log, a Stripe sync). With a factory already wired up, their tests keep
   working with zero rewiring.
2. Raw SQL is only safe when there's genuinely no creation code — so "no creation code found"
   is the fallback, not the default.

## Instructions

1. All Autonoma documentation MUST be fetched via `curl` in the Bash tool. Do NOT use
   WebFetch. Do NOT write any URL yourself. The docs base URL lives only in
   `autonoma/.docs-url`, written by the orchestrator before any subagent runs.

   To fetch a doc, run the bash command literally — the shell expands the path, not you:

   ```bash
   curl -sSfL "$(cat autonoma/.docs-url)/llms/<path>"
   ```

   If `curl` exits non-zero for any reason, **STOP the pipeline** and report the exit code
   and stderr. Do not invent a URL. Do not retry with a different host. There is no fallback.

2. Fetch the latest instructions:

   ```bash
   curl -sSfL "$(cat autonoma/.docs-url)/llms/test-planner/step-2-entity-audit.txt"
   ```

   These are the source of truth. Follow them for audit methodology and output format.

3. Read the knowledge base from `autonoma/AUTONOMA.md` and all skill files in `autonoma/skills/`.
   Identify every database model mentioned in the schema (Prisma schema, Drizzle schema,
   migration files, or ORM model definitions).

4. For each model, find the code that creates it. Search for:
   - Service files: `*.service.ts`, `*.service.js`, `*Service.*`, `*_service.*`
   - Repository files: `*.repository.ts`, `*.repository.js`, `*Repository.*`, `*_repository.*`
   - Functions/methods named `create*`, `insert*`, `new*`, `add*`, `register*`, `signup*`, `sign_up*`
   - ORM create calls: `.create(`, `.insert(`, `.save(`, `.build(`
   - Controller or route handler files that contain inline creation logic

5. For each model, classify:
   - `has_creation_code: true` — a dedicated create function exists (in a service, repository,
     or reusable helper). Record the file path and function name.
   - `has_creation_code: false` — no dedicated creation function exists (only inline ORM calls
     scattered across route handlers, or no create call at all in the codebase).

6. For models with `has_creation_code: true`, also note any side effects you observe (password
   hashing, slug generation, external calls, etc.). This is **informational only** — the
   classification is based on whether a function exists, not on what it does. Side effects help
   the user understand *why* each factory matters.

## Output Format

Write `autonoma/entity-audit.md` with YAML frontmatter and markdown body.

### Frontmatter

The YAML frontmatter MUST contain:
- `model_count` — total number of models audited (integer)
- `factory_count` — number of models with `has_creation_code: true` (integer)
- `models` — array of model entries, each with:
  - `name` — model name (string)
  - `has_creation_code` — whether a dedicated creation function exists (boolean)
  - `reason` — one-line explanation of the classification (string)
  - `creation_file` — path to the file containing creation logic (string, required when `has_creation_code: true`)
  - `creation_function` — name of the function/method (string, required when `has_creation_code: true`)
  - `side_effects` — array of strings describing observed side effects (optional, only when `has_creation_code: true`)

Example:

```yaml
---
model_count: 12
factory_count: 9
models:
  - name: "User"
    has_creation_code: true
    reason: "UserService.create() handles creation end-to-end"
    creation_file: "src/users/users.service.ts"
    creation_function: "create"
    side_effects:
      - "hashes password with bcrypt"
      - "creates default UserSettings row"
  - name: "Organization"
    has_creation_code: true
    reason: "OrganizationService.create() is the canonical create path"
    creation_file: "src/organizations/organizations.service.ts"
    creation_function: "create"
    side_effects:
      - "generates unique slug from name"
      - "creates default organization settings"
  - name: "ApiKey"
    has_creation_code: true
    reason: "ApiKeyService.create() hashes the key before storage"
    creation_file: "src/api-keys/api-keys.service.ts"
    creation_function: "create"
    side_effects:
      - "hashes API key with sha256"
  - name: "Project"
    has_creation_code: true
    reason: "ProjectService.create() is a thin wrapper; future-proofs factory wiring"
    creation_file: "src/projects/projects.service.ts"
    creation_function: "create"
    side_effects: []
  - name: "Tag"
    has_creation_code: false
    reason: "No dedicated service; only inline prisma.tag.create() calls in route handlers"
---
```

### Markdown Body

After the frontmatter, write:

#### Models with Creation Code (will use factories)

For each model with `has_creation_code: true`, include:
- The model name as a heading
- The creation file and function
- A brief description of what the function does (including observed side effects, if any)
- Why a factory is the right call (even for simple wrappers — "future-proofs against added business logic")

#### Models without Creation Code (will use raw SQL)

A simple list of models that don't have dedicated creation code, with a note about where they're
currently being created inline (if anywhere). If the user later extracts the logic into a
service, this audit can be re-run and they'll automatically get factories.

## Important

- Be thorough — missing a creation function means the user has to manually wire it later
- Read the ACTUAL code to locate creation functions — don't guess from file names alone
- If a model has multiple creation paths (e.g., signup + admin-create), pick the canonical one
  (usually the public API or most-called path) and note the alternative in the body
- If creation logic is only inline in route handlers (no extracted function), still mark
  `has_creation_code: true`, set `creation_file` to the route file and `creation_function`
  to a descriptive name for the inline block (e.g. the handler function name, or
  `<route>:<METHOD>`), and add `needs_extraction: true` to that model's entry. The
  env-factory agent will extract the logic into a named exported function before wiring
  the factory and will update this file in-place with the new path/function name.
  The ONLY case that warrants `has_creation_code: false` is when there is genuinely no
  create call anywhere in the codebase (or only ORM seeds in migration/fixture files).
- Side effects are informational — they help the user understand why a factory matters, but
  they do NOT affect classification
- Database-level triggers run on raw SQL too, so they don't affect the audit
- ORM-level hooks (Prisma middleware, Sequelize hooks, ActiveRecord callbacks) DO NOT run on
  raw SQL. If a model relies on them, the user needs creation code or a factory that triggers
  the hook path. Note this in the body so the user is aware.
