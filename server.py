"""
PostgreSQL MCP Server — Multi-DB Edition
Connects to 5 databases: online_lms, regular_lms, regular_cgc_lms, regular_amity_lms, crm
Exposes PostgreSQL operations as MCP tools over HTTP (Streamable HTTP / SSE)
Compatible with Claude.ai Integrations and Claude Desktop (Pro/Max/Team/Enterprise)
"""

import os
import json
import logging
import base64
import mimetypes
import asyncio
from typing import Any

import httpx
import requests

import asyncpg
import uvicorn
from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("postgres-mcp")

# ─── Multi-DB Config from environment ─────────────────────────────────────────
DB_CONFIGS: dict[str, dict] = {
    "online_lms": {
        "host":     os.getenv("ONLINE_LMS_DB_HOST", ""),
        "port":     int(os.getenv("ONLINE_LMS_DB_PORT", "5432")),
        "database": os.getenv("ONLINE_LMS_DB_NAME", ""),
        "user":     os.getenv("ONLINE_LMS_DB_USER", "postgres"),
        "password": os.getenv("ONLINE_LMS_DB_PASSWORD", ""),
    },
    "regular_lms": {
        "host":     os.getenv("REGULAR_LMS_DB_HOST", ""),
        "port":     int(os.getenv("REGULAR_LMS_DB_PORT", "5432")),
        "database": os.getenv("REGULAR_LMS_DB_NAME", ""),
        "user":     os.getenv("REGULAR_LMS_DB_USER", "postgres"),
        "password": os.getenv("REGULAR_LMS_DB_PASSWORD", ""),
    },
    "regular_cgc_lms": {
        "host":     os.getenv("REGULAR_CGC_LMS_DB_HOST", ""),
        "port":     int(os.getenv("REGULAR_CGC_LMS_DB_PORT", "5432")),
        "database": os.getenv("REGULAR_CGC_LMS_DB_NAME", ""),
        "user":     os.getenv("REGULAR_CGC_LMS_DB_USER", "postgres"),
        "password": os.getenv("REGULAR_CGC_LMS_DB_PASSWORD", ""),
    },
    "regular_amity_lms": {
        "host":     os.getenv("REGULAR_AMITY_LMS_DB_HOST", ""),
        "port":     int(os.getenv("REGULAR_AMITY_LMS_DB_PORT", "5432")),
        "database": os.getenv("REGULAR_AMITY_LMS_DB_NAME", ""),
        "user":     os.getenv("REGULAR_AMITY_LMS_DB_USER", "postgres"),
        "password": os.getenv("REGULAR_AMITY_LMS_DB_PASSWORD", ""),
    },
    "crm": {
        "host":     os.getenv("CRM_DB_HOST", ""),
        "port":     int(os.getenv("CRM_DB_PORT", "5432")),
        "database": os.getenv("CRM_DB_NAME", ""),
        "user":     os.getenv("CRM_DB_USER", "postgres"),
        "password": os.getenv("CRM_DB_PASSWORD", ""),
    },
}

MCP_HOST  = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT  = int(os.getenv("MCP_PORT", "8000"))
API_TOKEN = os.getenv("API_TOKEN", "")
MAX_ROWS  = int(os.getenv("MAX_ROWS", "1000"))

# ─── WhatsApp (WHAPI) Config ───────────────────────────────────────────────────
WHAPI_TOKEN     = os.getenv("WHAPI_TOKEN", "")
WHATSAPP_GROUP  = os.getenv("WHATSAPP_GROUP", "")

_WA_DOCUMENT_MIMES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls":  "application/vnd.ms-excel",
    ".pdf":  "application/pdf",
    ".csv":  "text/csv",
}
_WA_IMAGE_MIMES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png",  ".gif":  "image/gif",
}


def _wa_headers() -> dict:
    return {
        "accept": "application/json",
        "authorization": f"Bearer {WHAPI_TOKEN}",
        "content-type": "application/json",
    }


_encode_cache: dict[tuple, tuple[str, str]] = {}

def _encode_file(path: str) -> tuple[str, str]:
    stat = os.stat(path)
    cache_key = (path, stat.st_mtime, stat.st_size)
    if cache_key in _encode_cache:
        return _encode_cache[cache_key]
    ext = os.path.splitext(path)[1].lower()
    filename = os.path.basename(path)
    mime = (
        _WA_IMAGE_MIMES.get(ext)
        or _WA_DOCUMENT_MIMES.get(ext)
        or mimetypes.guess_type(path)[0]
        or "application/octet-stream"
    )
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    result = f"data:{mime};name={filename};base64,{b64}", ext
    _encode_cache[cache_key] = result
    return result

# ─── Connection pools (one per database, created lazily) ──────────────────────
_pools: dict[str, asyncpg.Pool] = {}


async def get_pool(db_name: str) -> asyncpg.Pool:
    if db_name not in DB_CONFIGS:
        raise ValueError(f"Unknown database '{db_name}'. Available: {list(DB_CONFIGS.keys())}")
    if db_name not in _pools:
        cfg = DB_CONFIGS[db_name]
        if not cfg["host"]:
            raise ValueError(f"Database '{db_name}' is not configured. Add its credentials to .env")
        logger.info(f"Connecting to {db_name} at {cfg['host']}:{cfg['port']}/{cfg['database']}")
        _pools[db_name] = await asyncpg.create_pool(
            **cfg,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        logger.info(f"Pool created for {db_name} ✓")
    return _pools[db_name]


def rows_to_dicts(records: list[asyncpg.Record]) -> list[dict[str, Any]]:
    """Convert asyncpg Record objects to plain dicts (JSON-serializable)."""
    return [dict(r) for r in records]


# ─── FastMCP app ───────────────────────────────────────────────────────────────
CONTEXT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "context.json")

mcp = FastMCP(
    name="postgres-mcp",
    instructions=(
        "This MCP server connects to 5 PostgreSQL databases simultaneously. "
        "ALWAYS follow this order: "
        "1) Call list_databases — see all DBs, their rulesets, and descriptions. "
        "2) Identify the correct db_name from the user's request: "
        "   online_lms = Online LMS. "
        "   regular_lms / regular_cgc_lms / regular_amity_lms = Regular LMS (CGC/Amity are university-specific). "
        "   crm = CRM database (customer relationship management). "
        "3) Call get_table_context(db_name, '_global_rules') FIRST — get the universal rules for that DB's ruleset. "
        "4) Call get_table_context(db_name, table_name) for each table you plan to query. "
        "5) Apply ALL ruleset rules when constructing every query. "
        "6) ALWAYS include _source_db in your response — critical for campaign analysis and conversion tracking. "
        "Key differences between rulesets: "
        "Regular: APPLICATION uses 8-status IN list (never course_status='Application'). "
        "Regular: first_icc_date lowercase no quotes. Online: double-quoted \"first_Icc_Date\". "
        "Regular: Shortlisted = latest_course_status='Shortlisted'. Online: is_shortlisted=true. "
        "Regular: PERCENTAGES must append || '%'. Regular: DEFAULT counsellor = L2 always. "
        "Regular: TEAM OWNER = role ILIKE '%to%' (never role='to' alone)."
    ),
)


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL 0 — list_databases
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool
async def list_databases() -> str:
    """
    List all available databases with their descriptions and rulesets.
    ALWAYS call this first to identify the correct db_name for the user's query.

    Returns:
        JSON array of databases with db_name, ruleset, description, and config status.
    """
    try:
        with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
            ctx = json.load(f)
        db_registry = ctx.get("_db_registry", {})
    except FileNotFoundError:
        db_registry = {}

    result = []
    for db_name, cfg in DB_CONFIGS.items():
        entry = {
            "db_name": db_name,
            "configured": bool(cfg["host"]),
            "database": cfg["database"] if cfg["host"] else "not configured",
            **db_registry.get(db_name, {}),
        }
        result.append(entry)
    logger.info("list_databases called")
    return json.dumps(result, default=str)


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL 1 — list_tables
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool
async def list_tables(db_name: str, schema: str = "public") -> str:
    """
    List all tables in the specified database schema.

    Args:
        db_name: Database to query. One of: online_lms, regular_lms, regular_cgc_lms, regular_amity_lms, crm
        schema:  Schema name (default: 'public')

    Returns:
        JSON with table names, types, row counts, tagged with _source_db.
    """
    pool = await get_pool(db_name)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                t.table_name,
                t.table_type,
                COALESCE(s.n_live_tup, 0) AS approx_row_count
            FROM information_schema.tables t
            LEFT JOIN pg_stat_user_tables s
                   ON s.schemaname = t.table_schema
                  AND s.relname    = t.table_name
            WHERE t.table_schema = $1
            ORDER BY t.table_name
            """,
            schema,
        )
    result = rows_to_dicts(rows)
    logger.info(f"list_tables({db_name}, schema={schema}) → {len(result)} tables")
    return json.dumps({"_source_db": db_name, "tables": result}, default=str)


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL 2 — describe_table
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool
async def describe_table(db_name: str, table_name: str, schema: str = "public") -> str:
    """
    Get the full schema/structure of a specific table including columns,
    data types, nullable flags, defaults, and constraints.

    Args:
        db_name:    Database to query. One of: online_lms, regular_lms, regular_cgc_lms, regular_amity_lms
        table_name: Name of the table to describe
        schema:     Schema name (default: 'public')

    Returns:
        JSON with columns and constraints, tagged with _source_db.
    """
    pool = await get_pool(db_name)
    async with pool.acquire() as conn:
        # Columns
        columns = await conn.fetch(
            """
            SELECT
                column_name,
                data_type,
                character_maximum_length,
                is_nullable,
                column_default,
                ordinal_position
            FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position
            """,
            schema,
            table_name,
        )

        # Constraints (PK, FK, UNIQUE, CHECK)
        constraints = await conn.fetch(
            """
            SELECT
                tc.constraint_name,
                tc.constraint_type,
                kcu.column_name,
                ccu.table_name  AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
               AND tc.table_schema    = kcu.table_schema
            LEFT JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
               AND ccu.table_schema    = tc.table_schema
            WHERE tc.table_schema = $1 AND tc.table_name = $2
            ORDER BY tc.constraint_type
            """,
            schema,
            table_name,
        )

    result = {
        "_source_db": db_name,
        "table": table_name,
        "schema": schema,
        "columns": rows_to_dicts(columns),
        "constraints": rows_to_dicts(constraints),
    }
    logger.info(f"describe_table({db_name}: {schema}.{table_name})")
    return json.dumps(result, default=str)


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL 3 — run_select_query  (READ-ONLY)
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool
async def run_select_query(db_name: str, query: str, params: list[Any] | None = None) -> str:
    """
    Execute a read-only SELECT query on the specified database.
    Results are capped at MAX_ROWS rows for safety.

    Args:
        db_name: Database to query. One of: online_lms, regular_lms, regular_cgc_lms, regular_amity_lms, crm
        query:   A SQL SELECT / WITH statement. Use $1, $2 … for parameters.
        params:  Optional list of parameter values matching the placeholders.

    Returns:
        JSON with 'rows', 'row_count', and '_source_db'.
    """
    normalized = query.strip().upper()
    if not (normalized.startswith("SELECT") or normalized.startswith("WITH")):
        return json.dumps({"error": "Only SELECT / WITH queries are allowed in run_select_query.", "_source_db": db_name})

    pool = await get_pool(db_name)
    async with pool.acquire() as conn:
        capped = f"SELECT * FROM ({query}) _q LIMIT {MAX_ROWS}"
        try:
            rows = await conn.fetch(capped, *(params or []))
        except asyncpg.PostgresError as e:
            logger.warning(f"Query error on {db_name}: {e}")
            return json.dumps({"error": str(e), "_source_db": db_name})

    result = {
        "_source_db": db_name,
        "rows": rows_to_dicts(rows),
        "row_count": len(rows),
        "capped_at": MAX_ROWS,
    }
    logger.info(f"run_select_query({db_name}) → {len(rows)} rows")
    return json.dumps(result, default=str)


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL 4 — run_write_query  (INSERT / UPDATE / DELETE)
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool
async def run_write_query(db_name: str, query: str, params: list[Any] | None = None) -> str:
    """
    Execute an INSERT, UPDATE, or DELETE inside a transaction on the specified database.
    The transaction is committed only if no error occurs.

    Args:
        db_name: Database to write to. One of: online_lms, regular_lms, regular_cgc_lms, regular_amity_lms, crm
        query:   SQL DML statement (INSERT / UPDATE / DELETE). Use $1, $2 … for parameters.
        params:  Optional list of parameter values.

    Returns:
        JSON with 'status', 'rows_affected', '_source_db', and optionally 'returning' rows.
    """
    normalized = query.strip().upper()
    allowed = ("INSERT", "UPDATE", "DELETE", "WITH")
    if not any(normalized.startswith(k) for k in allowed):
        return json.dumps({"error": "Only INSERT, UPDATE, DELETE, or WITH DML allowed.", "_source_db": db_name})

    pool = await get_pool(db_name)
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                rows = await conn.fetch(query, *(params or []))
            except asyncpg.PostgresError as e:
                logger.warning(f"Write query error on {db_name}: {e}")
                return json.dumps({"error": str(e), "_source_db": db_name})

    result: dict[str, Any] = {
        "_source_db": db_name,
        "status": "success",
        "rows_affected": len(rows),
    }
    if rows:
        result["returning"] = rows_to_dicts(rows)

    logger.info(f"run_write_query({db_name}) → {result}")
    return json.dumps(result, default=str)


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL 5 — list_schemas
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool
async def list_schemas(db_name: str) -> str:
    """
    List all user-defined schemas in the specified database.

    Args:
        db_name: Database to query. One of: online_lms, regular_lms, regular_cgc_lms, regular_amity_lms, crm

    Returns:
        JSON with schema names, tagged with _source_db.
    """
    pool = await get_pool(db_name)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast')
              AND schema_name NOT LIKE 'pg_temp_%'
            ORDER BY schema_name
            """
        )
    result = [r["schema_name"] for r in rows]
    logger.info(f"list_schemas({db_name}) → {result}")
    return json.dumps({"_source_db": db_name, "schemas": result})


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL 6 — get_table_indexes
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool
async def get_table_indexes(db_name: str, table_name: str, schema: str = "public") -> str:
    """
    List all indexes on a specific table.

    Args:
        db_name:    Database to query. One of: online_lms, regular_lms, regular_cgc_lms, regular_amity_lms
        table_name: Name of the table
        schema:     Schema name (default: 'public')

    Returns:
        JSON with index definitions, tagged with _source_db.
    """
    pool = await get_pool(db_name)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                indexname,
                indexdef,
                pg_size_pretty(pg_relation_size(indexname::regclass)) AS index_size
            FROM pg_indexes
            WHERE schemaname = $1 AND tablename = $2
            ORDER BY indexname
            """,
            schema,
            table_name,
        )
    return json.dumps({"_source_db": db_name, "indexes": rows_to_dicts(rows)}, default=str)


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL 7 — get_db_stats
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool
async def get_db_stats(db_name: str) -> str:
    """
    Get high-level database statistics: size, active connections,
    top tables by size, and cache hit ratio.

    Args:
        db_name: Database to query. One of: online_lms, regular_lms, regular_cgc_lms, regular_amity_lms, crm

    Returns:
        JSON with database health metrics, tagged with _source_db.
    """
    db_database = DB_CONFIGS[db_name]["database"]
    pool = await get_pool(db_name)
    async with pool.acquire() as conn:
        db_size = await conn.fetchval(
            "SELECT pg_size_pretty(pg_database_size($1))", db_database
        )
        connections = await conn.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
        )
        top_tables = await conn.fetch(
            """
            SELECT relname AS table_name,
                   pg_size_pretty(pg_total_relation_size(relid)) AS total_size
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size(relid) DESC
            LIMIT 10
            """
        )
        cache_hit = await conn.fetchrow(
            """
            SELECT
                round(
                    100.0 * sum(blks_hit) / nullif(sum(blks_hit + blks_read), 0), 2
                ) AS cache_hit_ratio
            FROM pg_stat_database
            WHERE datname = $1
            """,
            db_database,
        )

    result = {
        "_source_db": db_name,
        "database": db_database,
        "size": db_size,
        "active_connections": connections,
        "cache_hit_ratio_pct": float(cache_hit["cache_hit_ratio"] or 0),
        "top_tables_by_size": rows_to_dicts(top_tables),
    }
    return json.dumps(result, default=str)


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL 8 — get_table_context
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool
async def get_table_context(db_name: str, table_name: str, schema: str = "public") -> str:
    """
    Get full context: global ruleset rules + table business rules + live DB stats.
    Pass table_name='_global_rules' to get only the universal rules for this DB's ruleset.
    ALWAYS call get_table_context(db_name, '_global_rules') first, then per table.

    Args:
        db_name:    Database. One of: online_lms, regular_lms, regular_cgc_lms, regular_amity_lms, crm
        table_name: Table name, or '_global_rules' for universal ruleset rules only
        schema:     Schema name (default: 'public')

    Returns:
        JSON with global rules, table business rules, live column info, row count, sample values.
    """
    # ── 1. Load context (ruleset + table rules) ───────────────────────────────
    global_rules: dict = {}
    table_rules: dict = {}
    db_info: dict = {}
    ruleset_name: str = ""

    try:
        with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
            ctx = json.load(f)
        db_registry = ctx.get("_db_registry", {})
        db_info = db_registry.get(db_name, {})
        ruleset_name = db_info.get("ruleset", "")
        if ruleset_name and ruleset_name in ctx:
            ruleset = ctx[ruleset_name]
            global_rules = ruleset.get("_global_rules", {})
            if table_name != "_global_rules":
                table_rules = ruleset.get(table_name, {})
    except FileNotFoundError:
        pass

    # ── 2. If only global rules requested, return early ───────────────────────
    if table_name == "_global_rules":
        result = {
            "_source_db": db_name,
            "db_info": db_info,
            "ruleset": ruleset_name,
            "global_rules": global_rules,
        }
        logger.info(f"get_table_context({db_name}, _global_rules)")
        return json.dumps(result, default=str)

    # ── 3. Live DB queries ────────────────────────────────────────────────────
    pool = await get_pool(db_name)
    async with pool.acquire() as conn:
        try:
            row_count = await conn.fetchval(
                f'SELECT COUNT(*) FROM "{schema}"."{table_name}"'
            )
        except Exception as e:
            row_count = f"error: {e}"

        columns_raw = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position
            """,
            schema, table_name,
        )
        columns = rows_to_dicts(columns_raw)

        sample_values: dict[str, list] = {}
        text_types = {"text", "character varying", "varchar", "char", "USER-DEFINED"}
        for col in columns:
            if col["data_type"] in text_types:
                col_name = col["column_name"]
                try:
                    distinct_count = await conn.fetchval(
                        f'SELECT COUNT(DISTINCT "{col_name}") FROM "{schema}"."{table_name}"'
                    )
                    if distinct_count is not None and distinct_count <= 50:
                        vals = await conn.fetch(
                            f'SELECT DISTINCT "{col_name}" FROM "{schema}"."{table_name}" '
                            f'WHERE "{col_name}" IS NOT NULL ORDER BY "{col_name}" LIMIT 50'
                        )
                        sample_values[col_name] = [r[col_name] for r in vals]
                except Exception:
                    pass

    result = {
        "_source_db": db_name,
        "db_info": db_info,
        "ruleset": ruleset_name,
        "global_rules": global_rules,
        "table": table_name,
        "schema": schema,
        "row_count": row_count,
        "columns": columns,
        "sample_values_for_low_cardinality_columns": sample_values,
        "table_business_rules": table_rules if table_rules else "No custom rules defined. Use column info and sample values to infer meaning.",
    }
    logger.info(f"get_table_context({db_name}: {schema}.{table_name}) — {len(columns)} cols, {row_count} rows, {len(sample_values)} sampled cols")
    return json.dumps(result, default=str)


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL 9 — send_whatsapp_text
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool
async def send_whatsapp_text(message: str, to: str = "") -> str:
    """
    Send a plain-text WhatsApp message via WHAPI.

    Args:
        message: The text body to send.
        to:      Recipient phone number or group ID (e.g. '919876543210@s.whatsapp.net'
                 or '120363426619711887@g.us'). Defaults to the configured WHATSAPP_GROUP.

    Returns:
        JSON response from WHAPI confirming delivery.
    """
    recipient = to or WHATSAPP_GROUP
    if not WHAPI_TOKEN:
        return json.dumps({"error": "WHAPI_TOKEN is not configured in .env"})
    def _send():
        r = requests.post(
            "https://gate.whapi.cloud/messages/text",
            headers=_wa_headers(),
            json={"to": recipient, "body": message},
            timeout=30,
        )
        r.raise_for_status()
        return r
    resp = await asyncio.to_thread(_send)
    logger.info(f"send_whatsapp_text → {resp.status_code}")
    try:
        return json.dumps(resp.json(), default=str)
    except Exception:
        return json.dumps({"status_code": resp.status_code, "body": resp.text})


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL 10 — send_whatsapp_file
# ══════════════════════════════════════════════════════════════════════════════
@mcp.tool
async def send_whatsapp_file(media: str, to: str = "", caption: str = "") -> str:
    """
    Send a file (image or document) as a WhatsApp message via WHAPI.
    Supported images : .jpg, .jpeg, .png, .gif
    Supported documents: .xlsx, .xls, .pdf, .csv  (and any other file type)

    Args:
        media:   Either a base64 data URI (data:image/jpeg;base64,...) or a public https:// URL to the file.
        to:      Recipient phone number or group ID. Defaults to the configured WHATSAPP_GROUP.
        caption: Optional caption text to accompany the file.

    Returns:
        JSON response from WHAPI confirming delivery.
    """
    recipient = to or WHATSAPP_GROUP
    if not WHAPI_TOKEN:
        return json.dumps({"error": "WHAPI_TOKEN is not configured in .env"})
    def _send():
        if media.startswith("data:"):
            media_payload = media
            ext = media.split(";")[0].split("/")[-1]
        elif media.startswith("http"):
            media_payload = media
            ext = media.split(".")[-1].lower()
        else:
            raise ValueError("media must be a base64 data URI or a public URL")
        endpoint = (
            "https://gate.whapi.cloud/messages/image"
            if f".{ext}" in _WA_IMAGE_MIMES
            else "https://gate.whapi.cloud/messages/document"
        )
        r = requests.post(
            endpoint,
            headers=_wa_headers(),
            json={"to": recipient, "media": media_payload, "caption": caption},
            timeout=120,
        )
        r.raise_for_status()
        return r
    try:
        resp = await asyncio.to_thread(_send)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    logger.info(f"send_whatsapp_file → {resp.status_code}")
    try:
        return json.dumps(resp.json(), default=str)
    except Exception:
        return json.dumps({"status_code": resp.status_code, "body": resp.text})


# ─── Bearer-token auth middleware ──────────────────────────────────────────────
class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not API_TOKEN:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not (auth.startswith("Bearer ") and auth[7:] == API_TOKEN):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


# ─── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["http", "stdio"], default="http")
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        logger.info(f"Starting PostgreSQL MCP server on {MCP_HOST}:{MCP_PORT}")
        app = mcp.http_app(path="/mcp", middleware=[Middleware(BearerAuthMiddleware)])
        uvicorn.run(app, host=MCP_HOST, port=MCP_PORT, log_level="info")
