Hello Test Github Credentials

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A PostgreSQL MCP (Model Context Protocol) server built with FastMCP. It exposes 9 tools that let Claude query 4 PostgreSQL databases simultaneously via HTTP or stdio transport. Designed to be deployed on a VPS and connected to Claude.ai Integrations.

## Running the server

**Activate the local venv first:**
```
01_mcp\Scripts\activate
```

**Run (HTTP transport — default):**
```
python server.py --transport http
```

**Run (stdio transport — for Claude Desktop):**
```
python server.py --transport stdio
```

The server listens on `MCP_HOST:MCP_PORT` (default `0.0.0.0:8000`). The MCP endpoint is `/mcp`.

## Environment variables

Copy `.env.example` or create `.env` with these keys (all DB prefixes follow the pattern `ONLINE_LMS_`, `REGULAR_LMS_`, `REGULAR_CGC_LMS_`, `REGULAR_AMITY_LMS_`):

```
<PREFIX>_DB_HOST, <PREFIX>_DB_PORT, <PREFIX>_DB_NAME, <PREFIX>_DB_USER, <PREFIX>_DB_PASSWORD
MCP_HOST, MCP_PORT, API_TOKEN, MAX_ROWS
```

## Architecture

### `server.py` — single-file server
- **DB connection pools** (`_pools` dict): one `asyncpg.Pool` per database, created lazily on first use via `get_pool(db_name)`. Pool config: min=2, max=10, timeout=30s.
- **9 MCP tools** registered with `@mcp.tool`:
  - `list_databases` — reads `context.json` `_db_registry`, returns DB metadata (no DB connection needed)
  - `list_tables`, `describe_table`, `list_schemas`, `get_table_indexes`, `get_db_stats` — introspection tools
  - `run_select_query` — SELECT/WITH only; wraps query in `SELECT * FROM (...) _q LIMIT {MAX_ROWS}`
  - `run_write_query` — INSERT/UPDATE/DELETE; runs inside an explicit transaction
  - `get_table_context` — the key tool: merges live DB column info + `context.json` business rules + sample values for low-cardinality text columns (≤50 distinct values)

### `context.json` — business rules store
Structured as `{ "_db_registry": {...}, "online": {...}, "regular": {...} }`.
- `_db_registry` maps each `db_name` → `{ ruleset, description }`
- Each ruleset (`online`, `regular`) contains `_global_rules` and per-table rule objects
- `regular` ruleset is shared by `regular_lms`, `regular_cgc_lms`, and `regular_amity_lms`
- `get_table_context` merges `_global_rules` + per-table rules from the correct ruleset at runtime

### Deployment (`deploy.sh`)
Targets a Hostinger VPS (Ubuntu). Sets up Python venv → systemd service (`postgres-mcp.service`) → Nginx reverse proxy → Let's Encrypt SSL.
```
bash deploy.sh your-domain.com
```

### Testing (`test_context.py`)
Standalone script to test `get_table_context` logic against a single DB. Edit `TABLE_TO_TEST` and ensure `.env` is populated, then run:
```
python test_context.py
```

## Key design rules encoded in context.json

These rules are injected into every AI query session and must be preserved accurately when editing `context.json`:

- **Online vs Regular LMS differ** on: `first_Icc_Date` casing, shortlisted detection (`is_shortlisted=true` vs `latest_course_status='Shortlisted'`), application status values, percentage formatting (`|| '%'` required in Regular only), default counsellor level
- **`_source_db`** must always be included in tool responses — critical for cross-DB analysis
- **`run_select_query`** is strictly read-only; `run_write_query` uses a transaction
- Connection pools are module-level singletons; there is no explicit cleanup on shutdown
