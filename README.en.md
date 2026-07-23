# MarkSpace

[한국어](README.md) · **English**

> A small, closed-team collaborative document service — like Notion, but only the essentials.

MarkSpace is a hierarchical markdown collaboration tool for controlled environments with **no self sign-up** — every account is provisioned and managed manually by a single **admin**. It provides workspace-scoped permissions, unlimited version snapshots, a predictable trash model (no-absorption bundles), edit locking, and read-only share links.

This project was built with Claude Code and the **cc-sdd (Spec-Driven Development)** methodology. Requirements/design/task artifacts live in [`.kiro/specs/`](.kiro/specs/), and project-wide rules live in [`.kiro/steering/`](.kiro/steering/).

> Note: In-repo specs and steering documents are authored in Korean by project convention.

---

## Features

- **Workspace-based collaboration** — Users belong to one or more workspaces with an owner/member role. Edit and management permissions exist only at the workspace level (no per-document permissions), while reading documents, attachments, and versions is globally open to any authenticated active user (regardless of membership).
- **Versioning** — Every document save creates a snapshot (version), retained indefinitely. There is no rollback (restoring a past version).
- **Three-stage document lifecycle** — `active → trashed → deleted`. Deletion captures the subtree at that moment as a **"bundle"** under a *no-absorption* model — deletions from different points in time are never merged, and each bundle has its own independent retention timer.
- **Edit locking** — Concurrent-edit conflicts are prevented via a lock (real-time co-editing/CRDT is out of scope). Locks have no automatic timeout; instead, a force-unlock UI is exposed only to the lock holder, the workspace owner, and the admin.
- **Read-only share links** — Documents are shared externally on a per-document basis, gated by the workspace's `is_shareable` flag.
- **Attachments/images** — Stored as files (not inline base64) and isolated per workspace.

## Tech Stack

| Area | Stack |
|------|-------|
| Backend | FastAPI · Python 3.13+ · SQLAlchemy 2 · Alembic · MySQL 8 |
| Frontend | React 19 · Vite 6 · Tailwind CSS 4 · React Router 6 · TypeScript |
| Editor | Toast UI Editor (edit = WYSIWYG + markdown toggle / read = single viewer-mode path) · KaTeX (math) |
| Auth | Session cookies (itsdangerous-signed) · Argon2id password hashing (pwdlib) |
| Runtime / packaging | **uv** for the backend, **npm** for the frontend |

## Project Structure

```
notion_lite/
├─ backend/            FastAPI app (uv project)
│  ├─ app/             Domain packages: auth · workspace · document · trash ·
│  │                   lock_version · attachment · sharing · admin_account · user_settings
│  ├─ migrations/      Alembic migrations (versions/0001~0004)
│  ├─ tests/           pytest suites (unit + integration L1~L6)
│  ├─ admin_cli.py     Admin account provisioning CLI (out-of-band ops tool)
│  ├─ config.yml       Non-secret configuration (single source)
│  └─ .env             Secret values (DB password, session secret; git-ignored)
├─ frontend/           React + Vite SPA
│  └─ src/
│     ├─ app/          Cross-cutting concerns: routing, global 401 interceptor (common layer)
│     ├─ shared/       Shared API client, UI, permission gating
│     └─ features/     auth · workspace · document · editor · attachment · sharing
├─ scripts/            start.ps1 / stop.ps1 (start/stop both dev servers at once)
└─ .kiro/              cc-sdd artifacts (steering + specs)
```

> Architectural principle: permission checks, document state transitions, and configuration access are each encapsulated in a **single owning layer** and never duplicated at call sites. See [`.kiro/steering/structure.md`](.kiro/steering/structure.md) for the full rules.

## Prerequisites

- **Python 3.13+** and [`uv`](https://docs.astral.sh/uv/)
- **Node.js 18+** (npm)
- **MySQL 8** (local instance, default `127.0.0.1:3306`)

## Setup & Run

### 1. Prepare the database

Create the databases per the defaults in `config.yml`.

```sql
CREATE DATABASE markspace CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE markspace_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;  -- for tests
```

### 2. Backend

```bash
cd backend

# Configure secrets (copy .env.example and fill in values)
cp .env.example .env
#   db_password=...            (MySQL password)
#   session_secret=...         (long random string)

# Install dependencies + apply DB schema migrations
uv sync
uv run alembic upgrade head

# Provision the admin account (there is no self sign-up, so the first
# account must be created via the CLI)
uv run admin_cli.py create --login-id admin --name "Administrator"
uv run admin_cli.py set-password --login-id admin

# Run the dev server
uv run uvicorn app.main:app --reload   # http://127.0.0.1:8000
```

> **Non-secret settings** (DB host/port, file storage paths, retention days, etc.) go in `config.yml`; **secret values** go only in `.env`. All modules access configuration exclusively through a shared pydantic-settings `Settings` object.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev            # http://127.0.0.1:5173 (/api → backend proxy)
```

### 4. Start both at once (Windows)

PowerShell scripts are provided to start/stop both servers in the background.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1   # backend :8000 + frontend :5173
powershell -ExecutionPolicy Bypass -File scripts\stop.ps1
```

## Testing

```bash
# Backend
cd backend && uv run pytest

# Frontend
cd frontend && npm test          # vitest
npm run typecheck                # tsc --noEmit
```

Backend integration tests use a cumulative checkpoint structure (`tests/integration_L1`~`L6`): as each spec layer is added, it verifies regressions against the contracts of the layers beneath it.

## Development Methodology (cc-sdd)

This repository follows Kiro-style **Spec-Driven Development**: work proceeds through `Steering → Requirements → Design → Tasks → Implementation`, with a human review gate at each stage.

- **Steering** (`.kiro/steering/`) — project-wide rules and context (product, tech, structure)
- **Specs** (`.kiro/specs/{feature}/`) — per-feature requirements, design, tasks, validation

Check progress with `/kiro-spec-status {feature}`. See [`CLAUDE.md`](CLAUDE.md) for the full workflow.

## Key Design Decisions

- **No physical deletion** — users/documents/attachments are only flag/status-transitioned or moved to an archive folder (no dangling FKs).
- **No-absorption bundles** — delete/restore/purge always operate atomically per bundle, and bundles created at different times are never merged. Encapsulated as a single implementation in the `document` service layer.
- **Save = version creation** — frontend autosave runs **once on leaving the document**, not on a periodic timer, avoiding version explosion.
- **Single render path** — the edit view and read views (read viewer, share links) are not split into two paths; both use Toast UI Editor viewer mode.
