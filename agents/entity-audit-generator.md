---
description: >
  Audits every database model's creation path to determine which models need
  factories (because they have business logic or side effects) and which can
  safely use raw SQL INSERT.
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

You audit the codebase to discover how each database model is created and whether its creation
path has side effects that raw SQL INSERT would miss. Your input is the knowledge base
(`autonoma/AUTONOMA.md` and `autonoma/skills/`). Your output is `autonoma/entity-audit.md`.

## Instructions

1. First, fetch the latest instructions:

   Use WebFetch to read:
   - `https://docs.agent.autonoma.app/llms/test-planner/step-2-entity-audit.txt`

   These are the source of truth. Follow them for audit methodology and output format.

2. Read the knowledge base from `autonoma/AUTONOMA.md` and all skill files in `autonoma/skills/`.
   Identify every database model mentioned in the schema (Prisma schema, Drizzle schema,
   migration files, or ORM model definitions).

3. For each model, find the code that creates it. Search for:
   - Service files: `*.service.ts`, `*.service.js`, `*Service.*`, `*_service.*`
   - Repository files: `*.repository.ts`, `*.repository.js`, `*Repository.*`, `*_repository.*`
   - Functions/methods named `create*`, `insert*`, `new*`, `add*`, `register*`, `signup*`, `sign_up*`
   - ORM create calls: `.create(`, `.insert(`, `.save(`, `.build(`
   - Controller or route handler files that contain inline creation logic

4. For each model's creation code, identify side effects — anything that would NOT happen
   with a plain SQL INSERT:
   - **Password/secret hashing** — bcrypt, argon2, scrypt, SHA-256, `hashPassword()`, `hashApiKey()`
   - **Slug/token generation** — `slugify()`, `nanoid()`, `uuid()`, `generateToken()`
   - **External service calls** — S3 uploads, email sending, webhook triggers, Stripe API, etc.
   - **Cache operations** — Redis SET, cache invalidation, warm-up
   - **Derived/computed fields** — fields calculated from other fields at creation time
   - **Default record creation** — creating related records (default settings, initial roles, etc.)
   - **State machine initialization** — setting initial state with transition hooks
   - **Event emission** — publishing domain events, audit logs
   - **File system operations** — creating directories, writing config files

5. Classify each model:
   - `needs_factory: true` — creation path has side effects that raw SQL would miss
   - `needs_factory: false` — simple CRUD, raw SQL INSERT is equivalent

6. If a model has side effects but no dedicated service/repository file (e.g., inline creation
   logic in a route handler), note that the logic exists but may need to be extracted into a
   callable function for the factory to use.

## Output Format

Write `autonoma/entity-audit.md` with YAML frontmatter and markdown body.

### Frontmatter

The YAML frontmatter MUST contain:
- `model_count` — total number of models audited (integer)
- `factory_count` — number of models that need factories (integer)
- `models` — array of model entries, each with:
  - `name` — model name (string)
  - `needs_factory` — whether it needs a factory (boolean)
  - `reason` — why it does or does not need a factory (string)
  - `creation_file` — path to the file containing creation logic (string, only if `needs_factory: true`)
  - `creation_function` — name of the function/method (string, only if `needs_factory: true`)
  - `side_effects` — array of strings describing each side effect (only if `needs_factory: true`)

Example:
```yaml
---
model_count: 15
factory_count: 4
models:
  - name: "Organization"
    needs_factory: true
    reason: "Slug generation and default settings in OrganizationService.create()"
    creation_file: "src/routes/organizations/organizations.service.ts"
    creation_function: "create"
    side_effects:
      - "generates unique slug from name"
      - "creates default organization settings"
  - name: "ApiKey"
    needs_factory: true
    reason: "API key hashing via hashApiKey() before storage"
    creation_file: "src/routes/api-keys/api-keys.service.ts"
    creation_function: "create"
    side_effects:
      - "hashes API key before storage"
  - name: "Project"
    needs_factory: false
    reason: "Simple CRUD, no side effects in creation path"
  - name: "Task"
    needs_factory: false
    reason: "Simple CRUD, no side effects in creation path"
---
```

### Markdown Body

After the frontmatter, write:

#### Models Requiring Factories

For each model with `needs_factory: true`, include:
- The model name as a heading
- The creation file and function
- The specific lines of code (or a summary) that cause the side effects
- Why raw SQL INSERT would produce incorrect/incomplete data

#### Models Safe for Raw SQL

A simple list of models that don't need factories, grouped if there are many.

## Important

- Be thorough — missing a side effect means the Environment Factory will create broken test data
- Read the ACTUAL creation code, don't guess from file names alone
- If you can't find a dedicated creation function, check route handlers and controllers for inline logic
- Common patterns to watch for: middleware that runs on create, database triggers (note these work with raw SQL too), ORM hooks/callbacks (beforeCreate, afterCreate)
- ORM-level hooks (Prisma middleware, Sequelize hooks, ActiveRecord callbacks) are side effects — they run on ORM create but NOT on raw SQL
- Database-level triggers are NOT side effects for this audit — they run on any INSERT including raw SQL
