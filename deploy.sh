#!/usr/bin/env bash
# deploy.sh — Run this on your Hostinger VPS as ubuntu/root
# Usage: bash deploy.sh your-domain.com
set -euo pipefail

DOMAIN="${1:?Usage: bash deploy.sh <your-domain.com>}"
APP_DIR="/home/ubuntu/postgres-mcp"
SERVICE_NAME="postgres-mcp"

echo "══════════════════════════════════════════════"
echo "  PostgreSQL MCP Server — Deployment Script"
echo "  Domain: $DOMAIN"
echo "══════════════════════════════════════════════"

# ── 1. System dependencies ────────────────────────────────────────────────────
echo "[1/7] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx

# ── 2. Copy project files ─────────────────────────────────────────────────────
echo "[2/7] Setting up project directory..."
sudo mkdir -p "$APP_DIR"
sudo chown ubuntu:ubuntu "$APP_DIR"

# Copy your project files to the server before running this script, OR
# clone from your git repo here:
# git clone https://github.com/youruser/postgres-mcp.git "$APP_DIR"

# ── 3. Python virtual environment ─────────────────────────────────────────────
echo "[3/7] Creating Python virtual environment..."
cd "$APP_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
deactivate

echo "✓ Python environment ready"

# ── 4. Environment file ───────────────────────────────────────────────────────
echo "[4/7] Configuring .env (edit /home/ubuntu/postgres-mcp/.env with your DB credentials)"
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo "⚠  Created .env from .env.example — EDIT IT NOW with your real credentials!"
    echo "   nano $APP_DIR/.env"
fi

# ── 5. systemd service ────────────────────────────────────────────────────────
echo "[5/7] Installing systemd service..."
sudo cp "$APP_DIR/postgres-mcp.service" /etc/systemd/system/
sudo sed -i "s|/home/ubuntu|/home/ubuntu|g" /etc/systemd/system/postgres-mcp.service
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
echo "✓ Service status:"
sudo systemctl is-active "$SERVICE_NAME" && echo "  postgres-mcp is RUNNING ✓" || echo "  ⚠ Service not running — check: journalctl -u postgres-mcp -n 50"

# ── 6. Nginx config ───────────────────────────────────────────────────────────
echo "[6/7] Configuring Nginx..."
sudo cp "$APP_DIR/nginx-postgres-mcp.conf" /etc/nginx/sites-available/postgres-mcp
sudo sed -i "s/YOUR_DOMAIN/$DOMAIN/g" /etc/nginx/sites-available/postgres-mcp
sudo ln -sf /etc/nginx/sites-available/postgres-mcp /etc/nginx/sites-enabled/postgres-mcp
sudo nginx -t
sudo systemctl reload nginx
echo "✓ Nginx configured"

# ── 7. SSL with Let's Encrypt ─────────────────────────────────────────────────
echo "[7/7] Obtaining SSL certificate for $DOMAIN..."
sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "admin@$DOMAIN" || {
    echo "⚠  Certbot failed. Make sure your domain's DNS A record points to this VPS IP."
    echo "   Retry manually: sudo certbot --nginx -d $DOMAIN"
}

echo ""
echo "══════════════════════════════════════════════"
echo "  ✅  DEPLOYMENT COMPLETE"
echo ""
echo "  MCP Server URL: https://$DOMAIN/mcp"
echo ""
echo "  Add to Claude.ai:"
echo "  Settings → Integrations → Add → https://$DOMAIN/mcp"
echo ""
echo "  Useful commands:"
echo "  sudo systemctl status postgres-mcp"
echo "  sudo journalctl -u postgres-mcp -f"
echo "  sudo systemctl restart postgres-mcp"
echo "══════════════════════════════════════════════"
