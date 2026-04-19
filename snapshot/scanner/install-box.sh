#!/bin/bash
#
# Securva Snapshot - Box-side install script (Phase 4 Step 4)
#
# Runs on the Securva research box (babakinzo@165.232.109.143).
# Installs the FastAPI scanner service + nginx reverse proxy with
# Cloudflare IP allowlist.
#
# Prerequisites (Kingsley does these first):
#   - Phase B of desk checklist complete (D1, R2, KV created)
#   - R2 API credentials issued (Phase B Step 6)
#   - DNS A record scanner.internal.securva.net -> box IP, gray cloud
#
# What Kingsley needs to send Buddy via secure stdin:
#   - R2_ACCOUNT_ID       (Cloudflare account ID)
#   - R2_ACCESS_KEY_ID    (from R2 API token, Phase B Step 6)
#   - R2_SECRET_ACCESS_KEY
#
# Buddy generates BOX_API_TOKEN locally, then sends it back to Kingsley
# via secure paste so Kingsley can wrangler-secret-put it.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Pejji-ng/securva-net/feat/snapshot-phase-4-scaffold/snapshot/scanner/install-box.sh | sudo bash
#
# Or after cloning:
#   sudo bash install-box.sh

set -euo pipefail

BRANCH="${BRANCH:-feat/snapshot-phase-4-scaffold}"
INSTALL_DIR="${INSTALL_DIR:-/opt/securva-snapshot}"
SERVICE_USER="${SERVICE_USER:-babakinzo}"
NGINX_SITES="/etc/nginx/conf.d"

# ---------- 1. Prep system ----------

echo "[1/9] Installing system dependencies..."
apt-get update -qq
apt-get install -yq python3 python3-venv python3-pip nginx git \
    libpango-1.0-0 libpangoft2-1.0-0 libjpeg-dev libopenjp2-7-dev \
    libcairo2 shared-mime-info

# ---------- 2. Clone or update repo ----------

echo "[2/9] Pulling securva-net repo..."
if [ ! -d "$INSTALL_DIR" ]; then
    mkdir -p "$INSTALL_DIR"
    chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
    sudo -u "$SERVICE_USER" git clone https://github.com/Pejji-ng/securva-net.git "$INSTALL_DIR"
else
    cd "$INSTALL_DIR"
    sudo -u "$SERVICE_USER" git fetch origin
fi

cd "$INSTALL_DIR"
sudo -u "$SERVICE_USER" git checkout "$BRANCH"
sudo -u "$SERVICE_USER" git pull origin "$BRANCH"

# ---------- 3. Python venv ----------

echo "[3/9] Setting up Python venv + dependencies..."
cd "$INSTALL_DIR/snapshot/scanner"

if [ ! -d ".venv" ]; then
    sudo -u "$SERVICE_USER" python3 -m venv .venv
fi

sudo -u "$SERVICE_USER" .venv/bin/pip install --upgrade pip
sudo -u "$SERVICE_USER" .venv/bin/pip install \
    fastapi==0.115.0 \
    "uvicorn[standard]"==0.31.0 \
    jinja2==3.1.4 \
    weasyprint==63.0 \
    boto3==1.35.0 \
    pydantic==2.9.0 \
    httpx==0.27.0 \
    requests==2.32.0

# ---------- 4. Smoke-test the Python side ----------

echo "[4/9] Verifying scanner imports work..."
sudo -u "$SERVICE_USER" .venv/bin/python3 -c "
from orchestrator import orchestrate
from render import prepare_template_context, render_html, render_pdf
from api import app
print('OK — all imports resolve')
"

# ---------- 5. Env file (placeholder, Kingsley fills via secure stdin) ----------

echo "[5/9] Creating env file skeleton..."
mkdir -p /etc/securva

if [ ! -f /etc/securva/snapshot-api.env ]; then
    cat > /etc/securva/snapshot-api.env <<'EOF'
# Fill these in via secure-stdin paste from Kingsley.
# DO NOT commit this file. Permissions are 600 root:root.
BOX_API_TOKEN=
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=securva-snapshots
EOF
    chmod 600 /etc/securva/snapshot-api.env
    chown root:root /etc/securva/snapshot-api.env
    echo "  -> /etc/securva/snapshot-api.env created with empty values. Fill before starting service."
else
    echo "  -> /etc/securva/snapshot-api.env already exists, leaving alone"
fi

# ---------- 6. Generate BOX_API_TOKEN if not set ----------

if ! grep -q "^BOX_API_TOKEN=.\+" /etc/securva/snapshot-api.env; then
    echo "[6/9] Generating BOX_API_TOKEN..."
    TOKEN=$(openssl rand -base64 48 | tr '+/' '-_' | tr -d '=')
    sed -i "s|^BOX_API_TOKEN=.*|BOX_API_TOKEN=$TOKEN|" /etc/securva/snapshot-api.env
    echo ""
    echo "  ### IMPORTANT ### Send this token to Kingsley for wrangler secret put:"
    echo "  BOX_API_TOKEN=$TOKEN"
    echo ""
else
    echo "[6/9] BOX_API_TOKEN already set, skipping generation"
fi

# ---------- 7. systemd unit ----------

echo "[7/9] Installing systemd service..."
cat > /etc/systemd/system/securva-snapshot-api.service <<EOF
[Unit]
Description=Securva Snapshot Scanner API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR/snapshot/scanner
EnvironmentFile=/etc/securva/snapshot-api.env
ExecStart=$INSTALL_DIR/snapshot/scanner/.venv/bin/uvicorn api:app --host 127.0.0.1 --port 8089 --no-access-log
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true
ReadWritePaths=/tmp

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable securva-snapshot-api

# Only start if env file has all required values filled
if grep -q "^R2_ACCESS_KEY_ID=.\+" /etc/securva/snapshot-api.env && \
   grep -q "^R2_SECRET_ACCESS_KEY=.\+" /etc/securva/snapshot-api.env; then
    systemctl restart securva-snapshot-api
    sleep 2
    if systemctl is-active --quiet securva-snapshot-api; then
        echo "  -> Service active and running"
    else
        echo "  -> Service failed to start. Check: journalctl -u securva-snapshot-api -n 30"
    fi
else
    echo "  -> Service NOT started because R2 credentials are empty. Fill /etc/securva/snapshot-api.env then: systemctl restart securva-snapshot-api"
fi

# ---------- 8. nginx config ----------

echo "[8/9] Installing nginx reverse proxy with Cloudflare IP allowlist..."

# Fetch latest Cloudflare IP ranges
CF_IPS=$(curl -fsSL https://www.cloudflare.com/ips-v4 || echo "")

if [ -z "$CF_IPS" ]; then
    echo "  WARNING: could not fetch CF IPs, using static list"
    CF_IPS="173.245.48.0/20
103.21.244.0/22
103.22.200.0/22
103.31.4.0/22
141.101.64.0/18
108.162.192.0/18
190.93.240.0/20
188.114.96.0/20
197.234.240.0/22
198.41.128.0/17
162.158.0.0/15
104.16.0.0/13
104.24.0.0/14
172.64.0.0/13
131.0.72.0/22"
fi

# Build the geo block
GEO_BLOCK=$(echo "$CF_IPS" | sed 's|^|    |;s|$|  1;|')

cat > "$NGINX_SITES/snapshot-api.conf" <<EOF
geo \$is_cloudflare {
    default 0;
$GEO_BLOCK
    # Add your office/home IP below for curl testing:
    # YOUR_IP_HERE/32  1;
}

server {
    listen 80;
    server_name scanner.internal.securva.net;

    location / {
        if (\$is_cloudflare = 0) {
            return 403;
        }
        proxy_pass http://127.0.0.1:8089;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_read_timeout 90s;
    }
}
EOF

nginx -t
systemctl reload nginx
echo "  -> nginx configured. HTTPS not yet set up, run certbot separately when ready:"
echo "     certbot --nginx -d scanner.internal.securva.net"

# ---------- 9. Summary ----------

echo ""
echo "============================================================"
echo "  Securva Snapshot scanner API install complete."
echo "============================================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Paste R2 credentials into /etc/securva/snapshot-api.env:"
echo "     sudo nano /etc/securva/snapshot-api.env"
echo "   Fill R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY"
echo ""
echo "2. Start (or restart) the service:"
echo "     sudo systemctl restart securva-snapshot-api"
echo "     sudo systemctl status securva-snapshot-api"
echo ""
echo "3. Enable HTTPS on scanner.internal.securva.net:"
echo "     sudo certbot --nginx -d scanner.internal.securva.net"
echo ""
echo "4. Smoke test with a real scan:"
echo "     TOKEN=\$(grep '^BOX_API_TOKEN=' /etc/securva/snapshot-api.env | cut -d= -f2)"
echo "     curl -X POST https://scanner.internal.securva.net/scan-and-render \\"
echo "       -H \"Authorization: Bearer \$TOKEN\" \\"
echo "       -H \"Content-Type: application/json\" \\"
echo "       -d '{\"domain\":\"babakizo.com\",\"tier\":\"Starter\",\"job_id\":\"smoke-001\"}'"
echo ""
echo "5. Send BOX_API_TOKEN + BOX_SCANNER_ENDPOINT to Kingsley so he can"
echo "   wrangler-secret-put them into the Worker."
echo ""
echo "If anything failed, check:"
echo "   journalctl -u securva-snapshot-api -n 50"
echo "   nginx -t"
echo "   systemctl status securva-snapshot-api nginx"
echo ""
