# PostgreSQL MCP Server

A remote MCP server that gives Claude.ai direct access to 4 PostgreSQL databases simultaneously. Deploy it on a Hostinger VPS and connect it to Claude.ai as a Custom Connector.

## What it does

- Exposes 11 MCP tools: query, introspect, and write to your databases
- Injects business rules from `context.json` so Claude understands your schema
- Runs over HTTPS with bearer-token auth, ready for Claude.ai Integrations

---

## Repo structure

```
server.py                # The entire MCP server (all tools)
context.json             # Business rules + DB registry
requirements.txt         # Python dependencies
deploy.sh                # One-shot VPS deployment script
postgres-mcp.service     # systemd service file
nginx-postgres-mcp.conf  # Nginx reverse proxy config
.env.example             # Template — copy to .env and fill in credentials
```

---

## Local development guide

### Step 1 — Clone the repo

```bash
git clone https://github.com/MohitKapoor19/custom-mcp-server.git
cd custom-mcp-server
```

### Step 2 — Create a virtual environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Mac/Linux
python3 -m venv venv
source venv/bin/activate
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Create your `.env`

```bash
cp .env.example .env
```

Open `.env` and fill in your database credentials. You only need to fill in the databases you want to test — unconfigured ones are skipped automatically.

For local dev, `API_TOKEN` can be left empty (auth is skipped when the token is blank).

### Step 5 — Run the server

```bash
python server.py --transport http
```

Server starts at `http://localhost:8000`. The MCP endpoint is `http://localhost:8000/mcp`.

### Step 6 — Test a tool call manually

```bash
curl -s -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "list_databases",
      "arguments": {}
    }
  }'
```

### Step 7 — Test with Claude Desktop (optional)

Add this to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "postgres-mcp": {
      "command": "python",
      "args": ["C:/path/to/custom-mcp-server/server.py", "--transport", "stdio"]
    }
  }
}
```

Restart Claude Desktop — the tools will appear automatically.

### Editing business rules

`context.json` is read from disk on **every tool call** — no restart needed. Just edit and save:

```
context.json
├── _db_registry        ← add/rename databases here
├── online              ← rules for online_lms
│   ├── _global_rules   ← applies to every query in this ruleset
│   └── <table_name>    ← per-table rules
└── regular             ← rules for regular_lms, regular_cgc_lms, regular_amity_lms
    ├── _global_rules
    └── <table_name>
```

### Adding a new tool

Add a new `@mcp.tool` function anywhere in `server.py`:

```python
@mcp.tool
async def my_tool(db_name: str, param: str) -> str:
    """Description shown to Claude."""
    pool = await get_pool(db_name)
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT ...", param)
    return json.dumps({"_source_db": db_name, "results": rows_to_dicts(rows)}, default=str)
```

Restart the server — FastMCP auto-registers it, no other wiring needed.

### Pushing changes

```bash
git add server.py context.json  # or whichever files changed
git commit -m "your message"
git push
```

---

## Deployment guide (Hostinger VPS)

### Prerequisites

- Hostinger VPS running **Ubuntu 22.04**
- A **domain or subdomain** with its DNS A record pointed at the VPS IP (e.g. `mcp.yourdomain.com`)
- Your PostgreSQL databases must be **reachable from the VPS IP** (open port in DB firewall / pg_hba.conf)
- SSH access to the VPS

---

### Step 1 — Upload files to the VPS

From your local machine, upload the project files:

```bash
scp server.py context.json requirements.txt deploy.sh \
    postgres-mcp.service nginx-postgres-mcp.conf .env.example \
    root@YOUR_VPS_IP:/home/ubuntu/postgres-mcp/
```

> If the directory doesn't exist yet, SSH in first and run:
> `sudo mkdir -p /home/ubuntu/postgres-mcp && sudo chown ubuntu:ubuntu /home/ubuntu/postgres-mcp`

---

### Step 2 — Create your `.env` file on the VPS

SSH into the VPS and fill in credentials:

```bash
ssh root@YOUR_VPS_IP
cp /home/ubuntu/postgres-mcp/.env.example /home/ubuntu/postgres-mcp/.env
nano /home/ubuntu/postgres-mcp/.env
```

Fill in every value. The critical ones:

| Variable | What to set |
|---|---|
| `*_DB_HOST` | Your PostgreSQL server hostname/IP |
| `*_DB_PASSWORD` | Your database passwords |
| `API_TOKEN` | A strong random secret — run `openssl rand -hex 32` to generate one |

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).

---

### Step 3 — Run the deploy script

```bash
cd /home/ubuntu/postgres-mcp
chmod +x deploy.sh
bash deploy.sh mcp.yourdomain.com
```

The script does these steps automatically:

1. Installs Python 3, pip, venv, Nginx, and Certbot
2. Creates a Python virtual environment and installs `requirements.txt`
3. Installs and starts the systemd service (`postgres-mcp.service`)
4. Configures Nginx as a reverse proxy for your domain
5. Obtains a free SSL certificate from Let's Encrypt

> **DNS must already point to the VPS before running the script** — Certbot will fail if it can't verify your domain.

---

### Step 4 — Verify the deployment

```bash
# Check the service is running
sudo systemctl status postgres-mcp

# Test the MCP endpoint
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  https://mcp.yourdomain.com/mcp
# Should return 200 (or 405 — both mean the server is alive)

# Watch live logs
sudo journalctl -u postgres-mcp -f
```

---

### Step 5 — Connect to Claude.ai

1. Go to **claude.ai** → click your profile → **Settings** → **Integrations**
2. Click **Add custom connector** (or **Add integration**)
3. Enter the server URL: `https://mcp.yourdomain.com/mcp`
4. For authentication, select **Bearer token** and paste your `API_TOKEN`
5. Claude will handshake with the server and register all 11 tools

In any Claude conversation, Claude will now automatically use these tools when you ask questions about your databases.

---

## Updating after changes

### Update server code

```bash
# Upload the new file
scp server.py root@YOUR_VPS_IP:/home/ubuntu/postgres-mcp/

# Restart the service
ssh root@YOUR_VPS_IP "sudo systemctl restart postgres-mcp"
```

### Update business rules (`context.json`)

No restart needed — `context.json` is read from disk on every tool call:

```bash
scp context.json root@YOUR_VPS_IP:/home/ubuntu/postgres-mcp/
```

---

## Troubleshooting

**Service won't start**
```bash
sudo journalctl -u postgres-mcp -n 50
# Common cause: syntax error in .env, or wrong Python path
# Test manually: /home/ubuntu/postgres-mcp/venv/bin/python server.py
```

**Claude.ai can't connect**
```bash
sudo systemctl status nginx          # Nginx must be running
sudo certbot certificates            # SSL cert must be valid
curl -v https://mcp.yourdomain.com/mcp  # Check response
sudo ufw status                      # Port 443 must be ALLOW
nslookup mcp.yourdomain.com          # Must return your VPS IP
```

**Database connection errors**
```bash
# Test from the VPS directly
psql -h YOUR_DB_HOST -U YOUR_DB_USER -d YOUR_DB_NAME
# If this fails, the DB firewall is blocking the VPS IP
```

**SSL certificate expired** (Let's Encrypt certs last 90 days — Certbot auto-renews, but if needed):
```bash
sudo certbot renew && sudo systemctl reload nginx
```

---

## Security notes

- **Never commit `.env`** — it contains your database passwords and API token. It is in `.gitignore`.
- The `API_TOKEN` is enforced on every request via bearer-token middleware.
- Optionally restrict access to Anthropic's outbound IPs only (`160.79.104.0/21`) by uncommenting the `allow`/`deny` lines in `nginx-postgres-mcp.conf`.
- `run_select_query` is strictly read-only. `run_write_query` runs inside a transaction and auto-rolls back on error.
